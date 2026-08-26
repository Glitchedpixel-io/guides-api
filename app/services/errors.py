"""Business-rule errors raised by the service layer.

Distinct from the persistence errors in ``app/repositories/errors.py``: these are refusals
by the domain, not by the database.
"""

from __future__ import annotations


class ServiceError(Exception):
    """Base class for every service-layer domain error."""


class RevisionNotEditableError(ServiceError):
    """The revision is published or archived, so its content is frozen.

    Published content is frozen because the sheet someone is holding must stay reproducible
    from the database. Editing a published revision would quietly make an issued document
    unverifiable; issue a new revision instead.
    """


class InvalidTransitionError(ServiceError):
    """The requested lifecycle transition is not allowed from the current state."""


class RenderNotPossibleError(ServiceError):
    """The revision cannot be rendered as it stands."""


class SketchUnavailableError(ServiceError):
    """Sketch redraw was requested but cannot run."""
