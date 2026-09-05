"""Check the built artifacts, including license and absence of local configuration."""

from pathlib import Path
import tarfile
import zipfile

root = Path(__file__).resolve().parents[1]
wheels = list((root / "dist").glob("*.whl"))
archives = list((root / "dist").glob("*.tar.gz"))
assert len(wheels) == len(archives) == 1, "Expected exactly one wheel and source archive"


def inspect_names(names):
    for name in names:
        parts = Path(name).parts
        assert not any(p in {".venv", ".env", "locations.json", "locations.json.lock", ".DS_Store"} for p in parts), name
        assert not any(p.startswith("config-backup-") for p in parts), name


with zipfile.ZipFile(wheels[0]) as archive:
    inspect_names(archive.namelist())
    metadata_path = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
    metadata = archive.read(metadata_path).decode()
    assert "License-Expression: MIT" in metadata
    assert any(name.endswith("/licenses/LICENSE") for name in archive.namelist())
    assert "home_weather/english.py" in archive.namelist()

with tarfile.open(archives[0]) as archive:
    inspect_names(archive.getnames())
    for suffix in ("/LICENSE", "/README.md", "/README.ja.md", "/.github/workflows/ci.yml"):
        assert any(name.endswith(suffix) for name in archive.getnames()), suffix

print("PASS: wheel and source archive include MIT metadata and no local settings")
