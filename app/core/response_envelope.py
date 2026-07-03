"""Response envelope middleware.

Wraps every JSON response in a consistent envelope:

  Success (2xx):
    {"success": true,  "code": 200, "data":  <original body>}

  Error (4xx/5xx):
    {"success": false, "code": 422, "error": <original problem+json body>}

Skipped transparently:
  - /health, /metrics, /docs, /redoc, /openapi.json  (infra endpoints)
  - Streaming responses (no Content-Length)
  - Non-JSON content types
"""

from __future__ import annotations

import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_SKIP_PREFIXES = ("/healthz", "/readyz", "/health", "/metrics", "/docs", "/redoc", "/openapi.json")
_JSON_TYPES = ("application/json", "application/problem+json")


class ResponseEnvelopeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if any(request.url.path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        response = await call_next(request)

        ct = response.headers.get("content-type", "")
        if not any(ct.startswith(j) for j in _JSON_TYPES):
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            # Can't parse — pass through untouched.
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=ct,
            )

        code = response.status_code
        is_success = 200 <= code < 300

        envelope: dict = {
            "success": is_success,
            "code": code,
        }
        if is_success:
            envelope["data"] = payload
        else:
            envelope["error"] = payload

        content = json.dumps(envelope, ensure_ascii=False, default=str)
        headers = dict(response.headers)
        headers["content-length"] = str(len(content.encode()))

        return Response(
            content=content,
            status_code=code,
            headers=headers,
            media_type="application/json",
        )
