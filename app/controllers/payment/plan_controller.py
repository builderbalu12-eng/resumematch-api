from fastapi import HTTPException
from app.services.payment.razorpay_service import razorpay_service
from app.services.mongo import mongo
from app.models.payment.plan import PlanCreate, PlanUpdate, PlanOut
from bson import ObjectId
from datetime import datetime
from typing import Dict, List, Optional


class PlanController:

    @staticmethod
    async def create_plan(data: PlanCreate, current_user: str) -> Dict:  # ← add current_user
    # async def create_plan(data: PlanCreate) -> Dict:
        plan_data = {
            "period": data.period,
            "interval": data.interval,
            "item": {
                "name": data.plan_name,
                "amount": int(data.amount * 100),
                "currency": data.currency.upper(),
                "description": data.description
            }
        }

        razorpay_plan = razorpay_service.create_plan(plan_data)

        doc = {
            "_id": ObjectId(),
            "plan_name": data.plan_name,
            "amount": data.amount,
            "currency": data.currency,
            "period": data.period,
            "interval": data.interval,
            "credits_per_cycle": data.credits_per_cycle,
            "description": data.description,
            "razorpay_plan_id": razorpay_plan["id"],
            "is_active": data.is_active,
            "applicable_to": data.applicable_to,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }

        await mongo.plans.insert_one(doc)

        # FIX: Convert _id to string
        doc_safe = doc.copy()
        doc_safe["_id"] = str(doc_safe["_id"])

        return PlanOut(**doc_safe).model_dump(by_alias=True)

    @staticmethod
    async def get_plan(plan_id: str, current_user: str = None) -> Dict:
        doc = await mongo.plans.find_one({"_id": ObjectId(plan_id)})
        if not doc:
            raise HTTPException(404, "Plan not found")
        
        # Convert _id to string
        doc_safe = doc.copy()
        if "_id" in doc_safe:
            doc_safe["_id"] = str(doc_safe["_id"])
        
        return PlanOut(**doc_safe).model_dump(by_alias=True)

    @staticmethod
    async def list_plans(
        skip: int = 0,
        limit: int = 20,
        active_only: bool = True,
        current_user: str = None  # ← ADD THIS (can be None for public)
    ) -> Dict:
        query = {"is_active": True} if active_only else {}
        cursor = mongo.plans.find(query).skip(skip).limit(limit).sort("created_at", -1)
        plans = await cursor.to_list(length=limit)
        total = await mongo.plans.count_documents(query)

        result = []
        for p in plans:
            p_safe = p.copy()
            if "_id" in p_safe:
                p_safe["_id"] = str(p_safe["_id"])
            result.append(PlanOut(**p_safe).model_dump(by_alias=True))

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

        # Fetch updated document
        updated = await mongo.plans.find_one({"_id": ObjectId(plan_id)})

        # FIX: Convert _id to string for Pydantic
        updated_safe = updated.copy()
        if "_id" in updated_safe:
            updated_safe["_id"] = str(updated_safe["_id"])

        return PlanOut(**updated_safe).model_dump(by_alias=True)

    @staticmethod
    async def delete_plan(plan_id: str, current_user: str = None) -> Dict:
        result = await mongo.plans.delete_one({"_id": ObjectId(plan_id)})
        if result.deleted_count == 0:
            raise HTTPException(404, "Plan not found")
        return {"message": "Plan deleted"}