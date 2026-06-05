"""Unit tests for the i18n error seed script — inventory + idempotency.

Pure-Python tests: we do not exercise Postgres here (covered by the
integration test using the real entrypoint). These tests assert:

* every DomainError ``type_slug`` has a translation entry,
* every classified BusinessRuleViolation rule has an entry,
* row expansion is deterministic and complete,
* the SQL is an UPSERT on the right PK (text inspection).
"""

from __future__ import annotations

from app.core import errors as core_errors
from app.core.problem_details import _PLAN_RULE_TITLES
from scripts.seed_i18n_errors import (
    _UPSERT_SQL,
    ERROR_MESSAGES,
    VALIDATION_MESSAGES,
    _expand_error_rows,
    _expand_validation_rows,
)


def _all_domain_error_slugs() -> set[str]:
    out: set[str] = set()
    for name in dir(core_errors):
        cls = getattr(core_errors, name)
        if (
            isinstance(cls, type)
            and issubclass(cls, core_errors.DomainError)
            and cls is not core_errors.DomainError
        ):
            out.add(cls.type_slug.replace("-", "_"))
    return out


def test_every_domain_error_subclass_has_translation_entry() -> None:
    slugs = _all_domain_error_slugs()
    missing = slugs - set(ERROR_MESSAGES.keys())
    assert not missing, f"Missing i18n entries for: {sorted(missing)}"


def test_every_classified_business_rule_has_entry() -> None:
    # Classifier rules + the two prefix-classified ones.
    keys = set(_PLAN_RULE_TITLES.keys())
    keys.update({"segment_unsupported_mvp", "profile_missing"})
    missing = keys - set(ERROR_MESSAGES.keys())
    assert not missing, f"Missing classified rule entries: {sorted(missing)}"


def test_every_entry_has_both_locales_for_title() -> None:
    for key, entry in ERROR_MESSAGES.items():
        title = entry["title"]
        assert title is not None
        assert set(title.keys()) == {"es", "en"}, f"{key} title missing locale"


def test_detail_when_present_has_both_locales() -> None:
    for key, entry in ERROR_MESSAGES.items():
        detail = entry["detail"]
        if detail is None:
            continue
        assert set(detail.keys()) == {"es", "en"}, f"{key} detail missing locale"


def test_validation_messages_have_both_locales() -> None:
    for key, locales in VALIDATION_MESSAGES.items():
        assert set(locales.keys()) == {"es", "en"}, f"{key} missing locale"


def test_expand_error_rows_count_matches_inventory() -> None:
    rows = _expand_error_rows()
    expected = 0
    for entry in ERROR_MESSAGES.values():
        expected += 2  # title × {es,en}
        if entry["detail"] is not None:
            expected += 2  # detail × {es,en}
    assert len(rows) == expected


def test_expand_validation_rows_count_matches_inventory() -> None:
    rows = _expand_validation_rows()
    assert len(rows) == len(VALIDATION_MESSAGES) * 2


def test_expand_rows_are_unique_by_primary_key() -> None:
    rows = _expand_error_rows() + _expand_validation_rows()
    pks = [(r["scope"], r["key"], r["locale"]) for r in rows]
    assert len(pks) == len(set(pks)), "duplicate (scope,key,locale) in seed rows"


def test_upsert_sql_targets_correct_conflict_target() -> None:
    sql = str(_UPSERT_SQL)
    assert "ON CONFLICT (scope, key, locale)" in sql
    assert "DO UPDATE" in sql


def test_keys_are_canonical_snake_case() -> None:
    for key in ERROR_MESSAGES:
        # snake_case: lowercase + underscores. No dashes (those are URN-only).
        assert "-" not in key, f"{key} must be snake_case, not kebab"
        assert key == key.lower(), f"{key} must be lowercase"
