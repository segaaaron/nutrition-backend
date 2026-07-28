"""Static AST gate — block new ``except Exception`` / bare ``except`` sites.

Rationale (Patrón #2):
  ``except Exception:`` that swallows errors silently is the second-most
  common bug pattern that has bitten this codebase (caused the initial
  POST /register 500). Every new broad-except site MUST be explicitly
  whitelisted here with a justification comment, or the test fails.

Mechanics:
  - Walk ``app/`` and ``worker/`` for ``.py`` files.
  - AST-parse each, locate every ``ast.ExceptHandler`` whose type is
    either ``None`` (bare ``except:``) or ``Name(id='Exception')``.
  - Compare findings against ``ALLOWED_BROAD_EXCEPT`` keyed by
    ``relative_path:line_no``.
  - Fail loudly on:
      1. Findings NOT in whitelist  ("new broad except added")
      2. Whitelist entries NOT found ("stale whitelist entry — remove")

Adding to whitelist:
  Only when the except site falls under one of these justified categories,
  enumerated in the module docstring of each handler:
    OK1: event/handler bus boundary (must not crash sibling handlers)
    OK2: worker task top-level (must not crash arq loop or cause infinite
         retry)
    OK3: middleware/health probe boundary (must report degraded state
         without 500)
    OK4: best-effort cache/queue/telemetry write (logged + swallowed)
    OK5: SQLAlchemy session rollback wrapper (re-raises after rollback)
    OK6: circuit-breaker / generic decorator wrapping arbitrary callable
    OK7: cleanup / shutdown / finally block

  Each whitelisted handler MUST either:
    a) Re-raise (propagate after side-effect like rollback/log)
    b) Log via ``log.exception(...)`` or equivalent before swallowing
    c) Be explicitly documented in-line with a ``# noqa: BLE001`` and a
       short comment explaining which OK-category applies.

NEVER add a site that swallows silently without log.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


# Whitelist de líneas de excepción amplia sin ``# noqa: BLE001``.
# Desde 2026-07-27: el scanner excluye automáticamente cualquier línea que tenga
# ``# noqa: BLE001`` — esas líneas ya tienen justificación inline y no necesitan
# entrada aquí. Por tanto, este dict es vacío: todos los broad-excepts autorizados
# llevan el comentario noqa en el código fuente.
#
# Para autorizar un nuevo broad-except: agrega ``# noqa: BLE001 — OK<N>: razón``
# en la línea del except. NO agregues entradas aquí a menos que la línea genuinamente
# no pueda tener el comentario noqa (caso extremadamente raro).
ALLOWED_BROAD_EXCEPT: dict[str, set[int]] = {}


def _is_broad_except_node(node: ast.ExceptHandler) -> bool:
    """True if handler catches bare ``except:`` or ``except Exception``."""
    if node.type is None:
        return True  # bare except
    if isinstance(node.type, ast.Name) and node.type.id == "Exception":
        return True
    # except (Exception, X) — also considered broad.
    if isinstance(node.type, ast.Tuple):
        for elt in node.type.elts:
            if isinstance(elt, ast.Name) and elt.id == "Exception":
                return True
    return False


def _scan_file(path: Path) -> set[int]:
    """Return line numbers of broad except handlers that lack a noqa suppression.

    Lines with ``# noqa: BLE001`` are self-documented suppressions — they already
    carry an inline justification and do not need a separate whitelist entry.
    Only lines WITHOUT the suppression comment reach the whitelist gate.
    """
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    source_lines = source.splitlines()
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _is_broad_except_node(node):
            line_idx = node.lineno - 1  # 0-based
            line_text = source_lines[line_idx] if line_idx < len(source_lines) else ""
            if "# noqa: BLE001" not in line_text:
                found.add(node.lineno)
    return found


def _walk_targets() -> dict[str, set[int]]:
    """Walk app/ + worker/ and return {relative_path: {lines...}}."""
    findings: dict[str, set[int]] = {}
    for root_name in ("app", "worker"):
        root = REPO_ROOT / root_name
        for py in root.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            lines = _scan_file(py)
            if lines:
                findings[str(py.relative_to(REPO_ROOT))] = lines
    return findings


def test_no_unwhitelisted_broad_except() -> None:
    """Fail if any broad-except site is found that isn't whitelisted.

    Also fails if whitelist has stale entries (line no longer holds a
    broad except) — forces hygiene as code moves.
    """
    findings = _walk_targets()

    # 1) New broad-excepts not in whitelist
    new_offenders: list[str] = []
    for path, lines in findings.items():
        allowed = ALLOWED_BROAD_EXCEPT.get(path, set())
        new_lines = lines - allowed
        for ln in sorted(new_lines):
            new_offenders.append(f"{path}:{ln}")

    # 2) Stale whitelist entries — line no longer broad-except
    stale: list[str] = []
    for path, allowed_lines in ALLOWED_BROAD_EXCEPT.items():
        actual = findings.get(path, set())
        for ln in sorted(allowed_lines - actual):
            stale.append(f"{path}:{ln}")

    msg_parts = []
    if new_offenders:
        msg_parts.append(
            "NEW broad-except site(s) detected (add to ALLOWED_BROAD_EXCEPT "
            "with OK-category justification, OR narrow the exception class):\n  - "
            + "\n  - ".join(new_offenders)
        )
    if stale:
        msg_parts.append(
            "STALE whitelist entries (line no longer holds a broad except "
            "— remove from ALLOWED_BROAD_EXCEPT):\n  - " + "\n  - ".join(stale)
        )
    if msg_parts:
        raise AssertionError("\n\n".join(msg_parts))


def test_whitelist_paths_exist() -> None:
    """Each whitelisted path must exist (no rotting entries)."""
    missing = [p for p in ALLOWED_BROAD_EXCEPT if not (REPO_ROOT / p).is_file()]
    assert not missing, f"Whitelist references missing files: {missing}"
