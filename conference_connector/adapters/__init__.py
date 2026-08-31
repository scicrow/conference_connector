"""Adapter registry.

conference_connector ships one reference adapter (eccb2026) so there's a worked example to read
and copy. Real usage is expected to add a project-local adapter for whatever conference
the user actually cares about -- see conference_connector/skills/conference-scout/references/adapter-authoring.md.

A project can register its own adapter without editing this file by calling
`register(slug, module)` before `get(slug)` is called (e.g. from a small bootstrap
script in the project directory), or by installing a package that exposes a
`conference_connector.adapters` entry point (not required for local/private use).
"""
from __future__ import annotations

from importlib import import_module
from types import ModuleType

_REGISTRY: dict[str, ModuleType] = {}

_BUILTIN = {
    "eccb2026": "conference_connector.adapters.eccb2026",
}


def register(slug: str, module: ModuleType) -> None:
    _REGISTRY[slug] = module


def get(slug: str) -> ModuleType:
    if slug in _REGISTRY:
        return _REGISTRY[slug]
    if slug in _BUILTIN:
        module = import_module(_BUILTIN[slug])
        _REGISTRY[slug] = module
        return module
    raise KeyError(
        f"No adapter registered for '{slug}'. Built-in adapters: {sorted(_BUILTIN)}. "
        "Register a project-local adapter with conference_connector.adapters.register(slug, module) "
        "before calling get(), or pass --adapter-module a.b.c to the CLI."
    )


def available() -> list[str]:
    return sorted(set(_BUILTIN) | set(_REGISTRY))
