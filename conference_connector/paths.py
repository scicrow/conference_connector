"""Project layout resolution.

conference_connector is a library invoked from inside a *project directory* (e.g. eccb_2026), not
from its own install location. Every path is therefore relative to the current working
directory by default, overridable via environment variables so a project can keep its
config/data anywhere it likes.
"""
from __future__ import annotations

import os
from pathlib import Path


def _resolve(env_var: str, default_name: str) -> Path:
    override = os.environ.get(env_var)
    if override:
        return Path(override).resolve()
    return Path.cwd() / default_name


def config_dir() -> Path:
    return _resolve("CONFERENCE_CONNECTOR_CONFIG_DIR", "config")


def data_dir() -> Path:
    return _resolve("CONFERENCE_CONNECTOR_DATA_DIR", "data")


def raw_dir() -> Path:
    return data_dir() / "raw"


def interim_dir() -> Path:
    return data_dir() / "interim"


def processed_dir() -> Path:
    return data_dir() / "processed"


def outputs_dir() -> Path:
    return _resolve("CONFERENCE_CONNECTOR_OUTPUT_DIR", "outputs")


def fixtures_dir() -> Path:
    return _resolve("CONFERENCE_CONNECTOR_FIXTURES_DIR", "fixtures")
