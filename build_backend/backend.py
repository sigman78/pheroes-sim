from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


NAME = "sim-matter"
VERSION = "0.1.0"
WHEEL_NAME = f"sim_matter-{VERSION}-py3-none-any.whl"
DIST_INFO = f"sim_matter-{VERSION}.dist-info"
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "sim_matter"


def _metadata() -> str:
    return "\n".join(
        [
            "Metadata-Version: 2.1",
            f"Name: {NAME}",
            f"Version: {VERSION}",
            "Summary: Fast tactical hex-grid battle simulator inspired by Heroes-style combat.",
            "Requires-Python: >=3.13",
            "",
        ]
    )


def _wheel_file() -> str:
    return "\n".join(
        [
            "Wheel-Version: 1.0",
            "Generator: sim-matter-local-backend",
            "Root-Is-Purelib: true",
            "Tag: py3-none-any",
            "",
        ]
    )


def _entry_points() -> str:
    return "\n".join(["[console_scripts]", "sim-matter = sim_matter.cli:main", ""])


def _record_line(path: str, content: bytes) -> list[str]:
    digest = hashlib.sha256(content).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return [path, f"sha256={encoded}", str(len(content))]


def _build_contents() -> list[tuple[str, bytes]]:
    files: list[tuple[str, bytes]] = []
    for source in sorted(SRC.rglob("*")):
        if source.is_dir():
            continue
        relative = source.relative_to(SRC.parent).as_posix()
        files.append((relative, source.read_bytes()))

    files.extend(
        [
            (f"{DIST_INFO}/METADATA", _metadata().encode("utf-8")),
            (f"{DIST_INFO}/WHEEL", _wheel_file().encode("utf-8")),
            (f"{DIST_INFO}/entry_points.txt", _entry_points().encode("utf-8")),
            (f"{DIST_INFO}/top_level.txt", b"sim_matter\n"),
        ]
    )
    return files


def _build_wheel(wheel_directory: str) -> str:
    os.makedirs(wheel_directory, exist_ok=True)
    wheel_path = Path(wheel_directory) / WHEEL_NAME
    files = _build_contents()
    record_rows = [_record_line(path, content) for path, content in files]
    record_rows.append([f"{DIST_INFO}/RECORD", "", ""])

    with ZipFile(wheel_path, "w", compression=ZIP_DEFLATED) as archive:
        for path, content in files:
            archive.writestr(path, content)

        record_content = "".join(",".join(row) + "\n" for row in record_rows).encode("utf-8")
        archive.writestr(f"{DIST_INFO}/RECORD", record_content)

    return WHEEL_NAME


def build_wheel(wheel_directory: str, config_settings=None, metadata_directory=None) -> str:
    return _build_wheel(wheel_directory)


def build_editable(wheel_directory: str, config_settings=None, metadata_directory=None) -> str:
    return _build_wheel(wheel_directory)


def get_requires_for_build_wheel(config_settings=None) -> list[str]:
    return []


def get_requires_for_build_editable(config_settings=None) -> list[str]:
    return []


def prepare_metadata_for_build_wheel(metadata_directory: str, config_settings=None) -> str:
    dist_info_path = Path(metadata_directory) / DIST_INFO
    dist_info_path.mkdir(parents=True, exist_ok=True)
    (dist_info_path / "METADATA").write_text(_metadata(), encoding="utf-8")
    (dist_info_path / "WHEEL").write_text(_wheel_file(), encoding="utf-8")
    (dist_info_path / "entry_points.txt").write_text(_entry_points(), encoding="utf-8")
    (dist_info_path / "top_level.txt").write_text("sim_matter\n", encoding="utf-8")
    return DIST_INFO
