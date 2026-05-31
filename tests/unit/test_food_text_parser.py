"""Voice / text parser regex-path tests — no network."""
from __future__ import annotations

import pytest

from app.voice.infrastructure.food_text_parser import parse_regex


def test_parse_grams_and_qty_words() -> None:
    items = parse_regex("100g de avena con 2 platanos y café con leche")
    names = [i.name for i in items]
    assert any("avena" in n for n in names)
    assert any("platano" in n for n in names)
    avena = next(i for i in items if "avena" in i.name)
    assert avena.quantity_g == 100


def test_parse_word_qty_and_default_portion() -> None:
    items = parse_regex("una manzana")
    assert items, "should parse 'una manzana' to one item via default-portion fallback"
    assert items[0].quantity_g == 180


def test_parse_empty_text_returns_empty() -> None:
    assert parse_regex("") == []


def test_parse_unrecognised_falls_back_to_empty() -> None:
    out = parse_regex("blahblahblahblah")
    assert out == []
