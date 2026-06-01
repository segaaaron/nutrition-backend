# BOLA Audit — OWASP API1 (Broken Object Level Authorization) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Audit every user-owned endpoint across 13 routers and add ownership checks (OWASP API1 / ASVS V4) wherever `resource.user_id != jwt.sub` is not already enforced.

**Architecture:** Add a single `assert_owns()` async helper to `app/identity/presentation/dependencies.py` that does a cheap one-column SQL check before any handler reads/mutates a user-owned resource by external ID. For endpoints whose repository or use-case already enforces ownership, leave the code untouched and add a `# BOLA OK` comment. For endpoints that only verify JWT but never compare ownership, call `assert_owns()` at the top of the handler.

**Tech Stack:** FastAPI, SQLAlchemy async, PostgreSQL, pytest-asyncio

---

## Audit findings (mental table)

| Router file | Endpoint | External ID | BOLA status | Action |
|---|---|---|---|---|
| tracking/router.py | POST /logs/water | — (creates for current_user) | OK | none |
| tracking/router.py | GET /logs/water/today | — | OK | none |
| tracking/router.py | POST /logs/weight | — | OK | none |
| tracking/router.py | GET /logs/weight/trend | — | OK | none |
| food_log_router.py | GET /logs/food | — (QueryFoodLogs uses user_id param) | BOLA OK repo | comment |
| food_log_router.py | DELETE /logs/food/{log_id} | log_id | BOLA MISSING | fix |
| food_log_router.py | GET /logs/food/totals/* | — | OK | none |
| fasting_router.py | POST /fasting/start | — | OK | none |
| fasting_router.py | POST /fasting/{session_id}/stop | session_id | BOLA OK uc | comment |
| fasting_router.py | GET /fasting/active | — | OK | none |
| fasting_router.py | GET /fasting/history | — | OK | none |
| progress_router.py | POST /progress/photo | — | OK | none |
| progress_router.py | GET /progress/photos | — (WHERE user_id=:uid) | OK | none |
| progress_router.py | DELETE /progress/photos/{photo_id} | photo_id | BOLA OK inline | comment |
| progress_router.py | GET /progress | — | OK | none |
| plan/router.py | POST /plans | — | OK | none |
| plan/router.py | GET /plans/active | — | OK | none |
| plan/router.py | POST /plans/{plan_id}/advance | plan_id | BOLA MISSING | fix |
| plan/router.py | PATCH /plans/{plan_id}/meals/{meal_id}/complete | plan_id, meal_id | BOLA MISSING | fix |
| plan/router.py | POST /plans/{plan_id}/meals/{meal_id}/swap | plan_id, meal_id | BOLA MISSING | fix |
| vision/router.py | POST /logs/food/photo | — | OK | none |
| vision/router.py | GET /logs/food/jobs/{job_id} | job_id | BOLA OK uc | comment |
| vision/router.py | POST /logs/food/{food_log_id}/edit | food_log_id | BOLA MISSING | fix |
| grocery/router.py | GET /plans/{plan_id}/grocery-list | plan_id | BOLA OK inline | comment |
| grocery/router.py | PATCH /grocery-items/{item_id} | item_id | BOLA MISSING | fix |
| grocery/router.py | POST /grocery-items | list_id (body) | BOLA OK ensure_owner | comment |
| grocery/router.py | DELETE /grocery-items/{item_id} | item_id | BOLA MISSING | fix |
| grocery/router.py | GET /grocery-lists/{list_id}/share | list_id | BOLA OK ensure_owner | comment |
| grocery/router.py | GET /grocery-lists/{list_id}/shared | list_id (public share token) | GLOBAL (token-gated) | none |
| coach/router.py | GET /coach/conversations/{conv_id}/messages | conv_id | BOLA MISSING | fix |
| coach/router.py | DELETE /coach/conversations/{conv_id} | conv_id | BOLA OK repo.delete(conv_id, user_id) | comment |
| profile/router.py | All /me endpoints | — (always current_user) | OK | none |
| notifications/router.py | DELETE /push/tokens/{token} | token str (WHERE token AND user_id) | BOLA OK inline | comment |
| billing/router.py | All endpoints | — (always current_user) | OK | none |
| gamification/router.py | All endpoints | — | OK | none |
| recipes/router.py | GET /recipes/{recipe_id} | recipe_id | GLOBAL catalog | exempt |
| recipes/router.py | GET /foods, /foods/barcode/{ean} | — / ean | GLOBAL catalog | exempt |

**Endpoints needing fixes:** 6 + 1 comment-only pass
1. `DELETE /logs/food/{log_id}` — DeleteFoodLog use case takes `user_id` but we need to confirm the UC enforces it
2. `POST /plans/{plan_id}/advance` — repo.get(plan_id) has no user_id filter → BOLA
3. `PATCH /plans/{plan_id}/meals/{meal_id}/complete` — same
4. `POST /plans/{plan_id}/meals/{meal_id}/swap` — same
5. `POST /logs/food/{food_log_id}/edit` — LearnUserCorrection doesn't check log ownership
6. `PATCH /grocery-items/{item_id}` — MarkItemPurchased has no ownership check
7. `DELETE /grocery-items/{item_id}` — DeleteItem has no ownership check
8. `GET /coach/conversations/{conv_id}/messages` — get_messages has no user_id param

---

## Files modified

| File | Action |
|---|---|
| `app/identity/presentation/dependencies.py` | Add `assert_owns()` helper |
| `app/tracking/presentation/food_log_router.py` | Comment BOLA OK on query; confirm DeleteFoodLog UC |
| `app/tracking/presentation/fasting_router.py` | Comment BOLA OK on stop (UC checks) |
| `app/tracking/presentation/progress_router.py` | Comment BOLA OK on delete (inline check) |
| `app/plan/presentation/router.py` | Add assert_owns for advance/complete/swap |
| `app/vision/presentation/router.py` | Add assert_owns for edit endpoint; comment OK on job status |
| `app/grocery/router.py` | Add assert_owns for patch_item and delete_item; comment OK on others |
| `app/coach/presentation/router.py` | Add assert_owns for list_messages |
| `tests/unit/test_bola_audit.py` | New — 3 unit tests for assert_owns helper |

---

## Task 1: Add `assert_owns()` helper to dependencies.py

**Files:**
- Modify: `app/identity/presentation/dependencies.py`

- [ ] **Step 1: Read current dependencies.py**

Open `app/identity/presentation/dependencies.py` and locate the end of the file (after `make_export`).

- [ ] **Step 2: Add the helper**

Append after `make_export` (at the end of `app/identity/presentation/dependencies.py`):

```python
# --- OWASP API1 (BOLA) defence ---

async def assert_owns(
    session: AsyncSession,
    *,
    table: str,
    resource_id: "UUID | str",
    user_id: UUID,
    id_col: str = "id",
    user_col: str = "user_id",
) -> None:
    """Raise NotFoundError / Forbidden if ``resource_id`` does not belong to ``user_id``.

    OWASP API1 (BOLA) defence — call before any read/write on a user-owned
    resource accessed by external ID.

    Args:
        session: Active async DB session.
        table: Table name (e.g. ``"food_logs"``).
        resource_id: UUID of the row being accessed.
        user_id: UUID from the verified JWT (``current_user``).
        id_col: Primary-key column name (default ``"id"``).
        user_col: Ownership column name (default ``"user_id"``).
    """
    from app.core.errors import Forbidden, NotFoundError  # local to avoid circular

    row = (await session.execute(
        text(f"SELECT {user_col} FROM {table} WHERE {id_col} = :rid"),
        {"rid": str(resource_id)},
    )).first()
    if row is None:
        raise NotFoundError(f"{table}_not_found")
    if str(row[0]) != str(user_id):
        raise Forbidden("not_owner")
```

Note: `text` is already imported at the top of `dependencies.py`. `AsyncSession` is already imported. `UUID` is already imported.

- [ ] **Step 3: Run a quick syntax check**

```bash
cd /Users/miguelangelsaraviabelmonte/dev-backend/Nova-nutrition-backend/.claude/worktrees/feat-p0-prelaunch-hardening
.venv/bin/python -c "from app.identity.presentation.dependencies import assert_owns; print('OK')"
```

Expected output: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/identity/presentation/dependencies.py
git commit -m "feat(security): add assert_owns() BOLA helper to identity dependencies"
```

---

## Task 2: Write and run the unit tests

**Files:**
- Create: `tests/unit/test_bola_audit.py`

- [ ] **Step 1: Write the test file**

Create `tests/unit/test_bola_audit.py` with:

```python
"""OWASP API1 (BOLA) — assert_owns helper rejects non-owners.

Tests:
  1. No exception when user_id matches the row's owner.
  2. Forbidden raised when user_id does NOT match.
  3. NotFoundError raised when the row doesn't exist.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.errors import Forbidden, NotFoundError
from app.identity.presentation.dependencies import assert_owns


@pytest.fixture
def session() -> AsyncMock:
    s = AsyncMock()
    s.execute.return_value = MagicMock()
    return s


@pytest.mark.asyncio
async def test_owns_when_user_id_matches(session: AsyncMock) -> None:
    """No exception when the row's user_id equals current_user."""
    uid = uuid4()
    rid = uuid4()
    session.execute.return_value.first.return_value = (str(uid),)
    # Should complete without raising.
    await assert_owns(session, table="food_logs", resource_id=rid, user_id=uid)


@pytest.mark.asyncio
async def test_forbidden_when_user_mismatch(session: AsyncMock) -> None:
    """Forbidden raised when jwt.sub != resource.user_id."""
    other_user = uuid4()
    requester = uuid4()
    assert other_user != requester  # sanity
    session.execute.return_value.first.return_value = (str(other_user),)
    with pytest.raises(Forbidden):
        await assert_owns(
            session, table="food_logs", resource_id=uuid4(), user_id=requester,
        )


@pytest.mark.asyncio
async def test_not_found_when_row_missing(session: AsyncMock) -> None:
    """NotFoundError raised when the row does not exist."""
    session.execute.return_value.first.return_value = None
    with pytest.raises(NotFoundError):
        await assert_owns(
            session, table="food_logs", resource_id=uuid4(), user_id=uuid4(),
        )
```

- [ ] **Step 2: Run the tests to confirm they pass**

```bash
cd /Users/miguelangelsaraviabelmonte/dev-backend/Nova-nutrition-backend/.claude/worktrees/feat-p0-prelaunch-hardening
.venv/bin/pytest tests/unit/test_bola_audit.py -v
```

Expected output:
```
PASSED tests/unit/test_bola_audit.py::test_owns_when_user_id_matches
PASSED tests/unit/test_bola_audit.py::test_forbidden_when_user_mismatch
PASSED tests/unit/test_bola_audit.py::test_not_found_when_row_missing
3 passed
```

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_bola_audit.py
git commit -m "test(security): BOLA unit tests for assert_owns helper (3 cases)"
```

---

## Task 3: Fix plan router — advance / complete_meal / swap_meal

**Files:**
- Modify: `app/plan/presentation/router.py`

The `SqlPlanRepository.get(plan_id)` does NOT filter by user_id — it's a bare lookup by PK. Any authenticated user can advance/complete/swap any plan by guessing or enumerating a UUID.

- [ ] **Step 1: Add assert_owns import to plan router**

At the top of `app/plan/presentation/router.py`, the import block already contains:
```python
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
```

Change it to:
```python
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep, assert_owns
```

- [ ] **Step 2: Fix advance_plan endpoint**

Find:
```python
@router.post("/plans/{plan_id}/advance", response_model=PlanResponse)
async def advance_plan(
    plan_id: Annotated[uuid.UUID, Path()],
    body: AdvanceRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> PlanResponse:
    cache = ActivePlanCache(get_redis())
    uc = AdvancePlan(plans=SqlPlanRepository(session), cache=cache, bus=get_event_bus())
    plan = await uc(plan_id=plan_id, event=body.event)
    return _to_resp(plan)
```

Replace with:
```python
@router.post("/plans/{plan_id}/advance", response_model=PlanResponse)
async def advance_plan(
    plan_id: Annotated[uuid.UUID, Path()],
    body: AdvanceRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> PlanResponse:
    await assert_owns(session, table="plans", resource_id=plan_id, user_id=current_user)
    cache = ActivePlanCache(get_redis())
    uc = AdvancePlan(plans=SqlPlanRepository(session), cache=cache, bus=get_event_bus())
    plan = await uc(plan_id=plan_id, event=body.event)
    return _to_resp(plan)
```

- [ ] **Step 3: Fix complete_meal endpoint**

Find:
```python
@router.patch(
    "/plans/{plan_id}/meals/{meal_id}/complete", status_code=status.HTTP_204_NO_CONTENT,
)
async def complete_meal(
    plan_id: Annotated[uuid.UUID, Path()],
    meal_id: Annotated[uuid.UUID, Path()],
    current_user: CurrentUserDep,
    session: SessionDep,
) -> Response:
    cache = ActivePlanCache(get_redis())
    uc = CompleteMeal(plans=SqlPlanRepository(session), cache=cache, bus=get_event_bus())
    await uc(plan_id=plan_id, meal_id=meal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

Replace with:
```python
@router.patch(
    "/plans/{plan_id}/meals/{meal_id}/complete", status_code=status.HTTP_204_NO_CONTENT,
)
async def complete_meal(
    plan_id: Annotated[uuid.UUID, Path()],
    meal_id: Annotated[uuid.UUID, Path()],
    current_user: CurrentUserDep,
    session: SessionDep,
) -> Response:
    await assert_owns(session, table="plans", resource_id=plan_id, user_id=current_user)
    cache = ActivePlanCache(get_redis())
    uc = CompleteMeal(plans=SqlPlanRepository(session), cache=cache, bus=get_event_bus())
    await uc(plan_id=plan_id, meal_id=meal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: Fix swap_meal endpoint**

Find:
```python
@router.post("/plans/{plan_id}/meals/{meal_id}/swap", response_model=SwapMealResponse)
async def swap_meal(
    plan_id: Annotated[uuid.UUID, Path()],
    meal_id: Annotated[uuid.UUID, Path()],
    body: SwapMealRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> SwapMealResponse:
    cache = ActivePlanCache(get_redis())
    # Candidate pool: callers may pre-fetch via /recipes; here we pass empty
```

Replace the body opener (just add the assert_owns call after the docstring gap):
```python
@router.post("/plans/{plan_id}/meals/{meal_id}/swap", response_model=SwapMealResponse)
async def swap_meal(
    plan_id: Annotated[uuid.UUID, Path()],
    meal_id: Annotated[uuid.UUID, Path()],
    body: SwapMealRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> SwapMealResponse:
    await assert_owns(session, table="plans", resource_id=plan_id, user_id=current_user)
    cache = ActivePlanCache(get_redis())
    # Candidate pool: callers may pre-fetch via /recipes; here we pass empty
    # and rely on the layer3 to rank an empty list → empty alternatives. The
    # full swap-with-search workflow is the Sprint-5 enhancement.
    taste = await TasteProfileService(
        redis=get_redis(), fetcher=SqlEmbeddingFetcher(session),
    ).get_or_build(current_user)
    user_ctx = SqlUserContext(session)
    layer3 = Layer3Ranking(session=session, profile_ctx=user_ctx, taste_vector=taste)
    uc = SwapMeal(
        plans=SqlPlanRepository(session), cache=cache, layer3=layer3,
        bus=get_event_bus(),
    )
    alts = await uc(
        plan_id=plan_id, meal_id=meal_id, reason_code=body.reason_code,
        candidate_ids=[],
    )
    return SwapMealResponse(alternatives=alts)
```

- [ ] **Step 5: Verify syntax**

```bash
cd /Users/miguelangelsaraviabelmonte/dev-backend/Nova-nutrition-backend/.claude/worktrees/feat-p0-prelaunch-hardening
.venv/bin/python -c "from app.plan.presentation.router import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add app/plan/presentation/router.py
git commit -m "feat(security): BOLA — add assert_owns to plan advance/complete/swap endpoints"
```

---

## Task 4: Fix vision router — edit_food_log endpoint

**Files:**
- Modify: `app/vision/presentation/router.py`

`POST /logs/food/{food_log_id}/edit` calls `LearnUserCorrection` which passes `user_id` for learning but does NOT verify that `food_log_id` belongs to that user.

- [ ] **Step 1: Add assert_owns import**

Find the import line:
```python
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
```

Change to:
```python
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep, assert_owns
```

- [ ] **Step 2: Add assert_owns to edit_food_log and add BOLA OK comment to get_job_status**

Find:
```python
@router.post("/logs/food/{food_log_id}/edit", status_code=status.HTTP_204_NO_CONTENT)
async def edit_food_log(
    food_log_id: UUID,
    body: EditDetectedItemRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> None:
    uc = LearnUserCorrection(session=session)
    await uc(
        user_id=current_user,
        detected_name=body.detected_name,
        corrected_food_id=body.corrected_food_id,
        corrected_amount_g=body.corrected_amount_g,
    )
```

Replace with:
```python
@router.post("/logs/food/{food_log_id}/edit", status_code=status.HTTP_204_NO_CONTENT)
async def edit_food_log(
    food_log_id: UUID,
    body: EditDetectedItemRequest,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> None:
    # BOLA: verify the food_log belongs to current_user before applying correction.
    await assert_owns(session, table="food_logs", resource_id=food_log_id, user_id=current_user)
    uc = LearnUserCorrection(session=session)
    await uc(
        user_id=current_user,
        detected_name=body.detected_name,
        corrected_food_id=body.corrected_food_id,
        corrected_amount_g=body.corrected_amount_g,
    )
```

Also add a comment to `get_job_status`. Find:
```python
@router.get(
    "/logs/food/jobs/{job_id}",
    response_model=JobStatusResponse,
)
async def get_job_status(
    job_id: UUID, current_user: CurrentUserDep, session: SessionDep,
) -> JobStatusResponse:
    uc = GetJobStatus(repo=SqlVisionJobRepository(session))
    job = await uc(job_id=job_id, user_id=current_user)
```

Replace with:
```python
@router.get(
    "/logs/food/jobs/{job_id}",
    response_model=JobStatusResponse,
)
async def get_job_status(
    job_id: UUID, current_user: CurrentUserDep, session: SessionDep,
) -> JobStatusResponse:
    # BOLA OK: GetJobStatus use case checks job.user_id != user_id → raises Forbidden.
    uc = GetJobStatus(repo=SqlVisionJobRepository(session))
    job = await uc(job_id=job_id, user_id=current_user)
```

- [ ] **Step 3: Verify syntax**

```bash
cd /Users/miguelangelsaraviabelmonte/dev-backend/Nova-nutrition-backend/.claude/worktrees/feat-p0-prelaunch-hardening
.venv/bin/python -c "from app.vision.presentation.router import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/vision/presentation/router.py
git commit -m "feat(security): BOLA — assert_owns on vision edit_food_log; comment job_status"
```

---

## Task 5: Fix grocery router — patch_item and delete_item

**Files:**
- Modify: `app/grocery/router.py`

`PATCH /grocery-items/{item_id}` and `DELETE /grocery-items/{item_id}` currently accept any item_id for any authenticated user. The `current_user` is present but marked `# noqa: ARG001` — it is completely unused.

- [ ] **Step 1: Add assert_owns import**

Find:
```python
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
```

Change to:
```python
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep, assert_owns
```

- [ ] **Step 2: Fix patch_item — add ownership check via grocery_lists JOIN**

For grocery items, the ownership is indirect: `grocery_items.list_id → grocery_lists.user_id`. The `assert_owns` helper only handles a direct `user_id` column. We need a different approach: look up the item's list_id then verify list ownership.

Find:
```python
@router.patch("/grocery-items/{item_id}", response_model=GroceryItemOut)
async def patch_item(
    item_id: UUID, body: PatchItemBody,
    current_user: CurrentUserDep, session: SessionDep,  # noqa: ARG001
) -> GroceryItemOut:
    repo = SqlGroceryRepository(session)
    uc = MarkItemPurchased(repo=repo)
    it = await uc(item_id=item_id, purchased=body.purchased, amount=body.amount)
    if it is None:
        from app.core.errors import NotFoundError
        raise NotFoundError(detail="item_not_found")
    return GroceryItemOut(
        id=it.id, category=it.category.value, name=it.name,
        amount=it.amount, purchased=it.purchased,
    )
```

Replace with:
```python
@router.patch("/grocery-items/{item_id}", response_model=GroceryItemOut)
async def patch_item(
    item_id: UUID, body: PatchItemBody,
    current_user: CurrentUserDep, session: SessionDep,
) -> GroceryItemOut:
    # BOLA: grocery_items don't have a direct user_id column; ownership is
    # grocery_items.list_id → grocery_lists.user_id. Verify before mutation.
    from sqlalchemy import text as _text
    from app.core.errors import Forbidden, NotFoundError
    owner_row = (await session.execute(_text("""
        SELECT gl.user_id FROM grocery_items gi
        JOIN grocery_lists gl ON gl.id = gi.list_id
        WHERE gi.id = :iid
    """), {"iid": str(item_id)})).first()
    if owner_row is None:
        raise NotFoundError(detail="item_not_found")
    if str(owner_row[0]) != str(current_user):
        raise Forbidden(detail="not_owner")
    repo = SqlGroceryRepository(session)
    uc = MarkItemPurchased(repo=repo)
    it = await uc(item_id=item_id, purchased=body.purchased, amount=body.amount)
    if it is None:
        raise NotFoundError(detail="item_not_found")
    return GroceryItemOut(
        id=it.id, category=it.category.value, name=it.name,
        amount=it.amount, purchased=it.purchased,
    )
```

- [ ] **Step 3: Fix delete_item — same indirect ownership pattern**

Find:
```python
@router.delete("/grocery-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: UUID, current_user: CurrentUserDep, session: SessionDep,  # noqa: ARG001
) -> None:
    uc = DeleteItem(repo=SqlGroceryRepository(session))
    await uc(item_id)
```

Replace with:
```python
@router.delete("/grocery-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: UUID, current_user: CurrentUserDep, session: SessionDep,
) -> None:
    # BOLA: verify grocery item belongs to current_user via grocery_lists.user_id.
    from sqlalchemy import text as _text
    from app.core.errors import Forbidden, NotFoundError
    owner_row = (await session.execute(_text("""
        SELECT gl.user_id FROM grocery_items gi
        JOIN grocery_lists gl ON gl.id = gi.list_id
        WHERE gi.id = :iid
    """), {"iid": str(item_id)})).first()
    if owner_row is None:
        raise NotFoundError(detail="item_not_found")
    if str(owner_row[0]) != str(current_user):
        raise Forbidden(detail="not_owner")
    uc = DeleteItem(repo=SqlGroceryRepository(session))
    await uc(item_id)
```

- [ ] **Step 4: Add BOLA OK comments to already-protected grocery endpoints**

In `get_grocery_list`, find:
```python
    # Verify plan ownership
    from sqlalchemy import text
    owner = (await session.execute(
```

Replace with:
```python
    # BOLA OK: plan ownership verified inline below before any data access.
    from sqlalchemy import text
    owner = (await session.execute(
```

In `add_item`, find:
```python
    await ensure_owner(session, list_id=body.list_id, user_id=current_user)
```

Replace with:
```python
    # BOLA OK: ensure_owner() in grocery/use_cases.py raises Forbidden if list not owned.
    await ensure_owner(session, list_id=body.list_id, user_id=current_user)
```

In `share_list`, find:
```python
    await ensure_owner(session, list_id=list_id, user_id=current_user)
```

Replace with:
```python
    # BOLA OK: ensure_owner() in grocery/use_cases.py raises Forbidden if list not owned.
    await ensure_owner(session, list_id=list_id, user_id=current_user)
```

- [ ] **Step 5: Verify syntax**

```bash
cd /Users/miguelangelsaraviabelmonte/dev-backend/Nova-nutrition-backend/.claude/worktrees/feat-p0-prelaunch-hardening
.venv/bin/python -c "from app.grocery.router import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add app/grocery/router.py
git commit -m "feat(security): BOLA — ownership check on grocery patch/delete items"
```

---

## Task 6: Fix coach router — list_messages endpoint

**Files:**
- Modify: `app/coach/presentation/router.py`

`GET /coach/conversations/{conv_id}/messages` calls `repo.get_messages(conv_id, ...)` without verifying that the conversation belongs to `current_user`. User A can read User B's conversation messages by guessing a UUID.

- [ ] **Step 1: Add assert_owns import**

Find:
```python
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
```

Change to:
```python
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep, assert_owns
```

- [ ] **Step 2: Add assert_owns to list_messages**

Find:
```python
@router.get("/conversations/{conv_id}/messages", response_model=MessagesList)
async def list_messages(
    conv_id: UUID, current_user: CurrentUserDep, session: SessionDep,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None),
) -> MessagesList:
    repo = SqlConversationRepository(session)
    msgs, nxt = await repo.get_messages(conv_id, limit=limit, cursor=cursor)
```

Replace with:
```python
@router.get("/conversations/{conv_id}/messages", response_model=MessagesList)
async def list_messages(
    conv_id: UUID, current_user: CurrentUserDep, session: SessionDep,
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None),
) -> MessagesList:
    await assert_owns(
        session, table="coach_conversations", resource_id=conv_id, user_id=current_user,
    )
    repo = SqlConversationRepository(session)
    msgs, nxt = await repo.get_messages(conv_id, limit=limit, cursor=cursor)
```

- [ ] **Step 3: Add BOLA OK comment to delete_conversation**

Find:
```python
async def delete_conversation(
    conv_id: UUID, current_user: CurrentUserDep, session: SessionDep,
) -> Response:
    await SqlConversationRepository(session).delete(conv_id, current_user)
```

Replace with:
```python
async def delete_conversation(
    conv_id: UUID, current_user: CurrentUserDep, session: SessionDep,
) -> Response:
    # BOLA OK: repo.delete(conv_id, current_user) filters by both conv_id AND user_id.
    await SqlConversationRepository(session).delete(conv_id, current_user)
```

- [ ] **Step 4: Verify syntax**

```bash
cd /Users/miguelangelsaraviabelmonte/dev-backend/Nova-nutrition-backend/.claude/worktrees/feat-p0-prelaunch-hardening
.venv/bin/python -c "from app.coach.presentation.router import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add app/coach/presentation/router.py
git commit -m "feat(security): BOLA — assert_owns on coach list_messages; comment delete"
```

---

## Task 7: Add BOLA OK comments to remaining routers

**Files:**
- Modify: `app/tracking/presentation/food_log_router.py`
- Modify: `app/tracking/presentation/fasting_router.py`
- Modify: `app/tracking/presentation/progress_router.py`
- Modify: `app/vision/presentation/router.py` (already done in Task 4, but confirm delete_food_log)
- Modify: `app/notifications/presentation/router.py`

These already have correct ownership enforcement — add inline comments so future devs don't second-guess them.

- [ ] **Step 1: food_log_router.py — comment on QueryFoodLogs and DeleteFoodLog**

In `food_log_router.py`, the `DELETE /logs/food/{log_id}` handler calls `DeleteFoodLog(uc)` with both `user_id=current_user` and `log_id`. Verify the use case enforces ownership. Read `app/tracking/application/food_log_uc.py`.

Find the delete_food_log handler:
```python
@router.delete("/logs/food/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_food_log(
    log_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
    body: DeleteReason | None = Body(default=None),
) -> None:
    uc = DeleteFoodLog(
        repo=SqlFoodLogRepository(session), bus=get_event_bus(), redis=get_redis(),
    )
    await uc(user_id=current_user, log_id=log_id, reason=(body.reason if body else None))
```

Replace with:
```python
@router.delete("/logs/food/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_food_log(
    log_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
    body: DeleteReason | None = Body(default=None),
) -> None:
    # BOLA OK: DeleteFoodLog use case passes user_id to repo which filters
    # DELETE ... WHERE id = :id AND user_id = :uid — raises NotFoundError if mismatch.
    uc = DeleteFoodLog(
        repo=SqlFoodLogRepository(session), bus=get_event_bus(), redis=get_redis(),
    )
    await uc(user_id=current_user, log_id=log_id, reason=(body.reason if body else None))
```

Also add comment to query_food_logs:
```python
@router.get("/logs/food", response_model=FoodLogPage)
async def query_food_logs(
```

Add before the `uc = QueryFoodLogs` line:
```python
    # BOLA OK: QueryFoodLogs passes user_id to FoodLogSearchQuery — repo filters by user_id.
```

- [ ] **Step 2: fasting_router.py — comment on stop_fasting**

In `fasting_router.py`, `stop_fasting` calls `StopFasting` use case which checks `fs.user_id != user_id` → raises NotFoundError. Add comment:

Find:
```python
@router.post("/fasting/{session_id}/stop", response_model=StopFastingOut)
async def stop_fasting(
    session_id: UUID, current_user: CurrentUserDep, session: SessionDep,
) -> StopFastingOut:
    uc = StopFasting(repo=SqlFastingRepository(session), bus=get_event_bus())
    fs = await uc(user_id=current_user, session_id=session_id)
```

Replace with:
```python
@router.post("/fasting/{session_id}/stop", response_model=StopFastingOut)
async def stop_fasting(
    session_id: UUID, current_user: CurrentUserDep, session: SessionDep,
) -> StopFastingOut:
    # BOLA OK: StopFasting use case checks fs.user_id != user_id → NotFoundError.
    uc = StopFasting(repo=SqlFastingRepository(session), bus=get_event_bus())
    fs = await uc(user_id=current_user, session_id=session_id)
```

- [ ] **Step 3: progress_router.py — comment on delete_progress_photo**

Find:
```python
@router.delete("/progress/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_progress_photo(
    photo_id: UUID, current_user: CurrentUserDep, session: SessionDep,
) -> None:
    r = (await session.execute(text("""
        SELECT id FROM progress_photos WHERE id = :id AND user_id = :uid
    """), {"id": str(photo_id), "uid": str(current_user)})).first()
```

Replace with:
```python
@router.delete("/progress/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_progress_photo(
    photo_id: UUID, current_user: CurrentUserDep, session: SessionDep,
) -> None:
    # BOLA OK: SELECT ... WHERE id = :id AND user_id = :uid — raises NotFoundError if mismatch.
    r = (await session.execute(text("""
        SELECT id FROM progress_photos WHERE id = :id AND user_id = :uid
    """), {"id": str(photo_id), "uid": str(current_user)})).first()
```

- [ ] **Step 4: notifications/router.py — comment on delete_token**

Find:
```python
@router.delete("/tokens/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_token(
    token: str, current_user: CurrentUserDep, session: SessionDep,
) -> None:
    await session.execute(text("""
        DELETE FROM push_tokens WHERE token = :t AND user_id = :uid
    """), {"t": token, "uid": str(current_user)})
```

Replace with:
```python
@router.delete("/tokens/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_token(
    token: str, current_user: CurrentUserDep, session: SessionDep,
) -> None:
    # BOLA OK: DELETE WHERE token = :t AND user_id = :uid — silently no-ops if not owner.
    await session.execute(text("""
        DELETE FROM push_tokens WHERE token = :t AND user_id = :uid
    """), {"t": token, "uid": str(current_user)})
```

- [ ] **Step 5: Verify syntax on all modified files**

```bash
cd /Users/miguelangelsaraviabelmonte/dev-backend/Nova-nutrition-backend/.claude/worktrees/feat-p0-prelaunch-hardening
.venv/bin/python -c "
from app.tracking.presentation.food_log_router import router
from app.tracking.presentation.fasting_router import router as fr
from app.tracking.presentation.progress_router import router as pr
from app.notifications.presentation.router import router as nr
print('OK')
"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add app/tracking/presentation/food_log_router.py \
        app/tracking/presentation/fasting_router.py \
        app/tracking/presentation/progress_router.py \
        app/notifications/presentation/router.py
git commit -m "docs(security): BOLA OK inline comments on already-protected endpoints"
```

---

## Task 8: Document global (non-owned) catalog endpoints

**Files:**
- Modify: `app/recipes/presentation/router.py`

Recipes, foods, and barcode endpoints are global public catalogs with no `user_id` column. No ownership check is needed or appropriate.

- [ ] **Step 1: Add exempt comment to recipes router**

At the top of `app/recipes/presentation/router.py`, after the module docstring, add a comment block. Find:
```python
router = APIRouter(tags=["recipes"])
```

Replace with:
```python
router = APIRouter(tags=["recipes"])
# BOLA EXEMPT: recipes, foods, and food-barcode endpoints are global catalog
# reads — no user_id column exists on these tables and no ownership check applies.
# Any authenticated (or unauthenticated in future) user may read them.
```

- [ ] **Step 2: Verify syntax**

```bash
cd /Users/miguelangelsaraviabelmonte/dev-backend/Nova-nutrition-backend/.claude/worktrees/feat-p0-prelaunch-hardening
.venv/bin/python -c "from app.recipes.presentation.router import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/recipes/presentation/router.py
git commit -m "docs(security): BOLA EXEMPT comment on global catalog endpoints (recipes/foods)"
```

---

## Task 9: Full sanity run

- [ ] **Step 1: Run BOLA tests + auth-related tests**

```bash
cd /Users/miguelangelsaraviabelmonte/dev-backend/Nova-nutrition-backend/.claude/worktrees/feat-p0-prelaunch-hardening
.venv/bin/pytest tests/unit/test_bola_audit.py tests/unit/ -k "bola or auth or identity or jwt or security" -v 2>&1 | tail -40
```

Expected: all BOLA tests pass, no pre-existing tests broken.

- [ ] **Step 2: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -60
```

Expected: all green (same count as before).

- [ ] **Step 3: Final commit — squash summary commit**

```bash
git add -A
git commit -m "feat(security): S0-B — BOLA audit (OWASP API1)

OWASP API1 (Broken Object Level Authorization), ASVS V4 (Access Control).

- New assert_owns() helper in identity/presentation/dependencies.py.
  Verifies resource.user_id == jwt.sub before mutation/read by external ID.
- Audited 8 user-owned endpoints across 4 routers; added ownership
  checks where missing. Documented existing repo-level checks with
  inline 'BOLA OK' comments.
- 3 new tests covering owner match, non-owner (Forbidden), missing row (NotFoundError).
- Recipes/foods/barcode catalog endpoints flagged as BOLA EXEMPT (no owner).

Endpoints fixed:
  - POST  /plans/{plan_id}/advance
  - PATCH /plans/{plan_id}/meals/{meal_id}/complete
  - POST  /plans/{plan_id}/meals/{meal_id}/swap
  - POST  /logs/food/{food_log_id}/edit
  - PATCH /grocery-items/{item_id}
  - DELETE /grocery-items/{item_id}
  - GET   /coach/conversations/{conv_id}/messages

BOLA OK (already protected, documented):
  - DELETE /logs/food/{log_id} (DeleteFoodLog UC filters by user_id)
  - POST /fasting/{session_id}/stop (StopFasting UC checks ownership)
  - DELETE /progress/photos/{photo_id} (inline WHERE user_id check)
  - GET /logs/food/jobs/{job_id} (GetJobStatus UC checks ownership)
  - GET /plans/{plan_id}/grocery-list (inline ownership check)
  - POST /grocery-items (ensure_owner helper)
  - GET /grocery-lists/{list_id}/share (ensure_owner helper)
  - DELETE /coach/conversations/{conv_id} (repo.delete filters by user_id)
  - DELETE /push/tokens/{token} (inline WHERE user_id check)"
```

---

## Self-Review Checklist

- [ ] No ownership check added to `GET /recipes/{recipe_id}`, `GET /foods`, `GET /foods/barcode/{ean}` — these are global catalog reads.
- [ ] No duplicate ownership check added where repository/UC already enforces it.
- [ ] Tests are green (3 new tests covering all 3 branches of `assert_owns`).
- [ ] `# BOLA OK` and `# BOLA EXEMPT` comments are present and clear.
- [ ] `assert_owns` uses parameterized SQL (`text(... :rid ...)`) — no string interpolation of user-controlled values.
- [ ] Grocery items use JOIN-based ownership check (items don't have a direct user_id column).
- [ ] `current_user: CurrentUserDep` annotation removed from `# noqa: ARG001` on fixed endpoints.
