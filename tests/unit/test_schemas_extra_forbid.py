"""OWASP API3 (BOPLA) — input schemas must reject unknown fields.

Loads all *Update/*Create/*Patch/*In/*Request BaseModel subclasses from the
app and asserts they have model_config with extra='forbid'.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest
from pydantic import BaseModel

import app

INPUT_SUFFIXES = ("Create", "Update", "Patch", "In", "Request", "Body")
# Exempt: known response/internal schemas that happen to match the suffix.
EXEMPT = {
    # These are response DTOs that happen to end with a matching suffix.
    # ConversationDto, MessageDto — output-only, suffix "Dto" but safe to note.
    # No current exemptions needed; all *Request/*Patch/*In classes are input.
}


def _all_models():
    found = []
    seen = set()
    for mod_info in pkgutil.walk_packages(app.__path__, prefix="app."):
        try:
            mod = importlib.import_module(mod_info.name)
        except Exception:
            continue
        for name, obj in inspect.getmembers(mod):
            key = (mod_info.name, name)
            if key in seen:
                continue
            seen.add(key)
            if (
                inspect.isclass(obj)
                and issubclass(obj, BaseModel)
                and obj is not BaseModel
                and any(name.endswith(s) for s in INPUT_SUFFIXES)
                and name not in EXEMPT
            ):
                found.append((mod_info.name, name, obj))
    return found


@pytest.mark.parametrize(
    "mod,name,cls", _all_models(), ids=lambda x: x if isinstance(x, str) else ""
)
def test_input_schema_forbids_extra_fields(mod, name, cls):
    extra = cls.model_config.get("extra")
    assert extra == "forbid", (
        f"{mod}.{name} must set model_config = ConfigDict(extra='forbid') "
        f"to prevent BOPLA mass assignment. Got: {extra!r}"
    )
