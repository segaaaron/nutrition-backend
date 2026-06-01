"""Dump the FastAPI app's OpenAPI schema to ``docs/openapi/openapi.json``.

Idempotent: re-running with no schema changes leaves the file byte-identical
(pretty-printed, sorted keys).

Usage::

    uv run python -m scripts.export_openapi
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "docs" / "openapi" / "openapi.json"


def export() -> Path:
    # Import inside the function so that import errors surface with a real
    # exit code rather than at module-load time (helps CI diagnostics).
    from app.main import create_app

    app = create_app()
    schema: dict[str, Any] = app.openapi()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False)
    # Trailing newline — POSIX text file convention.
    OUTPUT_PATH.write_text(payload + "\n", encoding="utf-8")
    return OUTPUT_PATH


def main() -> int:
    path = export()
    print(f"openapi schema written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
