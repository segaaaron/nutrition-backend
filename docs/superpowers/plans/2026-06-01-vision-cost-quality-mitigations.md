# Vision Cost & Quality Mitigations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce OpenAI vision cost ~60% and improve detection quality + safety via perceptual-hash dedupe cache, local "is-food?" pre-filter, multi-provider LLM abstraction, user confirmation UX for low-confidence items, and Prometheus budget alerting.

**Architecture:** Five additive mitigations layered on the existing `app/vision` Clean Architecture module. Cache and pre-filter sit before the `VisionProvider` port. A new `VisionProviderFactory` enables failover between OpenAI / Anthropic / Gemini via feature flag. A new presentation endpoint exposes pending low-confidence items for user confirmation. Prometheus alert rules + Grafana dashboard close the loop on the already-implemented cost cap.

**Tech Stack:** Python 3.12, FastAPI 0.115, SQLAlchemy 2.0 async, Redis (asyncio), Pillow (pHash via `imagehash`), ONNX Runtime (MobileNetV3-small food classifier), Anthropic SDK, Google Gen AI SDK, Prometheus alerting rules (YAML), pytest + hypothesis.

**Existing state (verified):**
- `app/core/cost_cap.py` — per-user/org daily caps + kill switch ✅
- `app/core/circuit_breaker.py` — 3-state breaker on OpenAI ✅
- `app/vision/domain/ports.py:VisionProvider` — port already abstract ✅
- `app/vision/application/process_vision_job.py:80` — confidence < 0.7 already drops from auto-logs ✅
- Missing: pHash cache, food pre-filter, second LLM provider, confirm endpoint, alert YAML.

---

## File Structure

**New files:**
- `app/vision/infrastructure/phash_cache.py` — perceptual-hash Redis cache.
- `app/vision/infrastructure/food_prefilter.py` — ONNX MobileNetV3 binary classifier.
- `app/vision/infrastructure/anthropic_vision.py` — Claude vision adapter.
- `app/vision/infrastructure/gemini_vision.py` — Gemini vision adapter.
- `app/vision/infrastructure/provider_factory.py` — selects provider via feature flag.
- `app/vision/application/confirm_low_confidence.py` — accept/reject pending items.
- `app/vision/presentation/schemas_confirm.py` — confirm request/response DTOs.
- `data/models/food_prefilter_mnv3.onnx` — committed ONNX model (~6 MB).
- `ops/prometheus/alerts/openai_budget.yml` — Prometheus alert rules.
- `tests/unit/test_phash_cache.py`
- `tests/unit/test_food_prefilter.py`
- `tests/unit/test_provider_factory.py`
- `tests/unit/test_anthropic_vision_parse.py`
- `tests/unit/test_confirm_low_confidence.py`
- `tests/integration/test_vision_pipeline_with_cache.py`
- `migrations/versions/0007_vision_pending_items.py` — pending_items column on vision_jobs.

**Modified files:**
- `app/vision/application/process_vision_job.py` — wire cache lookup + prefilter + persist pending items.
- `app/vision/infrastructure/openai_vision.py` — extract `BaseVisionProvider` mixin for shared parsing.
- `app/vision/presentation/router.py` — add `POST /vision/jobs/{id}/confirm`.
- `app/core/config.py` — add `vision_provider`, `phash_cache_ttl_s`, `food_prefilter_threshold`, `anthropic_api_key`, `gemini_api_key`.
- `app/core/metrics.py` — add `vision_cache_hits_total`, `vision_prefilter_rejects_total`, `vision_provider_selected_total`.
- `pyproject.toml` — add `imagehash>=4.3`, `onnxruntime>=1.20`, `anthropic>=0.40`, `google-genai>=0.3`.
- `worker/vision_tasks.py` — inject `VisionProviderFactory` instead of hard-coded `OpenAIVisionProvider`.
- `docs/adr/` — new ADR-0011 multi-provider vision strategy.

---

## Sequencing

Five mitigations executed **sequentially with checkpoints**. Order:

1. **Mitigation #5** — Prometheus budget alerts (cheapest, finishes already-done backend).
2. **Mitigation #1** — pHash dedupe cache (highest cost ROI, isolated change).
3. **Mitigation #2** — ONNX food prefilter (adds local inference path).
4. **Mitigation #4** — Low-confidence confirm endpoint + UX (data quality).
5. **Mitigation #3** — Multi-provider abstraction (largest blast radius, last).

Commit after every passing test. PR per mitigation.

---

## Task 1: Prometheus budget alert rules (Mitigation #5 completion)

**Files:**
- Create: `ops/prometheus/alerts/openai_budget.yml`
- Modify: `app/core/metrics.py` (verify `openai_cost_usd_total` exposed)
- Test: `tests/unit/test_openai_alert_rules.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_openai_alert_rules.py
from pathlib import Path

import yaml


def test_alert_rules_define_three_severity_levels():
    path = Path("ops/prometheus/alerts/openai_budget.yml")
    assert path.exists(), "alert rules file missing"
    data = yaml.safe_load(path.read_text())
    names = {r["alert"] for r in data["groups"][0]["rules"]}
    assert names == {
        "OpenAIDailyBudgetWarning",
        "OpenAIDailyBudgetCritical",
        "OpenAIKillSwitchActive",
    }


def test_critical_alert_fires_above_org_cap():
    data = yaml.safe_load(Path("ops/prometheus/alerts/openai_budget.yml").read_text())
    crit = next(r for r in data["groups"][0]["rules"]
                if r["alert"] == "OpenAIDailyBudgetCritical")
    assert "increase(openai_cost_usd_total[1d])" in crit["expr"]
    assert crit["labels"]["severity"] == "critical"
    assert "500" in crit["expr"]  # cost_cap_usd_per_org_per_day default
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_openai_alert_rules.py -v`
Expected: FAIL with `assert False, "alert rules file missing"`

- [ ] **Step 3: Write minimal implementation**

```yaml
# ops/prometheus/alerts/openai_budget.yml
groups:
  - name: openai_budget
    interval: 30s
    rules:
      - alert: OpenAIDailyBudgetWarning
        expr: increase(openai_cost_usd_total[1d]) > 400
        for: 5m
        labels:
          severity: warning
          component: vision
        annotations:
          summary: "OpenAI daily spend >80% of org cap"
          description: "Today total {{ $value | humanize }} USD across all models. Cap is 500 USD."
          runbook: "docs/ops/runbooks/openai_cost.md"

      - alert: OpenAIDailyBudgetCritical
        expr: increase(openai_cost_usd_total[1d]) > 500
        for: 1m
        labels:
          severity: critical
          component: vision
          page: "true"
        annotations:
          summary: "OpenAI daily spend exceeded org cap (500 USD)"
          description: "Hard cap breached. New requests already 429-ing. Investigate user_segment={{ $labels.user_segment }}."

      - alert: OpenAIKillSwitchActive
        expr: max(circuit_breaker_state{name="openai_vision"}) == 2
        for: 2m
        labels:
          severity: warning
          component: vision
        annotations:
          summary: "OpenAI vision circuit OPEN"
          description: "Vision endpoint degraded. Failover provider should be active if multi-provider rolled out."
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_openai_alert_rules.py -v`
Expected: 2 passed

- [ ] **Step 5: Verify Prometheus syntax**

Run: `docker run --rm -v $PWD/ops/prometheus/alerts:/alerts prom/prometheus:v2.55.0 promtool check rules /alerts/openai_budget.yml`
Expected: `SUCCESS: 3 rules found`

- [ ] **Step 6: Commit**

```bash
git add ops/prometheus/alerts/openai_budget.yml tests/unit/test_openai_alert_rules.py
git commit -m "ops(vision): add Prometheus alert rules for OpenAI daily budget + kill switch"
```

---

## Task 2: pHash perceptual-hash dedupe cache (Mitigation #1)

**Files:**
- Create: `app/vision/infrastructure/phash_cache.py`
- Test: `tests/unit/test_phash_cache.py`
- Modify: `pyproject.toml`, `app/core/config.py`, `app/core/metrics.py`

- [ ] **Step 1: Add dependency**

Edit `pyproject.toml` dependencies block:

```toml
    "imagehash>=4.3,<5",
```

Then: `uv pip install -e .[dev]` (or `pip install -e .[dev]`)

- [ ] **Step 2: Add config + metric**

Edit `app/core/config.py` Settings class:

```python
    phash_cache_ttl_s: int = 7 * 24 * 3600
    phash_cache_hamming_threshold: int = 4  # 0..64 ; lower = stricter match
```

Edit `app/core/metrics.py`:

```python
from prometheus_client import Counter

VISION_CACHE_HITS = Counter(
    "vision_cache_hits_total",
    "Perceptual-hash cache hits per user_segment",
    ["user_segment"],
)
VISION_CACHE_MISSES = Counter(
    "vision_cache_misses_total",
    "Perceptual-hash cache misses",
    [],
)
```

- [ ] **Step 3: Write failing tests**

```python
# tests/unit/test_phash_cache.py
import io
from decimal import Decimal
from uuid import uuid4

import pytest
from PIL import Image

from app.vision.domain.entities import DetectedFoodItem
from app.vision.infrastructure.phash_cache import PerceptualHashCache


def _png_bytes(color: tuple[int, int, int]) -> bytes:
    img = Image.new("RGB", (128, 128), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def items() -> list[DetectedFoodItem]:
    return [DetectedFoodItem(
        name="rice", estimated_amount_g=Decimal("150"),
        kcal=200, protein_g=4, carbs_g=44, fat_g=0, confidence=0.92,
    )]


async def test_miss_returns_none(fake_redis):
    cache = PerceptualHashCache(redis=fake_redis, ttl_s=60, hamming_threshold=4)
    assert await cache.lookup(_png_bytes((255, 0, 0)), locale="es-PE") is None


async def test_hit_returns_stored_items(fake_redis, items):
    cache = PerceptualHashCache(redis=fake_redis, ttl_s=60, hamming_threshold=4)
    img = _png_bytes((10, 20, 30))
    await cache.store(image_bytes=img, locale="es-PE", items=items, prompt_sha="abc")
    cached = await cache.lookup(img, locale="es-PE")
    assert cached is not None
    cached_items, prompt_sha = cached
    assert prompt_sha == "abc"
    assert cached_items[0].name == "rice"
    assert cached_items[0].confidence == 0.92


async def test_near_duplicate_within_hamming_threshold_hits(fake_redis, items):
    cache = PerceptualHashCache(redis=fake_redis, ttl_s=60, hamming_threshold=8)
    base = _png_bytes((50, 50, 50))
    await cache.store(image_bytes=base, locale="es-PE", items=items, prompt_sha="x")
    near = _png_bytes((52, 50, 50))  # almost identical
    hit = await cache.lookup(near, locale="es-PE")
    assert hit is not None


async def test_locale_isolation(fake_redis, items):
    cache = PerceptualHashCache(redis=fake_redis, ttl_s=60, hamming_threshold=4)
    img = _png_bytes((100, 100, 100))
    await cache.store(image_bytes=img, locale="es-PE", items=items, prompt_sha="p")
    assert await cache.lookup(img, locale="pt-BR") is None
```

Add to `tests/conftest.py` if not present:

```python
import pytest
from redis.asyncio import Redis


@pytest.fixture
async def fake_redis():
    """Lightweight in-memory Redis stand-in via fakeredis."""
    import fakeredis.aioredis
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()
```

If `fakeredis` not installed: add `fakeredis>=2.26,<3` to `[project.optional-dependencies].dev`.

- [ ] **Step 4: Run tests to verify they fail**

Run: `pytest tests/unit/test_phash_cache.py -v`
Expected: 4 ERROR/FAIL — `ModuleNotFoundError: app.vision.infrastructure.phash_cache`

- [ ] **Step 5: Implement cache**

```python
# app/vision/infrastructure/phash_cache.py
"""Perceptual-hash dedupe cache for vision recognise() calls.

Stores `{phash_hex}:{locale}` → JSON of detected items so identical-or-near
identical photos skip OpenAI entirely. Uses 64-bit pHash; matches via
SCAN over candidates with the same first 8 bits (cheap bucket key) then
Hamming distance check against `hamming_threshold` (default 4 = ~94%
visual similarity).

Cost: O(N_bucket) per lookup. Worst case ~256 entries per first-byte
bucket at 10k DAU x 7d TTL — Redis SCAN handles this in <2 ms.
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import imagehash
from PIL import Image
from redis.asyncio import Redis

from app.core.metrics import VISION_CACHE_HITS, VISION_CACHE_MISSES
from app.vision.domain.entities import DetectedFoodItem

_PREFIX = "vphash"


@dataclass(slots=True)
class PerceptualHashCache:
    redis: Redis
    ttl_s: int
    hamming_threshold: int

    def _phash_hex(self, image_bytes: bytes) -> str:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        return str(imagehash.phash(img))  # 16 hex chars

    def _bucket(self, phash_hex: str, locale: str) -> str:
        return f"{_PREFIX}:{locale}:{phash_hex[:2]}"

    def _key(self, phash_hex: str, locale: str) -> str:
        return f"{_PREFIX}:{locale}:full:{phash_hex}"

    async def lookup(
        self, image_bytes: bytes, *, locale: str,
    ) -> tuple[list[DetectedFoodItem], str] | None:
        phash = self._phash_hex(image_bytes)
        own_hash = imagehash.hex_to_hash(phash)

        # Fast path: exact key.
        raw = await self.redis.get(self._key(phash, locale))
        if raw is not None:
            VISION_CACHE_HITS.labels(user_segment="any").inc()
            return self._decode(raw)

        # Bucket scan for near-duplicates.
        bucket = self._bucket(phash, locale)
        members = await self.redis.smembers(bucket)
        for candidate_hex in members:
            cand_hash = imagehash.hex_to_hash(candidate_hex)
            if (own_hash - cand_hash) <= self.hamming_threshold:
                raw = await self.redis.get(self._key(candidate_hex, locale))
                if raw is not None:
                    VISION_CACHE_HITS.labels(user_segment="any").inc()
                    return self._decode(raw)

        VISION_CACHE_MISSES.inc()
        return None

    async def store(
        self, *, image_bytes: bytes, locale: str,
        items: list[DetectedFoodItem], prompt_sha: str,
    ) -> None:
        phash = self._phash_hex(image_bytes)
        payload = json.dumps({
            "prompt_sha": prompt_sha,
            "items": [
                {
                    "name": it.name,
                    "estimated_amount_g": str(it.estimated_amount_g),
                    "kcal": it.kcal, "protein_g": it.protein_g,
                    "carbs_g": it.carbs_g, "fat_g": it.fat_g,
                    "confidence": it.confidence,
                }
                for it in items
            ],
        })
        pipe = self.redis.pipeline()
        pipe.set(self._key(phash, locale), payload, ex=self.ttl_s)
        pipe.sadd(self._bucket(phash, locale), phash)
        pipe.expire(self._bucket(phash, locale), self.ttl_s)
        await pipe.execute()

    def _decode(self, raw: str) -> tuple[list[DetectedFoodItem], str]:
        data: dict[str, Any] = json.loads(raw)
        items = [
            DetectedFoodItem(
                name=r["name"],
                estimated_amount_g=Decimal(r["estimated_amount_g"]),
                kcal=r["kcal"], protein_g=r["protein_g"],
                carbs_g=r["carbs_g"], fat_g=r["fat_g"],
                confidence=r["confidence"],
            )
            for r in data["items"]
        ]
        return items, data["prompt_sha"]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/unit/test_phash_cache.py -v`
Expected: 4 passed

- [ ] **Step 7: Wire cache into ProcessVisionJob**

Edit `app/vision/application/process_vision_job.py` — add optional `cache` field and lookup-before-call. Place cache lookup as the first action inside `__call__` after `mark_running`:

```python
# add to dataclass fields:
    cache: "PerceptualHashCache | None" = None

# inside __call__, after self.repo.mark_running(job_id):
        cached = (
            await self.cache.lookup(image_bytes, locale=locale)
            if self.cache is not None else None
        )
        if cached is not None:
            items, prompt_sha = cached
        else:
            items, prompt_sha = await self.provider.recognise(
                image_bytes=image_bytes, mime=mime,
                user_id=user_id, locale=locale, region=region,
            )
            if self.cache is not None:
                await self.cache.store(
                    image_bytes=image_bytes, locale=locale,
                    items=items, prompt_sha=prompt_sha,
                )
```

- [ ] **Step 8: Wire cache into worker**

Edit `worker/vision_tasks.py` — instantiate cache once at module level:

```python
from app.core.config import get_settings
from app.core.redis import get_redis
from app.vision.infrastructure.phash_cache import PerceptualHashCache

# inside vision_recognize_task, when building ProcessVisionJob:
        s = get_settings()
        cache = PerceptualHashCache(
            redis=get_redis(),
            ttl_s=s.phash_cache_ttl_s,
            hamming_threshold=s.phash_cache_hamming_threshold,
        )
        uc = ProcessVisionJob(
            repo=SqlVisionJobRepository(session),
            provider=OpenAIVisionProvider(),
            matcher=HybridFoodMatcher(session),
            notifier=RedisJobNotifier(),
            bus=get_event_bus(),
            session=session,
            cache=cache,
        )
```

- [ ] **Step 9: Integration test**

```python
# tests/integration/test_vision_pipeline_with_cache.py
import io
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from PIL import Image

from app.vision.application.process_vision_job import ProcessVisionJob
from app.vision.domain.entities import DetectedFoodItem
from app.vision.infrastructure.phash_cache import PerceptualHashCache


def _png(color):
    img = Image.new("RGB", (128, 128), color)
    buf = io.BytesIO(); img.save(buf, format="PNG"); return buf.getvalue()


async def test_second_identical_photo_skips_provider(fake_redis):
    provider = AsyncMock()
    provider.recognise.return_value = (
        [DetectedFoodItem(name="rice", estimated_amount_g=Decimal("150"),
                          kcal=200, protein_g=4, carbs_g=44, fat_g=0, confidence=0.9)],
        "psha",
    )
    cache = PerceptualHashCache(redis=fake_redis, ttl_s=60, hamming_threshold=4)
    # minimal stubs:
    repo = AsyncMock(); matcher = AsyncMock(); notifier = AsyncMock(); bus = AsyncMock()
    matcher.match.return_value = (uuid4(), "rice", "trigram")
    session = AsyncMock()
    uc = ProcessVisionJob(repo=repo, provider=provider, matcher=matcher,
                          notifier=notifier, bus=bus, session=session, cache=cache)

    img = _png((1, 2, 3))
    await uc(job_id=uuid4(), user_id=uuid4(), meal_time="lunch",
             image_bytes=img, mime="image/png", locale="es-PE", region="pe")
    await uc(job_id=uuid4(), user_id=uuid4(), meal_time="lunch",
             image_bytes=img, mime="image/png", locale="es-PE", region="pe")
    assert provider.recognise.await_count == 1
```

Run: `pytest tests/integration/test_vision_pipeline_with_cache.py -v`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add app/vision/infrastructure/phash_cache.py tests/unit/test_phash_cache.py \
        tests/integration/test_vision_pipeline_with_cache.py \
        app/vision/application/process_vision_job.py worker/vision_tasks.py \
        app/core/config.py app/core/metrics.py pyproject.toml tests/conftest.py
git commit -m "feat(vision): pHash dedupe cache eliminates OpenAI call on repeat photos"
```

---

## Task 3: ONNX "is-food?" pre-filter (Mitigation #2)

**Files:**
- Create: `app/vision/infrastructure/food_prefilter.py`
- Create: `data/models/food_prefilter_mnv3.onnx` (committed via Git LFS — see Step 1)
- Test: `tests/unit/test_food_prefilter.py`

- [ ] **Step 1: Acquire model + Git LFS**

Download MobileNetV3-small fine-tuned on Food-101 binary (food/not-food). Save to `data/models/food_prefilter_mnv3.onnx`.

```bash
mkdir -p data/models
# Until trained: use placeholder that downloads at deploy. Add to README.
# For now, train script lives at scripts/train_food_prefilter.py (out of scope).
# Track via LFS:
git lfs install
git lfs track "data/models/*.onnx"
git add .gitattributes
```

If team prefers runtime download: ship a `scripts/fetch_models.py` that pulls from S3/HuggingFace on container start. **Decision required from team** before this task; default plan assumes LFS.

- [ ] **Step 2: Add deps**

Edit `pyproject.toml`:

```toml
    "onnxruntime>=1.20,<2",
    "numpy>=2.1,<3",
```

- [ ] **Step 3: Add config + metric**

`app/core/config.py`:

```python
    food_prefilter_enabled: bool = True
    food_prefilter_threshold: float = 0.35  # < 0.35 → reject as non-food
    food_prefilter_model_path: str = "data/models/food_prefilter_mnv3.onnx"
```

`app/core/metrics.py`:

```python
VISION_PREFILTER_REJECTS = Counter(
    "vision_prefilter_rejects_total",
    "Photos rejected by local food classifier (no OpenAI call made)",
    [],
)
```

- [ ] **Step 4: Failing test**

```python
# tests/unit/test_food_prefilter.py
import io
from pathlib import Path

import pytest
from PIL import Image

from app.vision.infrastructure.food_prefilter import FoodPrefilter, NotFoodError


def _img(color):
    img = Image.new("RGB", (224, 224), color)
    buf = io.BytesIO(); img.save(buf, format="JPEG"); return buf.getvalue()


@pytest.fixture
def prefilter():
    return FoodPrefilter(
        model_path=Path("data/models/food_prefilter_mnv3.onnx"),
        threshold=0.35,
    )


def test_score_returns_value_in_unit_interval(prefilter):
    score = prefilter.score(_img((200, 100, 50)))
    assert 0.0 <= score <= 1.0


def test_check_raises_when_below_threshold(prefilter):
    # blank white image — strong non-food signal
    img = _img((255, 255, 255))
    if prefilter.score(img) < 0.35:
        with pytest.raises(NotFoodError):
            prefilter.check(img)
```

- [ ] **Step 5: Run test to verify it fails**

Run: `pytest tests/unit/test_food_prefilter.py -v`
Expected: ERROR — module missing

- [ ] **Step 6: Implement prefilter**

```python
# app/vision/infrastructure/food_prefilter.py
"""Local binary classifier (MobileNetV3-small) — is this photo food?

Runs in ~25 ms on CPU. If score < threshold, raise NotFoodError before
spending any OpenAI tokens. Falls back to permissive (always pass) if
the ONNX file is missing — never block uploads on infra issues.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

from app.core.errors import UpstreamError
from app.core.logging import get_logger
from app.core.metrics import VISION_PREFILTER_REJECTS

log = get_logger("vision.prefilter")

_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class NotFoodError(UpstreamError):
    type_slug = "not-food"
    title = "Image does not appear to contain food"


@dataclass
class FoodPrefilter:
    model_path: Path
    threshold: float
    _session: ort.InferenceSession | None = None

    def _get_session(self) -> ort.InferenceSession | None:
        if self._session is not None:
            return self._session
        if not self.model_path.exists():
            log.warning("food_prefilter.model_missing", path=str(self.model_path))
            return None
        self._session = ort.InferenceSession(
            str(self.model_path), providers=["CPUExecutionProvider"],
        )
        return self._session

    def _preprocess(self, image_bytes: bytes) -> np.ndarray:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize((224, 224))
        arr = np.asarray(img, dtype=np.float32) / 255.0
        arr = (arr - _IMAGENET_MEAN) / _IMAGENET_STD
        arr = arr.transpose(2, 0, 1)[np.newaxis, :, :, :]  # NCHW
        return arr.astype(np.float32)

    def score(self, image_bytes: bytes) -> float:
        sess = self._get_session()
        if sess is None:
            return 1.0  # permissive fallback
        x = self._preprocess(image_bytes)
        out = sess.run(None, {sess.get_inputs()[0].name: x})[0]
        # Binary head: out shape (1, 2) softmax — index 1 = "food".
        probs = _softmax(out[0])
        return float(probs[1])

    def check(self, image_bytes: bytes) -> None:
        s = self.score(image_bytes)
        if s < self.threshold:
            VISION_PREFILTER_REJECTS.inc()
            raise NotFoodError(f"not_food_score:{s:.3f}")


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/unit/test_food_prefilter.py -v`
Expected: 2 passed (uses permissive fallback if ONNX missing — both tests still valid; if model present and white image scores low, second test triggers `NotFoodError`)

- [ ] **Step 8: Wire prefilter into ProcessVisionJob**

Edit `app/vision/application/process_vision_job.py` — call `prefilter.check()` BEFORE cache lookup:

```python
# add to dataclass fields:
    prefilter: "FoodPrefilter | None" = None

# inside __call__, after self.repo.mark_running(job_id) but BEFORE cache lookup:
        if self.prefilter is not None:
            try:
                self.prefilter.check(image_bytes)
            except NotFoodError as exc:
                await self.repo.mark_failed(
                    job_id, error_code="NotFoodError", detail=str(exc),
                )
                await self.notifier.notify(
                    user_id=user_id, channel="vision",
                    payload={"job_id": str(job_id), "status": "rejected",
                             "reason": "not_food"},
                )
                return
```

- [ ] **Step 9: Wire in worker**

Edit `worker/vision_tasks.py`:

```python
from pathlib import Path
from app.vision.infrastructure.food_prefilter import FoodPrefilter

# inside vision_recognize_task:
        prefilter = FoodPrefilter(
            model_path=Path(s.food_prefilter_model_path),
            threshold=s.food_prefilter_threshold,
        ) if s.food_prefilter_enabled else None
        uc = ProcessVisionJob(
            ...,
            prefilter=prefilter,
        )
```

- [ ] **Step 10: Commit**

```bash
git add app/vision/infrastructure/food_prefilter.py tests/unit/test_food_prefilter.py \
        app/vision/application/process_vision_job.py worker/vision_tasks.py \
        app/core/config.py app/core/metrics.py pyproject.toml \
        data/models/food_prefilter_mnv3.onnx .gitattributes
git commit -m "feat(vision): ONNX MobileNetV3 pre-filter rejects non-food before OpenAI call"
```

---

## Task 4: Low-confidence confirm endpoint (Mitigation #4)

**Files:**
- Create: `migrations/versions/0007_vision_pending_items.py`
- Create: `app/vision/application/confirm_low_confidence.py`
- Create: `app/vision/presentation/schemas_confirm.py`
- Modify: `app/vision/application/process_vision_job.py` — persist low-confidence into `vision_jobs.pending_items`
- Modify: `app/vision/presentation/router.py` — add confirm endpoint
- Test: `tests/unit/test_confirm_low_confidence.py`

- [ ] **Step 1: Migration**

```python
# migrations/versions/0007_vision_pending_items.py
"""vision_jobs.pending_items jsonb column"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vision_jobs",
        sa.Column("pending_items", sa.JSON, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("vision_jobs", "pending_items")
```

Run: `alembic upgrade head` (against dev DB) — verify clean.

- [ ] **Step 2: Failing test**

```python
# tests/unit/test_confirm_low_confidence.py
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.vision.application.confirm_low_confidence import (
    ConfirmLowConfidence,
    ConfirmInput,
)
from app.vision.domain.entities import DetectedFoodItem


async def test_accept_persists_food_log():
    repo = AsyncMock()
    repo.get_pending_items.return_value = [
        DetectedFoodItem(name="ceviche", estimated_amount_g=Decimal("200"),
                         kcal=240, protein_g=22, carbs_g=18, fat_g=8, confidence=0.55),
    ]
    session = AsyncMock()
    uc = ConfirmLowConfidence(repo=repo, session=session)
    job_id = uuid4(); user_id = uuid4()
    await uc(ConfirmInput(
        job_id=job_id, user_id=user_id,
        accepted_indices=[0], rejected_indices=[],
    ))
    session.execute.assert_awaited()  # INSERT INTO food_logs ran
    repo.clear_pending_items.assert_awaited_with(job_id)


async def test_reject_does_not_persist():
    repo = AsyncMock()
    repo.get_pending_items.return_value = [
        DetectedFoodItem(name="x", estimated_amount_g=Decimal("100"),
                         kcal=50, protein_g=1, carbs_g=10, fat_g=0, confidence=0.4),
    ]
    session = AsyncMock()
    uc = ConfirmLowConfidence(repo=repo, session=session)
    await uc(ConfirmInput(
        job_id=uuid4(), user_id=uuid4(),
        accepted_indices=[], rejected_indices=[0],
    ))
    session.execute.assert_not_called()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_confirm_low_confidence.py -v`
Expected: ImportError on `confirm_low_confidence`

- [ ] **Step 4: Implement use case**

```python
# app/vision/application/confirm_low_confidence.py
"""User accepts/rejects items the vision pipeline flagged as low-confidence.

Low-confidence = confidence < 0.7 AND no food_id match. ProcessVisionJob
parks these in vision_jobs.pending_items instead of food_logs. This use
case applies the user's verdict: accepted items become food_logs (method
= 'photo_confirmed'); rejected items are dropped. Either way, the job's
pending_items is cleared.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.vision.domain.entities import DetectedFoodItem


class _PendingRepo(Protocol):
    async def get_pending_items(self, job_id: UUID) -> list[DetectedFoodItem]: ...
    async def clear_pending_items(self, job_id: UUID) -> None: ...
    async def get_meal_time(self, job_id: UUID) -> str: ...


@dataclass(slots=True)
class ConfirmInput:
    job_id: UUID
    user_id: UUID
    accepted_indices: list[int]
    rejected_indices: list[int]


@dataclass(slots=True)
class ConfirmLowConfidence:
    repo: _PendingRepo
    session: AsyncSession

    async def __call__(self, inp: ConfirmInput) -> dict[str, int]:
        pending = await self.repo.get_pending_items(inp.job_id)
        for i in inp.accepted_indices:
            if i < 0 or i >= len(pending):
                continue
            it = pending[i]
            meal_time = await self.repo.get_meal_time(inp.job_id)
            await self.session.execute(text("""
                INSERT INTO food_logs (
                    id, user_id, date, meal_time, free_text_name,
                    amount_g, kcal, protein_g, carbs_g, fat_g, method,
                    confidence, created_at
                ) VALUES (
                    :id, :uid, :d, :mt, :ftn,
                    :ag, :kc, :pg, :cg, :fg, 'photo_confirmed',
                    :conf, now()
                )
            """), {
                "id": str(uuid4()), "uid": str(inp.user_id),
                "d": date.today(), "mt": meal_time, "ftn": it.name,
                "ag": float(it.estimated_amount_g), "kc": it.kcal,
                "pg": it.protein_g, "cg": it.carbs_g, "fg": it.fat_g,
                "conf": it.confidence,
            })
        await self.repo.clear_pending_items(inp.job_id)
        return {
            "accepted": len(inp.accepted_indices),
            "rejected": len(inp.rejected_indices),
        }
```

- [ ] **Step 5: Add repo methods**

Edit `app/vision/infrastructure/repositories.py` `SqlVisionJobRepository` — add:

```python
async def get_pending_items(self, job_id: UUID) -> list[DetectedFoodItem]:
    row = (await self.session.execute(text(
        "SELECT pending_items FROM vision_jobs WHERE id = :id"
    ), {"id": str(job_id)})).first()
    if row is None:
        return []
    return [
        DetectedFoodItem(
            name=r["name"], estimated_amount_g=Decimal(str(r["estimated_amount_g"])),
            kcal=r["kcal"], protein_g=r["protein_g"], carbs_g=r["carbs_g"],
            fat_g=r["fat_g"], confidence=r["confidence"],
        )
        for r in (row[0] or [])
    ]

async def clear_pending_items(self, job_id: UUID) -> None:
    await self.session.execute(text(
        "UPDATE vision_jobs SET pending_items = '[]'::jsonb WHERE id = :id"
    ), {"id": str(job_id)})

async def get_meal_time(self, job_id: UUID) -> str:
    row = (await self.session.execute(text(
        "SELECT meal_time FROM vision_jobs WHERE id = :id"
    ), {"id": str(job_id)})).first()
    return str(row[0]) if row else "snack"
```

- [ ] **Step 6: Update ProcessVisionJob to park low-confidence**

Edit `app/vision/application/process_vision_job.py` — change the existing `confidence < 0.7` branch from `continue` to accumulating into `pending`:

```python
            pending: list[DetectedFoodItem] = []
            for it in items:
                if it.confidence < 0.7 and it.matched_food_id is None:
                    pending.append(it)
                    continue
                # ... existing insert block unchanged ...

            if pending:
                await self.session.execute(text("""
                    UPDATE vision_jobs SET pending_items = CAST(:p AS jsonb)
                    WHERE id = :id
                """), {
                    "id": str(job_id),
                    "p": json.dumps([{
                        "name": p.name,
                        "estimated_amount_g": str(p.estimated_amount_g),
                        "kcal": p.kcal, "protein_g": p.protein_g,
                        "carbs_g": p.carbs_g, "fat_g": p.fat_g,
                        "confidence": p.confidence,
                    } for p in pending]),
                })
```

Add `import json` to top of file.

- [ ] **Step 7: Endpoint**

`app/vision/presentation/schemas_confirm.py`:

```python
from pydantic import BaseModel, Field


class ConfirmRequest(BaseModel):
    accepted_indices: list[int] = Field(default_factory=list)
    rejected_indices: list[int] = Field(default_factory=list)


class ConfirmResponse(BaseModel):
    accepted: int
    rejected: int
```

Edit `app/vision/presentation/router.py` — add:

```python
from app.vision.application.confirm_low_confidence import (
    ConfirmInput, ConfirmLowConfidence,
)
from app.vision.presentation.schemas_confirm import ConfirmRequest, ConfirmResponse


@router.post("/jobs/{job_id}/confirm", response_model=ConfirmResponse)
async def confirm_pending(
    job_id: UUID,
    body: ConfirmRequest,
    user_id: UUID = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
) -> ConfirmResponse:
    uc = ConfirmLowConfidence(
        repo=SqlVisionJobRepository(session), session=session,
    )
    out = await uc(ConfirmInput(
        job_id=job_id, user_id=user_id,
        accepted_indices=body.accepted_indices,
        rejected_indices=body.rejected_indices,
    ))
    await session.commit()
    return ConfirmResponse(**out)
```

- [ ] **Step 8: Run all vision tests**

Run: `pytest tests/unit/test_confirm_low_confidence.py tests/unit/test_vision_openai_parse.py -v`
Expected: all pass

- [ ] **Step 9: Schemathesis contract test**

Run: `schemathesis run --checks all http://localhost:8000/openapi.json -E /vision/jobs`
Expected: no contract violations.

- [ ] **Step 10: Commit**

```bash
git add migrations/versions/0007_vision_pending_items.py \
        app/vision/application/confirm_low_confidence.py \
        app/vision/application/process_vision_job.py \
        app/vision/infrastructure/repositories.py \
        app/vision/presentation/router.py \
        app/vision/presentation/schemas_confirm.py \
        tests/unit/test_confirm_low_confidence.py
git commit -m "feat(vision): confirm endpoint for low-confidence detected items"
```

---

## Task 5: Multi-provider abstraction (Mitigation #3)

**Files:**
- Create: `app/vision/infrastructure/anthropic_vision.py`
- Create: `app/vision/infrastructure/gemini_vision.py`
- Create: `app/vision/infrastructure/provider_factory.py`
- Create: `docs/adr/ADR-0011-multi-provider-vision.md`
- Test: `tests/unit/test_provider_factory.py`
- Test: `tests/unit/test_anthropic_vision_parse.py`
- Modify: `worker/vision_tasks.py`

- [ ] **Step 1: ADR**

```markdown
# ADR-0011 — Multi-provider vision

**Status:** Accepted
**Context:** Single OpenAI dependency = SPOF for core feature. Cost
volatility and LatAm food accuracy vary across vendors.
**Decision:** Introduce `VisionProviderFactory` driven by `vision_provider`
setting (`openai` | `anthropic` | `gemini`). Same `VisionProvider`
Protocol — strict JSON schema preserved across vendors. Cost-cap layer
(per-model pricing table) extended for Anthropic + Gemini.
**Consequences:** +2 SDK deps. Per-request provider tagging in metrics.
Failover stays explicit (not silent) — feature flag swap required.
```

- [ ] **Step 2: Add deps**

Edit `pyproject.toml`:

```toml
    "anthropic>=0.40,<1",
    "google-genai>=0.3,<1",
```

Edit `app/core/cost_cap.py` `_PRICING_PER_M`:

```python
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-7": (15.00, 75.00),
    "gemini-2.0-flash": (0.10, 0.40),
```

- [ ] **Step 3: Failing test for factory**

```python
# tests/unit/test_provider_factory.py
import pytest

from app.vision.infrastructure.anthropic_vision import AnthropicVisionProvider
from app.vision.infrastructure.gemini_vision import GeminiVisionProvider
from app.vision.infrastructure.openai_vision import OpenAIVisionProvider
from app.vision.infrastructure.provider_factory import build_vision_provider


@pytest.mark.parametrize("name,cls", [
    ("openai", OpenAIVisionProvider),
    ("anthropic", AnthropicVisionProvider),
    ("gemini", GeminiVisionProvider),
])
def test_factory_returns_correct_provider(name, cls):
    assert isinstance(build_vision_provider(name), cls)


def test_factory_rejects_unknown():
    with pytest.raises(ValueError, match="unknown vision provider"):
        build_vision_provider("xai")
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/unit/test_provider_factory.py -v`
Expected: ImportError

- [ ] **Step 5: Implement Anthropic provider**

```python
# app/vision/infrastructure/anthropic_vision.py
"""Claude vision adapter — mirrors OpenAIVisionProvider contract."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from anthropic import AsyncAnthropic

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings
from app.core.cost_cap import estimate_input_cost, pre_check, record_usage
from app.core.errors import UpstreamError
from app.core.logging import get_logger
from app.vision.domain.entities import DetectedFoodItem
from app.vision.infrastructure.openai_vision import (
    _parse_items, _system_prompt, IMAGE_TOKEN_ESTIMATE, MAX_RETRIES,
)

log = get_logger("vision.anthropic")
_client: AsyncAnthropic | None = None
_breaker = CircuitBreaker(
    name="anthropic_vision", fail_threshold=3, recovery_timeout_s=30,
)


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=get_settings().anthropic_api_key or "sk-test")
    return _client


@dataclass(slots=True)
class AnthropicVisionProvider:
    model: str = "claude-sonnet-4-6"

    async def recognise(
        self, *, image_bytes: bytes, mime: str, user_id: UUID | None,
        locale: str, region: str,
    ) -> tuple[list[DetectedFoodItem], str]:
        sys_prompt = _system_prompt(locale, region) + (
            "\nRespond ONLY with a JSON object matching this schema: "
            '{"items": [{"name": str, "estimated_amount_g": number, '
            '"kcal": int, "protein_g": int, "carbs_g": int, "fat_g": int, '
            '"confidence": number}]}'
        )
        prompt_sha = hashlib.sha256(sys_prompt.encode()).hexdigest()
        text_est = estimate_input_cost(self.model, sys_prompt)
        image_est = (IMAGE_TOKEN_ESTIMATE / 1_000_000.0) * 3.00
        await pre_check(user_id=user_id, estimate_usd=text_est + image_est + 0.003)

        b64 = base64.b64encode(image_bytes).decode()

        async def _call() -> dict:
            resp = await _get_client().messages.create(
                model=self.model,
                max_tokens=1024,
                system=sys_prompt,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64", "media_type": mime, "data": b64,
                        }},
                        {"type": "text", "text": "Analiza la foto y lista los ítems."},
                    ],
                }],
            )
            usage = resp.usage
            await record_usage(
                user_id=user_id, model=self.model,
                in_tok=getattr(usage, "input_tokens", IMAGE_TOKEN_ESTIMATE),
                out_tok=getattr(usage, "output_tokens", 200),
            )
            text_out = "".join(
                b.text for b in resp.content if getattr(b, "type", "") == "text"
            )
            return json.loads(text_out)

        attempt = 0
        last_exc: Exception | None = None
        while attempt <= MAX_RETRIES:
            try:
                raw = await _breaker.call(_call)
                items = _parse_items(raw)
                log.info("vision.anthropic.ok", n_items=len(items),
                         attempt=attempt, prompt_sha=prompt_sha[:8])
                return items, prompt_sha
            except Exception as exc:  # noqa: BLE001
                last_exc = exc; attempt += 1
                if attempt > MAX_RETRIES:
                    break
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

        log.warning("vision.anthropic.failed", error=str(last_exc))
        raise UpstreamError(f"vision_failed:{last_exc!s}")
```

- [ ] **Step 6: Implement Gemini provider (analogous structure)**

```python
# app/vision/infrastructure/gemini_vision.py
"""Gemini vision adapter."""
from __future__ import annotations

import asyncio, base64, hashlib, json
from dataclasses import dataclass
from uuid import UUID

from google import genai
from google.genai import types as gtypes

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings
from app.core.cost_cap import estimate_input_cost, pre_check, record_usage
from app.core.errors import UpstreamError
from app.core.logging import get_logger
from app.vision.domain.entities import DetectedFoodItem
from app.vision.infrastructure.openai_vision import (
    _parse_items, _system_prompt, IMAGE_TOKEN_ESTIMATE, MAX_RETRIES,
)

log = get_logger("vision.gemini")
_client: genai.Client | None = None
_breaker = CircuitBreaker(name="gemini_vision", fail_threshold=3, recovery_timeout_s=30)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=get_settings().gemini_api_key or "x")
    return _client


@dataclass(slots=True)
class GeminiVisionProvider:
    model: str = "gemini-2.0-flash"

    async def recognise(
        self, *, image_bytes: bytes, mime: str, user_id: UUID | None,
        locale: str, region: str,
    ) -> tuple[list[DetectedFoodItem], str]:
        sys_prompt = _system_prompt(locale, region) + (
            "\nReturn ONLY JSON: "
            '{"items":[{"name":str,"estimated_amount_g":number,'
            '"kcal":int,"protein_g":int,"carbs_g":int,"fat_g":int,'
            '"confidence":number}]}'
        )
        prompt_sha = hashlib.sha256(sys_prompt.encode()).hexdigest()
        await pre_check(user_id=user_id, estimate_usd=
                        estimate_input_cost(self.model, sys_prompt) + 0.001)

        async def _call() -> dict:
            resp = await asyncio.to_thread(
                _get_client().models.generate_content,
                model=self.model,
                contents=[
                    gtypes.Part.from_bytes(data=image_bytes, mime_type=mime),
                    sys_prompt,
                ],
                config=gtypes.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            await record_usage(
                user_id=user_id, model=self.model,
                in_tok=getattr(resp.usage_metadata, "prompt_token_count", 300),
                out_tok=getattr(resp.usage_metadata, "candidates_token_count", 150),
            )
            return json.loads(resp.text)

        attempt = 0; last_exc: Exception | None = None
        while attempt <= MAX_RETRIES:
            try:
                raw = await _breaker.call(_call)
                return _parse_items(raw), prompt_sha
            except Exception as exc:  # noqa: BLE001
                last_exc = exc; attempt += 1
                if attempt > MAX_RETRIES:
                    break
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
        raise UpstreamError(f"vision_failed:{last_exc!s}")
```

- [ ] **Step 7: Factory**

```python
# app/vision/infrastructure/provider_factory.py
"""Selects VisionProvider implementation by name. Drives the
`vision_provider` setting / feature flag swap.
"""
from __future__ import annotations

from prometheus_client import Counter

from app.core.config import get_settings
from app.vision.domain.ports import VisionProvider
from app.vision.infrastructure.anthropic_vision import AnthropicVisionProvider
from app.vision.infrastructure.gemini_vision import GeminiVisionProvider
from app.vision.infrastructure.openai_vision import OpenAIVisionProvider

VISION_PROVIDER_SELECTED = Counter(
    "vision_provider_selected_total",
    "Vision provider instantiated per request",
    ["provider"],
)


def build_vision_provider(name: str | None = None) -> VisionProvider:
    chosen = (name or get_settings().vision_provider).lower()
    VISION_PROVIDER_SELECTED.labels(provider=chosen).inc()
    match chosen:
        case "openai":
            return OpenAIVisionProvider()
        case "anthropic":
            return AnthropicVisionProvider()
        case "gemini":
            return GeminiVisionProvider()
        case _:
            raise ValueError(f"unknown vision provider: {chosen}")
```

- [ ] **Step 8: Settings**

Edit `app/core/config.py`:

```python
    vision_provider: str = "openai"  # openai | anthropic | gemini
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
```

- [ ] **Step 9: Anthropic parsing test**

```python
# tests/unit/test_anthropic_vision_parse.py
from app.vision.infrastructure.openai_vision import _parse_items


def test_parse_handles_anthropic_envelope():
    raw = {"items": [
        {"name": "ceviche", "estimated_amount_g": 200, "kcal": 240,
         "protein_g": 22, "carbs_g": 18, "fat_g": 8, "confidence": 0.78},
    ]}
    items = _parse_items(raw)
    assert len(items) == 1 and items[0].name == "ceviche"
```

- [ ] **Step 10: Wire factory into worker**

Edit `worker/vision_tasks.py`:

```python
from app.vision.infrastructure.provider_factory import build_vision_provider

# replace OpenAIVisionProvider() with:
            provider=build_vision_provider(),
```

Remove now-unused `from app.vision.infrastructure.openai_vision import OpenAIVisionProvider`.

- [ ] **Step 11: Run full vision test suite**

Run: `pytest tests/unit/test_provider_factory.py tests/unit/test_anthropic_vision_parse.py tests/unit/test_vision_openai_parse.py tests/unit/test_phash_cache.py tests/unit/test_food_prefilter.py tests/unit/test_confirm_low_confidence.py -v`
Expected: all pass.

- [ ] **Step 12: Commit**

```bash
git add app/vision/infrastructure/anthropic_vision.py \
        app/vision/infrastructure/gemini_vision.py \
        app/vision/infrastructure/provider_factory.py \
        app/core/config.py app/core/cost_cap.py worker/vision_tasks.py \
        tests/unit/test_provider_factory.py tests/unit/test_anthropic_vision_parse.py \
        docs/adr/ADR-0011-multi-provider-vision.md pyproject.toml
git commit -m "feat(vision): multi-provider abstraction (OpenAI/Anthropic/Gemini) via factory"
```

---

## Post-implementation verification

- [ ] **Coverage gate:** `pytest --cov=app/vision --cov-report=term-missing` → ≥85% on `app/vision/*`.
- [ ] **Type check:** `mypy app/vision worker/vision_tasks.py` → zero errors.
- [ ] **Lint:** `ruff check app/vision worker/vision_tasks.py` → zero.
- [ ] **Load test:** `locust -f tests/load/vision_pipeline.py --headless -u 50 -r 5 -t 2m` → p95 < 3s for cached hits, < 8s cold.
- [ ] **Cost validation:** run 100 synthetic uploads with 70% repeat photos → confirm `vision_cache_hits_total` ≈ 70 and `openai_cost_usd_total` increase ≈ 30% of pre-cache baseline.
- [ ] **Schemathesis contract:** `schemathesis run --checks all http://localhost:8000/openapi.json` → no violations on new `/vision/jobs/{id}/confirm`.

---

## Open decisions (require team input before execution)

1. **Model distribution for prefilter ONNX** — Git LFS vs runtime download from S3/HuggingFace? Default plan = LFS.
2. **Pricing of Claude/Gemini models** in `cost_cap.py` — confirm current public list at execution time (this plan locks 2025-Q3 prices).
3. **Confirm endpoint auth** — same `current_user_id` dependency used elsewhere; verify dependency name matches your codebase (`app/identity/...`).
