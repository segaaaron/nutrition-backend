"""Grocery SQL repository."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.grocery.domain import GroceryCategory, GroceryItem, GroceryList


class SqlGroceryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get_or_create_list(self, plan_id: UUID) -> GroceryList:
        r = (
            (
                await self.s.execute(
                    text(
                        """
            SELECT id, plan_id, generated_at FROM grocery_lists
             WHERE plan_id = :pid ORDER BY generated_at DESC LIMIT 1
        """
                    ),
                    {"pid": str(plan_id)},
                )
            )
            .mappings()
            .first()
        )
        if r:
            items = await self._items(r["id"])
            return GroceryList(
                id=r["id"],
                plan_id=r["plan_id"],
                generated_at=r["generated_at"],
                items=items,
            )
        lid = uuid4()
        try:
            await self.s.execute(
                text(
                    """
                INSERT INTO grocery_lists (id, plan_id) VALUES (:id, :pid)
            """
                ),
                {"id": str(lid), "pid": str(plan_id)},
            )
        except IntegrityError:
            # Concurrent request already inserted — rollback savepoint and re-read.
            await self.s.rollback()
            r = (
                (
                    await self.s.execute(
                        text(
                            """
                SELECT id, plan_id, generated_at FROM grocery_lists
                 WHERE plan_id = :pid ORDER BY generated_at DESC LIMIT 1
            """
                        ),
                        {"pid": str(plan_id)},
                    )
                )
                .mappings()
                .first()
            )
            items = await self._items(r["id"])
            return GroceryList(
                id=r["id"],
                plan_id=r["plan_id"],
                generated_at=r["generated_at"],
                items=items,
            )
        return GroceryList(
            id=lid,
            plan_id=plan_id,
            generated_at=(
                await self.s.execute(
                    text("SELECT generated_at FROM grocery_lists WHERE id = :id"),
                    {"id": str(lid)},
                )
            ).scalar(),
            items=[],
        )

    async def _items(self, list_id: UUID) -> list[GroceryItem]:
        rows = (
            (
                await self.s.execute(
                    text(
                        """
            SELECT id, list_id, category, name, amount, purchased
              FROM grocery_items WHERE list_id = :lid
             ORDER BY category, name
        """
                    ),
                    {"lid": str(list_id)},
                )
            )
            .mappings()
            .all()
        )
        return [
            GroceryItem(
                id=r["id"],
                list_id=r["list_id"],
                category=GroceryCategory(r["category"]),
                name=r["name"],
                amount=r["amount"],
                purchased=r["purchased"],
            )
            for r in rows
        ]

    async def bulk_insert_items(self, items: list[GroceryItem]) -> None:
        if not items:
            return
        for it in items:
            await self.s.execute(
                text(
                    """
                INSERT INTO grocery_items (id, list_id, category, name, amount, purchased)
                VALUES (:id, :lid, :cat, :n, :a, :p)
            """
                ),
                {
                    "id": str(it.id),
                    "lid": str(it.list_id),
                    "cat": it.category.value,
                    "n": it.name,
                    "a": it.amount,
                    "p": it.purchased,
                },
            )

    async def update_item(
        self,
        *,
        item_id: UUID,
        purchased: bool | None,
        amount: str | None,
    ) -> GroceryItem | None:
        sets = []
        params: dict = {"id": str(item_id)}
        if purchased is not None:
            sets.append("purchased = :p")
            params["p"] = purchased
        if amount is not None:
            sets.append("amount = :a")
            params["a"] = amount
        if not sets:
            return None
        # S608 noqa: `sets` is exclusively assembled from literal SET clauses
        # ("purchased = :p", "amount = :a") branching on caller-controlled
        # booleans. No user input reaches the SQL string; all values bound.
        await self.s.execute(
            text(
                f"""
            UPDATE grocery_items SET {", ".join(sets)} WHERE id = :id
        """  # noqa: S608 — `sets` from literal SET clauses only; values bound
            ),
            params,
        )
        r = (
            (
                await self.s.execute(
                    text(
                        """
            SELECT id, list_id, category, name, amount, purchased
              FROM grocery_items WHERE id = :id
        """
                    ),
                    {"id": str(item_id)},
                )
            )
            .mappings()
            .first()
        )
        if not r:
            return None
        return GroceryItem(
            id=r["id"],
            list_id=r["list_id"],
            category=GroceryCategory(r["category"]),
            name=r["name"],
            amount=r["amount"],
            purchased=r["purchased"],
        )

    async def delete_item(self, item_id: UUID) -> None:
        await self.s.execute(
            text("DELETE FROM grocery_items WHERE id = :id"),
            {"id": str(item_id)},
        )

    async def add_item(self, item: GroceryItem) -> None:
        await self.bulk_insert_items([item])

    async def get_list(self, list_id: UUID) -> GroceryList | None:
        r = (
            (
                await self.s.execute(
                    text(
                        """
            SELECT id, plan_id, generated_at FROM grocery_lists WHERE id = :id
        """
                    ),
                    {"id": str(list_id)},
                )
            )
            .mappings()
            .first()
        )
        if not r:
            return None
        return GroceryList(
            id=r["id"],
            plan_id=r["plan_id"],
            generated_at=r["generated_at"],
            items=await self._items(r["id"]),
        )

    async def list_owner(self, list_id: UUID) -> UUID | None:
        r = (
            await self.s.execute(
                text(
                    """
            SELECT p.user_id FROM grocery_lists gl
              JOIN plans p ON p.id = gl.plan_id
             WHERE gl.id = :id
        """
                ),
                {"id": str(list_id)},
            )
        ).scalar()
        return r
