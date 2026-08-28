"""Progress photos + composite progress dashboard.

Uses the existing VipsImageCompressor (EXIF-strip-verified) for upload.
Photos persist URL-only in `progress_photos` — actual bytes go to object
storage (R2 in prod, local-disk in dev) via the compressor's `bytes_` payload.
For Sprint 7.E we accept the URL inline and rely on the upstream upload
pipeline (vision Sprint 5) to surface a CDN URL when needed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import text

from app.core.errors import NotFoundError
from app.identity.presentation.dependencies import CurrentUserDep, SessionDep
from app.imaging.domain.contracts import CompressionProfile
from app.imaging.infrastructure.vips_compressor import VipsImageCompressor

router = APIRouter(tags=["progress"])


class WeightTrendPoint(BaseModel):
    day: str
    weight_kg: float


class BodyCompositionOut(BaseModel):
    time: datetime | None = None
    weight_kg: float | None = None
    body_fat_pct: float | None = None
    waist_cm: float | None = None


class GoalOut(BaseModel):
    goal: str | None = None
    kcal_target: int | None = None


class RecentPhotoOut(BaseModel):
    id: str
    taken_at: str
    image_url: str | None = None
    weight_kg: float | None = None


class ProgressDashboardResponse(BaseModel):
    weight_trend: list[WeightTrendPoint]
    body_composition: BodyCompositionOut | None
    goal: GoalOut | None
    recent_photos: list[RecentPhotoOut]


class ProgressPhotoOut(BaseModel):
    id: UUID
    taken_at: datetime
    weight_kg: float | None = None
    image_url: str | None = None
    blurhash: str | None = None


@router.post(
    "/progress/photo",
    response_model=ProgressPhotoOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_progress_photo(
    current_user: CurrentUserDep,
    session: SessionDep,
    file: UploadFile = File(...),
    weight_kg: float | None = Form(default=None),
) -> ProgressPhotoOut:
    raw = await file.read()
    compressor = VipsImageCompressor()
    compressed = await compressor.compress(raw, profile=CompressionProfile.PROGRESS)
    # In production the bytes ship to object storage (R2). For now we
    # base64-tag the URL with a content hash so the row is non-null and
    # downstream consumers can swap the stored URL once the uploader lands.
    import hashlib

    sha = hashlib.sha256(compressed.bytes_).hexdigest()[:16]
    image_url = f"placeholder://progress/{current_user}/{sha}.{compressed.format}"

    pid = uuid4()
    await session.execute(
        text(
            """
        INSERT INTO progress_photos (id, user_id, taken_at, weight_kg, image_url)
        VALUES (:id, :uid, now(), :w, :url)
        ON CONFLICT (user_id, image_url) DO NOTHING
    """
        ),
        {
            "id": str(pid),
            "uid": str(current_user),
            "w": weight_kg,
            "url": image_url,
        },
    )
    return ProgressPhotoOut(
        id=pid,
        taken_at=datetime.now(UTC),
        weight_kg=weight_kg,
        image_url=image_url,
        blurhash=None,
    )


@router.get("/progress/photos")
async def list_progress_photos(
    current_user: CurrentUserDep,
    session: SessionDep,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    params: dict = {"uid": str(current_user), "limit": limit + 1}
    where = "user_id = :uid"
    if cursor:
        import base64

        obj = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        params["ct"] = datetime.fromisoformat(obj["t"])
        params["cid"] = obj["id"]
        where += " AND (taken_at, id) < (:ct, :cid)"
    # S608 noqa: `where` is assembled exclusively from literal WHERE fragments
    # authored in this function. All values bound via :params.
    rows = (
        (
            await session.execute(
                text(
                    f"""
        SELECT id, taken_at, weight_kg, image_url, blurhash
          FROM progress_photos
         WHERE {where}
         ORDER BY taken_at DESC, id DESC LIMIT :limit
    """  # noqa: S608 — `where` from literal fragments only; values bound
                ),
                params,
            )
        )
        .mappings()
        .all()
    )  # noqa: S608
    nxt = None
    if len(rows) > limit:
        rows = rows[:limit]
        import base64

        last = rows[-1]
        nxt = base64.urlsafe_b64encode(
            json.dumps({"t": last["taken_at"].isoformat(), "id": str(last["id"])}).encode()
        ).decode()
    return {
        "items": [
            {
                "id": str(r["id"]),
                "taken_at": r["taken_at"].isoformat(),
                "weight_kg": float(r["weight_kg"]) if r["weight_kg"] is not None else None,
                "image_url": r["image_url"],
                "blurhash": r["blurhash"],
            }
            for r in rows
        ],
        "next_cursor": nxt,
    }


@router.delete("/progress/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_progress_photo(
    photo_id: UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> Response:
    # BOLA OK: SELECT ... WHERE id = :id AND user_id = :uid — raises NotFoundError if mismatch.
    r = (
        await session.execute(
            text(
                """
        SELECT id FROM progress_photos WHERE id = :id AND user_id = :uid
    """
            ),
            {"id": str(photo_id), "uid": str(current_user)},
        )
    ).first()
    if r is None:
        raise NotFoundError(detail="photo_not_found")
    await session.execute(
        text(
            """
        INSERT INTO audit_log (actor_type, user_id, action, target_type, target_id, metadata)
        VALUES ('user', :uid, 'progress_photo.delete', 'progress_photo', :tid, '{}'::jsonb)
    """
        ),
        {"uid": str(current_user), "tid": str(photo_id)},
    )
    await session.execute(text("DELETE FROM progress_photos WHERE id = :id"), {"id": str(photo_id)})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/progress", response_model=ProgressDashboardResponse)
async def progress_dashboard(
    current_user: CurrentUserDep,
    session: SessionDep,
) -> ProgressDashboardResponse:
    # Weight trend (last 30d)
    trend = (
        (
            await session.execute(
                text(
                    """
        SELECT day, weight_kg_mean
          FROM biometric_aggregates_daily
         WHERE user_id = :uid
           AND day >= (CURRENT_DATE - INTERVAL '30 days')
         ORDER BY day ASC
    """
                ),
                {"uid": str(current_user)},
            )
        )
        .mappings()
        .all()
    )
    # Latest body composition
    latest = (
        (
            await session.execute(
                text(
                    """
        SELECT time, weight_kg, body_fat_pct, waist_cm FROM weight_logs
         WHERE user_id = :uid
         ORDER BY time DESC LIMIT 1
    """
                ),
                {"uid": str(current_user)},
            )
        )
        .mappings()
        .first()
    )
    # Goal progress
    goal = (
        (
            await session.execute(
                text(
                    """
        SELECT goal, kcal_target FROM plans
         WHERE user_id = :uid AND status = 'active' LIMIT 1
    """
                ),
                {"uid": str(current_user)},
            )
        )
        .mappings()
        .first()
    )
    photos = (
        (
            await session.execute(
                text(
                    """
        SELECT id, taken_at, weight_kg, image_url FROM progress_photos
         WHERE user_id = :uid ORDER BY taken_at DESC LIMIT 4
    """
                ),
                {"uid": str(current_user)},
            )
        )
        .mappings()
        .all()
    )
    return ProgressDashboardResponse(
        weight_trend=[
            WeightTrendPoint(day=r["day"].isoformat(), weight_kg=float(r["weight_kg_mean"]))
            for r in trend
        ],
        body_composition=BodyCompositionOut(
            time=latest["time"] if latest else None,
            weight_kg=float(latest["weight_kg"]) if latest and latest["weight_kg"] is not None else None,
            body_fat_pct=float(latest["body_fat_pct"]) if latest and latest["body_fat_pct"] is not None else None,
            waist_cm=float(latest["waist_cm"]) if latest and latest["waist_cm"] is not None else None,
        ) if latest else None,
        goal=GoalOut(
            goal=goal["goal"] if goal else None,
            kcal_target=int(goal["kcal_target"]) if goal and goal["kcal_target"] is not None else None,
        ) if goal else None,
        recent_photos=[
            RecentPhotoOut(
                id=str(p["id"]),
                taken_at=p["taken_at"].isoformat(),
                image_url=p["image_url"],
                weight_kg=float(p["weight_kg"]) if p["weight_kg"] is not None else None,
            )
            for p in photos
        ],
    )
