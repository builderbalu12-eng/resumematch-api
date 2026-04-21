import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from fastapi import HTTPException
from app.services.mongo import mongo
from app.services.payment.cashfree_service import verify_webhook_signature
from app.services.credits_service import CreditsService
from bson import ObjectId


class WebhookService:

    @staticmethod
    async def handle_cashfree_webhook(payload: bytes, signature: str | None, timestamp: str | None) -> Dict:
        print(f"🔔 Cashfree webhook hit — signature: {signature}, timestamp: {timestamp}")

        if not signature or not timestamp:
            raise HTTPException(400, "Missing x-webhook-signature or x-webhook-timestamp")

        if not verify_webhook_signature(payload, signature, timestamp):
            print("❌ Cashfree webhook signature verification failed")
            raise HTTPException(400, "Invalid webhook signature")

        try:
            event = json.loads(payload.decode("utf-8"))
        except Exception as e:
            raise HTTPException(400, f"Invalid payload: {e}")

        event_type = event.get("type")
        print(f"📦 Cashfree webhook received: {event_type}")

        handlers = {
            "PAYMENT_SUCCESS_WEBHOOK":      WebhookService._on_payment_success,
            "PAYMENT_FAILED_WEBHOOK":       WebhookService._on_payment_failed,
            "PAYMENT_USER_DROPPED_WEBHOOK": WebhookService._on_payment_dropped,
            "REFUND_STATUS_WEBHOOK":        WebhookService._on_refund,
        }

        handler = handlers.get(event_type)
        if handler:
            await handler(event)
        else:
            print(f"⚠️  Unhandled Cashfree event: {event_type}")

        return {"status": "received"}


    # ─── 1. Payment Success ───────────────────────────────────
    @staticmethod
    async def _on_payment_success(event: Dict[str, Any]):
        data = event.get("data", {})
        order = data.get("order", {})
        payment = data.get("payment", {})

        order_id = order.get("order_id")
        tags = order.get("order_tags") or {}

        # tags are stored as strings
        user_id = tags.get("user_id")
        plan_id = tags.get("plan_id")
        billing_cycle = tags.get("billing_cycle", "monthly")
        payment_id = str(payment.get("cf_payment_id", order_id))
        amount_paid = float(payment.get("payment_amount", order.get("order_amount", 0)))
        currency = payment.get("payment_currency", order.get("order_currency", "INR"))

        if not user_id:
            print(f"⚠️  No user_id in order_tags for order {order_id}")
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

        # Add credits
        if plan and plan.get("credits_per_cycle", 0) > 0:
            await CreditsService.add_credits(
                user_id=user_id,
                credits=plan["credits_per_cycle"],
                transaction_id=payment_id,
                amount_paid=amount_paid,
                currency=currency,
            )
            print(f"✅ Added {plan['credits_per_cycle']} credits for order {order_id}")

        # Activate plan on user
        if plan:
            await mongo.users.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"active_plan": plan["plan_name"], "updated_at": datetime.utcnow()}}
            )

            # Mark subscription active
            await mongo.subscriptions.update_one(
                {"user_id": user_id, "plan_id": plan_id, "status": {"$in": ["created", "pending"]}},
                {"$set": {
                    "status": "active",
                    "start_date": datetime.utcnow(),
                    "renewal_date": renewal_date,
                    "updated_at": datetime.utcnow(),
                }},
                upsert=False
            )

        await WebhookService._write_billing_history(
            user_id=user_id,
            plan_id=plan_id,
            plan_name=plan["plan_name"] if plan else None,
            amount=amount_paid,
            currency=currency,
            payment_status="succeeded",
            payment_provider="cashfree",
            payment_id=payment_id,
            is_recurring=billing_cycle in ("monthly", "yearly"),
            renewal_date=renewal_date,
        )

        print(f"✅ Payment success processed: {order_id} ₹{amount_paid}")


    # ─── 2. Payment Failed ────────────────────────────────────
    @staticmethod
    async def _on_payment_failed(event: Dict[str, Any]):
        data = event.get("data", {})
        order = data.get("order", {})
        payment = data.get("payment", {})

        order_id = order.get("order_id")
        tags = order.get("order_tags") or {}
        user_id = tags.get("user_id")
        payment_id = str(payment.get("cf_payment_id", order_id))
        amount = float(payment.get("payment_amount", 0))
        currency = payment.get("payment_currency", "INR")

        if not user_id:
            return

        await WebhookService._write_billing_history(
            user_id=user_id,
            plan_id=tags.get("plan_id"),
            plan_name=None,
            amount=amount,
            currency=currency,
            payment_status="failed",
            payment_provider="cashfree",
            payment_id=payment_id,
        )
        print(f"❌ Payment failed: {order_id}")


    # ─── 3. User Dropped ─────────────────────────────────────
    @staticmethod
    async def _on_payment_dropped(event: Dict[str, Any]):
        data = event.get("data", {})
        order = data.get("order", {})
        print(f"⚠️  User dropped payment for order {order.get('order_id')}")


    # ─── 4. Refund ───────────────────────────────────────────
    @staticmethod
    async def _on_refund(event: Dict[str, Any]):
        data = event.get("data", {})
        refund = data.get("refund", {})
        order_id = data.get("order", {}).get("order_id")
        refund_status = refund.get("refund_status")
        print(f"💰 Refund {refund_status} for order {order_id}")
        # TODO: if refund_status == "SUCCESS" → deduct credits if needed


    # ─── Helper ───────────────────────────────────────────────
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
            "created_at": datetime.utcnow(),
        })
