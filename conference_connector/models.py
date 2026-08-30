"""Shared item schema. Every adapter, regardless of source conference or platform,
normalises into this shape."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

ItemKind = Literal["poster", "talk", "keynote", "tutorial", "workshop"]


class Author(BaseModel):
    name: str
    affiliation_raw: str = ""
    affiliation_norm: str = ""
    country: str = ""
    position: int = 0          # 1-indexed position in the author list
    is_presenter: bool = False
    is_last: bool = False


class Item(BaseModel):
    item_id: str                      # "{kind}:{board_or_slug}" -- unique within a conference
    kind: ItemKind
    title: str
    abstract: str = ""
    track: str = ""
    board_id: Optional[str] = None      # posters, if the conference assigns them
    session_name: Optional[str] = None  # the parallel-session/track title, for talks
    presentation_type: Optional[str] = None  # e.g. "proceedings" | "highlight talk"
    day: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    room: Optional[str] = None
    authors: list[Author] = Field(default_factory=list)
    chairs: list[str] = Field(default_factory=list)       # talks: session moderators
    organisers: list[str] = Field(default_factory=list)   # tutorials/workshops
    keywords: list[str] = Field(default_factory=list)
    url: str = ""
    source: str = ""                  # adapter-defined source tag, e.g. "posters_html"
