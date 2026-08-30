"""Run an adapter and write the unified item list.

This module doesn't know which conference it's ingesting -- that's the whole point.
The adapter slug names a module under conference_connector.adapters (or a project-registered one)
that exposes fetch_all(refresh) -> list[Item].
"""
from __future__ import annotations

import json
from collections import Counter

from conference_connector.adapters import get as get_adapter
from conference_connector.models import Item
from conference_connector.paths import interim_dir

ITEMS_FILENAME = "items.jsonl"


def items_path():
    return interim_dir() / ITEMS_FILENAME


def build_items(adapter_slug: str, refresh: bool = False) -> list[Item]:
    adapter = get_adapter(adapter_slug)
    return adapter.fetch_all(refresh=refresh)


def write_items(items: list[Item]) -> None:
    interim_dir().mkdir(parents=True, exist_ok=True)
    with items_path().open("w", encoding="utf-8") as f:
        for item in items:
            f.write(item.model_dump_json() + "\n")


def load_items() -> list[Item]:
    items = []
    with items_path().open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(Item.model_validate_json(line))
    return items


def main(adapter_slug: str, refresh: bool = False) -> None:
    items = build_items(adapter_slug, refresh=refresh)
    write_items(items)

    kinds = Counter(it.kind for it in items)
    print(f"Wrote {len(items)} items to {items_path()}")
    for kind, n in sorted(kinds.items()):
        print(f"  {kind:10s} {n}")
