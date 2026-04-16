from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from datetime import datetime

from app.middleware.auth import get_current_user
from app.models.application import ApplicationRecordCreate, ApplicationRecordUpdate
from app.services.mongo import mongo

router = APIRouter(tags=["applications"])


@router.post("/applications", response_model=dict)
async def create_application(
    record: ApplicationRecordCreate,
    current_user: str = Depends(get_current_user),
):
    doc = {**record.dict(), "userId": current_user, "createdAt": datetime.utcnow()}
    result = await mongo.applications.insert_one(doc)
    return {"id": str(result.inserted_id), "message": "saved"}


@router.get("/applications", response_model=dict)
async def list_applications(
    current_user: str = Depends(get_current_user),
):
    cursor = mongo.applications.find({"userId": current_user}).sort("createdAt", -1).limit(100)
    docs = await cursor.to_list(100)
    for d in docs:
        d["_id"] = str(d["_id"])
    return {"applications": docs}


PIPELINE_STAGES_ORDER = [
    "evaluated", "applied", "responded", "contacted",
    "interview", "offer", "rejected", "discarded",
]


@router.get("/applications/stats", response_model=dict)
async def get_application_stats(
    current_user: str = Depends(get_current_user),
):
    pipeline = [
        {"$match": {"userId": current_user}},
        {
            "$group": {
                "_id": "$pipelineStage",
                "count": {"$sum": 1},
                # $avg returns null automatically when there are no docs,
                # but we need it to be null (None) for stages with 0 apps.
                # matchPercentage of 0 should not skew the average, so only
                # average docs where matchPercentage > 0.
                "sum_ats": {"$sum": "$matchPercentage"},
                "count_with_ats": {
                    "$sum": {
                        "$cond": [{"$gt": ["$matchPercentage", 0]}, 1, 0]
                    }
                },
                "sum_ats_nonzero": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$matchPercentage", 0]},
                            "$matchPercentage",
                            0,
                        ]
                    }
                },
            }
        },
    ]
    raw = await mongo.applications.aggregate(pipeline).to_list(None)

    # Build lookup by stage name
    by_stage: dict = {}
    for r in raw:
        stage = r["_id"] or "evaluated"
        count_with_ats = r.get("count_with_ats", 0)
        avg_ats = (
            round(r["sum_ats_nonzero"] / count_with_ats, 1)
            if count_with_ats > 0
            else None
        )
        by_stage[stage] = {"count": r["count"], "avg_ats": avg_ats}

    total = sum(v["count"] for v in by_stage.values())

    stage_breakdown = {s: by_stage.get(s, {}).get("count", 0) for s in PIPELINE_STAGES_ORDER}
    avg_ats_by_stage = {s: by_stage.get(s, {}).get("avg_ats", None) for s in PIPELINE_STAGES_ORDER}

    return {
        "totalApplications": total,
        "stageBreakdown": stage_breakdown,
        "avgAtsScoreByStage": avg_ats_by_stage,
    }


@router.patch("/applications/{app_id}", response_model=dict)
async def update_application(
    app_id: str,
    update: ApplicationRecordUpdate,
    current_user: str = Depends(get_current_user),
):
    try:
        oid = ObjectId(app_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid application ID")

    fields = update.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = await mongo.applications.update_one(
        {"_id": oid, "userId": current_user},
        {"$set": fields},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Application not found")

    return {"message": "updated"}


@router.delete("/applications/{app_id}", response_model=dict)
async def delete_application(
    app_id: str,
    current_user: str = Depends(get_current_user),
):
    try:
        oid = ObjectId(app_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid application ID")
    await mongo.applications.delete_one({"_id": oid, "userId": current_user})
    return {"message": "deleted"}
