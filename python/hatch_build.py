import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from packaging.tags import sys_tags


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name != "wheel":
            return

        root = Path(self.root)
        library = root / "taco" / "_lib" / _library_name()
        if not library.is_file():
            _compile_native(_native_source(root), library)

        # CFFI loads the library dynamically, so the wheel is independent of
        # CPython's ABI while remaining specific to its OS and architecture.
        build_data["pure_python"] = False
        build_data["tag"] = f"py3-none-{_platform_tag()}"


def _library_name() -> str:
    if sys.platform == "darwin":
        return "libtaco.dylib"
    if sys.platform == "win32":
        return "taco.dll"
    return "libtaco.so"


def _platform_tag() -> str:
    if sys.platform == "darwin":
        machine = platform.machine().lower()
        if machine == "aarch64":
            machine = "arm64"
        return f"macosx_11_0_{machine}"
    return next(
        tag.platform for tag in sys_tags() if "manylinux" not in tag.platform and "musllinux" not in tag.platform
    )


def _native_source(root: Path) -> Path:
    checkout = root.parent / "core"
    if (checkout / "CMakeLists.txt").is_file():
        return checkout

    sdist = root / "native" / "core"
    if (sdist / "CMakeLists.txt").is_file():
        return sdist

    raise RuntimeError("TACO native sources are missing from the source tree")


def _compile_native(source: Path, destination: Path) -> None:
    cmake = shutil.which("cmake")
    ninja = shutil.which("ninja")
    if not cmake or not ninja:
        raise RuntimeError("building taco-eo from source requires CMake and Ninja")

    with tempfile.TemporaryDirectory(prefix="taco-native-") as temporary:
        build = Path(temporary)
        subprocess.run(
            [
                cmake,
                "-S",
                str(source),
                "-B",
                str(build),
                "-G",
                "Ninja",
                "-DCMAKE_BUILD_TYPE=Release",
                "-DTACO_BUILD_TESTS=OFF",
            ],
            check=True,
        )
        subprocess.run(
            [cmake, "--build", str(build), "--target", "taco", "--config", "Release"],
            check=True,
        )

        candidates = list(build.rglob(_library_name()))
        if len(candidates) != 1:
            raise RuntimeError(f"native build did not produce exactly one {_library_name()}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidates[0], destination)
