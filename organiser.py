#!/usr/bin/env python3
"""Organize a Downloads folder by file type."""

from __future__ import annotations

import argparse
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_MAPPINGS: Dict[str, List[str]] = {
    "Images": ["jpg", "jpeg", "png", "gif", "webp", "tiff", "svg", "heic"],
    "Videos": ["mp4", "mov", "mkv", "avi", "webm"],
    "Audio": ["mp3", "wav", "m4a", "flac", "aac", "ogg"],
    "Documents": ["pdf", "doc", "docx", "txt", "rtf", "odt", "pages", "md"],
    "Spreadsheets": ["xls", "xlsx", "csv", "ods"],
    "Presentations": ["ppt", "pptx", "key"],
    "Archives": ["zip", "rar", "7z", "tar", "gz", "bz2", "tar.gz", "tar.bz2"],
    "Code": [
        "py",
        "js",
        "ts",
        "json",
        "yml",
        "yaml",
        "toml",
        "html",
        "css",
        "sh",
        "go",
        "rs",
    ],
    "Installers": ["dmg", "pkg", "app", "exe", "msi"],
    "Fonts": ["ttf", "otf", "woff", "woff2"],
}

TRANSIENT_EXTENSIONS = {".download", ".crdownload", ".part", ".partial", ".tmp"}
SKIP_NAMES = {".DS_Store"}


@dataclass
class Config:
    downloads_dir: Path
    mappings: Dict[str, List[str]]
    other_folder: str = "Other"
    scan_existing: bool = True
    watch: bool = True
    poll_interval_seconds: float = 3.0
    min_age_seconds: float = 3.0
    ignore_hidden: bool = True
    dry_run: bool = False


def _normalize_extension(ext: str) -> str:
    ext = ext.strip().lower()
    if not ext:
        return ""
    if not ext.startswith("."):
        ext = f".{ext}"
    return ext


def _build_extension_map(mappings: Dict[str, List[str]]) -> Dict[str, str]:
    ext_map: Dict[str, str] = {}
    for folder, extensions in mappings.items():
        for ext in extensions:
            ext_map[_normalize_extension(ext)] = folder
    return ext_map


def _extension_candidates(path: Path) -> List[str]:
    suffixes = [s.lower() for s in path.suffixes]
    if not suffixes:
        return [""]
    candidates: List[str] = []
    for i in range(len(suffixes)):
        candidates.append("".join(suffixes[i:]))
    return candidates


def _resolve_destination(dest_dir: Path, filename: str) -> Path:
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate

    stem = Path(filename).stem
    suffix = "".join(Path(filename).suffixes)
    index = 1
    while True:
        candidate = dest_dir / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _should_skip(path: Path, config: Config) -> bool:
    if path.name in SKIP_NAMES:
        return True
    if config.ignore_hidden and path.name.startswith("."):
        return True
    if path.suffix.lower() in TRANSIENT_EXTENSIONS:
        return True
    if not path.is_file():
        return True

    try:
        age = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return True

    return age < config.min_age_seconds


def _decide_folder(path: Path, ext_map: Dict[str, str], other_folder: str) -> str:
    candidates = _extension_candidates(path)
    for candidate in sorted(candidates, key=len, reverse=True):
        normalized = _normalize_extension(candidate)
        if normalized in ext_map:
            return ext_map[normalized]
    if "" in ext_map:
        return ext_map[""]
    return other_folder


def organize_file(path: Path, config: Config, ext_map: Dict[str, str]) -> Optional[Path]:
    if _should_skip(path, config):
        return None

    folder_name = _decide_folder(path, ext_map, config.other_folder)
    dest_dir = config.downloads_dir / folder_name
    if not dest_dir.exists():
        dest_dir.mkdir(parents=True, exist_ok=True)

    destination = _resolve_destination(dest_dir, path.name)
    if destination == path:
        return None

    if config.dry_run:
        print(f"DRY RUN: {path.name} -> {dest_dir.name}/")
        return destination

    try:
        shutil.move(str(path), str(destination))
        print(f"Moved: {path.name} -> {dest_dir.name}/")
        return destination
    except (OSError, shutil.Error) as exc:
        print(f"Failed: {path.name} ({exc})")
        return None


def scan_existing(config: Config, ext_map: Dict[str, str]) -> None:
    for item in config.downloads_dir.iterdir():
        if item.is_file() and item.parent == config.downloads_dir:
            organize_file(item, config, ext_map)


def _load_toml(path: Path) -> Dict:
    try:
        import tomllib  # type: ignore
    except ModuleNotFoundError:
        try:
            import tomli as tomllib  # type: ignore
        except ModuleNotFoundError:
            print("TOML parser not found. Install 'tomli' or use Python 3.11+.")
            return {}

    try:
        return tomllib.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except Exception as exc:
        print(f"Failed to read config {path}: {exc}")
        return {}


def load_config(path: Path) -> Config:
    defaults = Config(downloads_dir=Path.home() / "Downloads", mappings=DEFAULT_MAPPINGS)
    data = _load_toml(path)

    downloads_dir = Path(data.get("downloads_dir", defaults.downloads_dir)).expanduser()
    mappings = data.get("mappings", defaults.mappings)

    return Config(
        downloads_dir=downloads_dir,
        mappings=mappings,
        other_folder=data.get("other_folder", defaults.other_folder),
        scan_existing=bool(data.get("scan_existing", defaults.scan_existing)),
        watch=bool(data.get("watch", defaults.watch)),
        poll_interval_seconds=float(
            data.get("poll_interval_seconds", defaults.poll_interval_seconds)
        ),
        min_age_seconds=float(data.get("min_age_seconds", defaults.min_age_seconds)),
        ignore_hidden=bool(data.get("ignore_hidden", defaults.ignore_hidden)),
        dry_run=bool(data.get("dry_run", defaults.dry_run)),
    )


def _watch_with_watchdog(config: Config, ext_map: Dict[str, str]) -> bool:
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ModuleNotFoundError:
        return False

    def queue_organize(path: Path) -> None:
        def worker() -> None:
            attempts = 3
            for _ in range(attempts):
                try:
                    age = time.time() - path.stat().st_mtime
                except FileNotFoundError:
                    return

                if age < config.min_age_seconds:
                    time.sleep(config.min_age_seconds - age)
                    continue

                organize_file(path, config, ext_map)
                return

        threading.Thread(target=worker, daemon=True).start()

    class Handler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            path = Path(event.src_path)
            if path.parent != config.downloads_dir:
                return
            queue_organize(path)

        def on_moved(self, event):
            if event.is_directory:
                return
            path = Path(event.dest_path)
            if path.parent != config.downloads_dir:
                return
            queue_organize(path)

    observer = Observer()
    handler = Handler()
    observer.schedule(handler, str(config.downloads_dir), recursive=False)
    observer.start()

    print("Watching with watchdog (press Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    return True


def _watch_with_polling(config: Config, ext_map: Dict[str, str]) -> None:
    print("Watching with polling (press Ctrl+C to stop)")
    try:
        while True:
            scan_existing(config, ext_map)
            time.sleep(config.poll_interval_seconds)
    except KeyboardInterrupt:
        return


def _resolve_config_path(arg: Optional[str]) -> Path:
    if arg:
        return Path(arg).expanduser()
    cwd_candidate = Path.cwd() / "config.toml"
    if cwd_candidate.exists():
        return cwd_candidate
    return Path(__file__).with_name("config.toml")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Organize downloads by file type.")
    parser.add_argument("--config", help="Path to config.toml")
    args = parser.parse_args(argv)

    config_path = _resolve_config_path(args.config)
    config = load_config(config_path)
    ext_map = _build_extension_map(config.mappings)

    if not config.downloads_dir.exists():
        print(f"Downloads folder does not exist: {config.downloads_dir}")
        return 1

    print(f"Using downloads folder: {config.downloads_dir}")
    if config.scan_existing:
        scan_existing(config, ext_map)

    if not config.watch:
        return 0

    if not _watch_with_watchdog(config, ext_map):
        print("watchdog not installed; falling back to polling")
        _watch_with_polling(config, ext_map)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
