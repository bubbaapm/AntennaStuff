"""
Portable path & config resolution.

Goal: zero-config startup whether the app is on a flash drive, a local SSD,
or installed via the LibreVNA Windows installer. Config is written next to
the entry script so the flash-drive setup carries its preferences with it.
"""
from __future__ import annotations
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional


# ----------------------------------------------------------------- locations
def app_root() -> Path:
    """Folder that contains vna_tester.py — also where config lives."""
    # When frozen with pyinstaller, sys.executable is the launcher; otherwise
    # vna_tester.py lives one level above the package directory.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


CONFIG_FILE = app_root() / "vna_tester_config.json"


def default_export_dir() -> Path:
    """The "Images" folder next to the app — created on first export."""
    return app_root() / "Images"


# ----------------------------------------------------------------- config IO
DEFAULT_CONFIG: dict = {
    "librevna_path": None,           # absolute path to LibreVNA-GUI.exe
    "auto_launch": True,
    "scpi_host": "localhost",
    "scpi_port": 19542,
    "last_sweep": {},                # last successful sweep settings
    "saved_band_presets": {},        # user-defined band presets
    # Empty string means "use the auto-default": <app_root>/Images.
    # Computed lazily so the path is always under the app folder, which
    # works on a flash-drive too.
    "default_export_dir": "",
    "export_resolution": [1920, 1080],
    "session_dir": "sessions",
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            merged = dict(DEFAULT_CONFIG)
            merged.update(data)
            return merged
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict) -> None:
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError:
        pass


# ----------------------------------------------------------------- discovery
_LIBREVNA_EXE_NAMES = ("LibreVNA-GUI.exe", "LibreVNA-GUI")  # Windows + *nix


def _is_librevna(path: Path) -> bool:
    return path.is_file() and path.name in _LIBREVNA_EXE_NAMES


def _candidate_paths() -> list[Path]:
    """Sorted list of likely locations, ordered cheapest-first."""
    here = app_root()
    cands: list[Path] = []

    # 1) Sibling LibreVNA folder, multiple ancestor levels
    walk = here
    for _ in range(5):
        for sub in ("LibreVNA/release", "LibreVNA", "librevna/release", "librevna"):
            for name in _LIBREVNA_EXE_NAMES:
                cands.append(walk / sub / name)
        if walk.parent == walk:
            break
        walk = walk.parent

    # 2) Common Windows install paths
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root = os.environ.get(env)
        if root:
            for sub in ("LibreVNA", "LibreVNA-GUI"):
                for name in _LIBREVNA_EXE_NAMES:
                    cands.append(Path(root) / sub / name)
                    cands.append(Path(root) / sub / "release" / name)

    return cands


def _drive_search(max_depth: int = 4) -> Optional[Path]:
    """Last-resort glob-walk near the app's drive root for any LibreVNA install."""
    here = app_root()
    drive_root = Path(here.drive + os.sep) if here.drive else here.anchor
    drive_root = Path(drive_root)
    if not drive_root.exists():
        return None
    patterns = [
        "LibreVNA*/release/LibreVNA-GUI.exe",
        "LibreVNA*/LibreVNA-GUI.exe",
        "*/LibreVNA*/release/LibreVNA-GUI.exe",
        "*/LibreVNA*/LibreVNA-GUI.exe",
    ]
    for pat in patterns:
        try:
            for hit in drive_root.glob(pat):
                if _is_librevna(hit):
                    return hit
        except (PermissionError, OSError):
            continue
    return None


def find_librevna_gui(cached: Optional[str] = None) -> Optional[Path]:
    """
    Resolve the path to LibreVNA-GUI(.exe). Returns None if not found anywhere.
    Order: cached → relatives → install dirs → PATH → drive scan.
    """
    if cached:
        p = Path(cached)
        if _is_librevna(p):
            return p

    for cand in _candidate_paths():
        if _is_librevna(cand):
            return cand

    on_path = shutil.which("LibreVNA-GUI") or shutil.which("LibreVNA-GUI.exe")
    if on_path:
        p = Path(on_path)
        if _is_librevna(p):
            return p

    return _drive_search()


def remember_librevna_path(path: Path) -> None:
    cfg = load_config()
    cfg["librevna_path"] = str(path)
    save_config(cfg)
