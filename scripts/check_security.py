"""Check installed CA and optional package installers without network access."""
from importlib.metadata import PackageNotFoundError, version
from packaging.version import Version
from home_weather.security import require_safe_certifi

require_safe_certifi()
for package, minimum in (("pip", "26.2.2"), ("uv", "0.13.4")):
    try:
        installed = version(package)
    except PackageNotFoundError:
        continue  # uv-created project environments do not need either package.
    if Version(installed) < Version(minimum):
        raise RuntimeError(f"Upgrade {package} to >= {minimum} before using this environment")
print("PASS: certificate bundle and installed package tools meet security minimums")
