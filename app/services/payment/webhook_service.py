import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from fastapi import HTTPException
from app.services.mongo import mongo
from app.services.payment.razorpay_service import razorpay_service
from app.services.credits_service import CreditsService
from app.config import settings
from bson import ObjectId


class WebhookService:

    @staticmethod
    async def handle_razorpay_webhook(payload: bytes, signature: str | None) -> Dict:

        # ✅ DEBUG
        print(f"🔔 Webhook hit! Signature: {signature}")
        print(f"🔔 Payload type: {type(payload)}")
        print(f"🔔 Secret in settings: '{settings.razorpay_webhook_secret}'")

        try:
            if not signature:
                raise HTTPException(400, "Missing X-Razorpay-Signature header")

            if not razorpay_service.verify_webhook(payload, signature):
                raise HTTPException(400, "Invalid webhook signature")

            try:
                event = json.loads(payload.decode("utf-8"))
            except Exception as e:
                raise HTTPException(400, f"Invalid payload: {e}")

            event_type = event.get("event")
            print(f"📦 Razorpay webhook received: {event_type}")

            handlers = {
                "subscription.activated": WebhookService._on_subscription_activated,
                "subscription.charged":   WebhookService._on_subscription_charged,
                "subscription.cancelled": WebhookService._on_subscription_cancelled,
                "payment.captured":       WebhookService._on_payment_captured,
                "payment.failed":         WebhookService._on_payment_failed,
                "invoice.paid":           WebhookService._on_invoice_paid,
            }

            handler = handlers.get(event_type)
            if handler:
                await handler(event)
            else:
                print(f"⚠️  Unhandled Razorpay event: {event_type}")

            return {"status": "received"}

        except HTTPException:
            raise
        except Exception as e:
            import traceback
            print(f"🔴 WEBHOOK CRASH: {e}")
            print(traceback.format_exc())
            raise HTTPException(500, f"Webhook error: {str(e)}")


    # ─── 1. Subscription Activated ────────────────────────────
    @staticmethod
    async def _on_subscription_activated(event: Dict[str, Any]):
        sub = event["payload"]["subscription"]["entity"]
        razorpay_sub_id = sub["id"]

        doc = await mongo.subscriptions.find_one({"razorpay_subscription_id": razorpay_sub_id})
        if not doc:
            print(f"⚠️  Subscription {razorpay_sub_id} not found in DB")
            return

        await mongo.subscriptions.update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "status": "active",
                "start_date": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }}
        )

        await mongo.users.update_one(
            {"_id": ObjectId(doc["user_id"])},
            {"$set": {
                "active_plan": doc.get("plan_name", "Pro"),
                "updated_at": datetime.utcnow()
            }}
        )

        plan = await mongo.plans.find_one({"_id": ObjectId(doc["plan_id"])})
        if plan and plan.get("credits_per_cycle", 0) > 0:
            await CreditsService.add_credits(
                user_id=doc["user_id"],
                credits=plan["credits_per_cycle"],
                transaction_id=f"activated_{razorpay_sub_id}",
                amount_paid=doc.get("amount_paid", 0),
                currency=doc.get("currency", "INR")
            )
            print(f"✅ Added {plan['credits_per_cycle']} credits on activation")

        print(f"✅ Subscription activated: {razorpay_sub_id}")


    # ─── 2. Subscription Charged (Renewal) ───────────────────
    @staticmethod
    async def _on_subscription_charged(event: Dict[str, Any]):
        sub = event["payload"]["subscription"]["entity"]
        payment = event["payload"].get("payment", {}).get("entity", {})
        razorpay_sub_id = sub["id"]

        doc = await mongo.subscriptions.find_one({"razorpay_subscription_id": razorpay_sub_id})
        if not doc:
            print(f"⚠️  Subscription {razorpay_sub_id} not found in DB")
            return

        billing_cycle = doc.get("billing_cycle", "monthly")
        renewal_date = datetime.utcnow() + (
            timedelta(days=365) if billing_cycle == "yearly" else timedelta(days=30)
        )
        amount_paid = payment.get("amount", 0) / 100
        payment_id = payment.get("id", razorpay_sub_id)

        await mongo.subscriptions.update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "status": "active",
                "renewal_date": renewal_date,
                "updated_at": datetime.utcnow()
            }}
        )

        plan = await mongo.plans.find_one({"_id": ObjectId(doc["plan_id"])})
        if plan and plan.get("credits_per_cycle", 0) > 0:
            await CreditsService.add_credits(
                user_id=doc["user_id"],
                credits=plan["credits_per_cycle"],
                transaction_id=payment_id,
                amount_paid=amount_paid,
                currency=payment.get("currency", "INR")
            )
            print(f"✅ Added {plan['credits_per_cycle']} credits on renewal")

        await WebhookService._write_billing_history(
            user_id=doc["user_id"],
            plan_id=doc.get("plan_id"),
            plan_name=doc.get("plan_name"),
            amount=amount_paid,
            currency=payment.get("currency", "INR"),
            payment_status="succeeded",
            payment_provider="razorpay",
            payment_id=payment_id,
            subscription_id=str(doc["_id"]),
            is_recurring=doc.get("is_recurring", True),
            renewal_date=renewal_date,
        )

        print(f"✅ Subscription charged: {razorpay_sub_id} ₹{amount_paid}")


    # ─── 3. Subscription Cancelled ───────────────────────────
    @staticmethod
    async def _on_subscription_cancelled(event: Dict[str, Any]):
        sub = event["payload"]["subscription"]["entity"]
        razorpay_sub_id = sub["id"]

        doc = await mongo.subscriptions.find_one({"razorpay_subscription_id": razorpay_sub_id})
        if not doc:
            return

        await mongo.subscriptions.update_one(
            {"_id": doc["_id"]},
            {"$set": {
                "status": "cancelled",
                "cancelled_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }}
        )

        other_active = await mongo.subscriptions.count_documents({
            "user_id": doc["user_id"],
            "status": "active",
            "_id": {"$ne": doc["_id"]}
        })

        if other_active == 0:
            await mongo.users.update_one(
                {"_id": ObjectId(doc["user_id"])},
                {"$set": {
                    "active_plan": "Free",
                    "updated_at": datetime.utcnow()
                }}
            )

        print(f"✅ Subscription cancelled: {razorpay_sub_id}")


    # ─── 4. One-time Payment Captured ────────────────────────
    @staticmethod
    async def _on_payment_captured(event: Dict[str, Any]):
        payment = event["payload"]["payment"]["entity"]
        order_id = payment.get("order_id")
        if not order_id:
            return

        try:
            order = razorpay_service.client.order.fetch(order_id)
        except Exception as e:
            print(f"⚠️  Cannot fetch order {order_id}: {e}")
            return

        notes = order.get("notes", {})

        # ✅ FIX: subscription payments have notes as [] not {}
        if isinstance(notes, list):
            notes = {}

        user_id = notes.get("user_id")
        plan_id = notes.get("plan_id")
        billing_cycle = notes.get("billing_cycle", "monthly")

        if not user_id:
            # This is a subscription payment — already handled by subscription.charged
            print(f"⚠️  No user_id in notes for order {order_id} — skipping (subscription payment)")
            return

        plan = None
        if plan_id:
            try:
                plan = await mongo.plans.find_one({"_id": ObjectId(plan_id)})
            except Exception:
                pass

        renewal_date = datetime.utcnow() + (
            timedelta(days=365) if billing_cycle == "yearly" else timedelta(days=30)
        )

        if plan and plan.get("credits_per_cycle", 0) > 0:
            await CreditsService.add_credits(
                user_id=user_id,
                credits=plan["credits_per_cycle"],
                transaction_id=payment["id"],
                amount_paid=payment["amount"] / 100,
                currency=payment["currency"]
            )
            print(f"✅ Added {plan['credits_per_cycle']} credits for one-time payment")

        await WebhookService._write_billing_history(
            user_id=user_id,
            plan_id=plan_id,
            plan_name=plan["plan_name"] if plan else None,
            amount=payment["amount"] / 100,
            currency=payment["currency"],
            payment_status="succeeded",
            payment_provider="razorpay",
            payment_id=payment["id"],
            subscription_id=None,
            is_recurring=False,
            renewal_date=renewal_date,
        )

        if plan:
            await mongo.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {
                    "active_plan": plan["plan_name"],
                    "updated_at": datetime.utcnow()
                }}
            )

        print(f"✅ One-time payment captured: {payment['id']} ₹{payment['amount'] / 100}")

        # ─── 5. Payment Failed ────────────────────────────────────
    @staticmethod
    async def _on_payment_failed(event: Dict[str, Any]):
        payment = event["payload"]["payment"]["entity"]
        user_id = payment.get("notes", {}).get("user_id")
        if not user_id:
            return

        await WebhookService._write_billing_history(
            user_id=user_id,
            plan_id=None,
            plan_name=None,
            amount=payment.get("amount", 0) / 100,
            currency=payment.get("currency", "INR"),
            payment_status="failed",
            payment_provider="razorpay",
            payment_id=payment["id"],
            subscription_id=None,
            is_recurring=False,
        )

        print(f"❌ Payment failed: {payment['id']}")

    # ─── 6. Invoice Paid ──────────────────────────────────────
    @staticmethod
    async def _on_invoice_paid(event: Dict[str, Any]):
        invoice = event["payload"]["invoice"]["entity"]
        razorpay_sub_id = invoice.get("subscription_id")
        if not razorpay_sub_id:
            return

        doc = await mongo.subscriptions.find_one({"razorpay_subscription_id": razorpay_sub_id})
        if not doc:
            return

        await mongo.billing_history.update_one(
            {
                "subscription_id": str(doc["_id"]),
                "payment_date": {
                    "$gte": datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                }
            },
            {"$set": {"invoice_url": invoice.get("short_url")}}
        )

        print(f"✅ Invoice url updated: {invoice['id']}")


    # ─── Helper: Write Billing History ───────────────────────
    @staticmethod
    async def _write_billing_history(
        user_id: str,
        plan_id: Optional[str],
        plan_name: Optional[str],
        amount: float,
        currency: str,
        payment_status: str,
        payment_provider: str,
        payment_id: str,
        subscription_id: Optional[str] = None,
        is_recurring: bool = True,
        invoice_url: Optional[str] = None,
        renewal_date: Optional[datetime] = None,
    ):
        # ✅ Prevent duplicate entries
        existing = await mongo.billing_history.find_one({"payment_id": payment_id})
        if existing:
            print(f"⚠️  Duplicate billing entry for {payment_id}, skipping")
            return

        active_count = await mongo.subscriptions.count_documents(
            {"user_id": user_id, "status": "active"}
        )

        await mongo.billing_history.insert_one({
            "_id": ObjectId(),
            "user_id": user_id,
            "plan_id": plan_id,
            "plan_name": plan_name,
            "amount": amount,
            "currency": currency,
            "payment_status": payment_status,
            "payment_provider": payment_provider,
            "payment_id": payment_id,
            "invoice_url": invoice_url,
            "subscription_id": subscription_id,
            "is_recurring": is_recurring,
            "is_parallel": active_count > 1,
            "renewal_date": renewal_date,
            "payment_date": datetime.utcnow(),
            "created_at": datetime.utcnow()
        })
