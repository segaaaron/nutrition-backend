"""Grocery use cases: generate, mark purchased, add manual, scale, share."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Forbidden, NotFoundError
from app.grocery.domain import GroceryCategory, GroceryItem, GroceryList, categorise
from app.grocery.repository import SqlGroceryRepository


@dataclass(slots=True)
class GenerateGroceryList:
    """Idempotent per plan — re-generation reuses the existing list (deletes
    existing items and re-inserts to reflect plan swaps).
    """

    session: AsyncSession
    repo: SqlGroceryRepository

    async def __call__(
        self,
        *,
        plan_id: UUID,
        scale: float = 1.0,
    ) -> GroceryList:
        rows = (
            (
                await self.session.execute(
                    text(
                        """
            SELECT f.name_en, fl.amount_g
              FROM plan_meals pm
              JOIN plan_days pd ON pd.id = pm.plan_day_id
              JOIN recipes r ON r.id = pm.recipe_id
              JOIN recipe_components rc ON rc.recipe_id = r.id
              LEFT JOIN foods f ON f.id = rc.food_id
              LEFT JOIN food_logs fl ON false  -- placeholder dummy alias
             WHERE pd.plan_id = :pid AND f.id IS NOT NULL
        """
                    ),
                    {"pid": str(plan_id)},
                )
            )
            .mappings()
            .all()
        )
        # Re-run: simpler query — components only
        rows = (
            (
                await self.session.execute(
                    text(
                        """
            SELECT COALESCE(f.name_en, rc.free_text_name) AS name,
                   COALESCE(SUM(rc.amount_g), 0) AS total_g
              FROM plan_meals pm
              JOIN plan_days pd ON pd.id = pm.plan_day_id
              JOIN recipes r ON r.id = pm.recipe_id
              JOIN recipe_components rc ON rc.recipe_id = r.id
              LEFT JOIN foods f ON f.id = rc.food_id
             WHERE pd.plan_id = :pid
               AND (f.name_en IS NOT NULL OR rc.free_text_name IS NOT NULL)
             GROUP BY COALESCE(f.name_en, rc.free_text_name)
             ORDER BY name
        """
                    ),
                    {"pid": str(plan_id)},
                )
            )
            .mappings()
            .all()
        )

        gl = await self.repo.get_or_create_list(plan_id)
        # Clear previous items (idempotent regeneration).
        await self.session.execute(
            text("DELETE FROM grocery_items WHERE list_id = :lid"),
            {"lid": str(gl.id)},
        )
        items: list[GroceryItem] = []
        for r in rows:
            name = r["name"]
            total_g = float(r["total_g"] or 0) * scale
            amount = f"{int(round(total_g))} g" if total_g > 0 else None
            items.append(
                GroceryItem(
                    id=uuid4(),
                    list_id=gl.id,
                    category=categorise(name),
                    name=name,
                    amount=amount,
                )
            )
        await self.repo.bulk_insert_items(items)
        gl.items = items
        return gl


@dataclass(slots=True)
class MarkItemPurchased:
    repo: SqlGroceryRepository

    async def __call__(
        self,
        *,
        item_id: UUID,
        purchased: bool | None = None,
        amount: str | None = None,
    ) -> GroceryItem | None:
        return await self.repo.update_item(
            item_id=item_id,
            purchased=purchased,
            amount=amount,
        )


@dataclass(slots=True)
class AddManualItem:
    repo: SqlGroceryRepository

    async def __call__(
        self,
        *,
        list_id: UUID,
        name: str,
        amount: str | None = None,
        category: GroceryCategory | None = None,
    ) -> GroceryItem:
        item = GroceryItem(
            id=uuid4(),
            list_id=list_id,
            category=category or categorise(name),
            name=name,
            amount=amount,
        )
        await self.repo.add_item(item)
        return item


@dataclass(slots=True)
class DeleteItem:
    repo: SqlGroceryRepository

    async def __call__(self, item_id: UUID) -> None:
        await self.repo.delete_item(item_id)


# --- Share signed URLs ---
# HMAC over (list_id, expires_ts) using the JWT private key path digest as
# secret — avoids introducing a new secret; rotated on JWT key rotation.


def _share_secret() -> bytes:
    s = get_settings()
    return hashlib.sha256(s.jwt_private_key_path.encode()).digest()


def _sign(list_id: UUID, exp: int) -> str:
    payload = f"{list_id}.{exp}".encode()
    mac = hmac.new(_share_secret(), payload, hashlib.sha256).hexdigest()
    return f"{exp}.{mac}"


def verify_share_token(list_id: UUID, token: str) -> bool:
    try:
        exp_str, mac = token.split(".", 1)
        exp = int(exp_str)
    except Exception:  # noqa: BLE001
        return False
    if exp < int(datetime.now(UTC).timestamp()):
        return False
    expected = hmac.new(
        _share_secret(),
        f"{list_id}.{exp}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, mac)


@dataclass(slots=True)
class ShareList:
    repo: SqlGroceryRepository

    async def __call__(
        self,
        *,
        list_id: UUID,
        ttl_hours: int = 168,
    ) -> dict:
        gl = await self.repo.get_list(list_id)
        if gl is None:
            raise NotFoundError(detail="list_not_found")
        exp = int((datetime.now(UTC) + timedelta(hours=ttl_hours)).timestamp())
        token = _sign(list_id, exp)
        return {
            "url": f"/grocery-lists/{list_id}/shared?token={token}",
            "token": token,
            "expires_ts": exp,
        }


async def ensure_owner(
    session: AsyncSession,
    *,
    list_id: UUID,
    user_id: UUID,
) -> None:
    repo = SqlGroceryRepository(session)
    owner = await repo.list_owner(list_id)
    if owner is None:
        raise NotFoundError(detail="list_not_found")
    if owner != user_id:
        raise Forbidden(detail="not_list_owner")
