from importlib.metadata import PackageNotFoundError

import pytest

from app import version as version_module


def test_get_version_returns_the_installed_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(version_module, "version", lambda _: "1.2.3")
    assert version_module.get_version() == "1.2.3"


def test_get_version_falls_back_when_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(_: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(version_module, "version", _raise)
    assert version_module.get_version() == "0.0.0+unknown"
