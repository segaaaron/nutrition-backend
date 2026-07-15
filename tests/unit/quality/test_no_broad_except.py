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


# Whitelist: {relative_path: {line_no, ...}}.
# Keep alphabetised by path for stable diffs.
# When you add a new entry, also add the OK-category in a comment.
ALLOWED_BROAD_EXCEPT: dict[str, set[int]] = {
    # OK6: generic decorator wrapping arbitrary user-supplied callable.
    "app/coach/application/chat_message.py": {190, 231},
    # OK4: best-effort cache miss + LLM call boundary.
    "app/coach/application/context_builder.py": {162},
    # OK4: cost-cap soft-skip + best-effort feature lookup.
    "app/coach/application/features.py": {50, 73, 307},
    # OK4: best-effort LLM intent classifier — falls back to rule-based.
    "app/coach/infrastructure/intent_classifier.py": {157, 181, 186},
    # OK4: OpenAI client wrappers with structured fallback.
    "app/coach/infrastructure/openai_coach_client.py": {110, 119},
    # OK4: optional repository read — empty on infra hiccup.
    "app/coach/infrastructure/repositories.py": {35},
    # OK6: circuit breaker wraps arbitrary callable.
    "app/core/circuit_breaker.py": {98},
    # OK4: tiktoken optional + fallback heuristic for token count.
    "app/core/cost_cap.py": {104},
    # OK5: session.commit() rollback wrapper — re-raises after rollback.
    "app/core/db.py": {92},
    # OK3: ErrorTracker boundary — tracker must NEVER raise; re-raises original.
    "app/core/error_tracker.py": {84, 95, 119, 125, 130},
    # OK1: event bus per-handler boundary + outbox spool fallback.
    "app/core/event_bus.py": {241, 249, 372},
    # OK3: Redis IP rate-limit fail-open on infra error.
    "app/core/ip_rate_limit.py": {116},
    # OK3: arq queue depth probe — returns 0 on any error (health probe).
    "app/core/metrics.py": {141},
    # OK4: catalogue lookup best-effort.
    "app/grocery/use_cases.py": {211},
    # OK4: best-effort metadata read from request.state; PII-safe input repr.
    "app/core/problem_details.py": {444, 448, 489},
    # OK4: pHash compute is a best-effort cost optimization (logged, returns None).
    "app/imaging/infrastructure/phash.py": {63},
    # OK5: identity session rollback wrapper — re-raises.
    "app/identity/presentation/dependencies.py": {94},
    # OK4: OAuth verifier collapses provider errors into Unauthenticated.
    "app/identity/infrastructure/oauth_verifiers.py": {59},
    # OK3: identity rate-limit fail-open on infra surprise (logged).
    "app/identity/infrastructure/rate_limit.py": {53},
    # OK3: /readyz health probe — reports component status without 500.
    "app/main.py": {270, 276, 284},
    # OK1: nutrition event handlers — best-effort with explicit log.
    "app/nutrition/event_handlers.py": {76, 108},
    # OK4: ensure_goals fallback wrapper — logs and re-raises domain error.
    "app/plan/application/create_plan.py": {169, 448},
    # OK4: plan gen rate-limit Redis fail-open — Redis down must not block plan creation.
    "app/plan/presentation/router.py": {468},
    # OK4: taste profile cache fetch — falls through on miss.
    "app/plan/application/taste_profile.py": {48},
    # OK4: plan cache best-effort.
    "app/plan/infrastructure/cache.py": {32},
    # OK4: enqueue-and-wait — wrap a terminal worker failure into 503 (BE-7).
    "app/plan/infrastructure/plan_enqueuer.py": {68},
    # OK4: OpenAI coherence client — structured fallback.
    "app/plan/infrastructure/openai_coherence_client.py": {107, 120, 137, 189, 228},
    # OK4: taste fetcher SQL best-effort.
    "app/plan/infrastructure/taste_fetcher.py": {66},
    # OK1: profile event handler boundary.
    "app/profile/application/event_handlers.py": {74},
    # OK4: profile use_case OpenAI wrappers.
    "app/profile/application/use_cases.py": {135, 259},
    # OK4: recipes router fallback.
    "app/recipes/presentation/router.py": {58},
    # OK4: feature-flags Redis cache fail-open — leaderboard flag gate.
    "app/gamification/presentation/router.py": {179, 193},
    # OK4: i18n translation must never break a request + Redis locale cache fail-open.
    "app/shared/i18n/fastapi_dep.py": {71, 96, 118, 128, 139},
    # OK1: tracking event handler best-effort cache miss.
    "app/tracking/event_handlers.py": {21, 32, 43},
    # OK4: aggregate table optional — fallback path documented.
    "app/tracking/infrastructure/repositories.py": {80, 108},
    # OK4: dish-anchor lookup is a best-effort second opinion (logged).
    "app/vision/infrastructure/dish_anchor.py": {53},
    # OK1: notification handlers — fire-and-forget push, must not propagate.
    "app/notifications/application/event_handlers.py": {80, 116},
    # OK4: Redis cache helpers + Open Food Facts external API — best-effort, fail-open.
    "app/vision/infrastructure/usda_fdc.py": {406, 414, 618},
    # OK4: OpenAI vision wrappers with fallback contracts.
    "app/vision/application/learn_user_correction.py": {175},
    "app/vision/application/process_vision_job.py": {190, 431, 476, 554, 568},
    # OK4: macro grounding + USDA fallback — DB lookup best-effort.
    "app/vision/infrastructure/macro_grounder.py": {73},
    # OK4: plan context SQL — best-effort LLM hint.
    "app/vision/infrastructure/plan_context.py": {69},
    # OK4: user profile + portion calibration + portion anchors — Redis/DB best-effort.
    "app/vision/infrastructure/user_context.py": {46, 68, 90, 95, 125},
    # OK4: food log INSERT slot-cap Redis fail-open.
    "app/vision/infrastructure/food_log_writer.py": {60},
    # OK4: Redis inflight lock — fail-open on acquire/release errors + DB poll skip.
    "app/vision/infrastructure/inflight_lock.py": {32, 42, 68},
    "app/vision/infrastructure/food_matcher.py": {124},
    # OK4: dark-image enhancement (best-effort PIL), prefilter fail-open, invoke retry.
    "app/vision/infrastructure/openai_vision.py": {397, 403, 449, 615, 912},
    # OK4: plate explanation is decorative — poll must still serve items.
    "app/vision/presentation/router.py": {174, 219},
    # OK4: voice/food text parser — LLM best-effort.
    "app/voice/infrastructure/food_text_parser.py": {261},
    # OK2: worker task top-level boundaries (Arq retry control).
    "worker/anomaly_score_task.py": {224},
    "worker/coach_tasks.py": {62, 79, 96},
    "worker/nightly_maintenance.py": {87, 102},
    "worker/outbox_drainer.py": {148},
    "worker/outbox_listener.py": {56, 71, 78, 87},
    "worker/plan_tasks.py": {73},
    "worker/vision_tasks.py": {65},
}


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
    """Return the set of line numbers where broad except handlers live."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and _is_broad_except_node(node):
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
