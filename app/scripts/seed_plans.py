"""
Seed subscription plans into MongoDB.

Usage:
    cd resumematch-api
    python -m app.scripts.seed_plans

What it does:
    1. Deletes ALL existing plans from the `plans` collection
    2. Creates Razorpay plans for each paid recurring plan (both monthly + yearly)
    3. Inserts 7 fresh plan documents:
         - Free (no billing cycle variant needed)
         - Starter Monthly / Starter Yearly
         - Pro Monthly / Pro Yearly
         - Business Monthly / Business Yearly
"""

import asyncio
from datetime import datetime, timezone
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
import razorpay

from app.config import settings


# Base plan definitions — monthly amount in INR
# Yearly amount = monthly × 10  (2 months free)
BASE_PLANS = [
    {
        "plan_name": "Free",
        "amount": 0.0,
        "is_recurring": False,
        "credits_per_cycle": 20,
        "description": "Get started with the basics — no credit card needed.",
        "points": [
            "20 credits per month",
            "2 resume tailors per month",
            "10 job searches per day",
            "AI career chat",
            "Find up to 10 leads",
        ],
        "billing_cycles": ["monthly"],  # Free has no yearly variant
    },
    {
        "plan_name": "Starter",
        "amount": 299.0,
        "is_recurring": True,
        "credits_per_cycle": 80,
        "description": "Perfect for active job seekers building their career.",
        "points": [
            "80 credits per month",
            "5 resume tailors per month",
            "Unlimited job matching",
            "AI career chat",
            "Find up to 40 leads",
        ],
        "billing_cycles": ["monthly", "yearly"],
    },
    {
        "plan_name": "Pro",
        "amount": 799.0,
        "is_recurring": True,
        "credits_per_cycle": 300,
        "description": "For professionals and freelancers who need more reach.",
        "points": [
            "300 credits per month",
            "Unlimited resume tailoring",
            "Unlimited job matching",
            "AI career chat",
            "Find up to 150 leads",
            "AI outreach messages (up to 100/month)",
            "Email to leads",
            "Telegram job alerts",
        ],
        "billing_cycles": ["monthly", "yearly"],
    },
    {
        "plan_name": "Business",
        "amount": 1499.0,
        "is_recurring": True,
        "credits_per_cycle": 700,
        "description": "Built for entrepreneurs and lead-gen heavy workflows.",
        "points": [
            "700 credits per month",
            "Unlimited resume tailoring",
            "Unlimited job matching",
            "AI career chat",
            "Find up to 350 leads",
            "AI outreach messages (up to 230/month)",
            "Email to leads",
            "CSV lead exports",
            "Telegram job alerts",
            "Priority support",
        ],
        "billing_cycles": ["monthly", "yearly"],
    },
]


async def seed():
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.mongodb_db_name]
    rp_client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))

    # 1. Wipe existing plans
    result = await db.plans.delete_many({})
    print(f"🗑️  Deleted {result.deleted_count} existing plan(s)")

    # 2. Create and insert new plans
    inserted = 0

    for plan in BASE_PLANS:
        for cycle in plan["billing_cycles"]:
            # Yearly amount = monthly × 10
            amount = plan["amount"] * 10 if cycle == "yearly" else plan["amount"]
            plan_name = f"{plan['plan_name']} {'(Yearly)' if cycle == 'yearly' else '(Monthly)'}" if plan["amount"] > 0 else plan["plan_name"]

            razorpay_plan_id = None

            if amount > 0 and plan["is_recurring"]:
                try:
                    rp_plan = rp_client.plan.create(data={
                        "period": cycle,       # "monthly" or "yearly"
                        "interval": 1,
                        "item": {
                            "name": plan_name,
                            "amount": int(amount * 100),  # paise
                            "currency": "INR",
                            "description": plan["description"],
                        }
                    })
                    razorpay_plan_id = rp_plan["id"]
                    print(f"✅ Razorpay plan created: {plan_name} → {razorpay_plan_id}")
                except Exception as e:
                    print(f"⚠️  Razorpay plan creation failed for {plan_name}: {e}")
                    print(f"   Inserting into MongoDB without razorpay_plan_id")

            doc = {
                "_id": ObjectId(),
                "plan_name": plan["plan_name"],   # keep base name (Starter, Pro, etc.)
                "amount": amount,
                "currency": "INR",
                "is_recurring": plan["is_recurring"],
                "billing_cycle": cycle,
                "credits_per_cycle": plan["credits_per_cycle"],
                "points": plan["points"],
                "description": plan["description"],
                "razorpay_plan_id": razorpay_plan_id,
                "is_active": True,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }

            await db.plans.insert_one(doc)
            inserted += 1
            label = f"₹{int(amount)}/{cycle}"
            print(f"✅ Inserted: {plan['plan_name']} {label}, {plan['credits_per_cycle']} credits")

    print(f"\n🎉 Done — {inserted} plans seeded successfully!")
    client.close()


if __name__ == "__main__":
    asyncio.run(seed())
