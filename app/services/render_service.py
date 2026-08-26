"""Producing the PDF."""

from __future__ import annotations

from datetime import datetime, timezone

from app.config.schema import RenderConfig
from app.rendering.render import StepArt, render_html, render_pdf
from app.repositories.protocols import RenderRepository
from app.schemas.assets import RenderCreateInternal, RenderRead, RevisionDocument
from app.schemas.enums import AssetKind
from app.services.asset_service import AssetService
from app.services.document_service import DocumentService
from app.services.errors import RenderNotPossibleError
from app.storage import AssetNotFoundError


class RenderService:
    """Turns a stored revision into a stored PDF."""

    def __init__(
        self,
        documents: DocumentService,
        assets: AssetService,
        renders: RenderRepository,
        config: RenderConfig,
    ) -> None:
        """Bind the service to its collaborators.

        Args:
            documents: Assembles the printable revision.
            assets: Reads step drawings and stores the finished PDF.
            renders: Records each produced PDF.
            config: Render settings, including the house style.
        """
        self._documents = documents
        self._assets = assets
        self._renders = renders
        self._config = config

    async def _collect_art(self, document: RevisionDocument) -> dict[int, StepArt]:
        """Load every step's drawing.

        Args:
            document: The assembled revision.

        Returns:
            dict[int, StepArt]: Drawings keyed by step id. Steps with no drawing are
            simply absent, and render an empty plate rather than failing the whole sheet.

        Raises:
            RenderNotPossibleError: If a step references a drawing whose bytes are missing
                from the store — a silently blank plate on a procedure sheet is worse than
                a refused render.
        """
        art: dict[int, StepArt] = {}
        for step in document.steps:
            if step.image_asset_id is None:
                continue
            try:
                asset, data = await self._assets.read(step.image_asset_id)
            except AssetNotFoundError as exc:
                raise RenderNotPossibleError(
                    f"step {step.position} references asset {step.image_asset_id}, "
                    f"whose file is missing from the store"
                ) from exc
            art[step.id] = StepArt(content_type=asset.content_type, data=data)
        return art

    async def _logo(self) -> StepArt | None:
        """Load the configured logo, if there is one.

        Returns:
            StepArt | None: The logo bytes, or ``None`` when unset or unreadable. A
            missing logo degrades the sheet's appearance but must not block issuing it.
        """
        path = self._config.style.logo_path
        if path is None or not path.is_file():
            return None
        suffix = path.suffix.lower()
        content_type = "image/svg+xml" if suffix == ".svg" else "image/png"
        return StepArt(content_type=content_type, data=path.read_bytes())

    async def build_html(self, revision_id: int) -> str:
        """Assemble the sheet HTML for a revision, without rendering a PDF.

        Useful for previewing a layout change without paying for a full render.

        Args:
            revision_id: The revision to lay out.

        Returns:
            str: A self-contained HTML document.
        """
        document = await self._documents.build(revision_id)
        return render_html(
            document, self._config, await self._collect_art(document), await self._logo()
        )

    async def render(self, revision_id: int) -> RenderRead:
        """Render a revision to a stored PDF.

        Args:
            revision_id: The revision to render.

        Returns:
            RenderRead: The recorded render, pointing at the stored PDF asset.

        Raises:
            NotFoundError: If the revision does not exist.
            RenderNotPossibleError: If a referenced drawing is missing from the store.
        """
        document = await self._documents.build(revision_id)
        html = render_html(
            document, self._config, await self._collect_art(document), await self._logo()
        )
        rendered = render_pdf(html)

        asset = await self._assets.store_bytes(
            rendered.data,
            AssetKind.PDF,
            "application/pdf",
            original_filename=(f"{document.guide.doc_number}-rev{document.revision.rev_label}.pdf"),
        )

        # `template_version` alongside the revision is what makes a PDF in the wild
        # traceable: the same revision rendered under a restyled template is a different
        # document, and without this there is no way to tell which one someone is holding.
        return await self._renders.create(
            RenderCreateInternal(
                revision_id=revision_id,
                pdf_asset_id=asset.id,
                template_version=self._config.template_version,
                page_count=rendered.page_count,
                rendered_at=datetime.now(timezone.utc),
            )
        )

    async def list_for_revision(self, revision_id: int) -> list[RenderRead]:
        """List a revision's renders, newest first.

        Args:
            revision_id: The revision's primary key.

        Returns:
            list[RenderRead]: The recorded renders.
        """
        return await self._renders.list_for_revision(revision_id)

    async def latest(self, revision_id: int) -> RenderRead | None:
        """Return a revision's most recent render.

        Args:
            revision_id: The revision's primary key.

        Returns:
            RenderRead | None: The latest render, or ``None``.
        """
        return await self._renders.latest_for_revision(revision_id)
