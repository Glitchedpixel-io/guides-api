"""Content-addressed asset storage on a mounted filesystem.

Bytes live on disk; the database stores only the relative path. Files are named by their
own sha256, so writing identical content twice is idempotent and a path can never collide
with unrelated content.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.config.schema import StorageConfig


class StorageError(Exception):
    """Base class for asset-store failures."""


class AssetTooLargeError(StorageError):
    """The upload exceeded the configured size ceiling."""


class AssetNotFoundError(StorageError):
    """No file exists at that path inside the asset root."""


class UnsafePathError(StorageError):
    """The path escaped the asset root."""


@dataclass(frozen=True)
class StoredBytes:
    """The result of writing bytes into the store.

    Attributes:
        relative_path: Path beneath the asset root, as recorded in the database.
        sha256: Hex digest of the contents.
        byte_size: Length in bytes.
    """

    relative_path: str
    sha256: str
    byte_size: int


class AssetStore:
    """Reads and writes assets beneath a single configured root."""

    def __init__(self, config: StorageConfig) -> None:
        """Bind the store to its root directory.

        Args:
            config: Storage configuration, including the root and the size ceiling.
        """
        self._root = Path(config.asset_root)
        self._max_bytes = config.max_upload_bytes

    @property
    def root(self) -> Path:
        """The directory every asset lives beneath.

        Returns:
            Path: The asset root.
        """
        return self._root

    def write(self, data: bytes, suffix: str) -> StoredBytes:
        """Write bytes into the store, addressed by their own hash.

        Re-writing identical content is a no-op that returns the same path, which is what
        makes an accidental duplicate upload free rather than a second copy on disk.

        Args:
            data: The file contents.
            suffix: File extension to append, including the dot (e.g. ``.svg``). May be
                empty.

        Returns:
            StoredBytes: Where it landed, its digest, and its size.

        Raises:
            AssetTooLargeError: If the payload exceeds the configured ceiling.
        """
        if len(data) > self._max_bytes:
            raise AssetTooLargeError(f"{len(data)} bytes exceeds the {self._max_bytes} byte limit")

        digest = hashlib.sha256(data).hexdigest()
        # Fan out over two levels so no single directory accumulates every asset; a
        # directory with a million entries is slow to list and slow to back up.
        relative = f"{digest[:2]}/{digest[2:4]}/{digest}{suffix}"
        target = self._root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            # Write to a temporary neighbour then rename, so a crash mid-write can never
            # leave a truncated file sitting at a path the database already trusts.
            tmp = target.with_suffix(target.suffix + ".partial")
            tmp.write_bytes(data)
            tmp.replace(target)

        return StoredBytes(relative_path=relative, sha256=digest, byte_size=len(data))

    def resolve(self, relative_path: str) -> Path:
        """Turn a stored relative path into an absolute one, safely.

        Args:
            relative_path: The path recorded in the database.

        Returns:
            Path: The absolute path inside the asset root.

        Raises:
            UnsafePathError: If the path escapes the root.
        """
        candidate = (self._root / relative_path.lstrip("/")).resolve()
        root = self._root.resolve()
        if root != candidate and root not in candidate.parents:
            raise UnsafePathError(f"{relative_path!r} escapes the asset root")
        return candidate

    def read(self, relative_path: str) -> bytes:
        """Read a stored asset's contents.

        Args:
            relative_path: The path recorded in the database.

        Returns:
            bytes: The file contents.

        Raises:
            UnsafePathError: If the path escapes the root.
            AssetNotFoundError: If nothing is stored there.
        """
        path = self.resolve(relative_path)
        if not path.is_file():
            raise AssetNotFoundError(f"no asset at {relative_path!r}")
        return path.read_bytes()

    def exists(self, relative_path: str) -> bool:
        """Report whether a stored asset is present on disk.

        Args:
            relative_path: The path recorded in the database.

        Returns:
            bool: True when the file exists and is readable as a file.
        """
        try:
            return self.resolve(relative_path).is_file()
        except UnsafePathError:
            return False


SUFFIX_BY_CONTENT_TYPE: dict[str, str] = {
    "image/svg+xml": ".svg",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
}


def suffix_for(content_type: str) -> str:
    """Map a content type to the file extension the store should use.

    Args:
        content_type: The declared MIME type.

    Returns:
        str: A dotted extension, or ``.bin`` for anything unrecognised.
    """
    return SUFFIX_BY_CONTENT_TYPE.get(content_type.split(";")[0].strip().lower(), ".bin")
