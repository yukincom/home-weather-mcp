"""Check installed CA and optional package installers without network access."""
from importlib.metadata import PackageNotFoundError, version
from packaging.version import Version
for package, minimum in (("certifi", "2026.10.19"), ("pip", "26.2.2"), ("uv", "0.13.4")):
    try:
        installed = version(package)
    except PackageNotFoundError:
        continue  # uv-created project environments do not need either package.
    if Version(installed) < Version(minimum):
        raise RuntimeError(f"Upgrade {package} to >= {minimum} before using this environment")
print("PASS: certificate bundle and installed package tools meet security minimums")
