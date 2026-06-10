"""D8 — PII log grep gate tests.

Asserts:
  1. The actual `app/` tree is clean (regression gate).
  2. Synthetic violations are caught.
  3. DEBUG calls are not flagged.
"""

from __future__ import annotations

import sys
from pathlib import Path

from scripts.pii_log_grep import BANNED_TOKENS, main, scan_file

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_app_tree_is_clean(capsys) -> None:
    """Run the gate against the real app/ — must pass."""
    cwd_backup = sys.argv[:]
    try:
        rc = main([str(REPO_ROOT / "app")])
        assert rc == 0, capsys.readouterr().err
    finally:
        sys.argv = cwd_backup


def test_synthetic_info_with_bmi_is_flagged(tmp_path: Path) -> None:
    f = tmp_path / "leak.py"
    f.write_text(
        "import logging\n"
        "log = logging.getLogger(__name__)\n"
        "log.info('user check bmi=%s', 28.4)\n"
    )
    offenders = scan_file(f)
    assert offenders, "INFO call with bmi must be flagged"
    assert offenders[0][1] == "bmi"


def test_synthetic_debug_with_bmi_is_flagged(tmp_path: Path) -> None:
    """Policy extended 2026-06-09: DEBUG is now in scope.

    DEBUG can leak in dev/staging dumps and gets attached to Sentry
    issues. The Patrón #2 sweep also introduced many ``log.exception``
    calls that we cannot allow to ride PII along the stack trace
    payload — so the gate uniformly covers every tier now.
    """
    f = tmp_path / "leak.py"
    f.write_text(
        "import logging\n"
        "log = logging.getLogger(__name__)\n"
        "log.debug('intake_bias bmi=%s', 28.4)\n"
    )
    offenders = scan_file(f)
    assert offenders, "DEBUG call with bmi must be flagged under extended policy"
    assert offenders[0][1] == "bmi"


def test_synthetic_exception_with_email_is_flagged(tmp_path: Path) -> None:
    """``log.exception(..., email=...)`` MUST be caught — the stack
    trace ships to log aggregators and PII riding the kwargs leaks."""
    f = tmp_path / "exc.py"
    f.write_text(
        "import logging\n"
        "log = logging.getLogger(__name__)\n"
        "try:\n"
        "    x = 1\n"
        "except Exception:\n"
        "    log.exception('boom', email='x@y.com')\n"
    )
    offenders = scan_file(f)
    assert offenders, "exception() call with email must be flagged"
    assert offenders[0][1] == "email"


def test_multi_line_info_call_continuation_is_scanned(tmp_path: Path) -> None:
    f = tmp_path / "multi.py"
    f.write_text(
        "import logging\n"
        "log = logging.getLogger(__name__)\n"
        "log.warning(\n"
        "    'user contact',\n"
        "    email='x@y.com',\n"
        ")\n"
    )
    offenders = scan_file(f)
    assert offenders
    assert offenders[0][1] == "email"


def test_banned_tokens_list_documented() -> None:
    """Sanity guard against silent narrowing of the ban list."""
    required = {"bmi", "peso", "weight_kg", "allergen", "email", "phone"}
    assert required <= set(BANNED_TOKENS)
