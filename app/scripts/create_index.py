import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGODB_URL")          # ← FIXED
DB_NAME = os.getenv("MONGODB_DB_NAME")        # ← FIXED

async def create_indexes():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]

    print(f"🔧 Connecting to: {DB_NAME}")
    print("🔧 Creating indexes...")

    # ── Subscriptions ──────────────────────────────
    await db.subscriptions.create_index("user_id")
    print("✅ subscriptions.user_id")

    await db.subscriptions.create_index("razorpay_subscription_id")
    print("✅ subscriptions.razorpay_subscription_id")

    # ── Billing History ────────────────────────────
    await db.billing_history.create_index("user_id")
    print("✅ billing_history.user_id")

    await db.billing_history.create_index("payment_id", unique=True)
    print("✅ billing_history.payment_id (unique)")

    # ── Payment Logs ───────────────────────────────
    await db.payment_logs.create_index("transaction_id", unique=True)
    print("✅ payment_logs.transaction_id (unique)")

    # ── Coupons ────────────────────────────────────
    await db.coupons.create_index("code", unique=True)
    print("✅ coupons.code (unique)")

    # ── Plans ──────────────────────────────────────
    await db.plans.create_index("amount")
    print("✅ plans.amount")

    print("\n🎉 All indexes created successfully!")
    client.close()


if __name__ == "__main__":
    asyncio.run(create_indexes())
