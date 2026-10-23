"""Check the built artifacts, including license and absence of local configuration."""

from pathlib import Path
import tarfile
import zipfile
import tomllib

root = Path(__file__).resolve().parents[1]
release = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
wheels = list((root / "dist").glob(f"home_weather_mcp-{release}-*.whl"))
archives = list((root / "dist").glob(f"home_weather_mcp-{release}.tar.gz"))
assert len(wheels) == len(archives) == 1, "Expected exactly one wheel and source archive"


def inspect_names(names):
    for name in names:
        parts = Path(name).parts
        assert not any(p in {".venv", ".env", "locations.json", "locations.json.lock", ".DS_Store", "work", "target"} for p in parts), name
        assert not any(p.startswith("config-backup-") for p in parts), name


with zipfile.ZipFile(wheels[0]) as archive:
    inspect_names(archive.namelist())
    metadata_path = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
    metadata = archive.read(metadata_path).decode()
    assert "License-Expression: MIT" in metadata
    assert any(name.endswith("/licenses/LICENSE") for name in archive.namelist())
    assert "home_weather/english.py" in archive.namelist()
    assert any(name.startswith("home_weather/libhome_weather_core") and name.endswith((".so", ".dylib")) for name in archive.namelist())
    wheel_info = archive.read(next(name for name in archive.namelist() if name.endswith(".dist-info/WHEEL"))).decode()
    assert "Root-Is-Purelib: false" in wheel_info
    assert "Requires-Dist: certifi>=2026.10.19" in metadata

with tarfile.open(archives[0]) as archive:
    inspect_names(archive.getnames())
    for suffix in ("/LICENSE", "/README.md", "/README.ja.md", "/.github/workflows/ci.yml", "/native/src/lib.rs", "/native/Cargo.lock", "/hatch_build.py"):
        assert any(name.endswith(suffix) for name in archive.getnames()), suffix

print("PASS: wheel and source archive include MIT metadata and no local settings")
