from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    """Return the installed package version.

    Returns:
        str: The version from package metadata, or a dev placeholder outside an install.
    """
    try:
        return version("guides-api")
    except PackageNotFoundError:
        return "0.0.0+unknown"
