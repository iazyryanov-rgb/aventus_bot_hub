import sys
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    return app_dir() / "data"


def icon_path() -> Path:
    return app_dir() / "app-icon.png"


def ico_path() -> Path:
    return app_dir() / "app-icon.ico"
