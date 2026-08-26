"""Storing and retrieving binary assets."""

from __future__ import annotations

from app.repositories.protocols import AssetRepository
from app.schemas.assets import AssetCreateInternal, AssetRead
from app.schemas.enums import AssetKind
from app.storage import AssetStore, suffix_for


class AssetService:
    """Writes uploads to the asset store and records them in the database."""

    def __init__(self, assets: AssetRepository, store: AssetStore) -> None:
        """Bind the service to its repository and store.

        Args:
            assets: Storage for asset metadata.
            store: The filesystem-backed byte store.
        """
        self._assets = assets
        self._store = store

    async def store_bytes(
        self,
        data: bytes,
        kind: AssetKind,
        content_type: str,
        original_filename: str | None = None,
    ) -> AssetRead:
        """Write bytes to the store and record them.

        Identical content is deduplicated: the same bytes always hash to the same path, so
        a repeated upload reuses the existing row instead of writing a second copy.

        Args:
            data: The file contents.
            kind: What the asset is, which decides how the renderer embeds it.
            content_type: Its MIME type.
            original_filename: The uploaded filename, kept for display only.

        Returns:
            AssetRead: The stored asset.

        Raises:
            AssetTooLargeError: If the payload exceeds the configured ceiling.
        """
        stored = self._store.write(data, suffix_for(content_type))

        existing = await self._assets.find_by_sha256(stored.sha256)
        if existing is not None and existing.kind == kind:
            return existing

        return await self._assets.create(
            AssetCreateInternal(
                kind=kind,
                content_type=content_type,
                storage_path=stored.relative_path,
                sha256=stored.sha256,
                byte_size=stored.byte_size,
                original_filename=original_filename,
            )
        )

    async def get(self, asset_id: int) -> AssetRead:
        """Fetch an asset's metadata.

        Args:
            asset_id: The asset's primary key.

        Returns:
            AssetRead: The stored asset.
        """
        return await self._assets.get(asset_id)

    async def read(self, asset_id: int) -> tuple[AssetRead, bytes]:
        """Fetch an asset's metadata and its bytes.

        Args:
            asset_id: The asset's primary key.

        Returns:
            tuple[AssetRead, bytes]: The metadata and the file contents.

        Raises:
            NotFoundError: If the asset row does not exist.
            AssetNotFoundError: If the row exists but the file is missing from the store.
        """
        asset = await self._assets.get(asset_id)
        return asset, self._store.read(asset.storage_path)
