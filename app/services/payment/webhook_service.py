# app/services/payment/webhook_service.py
import json
from datetime import datetime
from typing import Dict, Any

from fastapi import HTTPException

from app.services.mongo import mongo
from app.services.credits_service import CreditsService
from app.services.payment.razorpay_service import razorpay_service


class WebhookService:

    @staticmethod
    async def handle_razorpay_webhook(payload: bytes, signature: str | None) -> Dict[str, str]:
        if not signature:
            raise HTTPException(400, "Missing X-Razorpay-Signature header")

        if not razorpay_service.verify_webhook(payload, signature):
            raise HTTPException(400, "Invalid webhook signature")

        try:
            event = json.loads(payload.decode('utf-8'))
        except Exception as e:
            raise HTTPException(400, f"Invalid payload: {str(e)}")

        event_type = event.get("event")

        handled = False

        if event_type == "payment.captured":
            await WebhookService._handle_one_time_payment(event)
            handled = True

        elif event_type in ("subscription.activated", "subscription.charged"):
            await WebhookService._handle_subscription_charge(event)
            handled = True

        # You can add more later: subscription.cancelled, invoice.paid, payment.failed, etc.

        if not handled:
            # Log unknown event (in production use structured logger)
            print(f"Unhandled Razorpay event: {event_type}")

        return {"status": "received"}

    @staticmethod
    async def _handle_one_time_payment(event: Dict[str, Any]):
        payment = event["payload"]["payment"]["entity"]
        order_id = payment.get("order_id")
        if not order_id:
            return

        try:
            order = razorpay_service.client.order.fetch(order_id)
        except Exception as e:
            print(f"Cannot fetch order {order_id}: {e}")
            return

        notes = order.get("notes", {})
        credits_str = notes.get("credits", "0")
        user_id = notes.get("user_id")

        try:
            credits = float(credits_str)
        except (ValueError, TypeError):
            credits = 0

        if credits <= 0 or not user_id:
            print(f"Invalid credits ({credits}) or user_id ({user_id}) in order {order_id}")
            return

        # Add credits + log
        await CreditsService.add_credits(
            user_id=user_id,
            credits=credits,
            transaction_id=payment["id"],
            amount_paid=payment["amount"] / 100,
            currency=payment["currency"]
        )

    @staticmethod
    async def _handle_subscription_charge(event: Dict[str, Any]):
        sub = event["payload"]["subscription"]["entity"]
        razorpay_sub_id = sub["id"]

        sub_doc = await mongo.subscriptions.find_one({"razorpay_subscription_id": razorpay_sub_id})
        if not sub_doc:
            print(f"Subscription {razorpay_sub_id} not found in DB")
            return

        plan_doc = await mongo.plans.find_one({"razorpay_plan_id": sub.get("plan_id")})
        if not plan_doc:
            print(f"Plan for subscription {razorpay_sub_id} not found")
            return

        credits_per_cycle = plan_doc.get("credits_per_cycle", 0)
        if credits_per_cycle <= 0:
            return

        amount_paid = sub.get("charge_amount", 0) / 100 if "charge_amount" in sub else 0
        currency = sub.get("currency", "INR")
        transaction_id = sub.get("latest_charge") or sub["id"]

        await CreditsService.add_credits(
            user_id=sub_doc["user_id"],
            credits=credits_per_cycle,
            transaction_id=transaction_id,
            amount_paid=amount_paid,
            currency=currency
        )

        # Update subscription document status
        await mongo.subscriptions.update_one(
            {"_id": sub_doc["_id"]},
            {"$set": {
                "status": sub["status"],
                "updated_at": datetime.utcnow()
            }}
        )