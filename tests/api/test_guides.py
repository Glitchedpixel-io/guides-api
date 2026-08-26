"""The HTTP surface for guides, revisions, and content."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.repositories.errors import DuplicateEntityError, NotFoundError
from app.schemas.enums import RevisionStatus
from app.services.errors import InvalidTransitionError, RevisionNotEditableError
from tests.factories import make_guide, make_revision, make_step

pytestmark = pytest.mark.api


class TestHealth:
    """Liveness and build identity."""

    async def test_reports_the_running_template_version(self, client: AsyncClient) -> None:
        """Two instances on different template versions render different sheets.

        That difference is invisible without this, so health carries it.

        Args:
            client: The API client.
        """
        response = await client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["template_version"] == "blueprint-1.0"


class TestGuides:
    """Guide CRUD."""

    async def test_create_returns_201(self, client: AsyncClient, guide_service: AsyncMock) -> None:
        """A created guide comes back with its stored representation.

        Args:
            client: The API client.
            guide_service: Faked guide service.
        """
        guide_service.create.return_value = make_guide()
        response = await client.post(
            "/api/guides/",
            json={
                "slug": "hole-pattern-measurement",
                "doc_number": "MSO-114",
                "title": "Hole Pattern Measurement Chevron Plate Flat Steel",
                "title_break_after": 3,
            },
        )
        assert response.status_code == 201
        assert response.json()["doc_number"] == "MSO-114"

    async def test_rejects_a_slug_that_is_not_kebab_case(self, client: AsyncClient) -> None:
        """A slug that would not survive a URL is refused at the edge.

        Args:
            client: The API client.
        """
        response = await client.post(
            "/api/guides/",
            json={"slug": "Not A Slug", "doc_number": "X", "title": "T"},
        )
        assert response.status_code == 422

    async def test_rejects_unknown_fields(self, client: AsyncClient) -> None:
        """``extra="forbid"`` means a typo is an error, not a silently ignored field.

        Args:
            client: The API client.
        """
        response = await client.post(
            "/api/guides/",
            json={"slug": "ok", "doc_number": "X", "title": "T", "titel": "typo"},
        )
        assert response.status_code == 422

    async def test_duplicate_slug_is_a_conflict(
        self, client: AsyncClient, guide_service: AsyncMock
    ) -> None:
        """A taken slug maps to 409, not 500.

        Args:
            client: The API client.
            guide_service: Faked guide service.
        """
        guide_service.create.side_effect = DuplicateEntityError("slug taken")
        response = await client.post(
            "/api/guides/", json={"slug": "taken", "doc_number": "X", "title": "T"}
        )
        assert response.status_code == 409

    async def test_missing_guide_is_a_404(
        self, client: AsyncClient, guide_service: AsyncMock
    ) -> None:
        """An unknown id is the caller's mistake, reported as 404.

        Args:
            client: The API client.
            guide_service: Faked guide service.
        """
        guide_service.get.side_effect = NotFoundError("guide 99 not found")
        response = await client.get("/api/guides/99")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    async def test_delete_returns_204_with_no_body(
        self, client: AsyncClient, guide_service: AsyncMock
    ) -> None:
        """A 204 must not carry a body; HTTP forbids one.

        Args:
            client: The API client.
            guide_service: Faked guide service.
        """
        guide_service.delete.return_value = None
        response = await client.delete("/api/guides/1")
        assert response.status_code == 204
        assert response.content == b""


class TestRevisionLifecycle:
    """Publishing and the frozen-content rule, over HTTP."""

    async def test_publish_returns_the_published_revision(
        self, client: AsyncClient, revision_service: AsyncMock
    ) -> None:
        """Publishing succeeds from a draft.

        Args:
            client: The API client.
            revision_service: Faked revision service.
        """
        revision_service.publish.return_value = make_revision(status=RevisionStatus.PUBLISHED)
        response = await client.post("/api/revisions/10/publish")
        assert response.status_code == 200
        assert response.json()["status"] == "published"

    async def test_publishing_twice_is_a_conflict(
        self, client: AsyncClient, revision_service: AsyncMock
    ) -> None:
        """The request is well formed; it is the state that refuses it.

        Args:
            client: The API client.
            revision_service: Faked revision service.
        """
        revision_service.publish.side_effect = InvalidTransitionError("already published")
        response = await client.post("/api/revisions/10/publish")
        assert response.status_code == 409

    async def test_editing_published_content_is_a_conflict(
        self, client: AsyncClient, step_service: AsyncMock
    ) -> None:
        """Adding a step to an issued revision is refused with 409.

        Args:
            client: The API client.
            step_service: Faked step service.
        """
        step_service.add.side_effect = RevisionNotEditableError("revision 10 is published")
        response = await client.post("/api/revisions/10/steps", json={"title": "Too late"})
        assert response.status_code == 409


class TestSteps:
    """Steps, ordering, and callouts."""

    async def test_add_step_returns_201(self, client: AsyncClient, step_service: AsyncMock) -> None:
        """A step is appended and returned.

        Args:
            client: The API client.
            step_service: Faked step service.
        """
        step_service.add.return_value = make_step(1)
        response = await client.post(
            "/api/revisions/10/steps",
            json={"title": "Seat the part", "instructions": "Clean it.", "est_minutes": 6},
        )
        assert response.status_code == 201
        assert response.json()["position"] == 1

    async def test_step_position_cannot_be_set_directly(self, client: AsyncClient) -> None:
        """Position is owned by append and reorder, so the create schema forbids it.

        Args:
            client: The API client.
        """
        response = await client.post("/api/revisions/10/steps", json={"title": "X", "position": 3})
        assert response.status_code == 422

    async def test_reorder_takes_a_complete_ordering(
        self, client: AsyncClient, step_service: AsyncMock
    ) -> None:
        """The reorder endpoint passes the whole permutation through.

        Args:
            client: The API client.
            step_service: Faked step service.
        """
        step_service.reorder.return_value = [make_step(1), make_step(2)]
        response = await client.post(
            "/api/revisions/10/steps/reorder",
            json={"items": [{"id": 101, "position": 2}, {"id": 102, "position": 1}]},
        )
        assert response.status_code == 200
        assert step_service.reorder.await_args.args[1].items[0].id == 101

    async def test_callout_coordinates_are_bounded(self, client: AsyncClient) -> None:
        """A callout outside the plate would be drawn off the drawing.

        Args:
            client: The API client.
        """
        response = await client.post(
            "/api/steps/101/callouts",
            json={"index": 1, "x_pct": 150, "y_pct": 10, "label": "off-plate"},
        )
        assert response.status_code == 422

    async def test_setting_an_image_returns_the_updated_step(
        self, client: AsyncClient, step_service: AsyncMock
    ) -> None:
        """Attaching a drawing goes through the service, which clears stale callouts.

        Args:
            client: The API client.
            step_service: Faked step service.
        """
        step_service.set_image.return_value = make_step(1, image_asset_id=777)
        response = await client.put("/api/steps/101/image/777")
        assert response.status_code == 200
        step_service.set_image.assert_awaited_once_with(101, 777)


class TestFrontMatterBlocks:
    """The three optional panels."""

    @pytest.mark.parametrize(
        ("path", "payload"),
        [
            ("bom", {"description": "Chevron plate specimen", "quantity": "1"}),
            ("tools", {"name": "Caliper, digital", "spec": "0.01 mm"}),
            ("warnings", {"severity": "warning", "text": "Sheared edges cut."}),
        ],
    )
    async def test_each_block_accepts_an_entry(
        self, client: AsyncClient, block_service: AsyncMock, path: str, payload: dict
    ) -> None:
        """All three panels expose the same add shape.

        Args:
            client: The API client.
            block_service: Faked block service.
            path: The panel's path segment.
            payload: A valid entry for that panel.
        """
        block_service.add.return_value = {
            "id": 1,
            "revision_id": 10,
            "position": 1,
            **payload,
        }
        response = await client.post(f"/api/revisions/10/{path}", json=payload)
        assert response.status_code == 201

    async def test_severity_is_constrained_to_the_signal_words(self, client: AsyncClient) -> None:
        """Severity follows ANSI Z535; an invented level is refused.

        Args:
            client: The API client.
        """
        response = await client.post(
            "/api/revisions/10/warnings", json={"severity": "extremely-bad", "text": "x"}
        )
        assert response.status_code == 422
