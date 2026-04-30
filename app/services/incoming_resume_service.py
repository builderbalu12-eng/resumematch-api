# app/services/incoming_resume_service.py
from app.services.mongo import mongo
from datetime import datetime
from typing import Dict, Optional


class IncomingResumeService:
    @staticmethod
    async def save_or_update(
        user_id: str,
        raw_input: str,
        extracted_data: Dict
    ) -> None:
        now = datetime.utcnow()

        await mongo.incoming_resumes.update_one(  # ← use the new property
            {"user_id": user_id},
            {
                "$set": {
                    "raw_input": raw_input,
                    "extracted_data": extracted_data,
                    "updated_at": now
                },
                "$setOnInsert": {
                    "created_at": now
                }
            },
            upsert=True
        )

    @staticmethod
    async def get_latest(user_id: str) -> Optional[Dict]:
        return await mongo.incoming_resumes.find_one(  # ← same property
            {"user_id": user_id},
            sort=[("updated_at", -1)]
        )

    @staticmethod
    async def set_master_text(user_id: str, raw_text: str) -> None:
        now = datetime.utcnow()
        await mongo.incoming_resumes.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "master_resume_text": raw_text,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

    @staticmethod
    async def get_master_text(user_id: str) -> Optional[str]:
        doc = await mongo.incoming_resumes.find_one(
            {"user_id": user_id},
            {"master_resume_text": 1},
        )
        return doc.get("master_resume_text") if doc else None