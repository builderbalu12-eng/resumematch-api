from datetime import datetime, timezone
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
    {
        "feature":           "extract_resume",
        "display_name":      "Upload / Parse Resume",
        "credits_per_unit":  1,
        "unit":              "per upload",
        "description":       "Credits charged per resume upload and extraction",
        "is_active":         True,
    },
    {
        "feature":           "tailor_resume",
        "display_name":      "Tailor Resume",
        "credits_per_unit":  2,
        "unit":              "per tailor",
        "description":       "Credits charged per AI-tailored resume version",
        "is_active":         True,
    },
    {
        "feature":           "ats_score",
        "display_name":      "ATS Score Check",
        "credits_per_unit":  1,
        "unit":              "per check",
        "description":       "Credits charged per ATS compatibility check",
        "is_active":         True,
    },
    {
        "feature":           "analyze_resume",
        "display_name":      "Resume Analysis",
        "credits_per_unit":  1,
        "unit":              "per analysis",
        "description":       "Credits charged per resume-job match analysis",
        "is_active":         True,
    },
    {
        "feature":           "parse_job",
        "display_name":      "Parse Job Description",
        "credits_per_unit":  1,
        "unit":              "per parse",
        "description":       "Credits charged per job description parse",
        "is_active":         True,
    },
    {
        "feature":           "cover_letter",
        "display_name":      "Cover Letter Generation",
        "credits_per_unit":  3,
        "unit":              "per letter",
        "description":       "Credits charged per AI-generated cover letter",
        "is_active":         True,
    },
    {
        "feature":           "check_completeness",
        "display_name":      "Completeness Check",
        "credits_per_unit":  1,
        "unit":              "per check",
        "description":       "Credits charged per resume completeness check",
        "is_active":         True,
    },
    {
        "feature":           "create_resume",
        "display_name":      "Create New Resume",
        "credits_per_unit":  1,
        "unit":              "per resume",
        "description":       "Credits charged per new resume created",
        "is_active":         True,
    },
    {
        "feature":           "find_jobs",
        "display_name":      "Find Jobs",
        "credits_per_unit":  1,
        "unit":              "per search",
        "description":       "Credits charged per AI job search",
        "is_active":         True,
    },
    {
        "feature":           "ai_chat",
        "display_name":      "AI Chat Message",
        "credits_per_unit":  1,
        "unit":              "per message",
        "description":       "Credits charged per AI chat message sent",
        "is_active":         True,
    },
    {
        "feature":           "keyword_distribution",
        "display_name":      "Keyword Match Distribution",
        "credits_per_unit":  1,
        "unit":              "per analysis",
        "description":       "Credits charged per keyword distribution categorization for the Optimizer pie chart",
        "is_active":         True,
    },
    {
        "feature":           "skills_roadmap",
        "display_name":      "Skills Learning Roadmap",
        "credits_per_unit":  1,
        "unit":              "per roadmap",
        "description":       "Credits charged per skills-roadmap generation",
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
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            })
            print(f"✅ Inserted: {feature['feature']}")
        else:
            # Fill in any missing metadata fields without overriding credits_per_unit
            update_fields = {
                k: v for k, v in feature.items()
                if k not in ("credits_per_unit", "feature", "is_active")
                and not existing.get(k)
            }
            if update_fields:
                update_fields["updated_at"] = datetime.now(timezone.utc)
                await db.credits_on_features.update_one(
                    {"feature": feature["feature"]},
                    {"$set": update_fields},
                )
                print(f"🔄 Updated metadata: {feature['feature']}")
            else:
                print(f"⏭️  Already exists: {feature['feature']}")

    print("✅ Seeding complete!")
    client.close()


if __name__ == "__main__":
    asyncio.run(seed())
