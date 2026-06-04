"""Grocery REST endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, ConfigDict

from app.grocery.domain import GroceryCategory
from app.grocery.repository import SqlGroceryRepository
from app.grocery.use_cases import (
    AddManualItem,
    DeleteItem,
    GenerateGroceryList,
    MarkItemPurchased,
    ShareList,
    ensure_owner,
    verify_share_token,
)
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep

router = APIRouter(tags=["grocery"])


class GroceryItemOut(BaseModel):
    id: UUID
    category: str
    name: str
    amount: str | None = None
    purchased: bool


class GroceryListOut(BaseModel):
    id: UUID
    plan_id: UUID
    items: list[GroceryItemOut]


def _to_out(gl) -> GroceryListOut:
    return GroceryListOut(
        id=gl.id,
        plan_id=gl.plan_id,
        items=[
            GroceryItemOut(
                id=i.id,
                category=i.category.value,
                name=i.name,
                amount=i.amount,
                purchased=i.purchased,
            )
            for i in gl.items
        ],
    )


@router.get("/plans/{plan_id}/grocery-list", response_model=GroceryListOut)
async def get_grocery_list(
    plan_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
    scale: float = Query(default=1.0, ge=0.1, le=20.0),
    regenerate: bool = Query(default=False),
) -> GroceryListOut:
    # BOLA OK: plan ownership verified inline below before any data access.
    from sqlalchemy import text

    owner = (
        await session.execute(
            text("SELECT user_id FROM plans WHERE id = :pid"),
            {"pid": str(plan_id)},
        )
    ).scalar()
    if owner is None or owner != current_user:
        from app.core.errors import Forbidden, NotFoundError

        if owner is None:
            raise NotFoundError(detail="plan_not_found")
        raise Forbidden(detail="not_plan_owner")
    repo = SqlGroceryRepository(session)
    if regenerate:
        uc = GenerateGroceryList(session=session, repo=repo)
        gl = await uc(plan_id=plan_id, scale=scale)
    else:
        existing = await repo.get_or_create_list(plan_id)
        if not existing.items:
            uc = GenerateGroceryList(session=session, repo=repo)
            existing = await uc(plan_id=plan_id, scale=scale)
        gl = existing
    return _to_out(gl)


class PatchItemBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purchased: bool | None = None
    amount: str | None = None


@router.patch("/grocery-items/{item_id}", response_model=GroceryItemOut)
async def patch_item(
    item_id: UUID,
    body: PatchItemBody,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> GroceryItemOut:
    # BOLA: grocery_items don't have a direct user_id column; ownership is
    # grocery_items.list_id → grocery_lists.user_id. Verify before mutation.
    from sqlalchemy import text as _text

    from app.core.errors import Forbidden, NotFoundError

    owner_row = (
        await session.execute(
            _text(
                """
        SELECT gl.user_id FROM grocery_items gi
        JOIN grocery_lists gl ON gl.id = gi.list_id
        WHERE gi.id = :iid
    """
            ),
            {"iid": str(item_id)},
        )
    ).first()
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
        id=it.id,
        category=it.category.value,
        name=it.name,
        amount=it.amount,
        purchased=it.purchased,
    )


class AddItemBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    list_id: UUID
    name: str
    amount: str | None = None
    category: GroceryCategory | None = None


@router.post("/grocery-items", response_model=GroceryItemOut, status_code=status.HTTP_201_CREATED)
async def add_item(
    body: AddItemBody,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> GroceryItemOut:
    # BOLA OK: ensure_owner() in grocery/use_cases.py raises Forbidden if list not owned.
    await ensure_owner(session, list_id=body.list_id, user_id=current_user)
    uc = AddManualItem(repo=SqlGroceryRepository(session))
    it = await uc(
        list_id=body.list_id,
        name=body.name,
        amount=body.amount,
        category=body.category,
    )
    return GroceryItemOut(
        id=it.id,
        category=it.category.value,
        name=it.name,
        amount=it.amount,
        purchased=it.purchased,
    )


@router.delete("/grocery-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> None:
    # BOLA: verify grocery item belongs to current_user via grocery_lists.user_id.
    from sqlalchemy import text as _text

    from app.core.errors import Forbidden, NotFoundError

    owner_row = (
        await session.execute(
            _text(
                """
        SELECT gl.user_id FROM grocery_items gi
        JOIN grocery_lists gl ON gl.id = gi.list_id
        WHERE gi.id = :iid
    """
            ),
            {"iid": str(item_id)},
        )
    ).first()
    if owner_row is None:
        raise NotFoundError(detail="item_not_found")
    if str(owner_row[0]) != str(current_user):
        raise Forbidden(detail="not_owner")
    uc = DeleteItem(repo=SqlGroceryRepository(session))
    await uc(item_id)


@router.get("/grocery-lists/{list_id}/share")
async def share_list(
    list_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
    ttl_hours: int = Query(default=168, ge=1, le=720),
) -> dict:
    # BOLA OK: ensure_owner() in grocery/use_cases.py raises Forbidden if list not owned.
    await ensure_owner(session, list_id=list_id, user_id=current_user)
    uc = ShareList(repo=SqlGroceryRepository(session))
    return await uc(list_id=list_id, ttl_hours=ttl_hours)


@router.get("/grocery-lists/{list_id}/shared", response_model=GroceryListOut)
async def shared_view(
    list_id: UUID,
    session: SessionDep,
    token: str = Query(...),
) -> GroceryListOut:
    if not verify_share_token(list_id, token):
        from app.core.errors import Forbidden

        raise Forbidden(detail="invalid_or_expired_token")
    gl = await SqlGroceryRepository(session).get_list(list_id)
    if gl is None:
        from app.core.errors import NotFoundError

        raise NotFoundError(detail="list_not_found")
    return _to_out(gl)
