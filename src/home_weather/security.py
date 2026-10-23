"""Reject environments with the pre-incident certificate bundle."""

from importlib.metadata import version
from packaging.version import Version


def require_safe_certifi():
    if Version(version("certifi")) < Version("2026.10.19"):
        raise RuntimeError("certifi >= 2026.10.19 is required. Recreate this environment with uv >= 0.13.4.")
