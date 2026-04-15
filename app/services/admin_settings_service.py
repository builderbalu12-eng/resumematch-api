"""
admin_settings_service.py
Reads/writes global admin settings stored in MongoDB admin_settings collection.
Currently used for: default signup credits, app branding config.
"""

from app.services.mongo import mongo

DEFAULT_SIGNUP_CREDITS = 150.0

DEFAULT_APP_CONFIG = {
    "app_name": "LandYourJob",
    "support_email": "zenlead.info@gmail.com",
    "logo_url": "/logo/lo9o.png",
    "social_links": {
        "twitter": "",
        "linkedin": "",
        "github": "",
        "facebook": "",
        "instagram": "",
        "youtube": "",
    },
    "collaborators": [],  # [{name, role, image_url}]
}


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


async def get_app_config() -> dict:
    doc = await mongo.admin_settings.find_one({"key": "app_config"})
    if doc and isinstance(doc.get("value"), dict):
        # Deep merge with defaults so new keys are always present
        config = dict(DEFAULT_APP_CONFIG)
        stored = doc["value"]
        config.update({k: v for k, v in stored.items() if k in DEFAULT_APP_CONFIG})
        # Merge nested social_links
        if "social_links" in stored and isinstance(stored["social_links"], dict):
            config["social_links"] = {**DEFAULT_APP_CONFIG["social_links"], **stored["social_links"]}
        return config
    return dict(DEFAULT_APP_CONFIG)


async def set_app_config(updates: dict) -> dict:
    current = await get_app_config()
    # Deep merge social_links if provided
    if "social_links" in updates and isinstance(updates["social_links"], dict):
        current["social_links"] = {**current["social_links"], **updates["social_links"]}
        updates = {k: v for k, v in updates.items() if k != "social_links"}
    current.update(updates)
    await mongo.admin_settings.update_one(
        {"key": "app_config"},
        {"$set": {"key": "app_config", "value": current}},
        upsert=True,
    )
    return current
