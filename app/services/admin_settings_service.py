"""
admin_settings_service.py
Reads/writes global admin settings stored in MongoDB admin_settings collection.
Currently used for: default signup credits.
"""

from app.services.mongo import mongo

DEFAULT_SIGNUP_CREDITS = 150.0


async def get_default_credits() -> float:
    doc = await mongo.admin_settings.find_one({"key": "signup_credits"})
    if doc:
        return float(doc.get("value", DEFAULT_SIGNUP_CREDITS))
    return DEFAULT_SIGNUP_CREDITS


async def set_default_credits(value: float) -> float:
    await mongo.admin_settings.update_one(
        {"key": "signup_credits"},
        {"$set": {"key": "signup_credits", "value": value}},
        upsert=True,
    )
    return value
