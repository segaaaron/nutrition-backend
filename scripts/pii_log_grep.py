"""CI gate — fail when INFO/WARN log lines under app/ contain PII tokens.

Rationale (D8 + docs/security/PII_LOG_POLICY.md):
  DEBUG is verbose-by-design and disabled in PROD log streams.
  INFO / WARN / ERROR ship to the aggregator (Loki / CloudWatch / etc.)
  and persist for the retention window of the platform. Any biometric
  (BMI, weight), free-text condition / allergen, or contact (email,
  phone) landing in those tiers is a GDPR / LGPD violation regardless of
  whether the field is "just a number".

Strategy:
  Walk `app/` for `.py` files. For every line that starts a logger call
  at INFO+ (`log.info`, `log.warning`, `log.warn`, `log.error`,
  `logger.info` …, `_logger.info` …), search the *full statement*
  (continuation lines included) for banned tokens (case-insensitive).
  Tokens are matched as substrings, not whole words, so `bmi=…`,
  `BMIvalue`, and `body_mass_index` all trip.

Exit code:
  0 — clean.
  1 — at least one offending line; offenders printed to stderr.

Usage:
  python -m scripts.pii_log_grep                # walk default app/
  python -m scripts.pii_log_grep app/ shared/   # walk multiple roots
"""
from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Iterator
from pathlib import Path

BANNED_TOKENS: tuple[str, ...] = (
    "bmi",
    "peso",
    "weight_kg",
    "condicion",
    "alergia",
    "allergen",
    "email",
    "phone",
)

# Word-boundary regex per token: matches only when the token sits between
# non-identifier characters (e.g. `bmi=`, `BMI:`, ` bmi `) and NOT inside
# longer identifiers like `submit` (contains "bmi" as a substring) or
# `phoneme` / `emailbox`. Compiled once.
_BANNED_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(rf"(?<![A-Za-z0-9_]){re.escape(tok)}(?![A-Za-z0-9_])", re.IGNORECASE)
    for tok in BANNED_TOKENS
)

# Any logger call at INFO / WARN / ERROR / CRITICAL. DEBUG is intentionally
# excluded — it's verbose telemetry and disabled in PROD log shipping.
_LOG_CALL = re.compile(
    r"""\b
        (?:log|logger|_logger|_log)        # common logger identifiers
        \s*\.\s*
        (info|warning|warn|error|critical) # tier filter
        \s*\(
    """,
    re.VERBOSE,
)


def _iter_py_files(roots: Iterable[Path]) -> Iterator[Path]:
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            yield root
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path


def _statement_spans(text: str) -> Iterator[tuple[int, int]]:
    """Yield (start_line, end_line) for every log-call statement.

    The end is found by paren-counting from the first `(` so multi-line
    log calls have their continuation lines included in the scan.
    """
    for match in _LOG_CALL.finditer(text):
        i = match.end() - 1  # position of '('
        depth = 1
        n = len(text)
        j = i + 1
        while j < n and depth > 0:
            ch = text[j]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            j += 1
        start_line = text.count("\n", 0, match.start()) + 1
        end_line = text.count("\n", 0, j) + 1
        yield start_line, end_line


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return (line_no, banned_token, snippet) for every offending statement."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    lines = text.splitlines()
    offenders: list[tuple[int, str, str]] = []
    for start, end in _statement_spans(text):
        snippet = "\n".join(lines[start - 1 : end])
        for token, pattern in zip(BANNED_TOKENS, _BANNED_PATTERNS, strict=True):
            if pattern.search(snippet):
                offenders.append((start, token, snippet.strip()[:200]))
                break  # one finding per statement is enough
    return offenders


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    roots = [Path(a) for a in args] if args else [Path("app")]
    failures: list[str] = []
    for path in _iter_py_files(roots):
        for line_no, token, snippet in scan_file(path):
            failures.append(f"{path}:{line_no}: banned token '{token}' in: {snippet}")
    if failures:
        print("PII log audit: FAIL", file=sys.stderr)
        for f in failures:
            print(f, file=sys.stderr)
        print(f"\n{len(failures)} offending log statement(s).", file=sys.stderr)
        return 1
    print("PII log audit: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
