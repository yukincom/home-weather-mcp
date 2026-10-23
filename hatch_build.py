"""Build the required Rust core into each platform wheel (no Python fallback)."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if self.target_name != "wheel":
            return
        root = Path(self.root)
        subprocess.run(["cargo", "build", "--release", "--locked", "--offline",
                        "--manifest-path", str(root / "native/Cargo.toml")], check=True)
        extension = ".dylib" if sys.platform == "darwin" else ".so"
        target = Path(os.environ.get("CARGO_TARGET_DIR", root / "native/target"))
        source = target / "release" / ("libhome_weather_core" + extension)
        destination = root / "src/home_weather" / ("libhome_weather_core" + extension)
        shutil.copy2(source, destination)
        build_data["artifacts"].append("src/home_weather/libhome_weather_core" + extension)
        build_data["pure_python"] = False
        from packaging.tags import sys_tags
        build_data["tag"] = "py3-none-" + next(sys_tags()).platform
