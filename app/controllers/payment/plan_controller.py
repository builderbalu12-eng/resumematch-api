from fastapi import HTTPException
from app.services.payment.razorpay_service import razorpay_service
from app.services.mongo import mongo
from app.models.payment.plan import PlanCreate, PlanUpdate, PlanOut
from bson import ObjectId
from datetime import datetime
from typing import Dict


def normalize_id(doc: Dict) -> Dict:
    if doc and "_id" in doc and isinstance(doc["_id"], ObjectId):
        doc["_id"] = str(doc["_id"])
    return doc


CYCLE_TO_PERIOD = {
    "monthly": ("monthly", 1),
    "yearly":  ("yearly",  1),
}


class PlanController:

    @staticmethod
    async def create_plan(data: PlanCreate, current_user: str) -> Dict:
        razorpay_plan_id = None

        # Only call Razorpay for paid + recurring plans
        if data.amount > 0 and data.is_recurring:
            period, interval = CYCLE_TO_PERIOD.get(data.billing_cycle, ("monthly", 1))
            rp_data = {
                "period": period,
                "interval": interval,
                "item": {
                    "name": data.plan_name,
                    "amount": int(data.amount * 100),
                    "currency": data.currency.upper(),
                    "description": data.description or data.plan_name
                }
            }
            rp_plan = razorpay_service.create_plan(rp_data)
            razorpay_plan_id = rp_plan["id"]

        doc = {
            "_id": ObjectId(),
            "plan_name": data.plan_name,
            "amount": data.amount,
            "currency": data.currency.upper(),
            "is_recurring": data.is_recurring,
            "billing_cycle": data.billing_cycle,
            "credits_per_cycle": data.credits_per_cycle,   # ← ADDED
            "points": data.points,
            "description": data.description,
            "razorpay_plan_id": razorpay_plan_id,
            "is_active": data.is_active,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }

        await mongo.plans.insert_one(doc)

        return {
            "status": 200,
            "success": True,
            "message": "Plan created successfully",
            "data": PlanOut(**normalize_id(doc.copy())).model_dump(by_alias=True)
        }

    @staticmethod
    async def get_plan(plan_id: str, current_user: str = None) -> Dict:
        doc = await mongo.plans.find_one({"_id": ObjectId(plan_id)})
        if not doc:
            raise HTTPException(404, "Plan not found")
        return PlanOut(**normalize_id(doc.copy())).model_dump(by_alias=True)

    @staticmethod
    async def list_plans(
        skip: int = 0,
        limit: int = 20,
        active_only: bool = True,
        current_user: str = None
    ) -> Dict:
        query = {"is_active": True} if active_only else {}
        cursor = mongo.plans.find(query).skip(skip).limit(limit).sort("amount", 1)
        plans = await cursor.to_list(length=limit)
        total = await mongo.plans.count_documents(query)

        result = [PlanOut(**normalize_id(p.copy())).model_dump(by_alias=True) for p in plans]

        return {
            "status": 200,
            "success": True,
            "message": f"Found {len(result)} plans",
            "data": {
                "items": result,
                "total": total,
                "skip": skip,
                "limit": limit
            }
        }

    @staticmethod
    async def update_plan(plan_id: str, data: PlanUpdate, current_user: str) -> Dict:
        update_dict = data.model_dump(exclude_unset=True)
        if not update_dict:
            raise HTTPException(400, "No fields to update")

        update_dict["updated_at"] = datetime.utcnow()

        result = await mongo.plans.update_one(
            {"_id": ObjectId(plan_id)},
            {"$set": update_dict}
        )

        if result.modified_count == 0:
            raise HTTPException(404, "Plan not found or no changes")

        updated = await mongo.plans.find_one({"_id": ObjectId(plan_id)})
        return PlanOut(**normalize_id(updated.copy())).model_dump(by_alias=True)

    @staticmethod
    async def delete_plan(plan_id: str, current_user: str = None) -> Dict:
        result = await mongo.plans.delete_one({"_id": ObjectId(plan_id)})
        if result.deleted_count == 0:
            raise HTTPException(404, "Plan not found")
        return {"status": 200, "success": True, "message": "Plan deleted"}
