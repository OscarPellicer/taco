import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "r" / "src" / "vendor"
VERSION_HEADER = ROOT / "r" / "src" / "taco_versions.h"


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, dirs_exist_ok=True)


def main() -> None:
    shutil.rmtree(VENDOR, ignore_errors=True)
    copy_tree(ROOT / "core" / "include", VENDOR / "taco" / "include")
    copy_tree(ROOT / "core" / "src", VENDOR / "taco" / "src")
    copy_tree(ROOT / "extern" / "karu" / "include", VENDOR / "karu" / "include")
    copy_tree(ROOT / "extern" / "karu" / "src", VENDOR / "karu" / "src")
    shutil.copy2(ROOT / "extern" / "karu" / "VERSION", VENDOR / "karu" / "VERSION")
    cmake = (ROOT / "core" / "CMakeLists.txt").read_text()
    match = re.search(r"project\(taco\s+VERSION\s+([^\s)]+)", cmake)
    if match is None:
        raise RuntimeError("could not read the TACO version from core/CMakeLists.txt")
    taco_version = match.group(1)
    karu_version = (ROOT / "extern" / "karu" / "VERSION").read_text().strip()
    VERSION_HEADER.write_text(
        "#ifndef TACO_R_VERSIONS_H\n"
        "#define TACO_R_VERSIONS_H\n\n"
        f'#define TACO_VERSION_STRING "{taco_version}"\n'
        f'#define KARU_VERSION_STRING "{karu_version}"\n\n'
        "#endif\n"
    )
    (ROOT / "r" / "inst").mkdir(exist_ok=True)
    shutil.copy2(
        ROOT / "extern" / "karu" / "LICENSE", ROOT / "r" / "inst" / "karu-LICENSE"
    )


if __name__ == "__main__":
    main()
