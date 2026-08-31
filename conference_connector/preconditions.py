"""Friendly precondition checks for pipeline stages.

The stages depend on each other's output files, so running them out of order is the
single most common first-time mistake. Without these checks that surfaces as a raw
FileNotFoundError traceback pointing into pathlib, which tells the user nothing about
which command they actually needed to run first.
"""
from __future__ import annotations

from pathlib import Path


class PipelineError(Exception):
    """A precondition failure with an actionable message. The CLI prints it plainly
    (no traceback) -- these are user-fixable situations, not crashes."""


def require_file(path: Path, produced_by: str, description: str) -> None:
    if not path.exists():
        raise PipelineError(
            f"Missing {description}:\n"
            f"  {path}\n\n"
            f"Run `{produced_by}` first."
        )


def require_config(*keys: str) -> dict:
    """Load config.yaml and assert the given top-level keys exist."""
    from conference_connector import config

    cfg = config.load()
    if not cfg:
        raise PipelineError(
            f"No config found at {config.config_path()}.\n\n"
            "Run `conference_connector init` to create one from the template, then "
            "edit it (or let the conference-scout skill write it for you -- see "
            "`conference_connector install-skill`)."
        )
    missing = [k for k in keys if k not in cfg]
    if missing:
        raise PipelineError(
            f"Config at {config.config_path()} is missing required section(s): "
            f"{', '.join(missing)}.\n\n"
            "Compare it against the template in "
            "conference_connector/templates/config.example.yaml -- `conference_connector "
            "init --force` will rewrite a fresh copy (overwriting your edits)."
        )
    return cfg
