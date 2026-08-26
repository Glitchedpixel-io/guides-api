"""The Claude-backed redraw client, with the SDK faked at the stream boundary.

No network. What is being tested is the request the client builds, the guards it applies
before making one, and how it interprets what comes back.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config.schema import SketchConfig
from app.schemas.enums import LeaderDir
from app.sketch.client import (
    RedrawOutput,
    SketchDisabledError,
    SketchError,
    SketchRedrawClient,
    SketchRefusedError,
    SuggestedCallout,
    UnsupportedSketchFormatError,
    load_prompt,
)
from tests.factories import SAMPLE_SVG

pytestmark = pytest.mark.unit

PNG = b"\x89PNG\r\n\x1a\nfake-sketch-bytes"


def fake_anthropic(message: object) -> MagicMock:
    """Build a stand-in Anthropic client whose stream yields ``message``.

    Args:
        message: The final message ``get_final_message()`` should return.

    Returns:
        MagicMock: A client exposing ``messages.stream`` as an async context manager.
    """
    stream = MagicMock()
    stream.__aenter__ = AsyncMock(
        return_value=SimpleNamespace(get_final_message=AsyncMock(return_value=message))
    )
    stream.__aexit__ = AsyncMock(return_value=False)

    client = MagicMock()
    client.messages.stream = MagicMock(return_value=stream)
    return client


def message_with(output: RedrawOutput | None, stop_reason: str = "end_turn") -> SimpleNamespace:
    """Build a fake final message.

    Args:
        output: The structured output to attach to a text block, or ``None`` for a
            response carrying no parsed drawing.
        stop_reason: The message's stop reason.

    Returns:
        SimpleNamespace: A message shaped like the SDK's.
    """
    block = SimpleNamespace(type="text", text="{}", parsed_output=output)
    return SimpleNamespace(
        content=[block],
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(explanation="policy"),
    )


VALID_OUTPUT = RedrawOutput(
    svg=SAMPLE_SVG,
    suggested_callouts=[
        SuggestedCallout(
            index=1, x_pct=25.0, y_pct=30.0, leader_dir=LeaderDir.RIGHT, label="Burr side up."
        )
    ],
    notes="assumed the holes are concentric",
    confidence=0.82,
)


class TestGuards:
    """Refusals that happen before any request is made."""

    async def test_disabled_configuration_declines(self) -> None:
        """A disabled environment never reaches the SDK."""
        client = SketchRedrawClient(SketchConfig(enabled=False), client=MagicMock())
        with pytest.raises(SketchDisabledError):
            await client.redraw(PNG, "image/png", "Step", "Do the thing")

    @pytest.mark.parametrize(
        "media_type", ["image/svg+xml", "application/pdf", "text/plain", "image/tiff"]
    )
    async def test_unsupported_formats_are_refused(self, media_type: str) -> None:
        """Only formats the model accepts as an image get sent.

        Args:
            media_type: A type the vision API does not take.
        """
        client = SketchRedrawClient(SketchConfig(api_key="k"), client=MagicMock())
        with pytest.raises(UnsupportedSketchFormatError, match="not a supported"):
            await client.redraw(PNG, media_type, "Step", "Do the thing")

    @pytest.mark.parametrize("media_type", ["image/png", "IMAGE/PNG", "image/jpeg; charset=binary"])
    async def test_accepted_formats_are_normalised(self, media_type: str) -> None:
        """Case and parameters are tolerated rather than rejected on formatting.

        Args:
            media_type: A supported type, awkwardly spelled.
        """
        fake = fake_anthropic(message_with(VALID_OUTPUT))
        client = SketchRedrawClient(SketchConfig(api_key="k"), client=fake)
        await client.redraw(PNG, media_type, "Step", "Do the thing")
        sent = fake.messages.stream.call_args.kwargs["messages"][0]["content"][0]
        assert sent["source"]["media_type"] in {"image/png", "image/jpeg"}


class TestRequestShape:
    """What the client actually sends."""

    async def test_sends_the_sketch_as_a_base64_image_block(self) -> None:
        """The sketch is uploaded inline, base64-encoded, as the first content block."""
        fake = fake_anthropic(message_with(VALID_OUTPUT))
        await SketchRedrawClient(SketchConfig(api_key="k"), client=fake).redraw(
            PNG, "image/png", "Seat the part", "Clean both faces."
        )
        content = fake.messages.stream.call_args.kwargs["messages"][0]["content"]
        assert content[0]["type"] == "image"
        assert content[0]["source"]["data"] == base64.standard_b64encode(PNG).decode()

    async def test_sends_the_step_context_so_ambiguity_can_be_resolved(self) -> None:
        """The step's title and instructions accompany the drawing.

        A sketch alone is often ambiguous about what matters in it; the instructions are
        what let the model choose the reading the author meant.
        """
        fake = fake_anthropic(message_with(VALID_OUTPUT))
        await SketchRedrawClient(SketchConfig(api_key="k"), client=fake).redraw(
            PNG, "image/png", "Seat the part", "Clean both faces."
        )
        text = fake.messages.stream.call_args.kwargs["messages"][0]["content"][1]["text"]
        assert "Seat the part" in text
        assert "Clean both faces." in text

    async def test_uses_the_versioned_house_style_prompt_as_system(self) -> None:
        """The system prompt is the versioned file, not an inline string."""
        fake = fake_anthropic(message_with(VALID_OUTPUT))
        await SketchRedrawClient(SketchConfig(api_key="k"), client=fake).redraw(
            PNG, "image/png", "Step", "Instructions"
        )
        assert fake.messages.stream.call_args.kwargs["system"] == load_prompt("blueprint-v1")

    async def test_requests_structured_output_and_adaptive_thinking(self) -> None:
        """Structured output makes parsing a schema check rather than a heuristic."""
        fake = fake_anthropic(message_with(VALID_OUTPUT))
        config = SketchConfig(api_key="k", model="claude-opus-5", effort="high")
        await SketchRedrawClient(config, client=fake).redraw(
            PNG, "image/png", "Step", "Instructions"
        )
        kwargs = fake.messages.stream.call_args.kwargs
        assert kwargs["model"] == "claude-opus-5"
        assert kwargs["output_format"] is RedrawOutput
        assert kwargs["output_config"] == {"effort": "high"}
        assert kwargs["thinking"] == {"type": "adaptive"}

    async def test_streams_rather_than_blocking(self) -> None:
        """SVG output is long enough that a non-streamed call risks an HTTP timeout."""
        fake = fake_anthropic(message_with(VALID_OUTPUT))
        await SketchRedrawClient(SketchConfig(api_key="k"), client=fake).redraw(
            PNG, "image/png", "Step", "Instructions"
        )
        fake.messages.stream.assert_called_once()
        fake.messages.create.assert_not_called()


class TestResponseHandling:
    """What the client makes of the reply."""

    async def test_returns_the_parsed_drawing_and_callouts(self) -> None:
        """A successful redraw comes back as structured data, not prose."""
        fake = fake_anthropic(message_with(VALID_OUTPUT))
        result = await SketchRedrawClient(SketchConfig(api_key="k"), client=fake).redraw(
            PNG, "image/png", "Step", "Instructions"
        )
        assert result.svg == SAMPLE_SVG
        assert result.suggested_callouts[0].label == "Burr side up."
        assert result.confidence == pytest.approx(0.82)

    async def test_a_refusal_is_surfaced_not_swallowed(self) -> None:
        """A policy decline is reported so the author sees why nothing was drawn."""
        fake = fake_anthropic(message_with(None, stop_reason="refusal"))
        client = SketchRedrawClient(SketchConfig(api_key="k"), client=fake)
        with pytest.raises(SketchRefusedError, match="declined"):
            await client.redraw(PNG, "image/png", "Step", "Instructions")

    async def test_a_response_with_no_drawing_is_an_error(self) -> None:
        """A reply that parsed to nothing is a failure, not an empty drawing."""
        fake = fake_anthropic(message_with(None))
        client = SketchRedrawClient(SketchConfig(api_key="k"), client=fake)
        with pytest.raises(SketchRefusedError, match="no structured drawing"):
            await client.redraw(PNG, "image/png", "Step", "Instructions")


class TestPromptVersioning:
    """The house-style prompt is a versioned artefact."""

    def test_loads_the_named_version(self) -> None:
        """The shipped prompt is real and non-trivial."""
        assert "viewBox" in load_prompt("blueprint-v1")

    def test_unknown_version_is_an_error(self) -> None:
        """A misconfigured version fails loudly rather than silently prompting nothing."""
        with pytest.raises(SketchError, match="no house-style prompt"):
            load_prompt("does-not-exist")
