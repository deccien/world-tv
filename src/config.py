"""Load the YAML configuration files."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def _load(name: str, config_dir: Path | None = None) -> dict:
    path = (config_dir or CONFIG_DIR) / name
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_settings(config_dir: Path | None = None) -> dict:
    s = _load("settings.yaml", config_dir)
    user = str(s.get("github_user") or "YOUR_GITHUB_USERNAME")
    repo = str(s.get("repo_name") or "world-tv")
    s["user_agent"] = str(s.get("user_agent", "WorldTV-Builder/1.0")).format(github_user=user, repo_name=repo)
    env_url = os.environ.get("PAGES_URL", "").strip()
    url = env_url or str(s.get("pages_url") or "").strip()
    if not url and user != "YOUR_GITHUB_USERNAME":
        url = f"https://{user.lower()}.github.io/{repo}/"
    if url and not url.endswith("/"):
        url += "/"
    s["resolved_pages_url"] = url
    return s


def load_sources(config_dir: Path | None = None) -> list:
    data = _load("sources.yaml", config_dir)
    srcs = [s for s in data.get("sources", []) if s.get("enabled")]
    return sorted(srcs, key=lambda s: s.get("priority", 100))


def load_all_sources(config_dir: Path | None = None) -> list:
    return _load("sources.yaml", config_dir).get("sources", [])


def load_countries(config_dir: Path | None = None) -> dict:
    return _load("countries.yaml", config_dir)


def load_favorites(config_dir: Path | None = None) -> dict:
    return _load("favorites.yaml", config_dir)
