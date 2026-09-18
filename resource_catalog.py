"""Scan the local creative libraries into a machine-readable manifest."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ResourceItem:
    kind: str
    name: str
    path: str = ""
    extension: str = ""
    resource_id: str = ""
    description: str = ""
    ffmpeg_compatible: bool = False
    jianying_compatible: bool = False


@dataclass(frozen=True)
class ResourceCatalog:
    schema_version: int = 1
    stickers: list[ResourceItem] = field(default_factory=list)
    fonts: list[ResourceItem] = field(default_factory=list)
    filters: list[ResourceItem] = field(default_factory=list)
    voices: list[ResourceItem] = field(default_factory=list)
    flower_text: list[ResourceItem] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=lambda: {
        "flower_text": "未配置本地花字资源",
    })

    def as_dict(self) -> dict:
        return asdict(self)


def _scan_files(directory: str, kind: str, extensions: set[str], *,
                ffmpeg: bool, jianying: bool) -> list[ResourceItem]:
    root = Path(directory)
    if not root.is_dir():
        return []
    items = []
    for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        extension = path.suffix.lower()
        if path.is_file() and extension in extensions:
            items.append(ResourceItem(
                kind=kind,
                name=path.name,
                path=str(path.resolve()),
                extension=extension,
                ffmpeg_compatible=ffmpeg,
                jianying_compatible=jianying,
            ))
    return items


def _scan_voices(path: str) -> list[ResourceItem]:
    voice_file = Path(path)
    if not voice_file.is_file():
        return []
    items = []
    for raw_line in voice_file.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        voice_id, separator, description = line.partition("|")
        voice_id = voice_id.strip()
        if voice_id:
            items.append(ResourceItem(
                kind="voice",
                name=voice_id,
                resource_id=voice_id,
                description=description.strip() if separator else "",
                jianying_compatible=True,
            ))
    return sorted(items, key=lambda item: item.resource_id.casefold())


def scan_resource_catalog(config) -> ResourceCatalog:
    return ResourceCatalog(
        stickers=_scan_files(
            config.STICKER_DIR, "sticker", {".png", ".webp", ".jpg", ".jpeg"},
            ffmpeg=True, jianying=True,
        ),
        fonts=_scan_files(
            config.FONT_LIB_DIR, "font", {".ttf", ".otf"},
            ffmpeg=True, jianying=True,
        ),
        filters=_scan_files(
            config.FILTER_LIB_DIR, "filter", {".txt"},
            ffmpeg=True, jianying=False,
        ),
        voices=_scan_voices(config.VOICE_LIB_FILE),
    )


def write_resource_catalog(catalog: ResourceCatalog, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f"{target.stem}-", suffix=".json.tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(catalog.as_dict(), handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target
