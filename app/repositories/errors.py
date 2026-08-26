"""Domain errors raised by the persistence layer.

Routers translate these to HTTP status codes. Nothing above this layer should ever see a
``sqlalchemy`` exception type.
"""

from __future__ import annotations


class RepositoryError(Exception):
    """Base class for every persistence-layer domain error."""


class NotFoundError(RepositoryError):
    """The requested row does not exist."""


class DuplicateEntityError(RepositoryError):
    """A uniqueness constraint rejected the write."""


class InvalidDataError(RepositoryError):
    """The value was well-formed but the database refused it."""


class RequiredFieldError(RepositoryError):
    """A NOT NULL column was left unset."""


class DatabaseLockedError(RepositoryError):
    """The database is read-only or the role lacks permission."""
