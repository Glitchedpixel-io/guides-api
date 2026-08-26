"""The HTTP surface for sketch redraw and rendering."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.repositories.errors import NotFoundError
from app.schemas.assets import AssetRead, RenderRead, SketchJobRead
from app.schemas.enums import AssetKind, SketchJobStatus
from app.services.errors import RenderNotPossibleError, SketchUnavailableError
from app.sketch.client import UnsupportedSketchFormatError
from app.storage import AssetTooLargeError
from tests.factories import NOW

pytestmark = pytest.mark.api


def make_job(**overrides: object) -> SketchJobRead:
    """Build a redraw job read model.

    Args:
        **overrides: Field values to replace.

    Returns:
        SketchJobRead: The fixture job.
    """
    data: dict[str, object] = {
        "id": 1,
        "step_id": 101,
        "source_asset_id": 500,
        "result_asset_id": None,
        "status": SketchJobStatus.PENDING,
        "model": "claude-opus-5",
        "prompt_version": "blueprint-v1",
        "notes": "",
        "error": None,
        "completed_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    data.update(overrides)
    return SketchJobRead(**data)  # type: ignore[arg-type]


class TestSketchRedraw:
    """Upload, poll, review, promote."""

    async def test_upload_is_accepted_not_completed(
        self, client: AsyncClient, sketch_service: AsyncMock
    ) -> None:
        """A redraw takes tens of seconds, so the call returns 202 with a job handle.

        Args:
            client: The API client.
            sketch_service: Faked sketch service.
        """
        sketch_service.queue.return_value = make_job()
        response = await client.post(
            "/api/steps/101/sketch",
            files={"file": ("sketch.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
        )
        assert response.status_code == 202
        assert response.json()["status"] == "pending"

    async def test_upload_schedules_the_redraw_in_the_background(
        self, client: AsyncClient, sketch_service: AsyncMock
    ) -> None:
        """The request does not block on the model call.

        Args:
            client: The API client.
            sketch_service: Faked sketch service.
        """
        sketch_service.queue.return_value = make_job(id=42)
        await client.post(
            "/api/steps/101/sketch",
            files={"file": ("s.png", b"bytes", "image/png")},
        )
        sketch_service.run.assert_awaited_once_with(42)

    async def test_unsupported_format_is_refused_at_upload(
        self, client: AsyncClient, sketch_service: AsyncMock
    ) -> None:
        """A file the model cannot read is rejected now, not by a failed job later.

        Args:
            client: The API client.
            sketch_service: Faked sketch service.
        """
        sketch_service.queue.side_effect = UnsupportedSketchFormatError("svg is not a sketch")
        response = await client.post(
            "/api/steps/101/sketch",
            files={"file": ("drawing.svg", b"<svg/>", "image/svg+xml")},
        )
        assert response.status_code == 400
        sketch_service.run.assert_not_awaited()

    async def test_disabled_redraw_is_service_unavailable(
        self, client: AsyncClient, sketch_service: AsyncMock
    ) -> None:
        """A disabled environment declines with 503 rather than a generic error.

        Args:
            client: The API client.
            sketch_service: Faked sketch service.
        """
        sketch_service.queue.side_effect = SketchUnavailableError("disabled")
        response = await client.post(
            "/api/steps/101/sketch", files={"file": ("s.png", b"x", "image/png")}
        )
        assert response.status_code == 503

    async def test_oversized_sketch_is_rejected(
        self, client: AsyncClient, sketch_service: AsyncMock
    ) -> None:
        """An upload past the ceiling maps to 413.

        Args:
            client: The API client.
            sketch_service: Faked sketch service.
        """
        sketch_service.queue.side_effect = AssetTooLargeError("too big")
        response = await client.post(
            "/api/steps/101/sketch", files={"file": ("s.png", b"x", "image/png")}
        )
        assert response.status_code == 413

    async def test_failed_job_reports_its_error(
        self, client: AsyncClient, sketch_service: AsyncMock
    ) -> None:
        """A refusal is visible to the author on the job, not swallowed.

        Args:
            client: The API client.
            sketch_service: Faked sketch service.
        """
        sketch_service.get.return_value = make_job(
            status=SketchJobStatus.FAILED, error="the model declined"
        )
        response = await client.get("/api/sketch-jobs/1")
        assert response.status_code == 200
        assert response.json()["error"] == "the model declined"

    async def test_approving_an_unfinished_job_is_refused(
        self, client: AsyncClient, sketch_service: AsyncMock
    ) -> None:
        """There is nothing to promote until the job succeeded.

        Args:
            client: The API client.
            sketch_service: Faked sketch service.
        """
        sketch_service.approve.side_effect = SketchUnavailableError("no drawing")
        response = await client.post("/api/sketch-jobs/1/approve")
        assert response.status_code == 503

    async def test_approve_promotes_the_drawing(
        self, client: AsyncClient, sketch_service: AsyncMock
    ) -> None:
        """Promotion is the explicit human step between redraw and sheet.

        Args:
            client: The API client.
            sketch_service: Faked sketch service.
        """
        sketch_service.approve.return_value = make_job(
            status=SketchJobStatus.SUCCEEDED, result_asset_id=777
        )
        response = await client.post("/api/sketch-jobs/1/approve")
        assert response.status_code == 200
        sketch_service.approve.assert_awaited_once_with(1)


class TestRendering:
    """Rendering and download."""

    @staticmethod
    def _render() -> RenderRead:
        """Build a render read model.

        Returns:
            RenderRead: The fixture render.
        """
        return RenderRead(
            id=1,
            revision_id=10,
            pdf_asset_id=900,
            template_version="blueprint-1.0",
            page_count=4,
            rendered_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        )

    async def test_render_records_the_template_version(
        self, client: AsyncClient, render_service: AsyncMock
    ) -> None:
        """A PDF is traceable to the template as well as the revision.

        The same revision under a restyled template is a different document; without the
        template version there is no way to tell which one someone is holding.

        Args:
            client: The API client.
            render_service: Faked render service.
        """
        render_service.render.return_value = self._render()
        response = await client.post("/api/revisions/10/render")
        assert response.status_code == 201
        body = response.json()
        assert body["template_version"] == "blueprint-1.0"
        assert body["page_count"] == 4

    async def test_missing_drawing_refuses_the_render(
        self, client: AsyncClient, render_service: AsyncMock
    ) -> None:
        """A silently blank plate on a procedure sheet is worse than a refusal.

        Args:
            client: The API client.
            render_service: Faked render service.
        """
        render_service.render.side_effect = RenderNotPossibleError("asset 5 missing")
        response = await client.post("/api/revisions/10/render")
        assert response.status_code == 400

    async def test_download_before_any_render_is_a_404(
        self, client: AsyncClient, render_service: AsyncMock
    ) -> None:
        """Asking for a sheet that was never produced is a 404, not an empty PDF.

        Args:
            client: The API client.
            render_service: Faked render service.
        """
        render_service.latest.return_value = None
        response = await client.get("/api/revisions/10/sheet.pdf")
        assert response.status_code == 404

    async def test_download_returns_the_pdf_bytes(
        self, client: AsyncClient, render_service: AsyncMock, asset_service: AsyncMock
    ) -> None:
        """The latest render is served with its content type and filename.

        Args:
            client: The API client.
            render_service: Faked render service.
            asset_service: Faked asset service.
        """
        render_service.latest.return_value = self._render()
        asset_service.read.return_value = (
            AssetRead(
                id=900,
                kind=AssetKind.PDF,
                content_type="application/pdf",
                storage_path="ab/cd/x.pdf",
                sha256="0" * 64,
                byte_size=9,
                original_filename="MSO-114-revC.pdf",
                created_at=NOW,
                updated_at=NOW,
            ),
            b"%PDF-1.7\n",
        )
        response = await client.get("/api/revisions/10/sheet.pdf")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "MSO-114-revC.pdf" in response.headers["content-disposition"]
        assert response.content.startswith(b"%PDF")

    async def test_html_preview_is_served_for_template_work(
        self, client: AsyncClient, render_service: AsyncMock
    ) -> None:
        """The preview is exactly what WeasyPrint is handed.

        Args:
            client: The API client.
            render_service: Faked render service.
        """
        render_service.build_html.return_value = "<!DOCTYPE html><html></html>"
        response = await client.get("/api/revisions/10/preview.html")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")

    async def test_unknown_asset_is_a_404(
        self, client: AsyncClient, asset_service: AsyncMock
    ) -> None:
        """A missing asset is the caller's mistake.

        Args:
            client: The API client.
            asset_service: Faked asset service.
        """
        asset_service.get.side_effect = NotFoundError("asset 5 not found")
        response = await client.get("/api/assets/5")
        assert response.status_code == 404
