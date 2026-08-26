"""Repository behaviour against a real Postgres schema."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.block_repo import SQLAlchemyBomItemRepository
from app.repositories.errors import DuplicateEntityError, InvalidDataError, NotFoundError
from app.repositories.guide_repo import SQLAlchemyGuideRepository, SQLAlchemyRevisionRepository
from app.repositories.step_repo import SQLAlchemyStepRepository
from app.schemas.blocks import BomItemCreateInternal
from app.schemas.guides import GuideCreateInternal, GuidePatchInternal, RevisionCreateInternal
from app.schemas.steps import CalloutCreateInternal, StepCreateInternal

pytestmark = [pytest.mark.integration]


async def _guide(session: AsyncSession, slug: str = "hole-pattern") -> int:
    """Create a guide and return its id.

    Args:
        session: The test session.
        slug: The guide's slug.

    Returns:
        int: The new guide's primary key.
    """
    guide = await SQLAlchemyGuideRepository(session).create(
        GuideCreateInternal(slug=slug, doc_number="MSO-114", title="Hole Pattern Measurement")
    )
    return guide.id


async def _revision(session: AsyncSession, guide_id: int, label: str = "A") -> int:
    """Create a revision and return its id.

    Args:
        session: The test session.
        guide_id: The owning guide.
        label: The revision label.

    Returns:
        int: The new revision's primary key.
    """
    revision = await SQLAlchemyRevisionRepository(session).create(
        RevisionCreateInternal(
            guide_id=guide_id,
            rev_label=label,
            revision_date=date(2026, 8, 26),
            author_byline="R. Vane",
        )
    )
    return revision.id


class TestGuideRepository:
    """Guide persistence."""

    async def test_round_trips_a_guide(self, db_session: AsyncSession) -> None:
        """A stored guide reads back with server-set timestamps.

        Args:
            db_session: The test session.
        """
        repo = SQLAlchemyGuideRepository(db_session)
        created = await repo.create(
            GuideCreateInternal(slug="a-slug", doc_number="D-1", title="A Title")
        )
        fetched = await repo.get(created.id)
        assert fetched.slug == "a-slug"
        assert fetched.created_at is not None

    async def test_slug_is_unique(self, db_session: AsyncSession) -> None:
        """A duplicate slug surfaces as a domain error, not a driver exception.

        Args:
            db_session: The test session.
        """
        repo = SQLAlchemyGuideRepository(db_session)
        await repo.create(GuideCreateInternal(slug="dup", doc_number="D", title="T"))
        with pytest.raises(DuplicateEntityError):
            await repo.create(GuideCreateInternal(slug="dup", doc_number="E", title="U"))

    async def test_partial_update_leaves_other_fields_alone(self, db_session: AsyncSession) -> None:
        """An unset field is untouched rather than nulled.

        Args:
            db_session: The test session.
        """
        repo = SQLAlchemyGuideRepository(db_session)
        created = await repo.create(
            GuideCreateInternal(slug="s", doc_number="D-9", title="Original")
        )
        updated = await repo.update(created.id, GuidePatchInternal(title="Changed"))
        assert updated.title == "Changed"
        assert updated.doc_number == "D-9"

    async def test_missing_guide_raises(self, db_session: AsyncSession) -> None:
        """An absent row is a domain NotFoundError.

        Args:
            db_session: The test session.
        """
        with pytest.raises(NotFoundError):
            await SQLAlchemyGuideRepository(db_session).get(999_999)

    async def test_deleting_a_guide_cascades_to_revisions(self, db_session: AsyncSession) -> None:
        """A guide's revisions do not outlive it.

        Args:
            db_session: The test session.
        """
        guide_id = await _guide(db_session, "cascade-me")
        await _revision(db_session, guide_id)
        await SQLAlchemyGuideRepository(db_session).delete(guide_id)
        assert await SQLAlchemyRevisionRepository(db_session).list_for_guide(guide_id) == []


class TestStepOrdering:
    """Strict step order, enforced by the database."""

    async def test_appending_assigns_sequential_positions(self, db_session: AsyncSession) -> None:
        """Steps land in the order they were added.

        Args:
            db_session: The test session.
        """
        revision_id = await _revision(db_session, await _guide(db_session, "order-1"))
        repo = SQLAlchemyStepRepository(db_session)
        for title in ("First", "Second", "Third"):
            await repo.append(
                revision_id,
                StepCreateInternal(revision_id=revision_id, position=0, title=title),
            )
        steps = await repo.list_for_revision(revision_id)
        assert [s.position for s in steps] == [1, 2, 3]
        assert [s.title for s in steps] == ["First", "Second", "Third"]

    async def test_reorder_survives_a_swap(self, db_session: AsyncSession) -> None:
        """Two steps exchanging positions does not trip the uniqueness constraint.

        This is the case the two-phase renumber exists for: assigning final positions
        directly would collide the moment a swap is requested.

        Args:
            db_session: The test session.
        """
        revision_id = await _revision(db_session, await _guide(db_session, "order-2"))
        repo = SQLAlchemyStepRepository(db_session)
        created = [
            await repo.append(
                revision_id,
                StepCreateInternal(revision_id=revision_id, position=0, title=t),
            )
            for t in ("A", "B")
        ]

        reordered = await repo.reorder(revision_id, {created[0].id: 2, created[1].id: 1})

        assert [s.title for s in reordered] == ["B", "A"]

    async def test_full_reversal_survives(self, db_session: AsyncSession) -> None:
        """Reversing every position at once is legal.

        Args:
            db_session: The test session.
        """
        revision_id = await _revision(db_session, await _guide(db_session, "order-3"))
        repo = SQLAlchemyStepRepository(db_session)
        created = [
            await repo.append(
                revision_id,
                StepCreateInternal(revision_id=revision_id, position=0, title=t),
            )
            for t in ("A", "B", "C", "D")
        ]
        order = {step.id: 4 - index for index, step in enumerate(created)}

        reordered = await repo.reorder(revision_id, order)

        assert [s.title for s in reordered] == ["D", "C", "B", "A"]

    async def test_partial_reorder_is_refused(self, db_session: AsyncSession) -> None:
        """Omitting a step is ambiguous, so the whole request is rejected.

        Args:
            db_session: The test session.
        """
        revision_id = await _revision(db_session, await _guide(db_session, "order-4"))
        repo = SQLAlchemyStepRepository(db_session)
        first = await repo.append(
            revision_id, StepCreateInternal(revision_id=revision_id, position=0, title="A")
        )
        await repo.append(
            revision_id, StepCreateInternal(revision_id=revision_id, position=0, title="B")
        )
        with pytest.raises(InvalidDataError):
            await repo.reorder(revision_id, {first.id: 1})

    async def test_deleting_a_step_closes_the_gap(self, db_session: AsyncSession) -> None:
        """Positions stay 1..n so the sheet never prints "STEP 1, STEP 3".

        Args:
            db_session: The test session.
        """
        revision_id = await _revision(db_session, await _guide(db_session, "order-5"))
        repo = SQLAlchemyStepRepository(db_session)
        created = [
            await repo.append(
                revision_id,
                StepCreateInternal(revision_id=revision_id, position=0, title=t),
            )
            for t in ("A", "B", "C")
        ]

        await repo.delete(created[1].id)

        steps = await repo.list_for_revision(revision_id)
        assert [(s.position, s.title) for s in steps] == [(1, "A"), (2, "C")]

    async def test_callouts_come_back_with_their_step(self, db_session: AsyncSession) -> None:
        """Callouts are eagerly loaded, so no lazy load escapes the session.

        Args:
            db_session: The test session.
        """
        revision_id = await _revision(db_session, await _guide(db_session, "callouts"))
        repo = SQLAlchemyStepRepository(db_session)
        step = await repo.append(
            revision_id, StepCreateInternal(revision_id=revision_id, position=0, title="A")
        )
        await repo.add_callout(
            CalloutCreateInternal(step_id=step.id, index=1, x_pct=10, y_pct=20, label="Here")
        )

        fetched = await repo.get(step.id)
        assert [c.label for c in fetched.callouts] == ["Here"]

    async def test_callout_index_is_unique_per_step(self, db_session: AsyncSession) -> None:
        """Two bubbles numbered 1 on one plate would be unreadable.

        Args:
            db_session: The test session.
        """
        revision_id = await _revision(db_session, await _guide(db_session, "callouts-2"))
        repo = SQLAlchemyStepRepository(db_session)
        step = await repo.append(
            revision_id, StepCreateInternal(revision_id=revision_id, position=0, title="A")
        )
        await repo.add_callout(CalloutCreateInternal(step_id=step.id, index=1, x_pct=1, y_pct=1))
        with pytest.raises(DuplicateEntityError):
            await repo.add_callout(
                CalloutCreateInternal(step_id=step.id, index=1, x_pct=2, y_pct=2)
            )


class TestBlockOrdering:
    """The shared ordered-child machinery, exercised through the BOM."""

    async def test_reorder_and_delete_keep_positions_contiguous(
        self, db_session: AsyncSession
    ) -> None:
        """The generic block repository behaves like the step repository.

        Args:
            db_session: The test session.
        """
        revision_id = await _revision(db_session, await _guide(db_session, "bom"))
        repo = SQLAlchemyBomItemRepository(db_session)
        created = [
            await repo.append(
                revision_id,
                BomItemCreateInternal(revision_id=revision_id, position=0, description=d),
            )
            for d in ("Plate", "Dye", "Gauges")
        ]

        reordered = await repo.reorder(
            revision_id,
            {created[0].id: 3, created[1].id: 1, created[2].id: 2},
        )
        assert [i.description for i in reordered] == ["Dye", "Gauges", "Plate"]

        await repo.delete(created[1].id)
        remaining = await repo.list_for_revision(revision_id)
        assert [i.position for i in remaining] == [1, 2]


class TestRevisionUniqueness:
    """A guide cannot carry the same revision label twice."""

    async def test_duplicate_label_is_refused(self, db_session: AsyncSession) -> None:
        """Two "Rev C" sheets for one guide would be unresolvable.

        Args:
            db_session: The test session.
        """
        guide_id = await _guide(db_session, "rev-unique")
        await _revision(db_session, guide_id, "C")
        with pytest.raises(DuplicateEntityError):
            await _revision(db_session, guide_id, "C")
