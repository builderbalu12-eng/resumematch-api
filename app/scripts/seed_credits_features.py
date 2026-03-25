from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings
import asyncio


FEATURES = [
    {
        "feature":           "find_leads",
        "display_name":      "Find Leads",
        "credits_per_unit":  2,
        "unit":              "per lead",
        "description":       "Credits charged per lead found via Google Maps",
        "is_active":         True,
    },
    {
        "feature":           "export_leads",
        "display_name":      "Export Leads (CSV)",
        "credits_per_unit":  5,
        "unit":              "per export",
        "description":       "Credits charged per CSV export",
        "is_active":         True,
    },
    {
        "feature":           "ai_outreach",
        "display_name":      "AI Outreach Message",
        "credits_per_unit":  3,
        "unit":              "per message",
        "description":       "Credits charged per AI-generated outreach message",
        "is_active":         True,
    },
    {
        "feature":           "email_send",
        "display_name":      "Send Email to Lead",
        "credits_per_unit":  1,
        "unit":              "per email",
        "description":       "Credits charged per email sent to a lead",
        "is_active":         True,
    },
]


async def seed():
    client = AsyncIOMotorClient(settings.mongodb_url)
    db     = client[settings.mongodb_db_name]

    for feature in FEATURES:
        existing = await db.credits_on_features.find_one({"feature": feature["feature"]})
        if not existing:
            await db.credits_on_features.insert_one({
                **feature,
                "created_at": datetime.now(datetime.UTC),
                "updated_at": datetime.now(datetime.UTC),
            })
            print(f"✅ Inserted: {feature['feature']}")
        else:
            print(f"⏭️  Already exists: {feature['feature']}")

    print("✅ Seeding complete!")
    client.close()


if __name__ == "__main__":
    asyncio.run(seed())
