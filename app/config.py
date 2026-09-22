"""
Configuration management for Facebook Comment Collector.
Loads settings from .env file and environment variables, with support
for updating settings securely from within the desktop application.
"""

import sys
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv


@dataclass
class AppConfig:
    app_id: Optional[str] = None
    app_secret: Optional[str] = None
    access_token: Optional[str] = None
    output_dir: Path = Path("output")
    api_version: str = "v21.0"
    demo_mode: bool = False

    @property
    def has_access_token(self) -> bool:
        return bool(self.access_token and self.access_token.strip())


def get_project_root() -> Path:
    """
    Returns root directory of the application.
    When packaged as a frozen PyInstaller executable, returns the folder containing the .exe.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_env_path() -> Path:
    """Returns the path to the .env file."""
    return get_project_root() / ".env"


def load_config() -> AppConfig:
    """
    Loads configuration from .env file and environment variables.
    """
    env_path = get_env_path()
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
    else:
        # Also try default load_dotenv for CWD
        load_dotenv(override=True)

    app_id = os.getenv("META_APP_ID", "").strip() or None
    app_secret = os.getenv("META_APP_SECRET", "").strip() or None
    access_token = os.getenv("META_ACCESS_TOKEN", "").strip() or None
    demo_mode = os.getenv("DEMO_MODE", "false").strip().lower() in ("true", "1", "yes")

    output_dir = get_project_root() / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    return AppConfig(
        app_id=app_id,
        app_secret=app_secret,
        access_token=access_token,
        output_dir=output_dir,
        api_version=os.getenv("META_GRAPH_API_VERSION", "v21.0").strip(),
        demo_mode=demo_mode
    )


def save_config(
    access_token: Optional[str] = None,
    app_id: Optional[str] = None,
    app_secret: Optional[str] = None,
    demo_mode: Optional[bool] = None
) -> AppConfig:
    """
    Saves or updates configuration keys in the .env file.
    Does not overwrite unrelated keys.
    """
    env_path = get_env_path()
    lines = []
    existing_keys = set()

    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            lines = []

    new_lines = []
    updates = {
        "META_APP_ID": app_id,
        "META_APP_SECRET": app_secret,
        "META_ACCESS_TOKEN": access_token
    }
    if demo_mode is not None:
        updates["DEMO_MODE"] = "true" if demo_mode else "false"

    for line in lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                existing_keys.add(key)
                val = updates[key]
                if val is not None:
                    new_lines.append(f"{key}={val}\n")
                else:
                    new_lines.append(line)
                continue
        new_lines.append(line)

    # Append any keys that weren't already present
    for key, val in updates.items():
        if key not in existing_keys and val is not None:
            new_lines.append(f"{key}={val}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    # Reload into environment
    return load_config()
