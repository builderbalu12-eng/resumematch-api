# app/controllers/client_controller.py

from fastapi import HTTPException
from app.services.mongo import mongo
from app.models.client import ClientCreate, ClientUpdate, ClientOut
from app.services.geo_service import geo_service
from bson import ObjectId
from datetime import datetime
from typing import Dict, Optional


def normalize_id(doc: Dict) -> Dict:
    if doc and "_id" in doc and isinstance(doc["_id"], ObjectId):
        doc["_id"] = str(doc["_id"])
    return doc


class ClientController:

    # ─── Create ──────────────────────────────────────────────
    @staticmethod
    async def create_client(data: ClientCreate, current_user: str) -> Dict:

        location = data.location.model_dump() if data.location else None
        if not location and data.address:
            location = await geo_service.get_coordinates(data.address)
            if not location:
                print(f"⚠️  Could not geocode: {data.address}")

        # ✅ Extract flat lat/lng from location for map pins
        lat_val = None
        lng_val = None
        if location and location.get("coordinates"):
            lng_val = location["coordinates"][0]
            lat_val = location["coordinates"][1]

        doc = {
            "_id": ObjectId(),
            "owner_id": current_user,
            "name": data.name,
            "company": data.company,
            "photo_url": data.photo_url,
            "email": data.email,
            "phone": data.phone,
            "whatsapp": data.whatsapp,
            "website": data.website,
            "has_website": bool(data.website),
            "address": data.address,
            "source": "manual",
            "rating": None,
            "lat": lat_val,          # ✅ ADDED
            "lng": lng_val,          # ✅ ADDED
            "category": data.category,
            "budget_min": data.budget_min,
            "budget_max": data.budget_max,
            "status": data.status,
            "location": location,
            "tags": data.tags or [],
            "notes": data.notes,
            "social_links": data.social_links or {},
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }

        await mongo.clients.insert_one(doc)

        return {
            "status": 200,
            "success": True,
            "message": "Client created successfully",
            "data": ClientOut(**normalize_id(doc.copy())).model_dump(by_alias=True)
        }

    # ─── Get One ─────────────────────────────────────────────
    @staticmethod
    async def get_client(client_id: str, current_user: str) -> Dict:
        doc = await mongo.clients.find_one({"_id": ObjectId(client_id)})
        if not doc:
            raise HTTPException(404, "Client not found")
        if doc.get("owner_id") != current_user:
            raise HTTPException(403, "Access denied")

        return {
            "status": 200,
            "success": True,
            "data": ClientOut(**normalize_id(doc.copy())).model_dump(by_alias=True)
        }

    # ─── List All ────────────────────────────────────────────
    @staticmethod
    async def list_clients(
        skip: int = 0,
        limit: int = 20,
        category: Optional[str] = None,
        status: Optional[str] = None,
        has_website: Optional[bool] = None,
        source: Optional[str] = None,
        current_user: str = None
    ) -> Dict:
        query = {"owner_id": current_user}
        print(f"🔍 DEBUG query: {query}")        # ← ADD THIS
        print(f"🔍 DEBUG source param: {source}") # ← ADD THIS
        if category:
            query["category"] = category
        if status:
            query["status"] = status
        if has_website is not None:
            query["has_website"] = has_website
        if source:
            query["source"] = source

        cursor = mongo.clients.find(query).skip(skip).limit(limit).sort("created_at", -1)
        clients = await cursor.to_list(length=limit)
        total = await mongo.clients.count_documents(query)
        result = [ClientOut(**normalize_id(c.copy())).model_dump(by_alias=True) for c in clients]

        return {
            "status": 200,
            "success": True,
            "message": f"Found {len(result)} clients",
            "data": {"items": result, "total": total, "skip": skip, "limit": limit}
        }

    # ─── Update ──────────────────────────────────────────────
    @staticmethod
    async def update_client(client_id: str, data: ClientUpdate, current_user: str) -> Dict:
        doc = await mongo.clients.find_one({"_id": ObjectId(client_id)})
        if not doc:
            raise HTTPException(404, "Client not found")
        if doc.get("owner_id") != current_user:
            raise HTTPException(403, "Access denied")

        update_dict = data.model_dump(exclude_unset=True)
        if not update_dict:
            raise HTTPException(400, "No fields to update")

        # Re-geocode if address updated
        if "address" in update_dict and update_dict["address"]:
            new_location = await geo_service.get_coordinates(update_dict["address"])
            if new_location:
                update_dict["location"] = new_location
                # ✅ Also update flat lat/lng
                coords = new_location.get("coordinates", [])
                if len(coords) == 2:
                    update_dict["lng"] = coords[0]
                    update_dict["lat"] = coords[1]

        if "location" in update_dict and update_dict["location"]:
            update_dict["location"] = (
                update_dict["location"].model_dump()
                if hasattr(update_dict["location"], "model_dump")
                else update_dict["location"]
            )

        if "website" in update_dict:
            update_dict["has_website"] = bool(update_dict["website"])

        update_dict["updated_at"] = datetime.utcnow()

        await mongo.clients.update_one(
            {"_id": ObjectId(client_id)},
            {"$set": update_dict}
        )

        updated = await mongo.clients.find_one({"_id": ObjectId(client_id)})
        return {
            "status": 200,
            "success": True,
            "message": "Client updated successfully",
            "data": ClientOut(**normalize_id(updated.copy())).model_dump(by_alias=True)
        }

    # ─── Delete ──────────────────────────────────────────────
    @staticmethod
    async def delete_client(client_id: str, current_user: str) -> Dict:
        doc = await mongo.clients.find_one({"_id": ObjectId(client_id)})
        if not doc:
            raise HTTPException(404, "Client not found")
        if doc.get("owner_id") != current_user:
            raise HTTPException(403, "Access denied")

        await mongo.clients.delete_one({"_id": ObjectId(client_id)})

        return {"status": 200, "success": True, "message": "Client deleted successfully"}

    # ─── Nearby Search ───────────────────────────────────────
    @staticmethod
    async def search_nearby(
        lat: float,
        lng: float,
        radius_km: float = 10,
        category: Optional[str] = None,
        has_website: Optional[bool] = None,
        current_user: str = None
    ) -> Dict:
        query = {
            "owner_id": current_user,
            "location": {
                "$near": {
                    "$geometry": {
                        "type": "Point",
                        "coordinates": [lng, lat]
                    },
                    "$maxDistance": radius_km * 1000
                }
            }
        }
        if category:
            query["category"] = category
        if has_website is not None:
            query["has_website"] = has_website

        cursor = mongo.clients.find(query).limit(50)
        clients = await cursor.to_list(length=50)
        result = [ClientOut(**normalize_id(c.copy())).model_dump(by_alias=True) for c in clients]

        return {
            "status": 200,
            "success": True,
            "message": f"Found {len(result)} clients within {radius_km}km",
            "data": {"items": result, "total": len(result)}
        }

    # ─── Text Search ─────────────────────────────────────────
    @staticmethod
    async def search_clients(q: str, current_user: str) -> Dict:
        query = {
            "owner_id": current_user,
            "$or": [
                {"name":    {"$regex": q, "$options": "i"}},
                {"company": {"$regex": q, "$options": "i"}},
                {"email":   {"$regex": q, "$options": "i"}},
                {"tags":    {"$regex": q, "$options": "i"}},
                {"phone":   {"$regex": q, "$options": "i"}},
                {"address": {"$regex": q, "$options": "i"}},
            ]
        }

        cursor = mongo.clients.find(query).limit(20)
        clients = await cursor.to_list(length=20)
        result = [ClientOut(**normalize_id(c.copy())).model_dump(by_alias=True) for c in clients]

        return {
            "status": 200,
            "success": True,
            "message": f"Found {len(result)} clients for '{q}'",
            "data": {"items": result, "total": len(result)}
        }
