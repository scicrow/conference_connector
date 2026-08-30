"""Single project config file.

One project directory (one conference/profile combination) holds one
config/config.yaml with everything that shapes scoring and ranking: research threads
and keywords, prefilter settings, and the ranking weights (composite formula,
geography tiers, role tables, output tier cutoffs). See config/config.example.yaml
for the schema.

Writing this file by hand is the fallback path, not the intended one -- the
conference-scout skill interviews you about your research and outreach goals and
writes it for you (see skills/conference-scout/SKILL.md). The file exists as the
stable, reproducible artifact underneath that conversation: ingest/prefilter/rank/
render run as separate commands, sometimes hours or days apart while you tune
weights, and something has to hold the answer in between -- re-prompting an LLM for
your profile on every single run would make re-running `rank` after a weight tweak
nondeterministic instead of instant.

Loaded once per process and cached; call reload() if the file changes and you need
to see the update without starting a new process (rare in normal CLI usage, useful
in a long-lived session or notebook).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from conference_connector.paths import config_dir

CONFIG_FILENAME = "config.yaml"

_cache: dict | None = None


def config_path() -> Path:
    return config_dir() / CONFIG_FILENAME


def load() -> dict:
    global _cache
    if _cache is None:
        path = config_path()
        _cache = yaml.safe_load(path.read_text()) or {} if path.exists() else {}
    return _cache


def reload() -> None:
    global _cache
    _cache = None
