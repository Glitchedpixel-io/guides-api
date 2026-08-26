"""The content-addressed asset store."""

from __future__ import annotations

import hashlib

import pytest

from app.config.schema import StorageConfig
from app.storage import (
    AssetNotFoundError,
    AssetStore,
    AssetTooLargeError,
    UnsafePathError,
    suffix_for,
)

pytestmark = pytest.mark.unit


def test_write_addresses_by_content_hash(asset_store: AssetStore) -> None:
    """The stored path is derived from the bytes, not from a name.

    Args:
        asset_store: A store over a temporary root.
    """
    stored = asset_store.write(b"hello", ".svg")
    digest = hashlib.sha256(b"hello").hexdigest()
    assert stored.sha256 == digest
    assert stored.relative_path == f"{digest[:2]}/{digest[2:4]}/{digest}.svg"
    assert stored.byte_size == 5


def test_writing_the_same_bytes_twice_is_idempotent(asset_store: AssetStore) -> None:
    """A repeated upload reuses the file rather than writing a second copy.

    Args:
        asset_store: A store over a temporary root.
    """
    first = asset_store.write(b"same", ".png")
    second = asset_store.write(b"same", ".png")
    assert first == second
    assert len(list(asset_store.root.rglob("*.png"))) == 1


def test_round_trips_content(asset_store: AssetStore) -> None:
    """What is written comes back byte for byte.

    Args:
        asset_store: A store over a temporary root.
    """
    stored = asset_store.write(b"\x00\x01\x02binary", ".bin")
    assert asset_store.read(stored.relative_path) == b"\x00\x01\x02binary"


def test_leaves_no_partial_file_behind(asset_store: AssetStore) -> None:
    """The write-then-rename means no truncated file sits at a trusted path.

    Args:
        asset_store: A store over a temporary root.
    """
    asset_store.write(b"content", ".svg")
    assert list(asset_store.root.rglob("*.partial")) == []


def test_refuses_oversized_payload(storage_config: StorageConfig) -> None:
    """An upload past the ceiling is refused rather than filling the volume.

    Args:
        storage_config: Storage settings for the test.
    """
    small = AssetStore(StorageConfig(asset_root=storage_config.asset_root, max_upload_bytes=8))
    with pytest.raises(AssetTooLargeError, match="exceeds"):
        small.write(b"far too many bytes", ".bin")


@pytest.mark.parametrize(
    "path",
    ["../../etc/passwd", "/etc/passwd", "ab/../../../../etc/shadow"],
)
def test_rejects_paths_that_escape_the_root(asset_store: AssetStore, path: str) -> None:
    """Traversal is refused, whichever way it is spelled.

    Args:
        asset_store: A store over a temporary root.
        path: A path attempting to escape.
    """
    with pytest.raises((UnsafePathError, AssetNotFoundError)):
        asset_store.read(path)


def test_escaping_path_is_reported_as_unsafe(asset_store: AssetStore) -> None:
    """A clearly-escaping path is refused by containment, not by absence.

    Args:
        asset_store: A store over a temporary root.
    """
    with pytest.raises(UnsafePathError, match="escapes"):
        asset_store.resolve("../../../../etc/passwd")


def test_missing_file_is_reported_as_missing(asset_store: AssetStore) -> None:
    """A path inside the root with nothing at it reads as absent.

    Args:
        asset_store: A store over a temporary root.
    """
    with pytest.raises(AssetNotFoundError):
        asset_store.read("ab/cd/nothing.svg")


def test_exists_is_false_for_unsafe_paths(asset_store: AssetStore) -> None:
    """Probing outside the root answers no rather than raising.

    Args:
        asset_store: A store over a temporary root.
    """
    assert asset_store.exists("../../../../etc/passwd") is False


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("image/svg+xml", ".svg"),
        ("image/png", ".png"),
        ("image/jpeg", ".jpg"),
        ("application/pdf", ".pdf"),
        ("IMAGE/PNG", ".png"),
        ("image/png; charset=binary", ".png"),
        ("application/x-unheard-of", ".bin"),
    ],
)
def test_suffix_for_content_type(content_type: str, expected: str) -> None:
    """Extensions follow the declared type, tolerating case and parameters.

    Args:
        content_type: The declared MIME type.
        expected: The extension the store should use.
    """
    assert suffix_for(content_type) == expected
