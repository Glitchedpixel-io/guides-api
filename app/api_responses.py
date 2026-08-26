"""Translating domain errors into HTTP, and the shared OpenAPI response documentation.

The mapping happens *inside* the endpoint, not in an ``app.exception_handler``. Logfire's
FastAPI instrumentation records an exception the moment it leaves the endpoint function —
before any handler runs — so a 404 raised and handled later still files an issue. Catching
here, and letting :class:`~app.routers.base.QuietClientErrorRoute` return rather than raise,
is what keeps caller mistakes out of the exception stream.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException, status

from app.repositories.errors import (
    DatabaseLockedError,
    DuplicateEntityError,
    InvalidDataError,
    NotFoundError,
    RequiredFieldError,
)
from app.rendering.render import UnknownPageSizeError
from app.services.errors import (
    InvalidTransitionError,
    RenderNotPossibleError,
    RevisionNotEditableError,
    SketchUnavailableError,
)
from app.sketch.client import SketchDisabledError, UnsupportedSketchFormatError
from app.storage import AssetNotFoundError, AssetTooLargeError

COMMON_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"description": "No such resource"},
    423: {"description": "Database is read-only or the role lacks permission"},
}

WRITE_RESPONSES: dict[int | str, dict[str, Any]] = {
    **COMMON_RESPONSES,
    400: {"description": "Invalid data or a required field is missing"},
    409: {"description": "Conflicts with an existing entity, or with the revision's state"},
}


@contextmanager
def http_errors() -> Iterator[None]:
    """Translate domain errors raised inside the block into ``HTTPException``.

    Yields:
        None: The block runs with domain errors mapped on exit.

    Raises:
        HTTPException: The HTTP equivalent of whichever domain error was raised.
    """
    try:
        yield
    except (NotFoundError, AssetNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateEntityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (RevisionNotEditableError, InvalidTransitionError) as exc:
        # 409 rather than 403: the request is well-formed and the caller is permitted; it
        # is the resource's current state that refuses it.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except AssetTooLargeError as exc:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)) from exc
    except (
        InvalidDataError,
        RequiredFieldError,
        UnsupportedSketchFormatError,
        UnknownPageSizeError,
        RenderNotPossibleError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (SketchUnavailableError, SketchDisabledError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except DatabaseLockedError as exc:
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=str(exc)) from exc
