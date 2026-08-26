"""Assembles the whole printable document for a revision."""

from __future__ import annotations

from app.repositories.protocols import (
    BomItemRepository,
    GuideRepository,
    RequiredToolRepository,
    RevisionRepository,
    SafetyWarningRepository,
    StepRepository,
)
from app.schemas.assets import RevisionDocument, RevisionHistoryEntry


class DocumentService:
    """Gathers a revision and everything printed alongside it.

    This is the single input to the renderer, which is what lets the template be tested
    without a database.
    """

    def __init__(
        self,
        guides: GuideRepository,
        revisions: RevisionRepository,
        steps: StepRepository,
        bom_items: BomItemRepository,
        required_tools: RequiredToolRepository,
        safety_warnings: SafetyWarningRepository,
    ) -> None:
        """Bind the service to every repository the sheet draws from.

        Args:
            guides: Storage for guide identities.
            revisions: Storage for revisions.
            steps: Storage for steps and callouts.
            bom_items: Storage for bill-of-materials lines.
            required_tools: Storage for required tools.
            safety_warnings: Storage for safety warnings.
        """
        self._guides = guides
        self._revisions = revisions
        self._steps = steps
        self._bom_items = bom_items
        self._required_tools = required_tools
        self._safety_warnings = safety_warnings

    async def build(self, revision_id: int) -> RevisionDocument:
        """Assemble the printable document for one revision.

        Args:
            revision_id: The revision to assemble.

        Returns:
            RevisionDocument: Everything the sheet prints.

        Raises:
            NotFoundError: If the revision does not exist.
        """
        revision = await self._revisions.get(revision_id)
        guide = await self._guides.get(revision.guide_id)

        # The printed revision history is every revision of this guide up to and including
        # this one. Later revisions are deliberately excluded: a sheet must not claim
        # knowledge of edits made after it was issued.
        siblings = await self._revisions.list_for_guide(revision.guide_id)
        history = [
            RevisionHistoryEntry(
                rev_label=entry.rev_label,
                revision_date=entry.revision_date,
                change_note=entry.change_note,
                author_byline=entry.author_byline,
            )
            for entry in siblings
            if (entry.revision_date, entry.id) <= (revision.revision_date, revision.id)
        ]

        return RevisionDocument(
            guide=guide,
            revision=revision,
            steps=await self._steps.list_for_revision(revision_id),
            bom_items=await self._bom_items.list_for_revision(revision_id),
            required_tools=await self._required_tools.list_for_revision(revision_id),
            safety_warnings=await self._safety_warnings.list_for_revision(revision_id),
            history=history,
        )
