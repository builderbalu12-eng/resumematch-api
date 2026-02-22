# app/controllers/payment/coupon_controller.py
from fastapi import HTTPException
from app.services.mongo import mongo
from app.models.payment.coupon import CouponCreate, CouponUpdate, CouponOut
from bson import ObjectId
from datetime import datetime
from typing import Dict, List, Optional


def normalize_id(doc: Dict) -> Dict:
    """Convert MongoDB _id to string for Pydantic"""
    if doc and "_id" in doc and isinstance(doc["_id"], ObjectId):
        doc["_id"] = str(doc["_id"])
    return doc


class CouponController:

    @staticmethod
    async def create_coupon(data: CouponCreate) -> Dict:
        doc = {
            "_id": ObjectId(),
            "code": data.code.upper(),
            "discount_percent": data.discount_percent,
            "discount_amount": data.discount_amount,
            "max_uses": data.max_uses,
            "expires_at": data.expires_at,
            "is_active": data.is_active,
            "applicable_to_plans": data.applicable_to_plans,
            "applicable_to_domains": data.applicable_to_domains,
            "uses_count": 0,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }

        await mongo.coupons.insert_one(doc)

        # Convert _id before returning
        doc_safe = normalize_id(doc.copy())
        return CouponOut(**doc_safe).model_dump(by_alias=True)

    @staticmethod
    async def get_coupon(coupon_id: str) -> Dict:
        doc = await mongo.coupons.find_one({"_id": ObjectId(coupon_id)})
        if not doc:
            raise HTTPException(404, "Coupon not found")

        doc_safe = normalize_id(doc.copy())
        return CouponOut(**doc_safe).model_dump(by_alias=True)

    @staticmethod
    async def list_coupons(
        skip: int = 0,
        limit: int = 20,
        active_only: bool = True,
        current_user: str = None  # optional for future filtering
    ) -> Dict:
        query = {"is_active": True} if active_only else {}
        cursor = mongo.coupons.find(query).skip(skip).limit(limit).sort("created_at", -1)
        coupons = await cursor.to_list(length=limit)
        total = await mongo.coupons.count_documents(query)

        result = []
        for c in coupons:
            c_safe = normalize_id(c.copy())
            result.append(CouponOut(**c_safe).model_dump(by_alias=True))

        return {
            "status": 200,
            "success": True,
            "message": f"Found {len(result)} coupons",
            "data": {
                "items": result,
                "total": total,
                "skip": skip,
                "limit": limit
            }
        }

    @staticmethod
    async def update_coupon(coupon_id: str, data: CouponUpdate) -> Dict:
        update_dict = data.model_dump(exclude_unset=True)
        if not update_dict:
            raise HTTPException(400, "No fields to update")

        update_dict["updated_at"] = datetime.utcnow()

        result = await mongo.coupons.update_one(
            {"_id": ObjectId(coupon_id)},
            {"$set": update_dict}
        )

        if result.modified_count == 0:
            raise HTTPException(404, "Coupon not found or no changes")

        updated = await mongo.coupons.find_one({"_id": ObjectId(coupon_id)})
        updated_safe = normalize_id(updated.copy())
        return CouponOut(**updated_safe).model_dump(by_alias=True)

    @staticmethod
    async def delete_coupon(coupon_id: str) -> Dict:
        result = await mongo.coupons.delete_one({"_id": ObjectId(coupon_id)})
        if result.deleted_count == 0:
            raise HTTPException(404, "Coupon not found")
        return {"status": 200, "success": True, "message": "Coupon deleted"}