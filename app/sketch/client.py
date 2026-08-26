"""The Claude-backed sketch redraw.

Claude has vision input and writes the house-style SVG as text; there is no image
generation involved. Vector output is the right answer for a drawing plate — it stays crisp
at print resolution, diffs meaningfully, and can be re-styled without another model call.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Literal, cast

import anthropic
from anthropic.types import (
    ImageBlockParam,
    MessageParam,
    OutputConfigParam,
    TextBlockParam,
)
from pydantic import BaseModel, Field

from app.config.schema import SketchConfig
from app.schemas.enums import LeaderDir

PROMPT_DIR = Path(__file__).parent / "prompts"

SupportedMediaType = Literal["image/png", "image/jpeg", "image/gif", "image/webp"]
SUPPORTED_MEDIA_TYPES: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/gif", "image/webp"}
)


class SketchError(Exception):
    """Base class for redraw failures."""


class SketchDisabledError(SketchError):
    """Redraw is switched off in configuration."""


class UnsupportedSketchFormatError(SketchError):
    """The uploaded sketch is not in a format the model accepts as an image."""


class SketchRefusedError(SketchError):
    """The model declined to produce a drawing."""


class SuggestedCallout(BaseModel):
    """A callout the model proposes for the redrawn plate.

    Attributes:
        index: Reading order, starting at 1.
        x_pct: Anchor position across the drawing, 0-100.
        y_pct: Anchor position down the drawing, 0-100.
        leader_dir: Which way the leader line runs from the bubble.
        label: Short imperative note printed in the callout key.
    """

    index: int = Field(ge=1)
    x_pct: float = Field(ge=0.0, le=100.0)
    y_pct: float = Field(ge=0.0, le=100.0)
    leader_dir: LeaderDir
    label: str


class RedrawOutput(BaseModel):
    """The structured result of one redraw.

    Structured output is used rather than prose-with-an-SVG-in-it so parsing is a schema
    check instead of a heuristic, and so callouts arrive as data the author can edit.

    Attributes:
        svg: The redrawn line art. Sanitised before it is stored.
        suggested_callouts: Callouts the model proposes; the author may keep or drop them.
        notes: What the model assumed where the sketch was ambiguous.
        confidence: The model's own estimate of fidelity, 0-1.
    """

    svg: str
    suggested_callouts: list[SuggestedCallout] = Field(default_factory=list)
    notes: str = ""
    confidence: float = Field(ge=0.0, le=1.0)


def load_prompt(version: str) -> str:
    """Load a versioned house-style prompt from disk.

    The prompt is a file rather than a string literal so its version can be recorded on
    each job — that is what tells us later which drawings predate a style change.

    Args:
        version: Prompt version, e.g. ``blueprint-v1``.

    Returns:
        str: The prompt text.

    Raises:
        SketchError: If no prompt file exists for that version.
    """
    path = PROMPT_DIR / f"{version.replace('-', '_')}.md"
    if not path.is_file():
        raise SketchError(f"no house-style prompt for version {version!r}")
    return path.read_text(encoding="utf-8")


class SketchRedrawClient:
    """Turns a hand-drawn sketch into house-style SVG line art."""

    def __init__(
        self,
        config: SketchConfig,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        """Build a redraw client.

        Args:
            config: Sketch configuration — model, effort, ceilings, prompt version.
            client: An Anthropic client to use. Injected in tests; when omitted, one is
                built lazily so importing this module never requires credentials.
        """
        self._config = config
        self._client = client

    def _anthropic(self) -> anthropic.AsyncAnthropic:
        """Return the Anthropic client, constructing it on first use.

        Returns:
            anthropic.AsyncAnthropic: The client.
        """
        if self._client is None:
            # A bare constructor is correct here: with no api_key the SDK still resolves
            # ANTHROPIC_AUTH_TOKEN or a logged-in profile, so passing None explicitly
            # would be no better and passing "" would break those paths.
            self._client = (
                anthropic.AsyncAnthropic(api_key=self._config.api_key)
                if self._config.api_key
                else anthropic.AsyncAnthropic()
            )
        return self._client

    async def redraw(
        self,
        image_bytes: bytes,
        media_type: str,
        step_title: str,
        instructions: str,
    ) -> RedrawOutput:
        """Redraw one sketch in the house style.

        Args:
            image_bytes: The uploaded sketch.
            media_type: Its MIME type; must be one the model accepts as an image.
            step_title: The step's title, used to disambiguate what is being drawn.
            instructions: The step's instructions, for the same reason.

        Returns:
            RedrawOutput: The SVG, proposed callouts, assumptions, and confidence.

        Raises:
            SketchDisabledError: If redraw is switched off.
            UnsupportedSketchFormatError: If the media type is not an accepted image type.
            SketchRefusedError: If the model declined, or returned no parsed output.
        """
        if not self._config.enabled:
            raise SketchDisabledError("sketch redraw is disabled in this environment")

        normalised = media_type.split(";")[0].strip().lower()
        if normalised not in SUPPORTED_MEDIA_TYPES:
            raise UnsupportedSketchFormatError(
                f"{media_type!r} is not a supported sketch format; "
                f"use one of {sorted(SUPPORTED_MEDIA_TYPES)}"
            )

        system = load_prompt(self._config.prompt_version)
        encoded = base64.standard_b64encode(image_bytes).decode("ascii")

        sketch_block: ImageBlockParam = {
            "type": "image",
            # The membership check above is what makes this narrowing sound.
            "source": {
                "type": "base64",
                "media_type": cast(SupportedMediaType, normalised),
                "data": encoded,
            },
        }
        context_block: TextBlockParam = {
            "type": "text",
            "text": (
                f"Step title: {step_title}\n\n"
                f"Step instructions:\n{instructions or '(none supplied)'}\n\n"
                "Redraw the sketch above as house-style line art."
            ),
        }
        message_param: MessageParam = {
            "role": "user",
            "content": [sketch_block, context_block],
        }
        output_config: OutputConfigParam = {"effort": self._config.effort}

        client = self._anthropic()
        # Streamed: SVG line art is long output, and a non-streamed request at this
        # max_tokens risks an HTTP timeout rather than a useful error.
        async with client.messages.stream(
            model=self._config.model,
            max_tokens=self._config.max_tokens,
            system=system,
            thinking={"type": "adaptive"},
            output_config=output_config,
            output_format=RedrawOutput,
            timeout=self._config.timeout_seconds,
            messages=[message_param],
        ) as stream:
            message = await stream.get_final_message()

        if message.stop_reason == "refusal":
            detail = getattr(message.stop_details, "explanation", None) or "no explanation given"
            raise SketchRefusedError(f"the model declined to redraw this sketch: {detail}")

        for block in message.content:
            parsed = getattr(block, "parsed_output", None)
            if isinstance(parsed, RedrawOutput):
                return parsed

        raise SketchRefusedError(
            f"no structured drawing in the response (stop_reason={message.stop_reason})"
        )
