import razorpay
from fastapi import HTTPException
from app.config import settings
from datetime import datetime
from typing import Optional


class RazorpayService:
    def __init__(self):
        self.client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))

    def create_plan(self, data):
        try:
            return self.client.plan.create(data=data)
        except Exception as e:
            raise HTTPException(500, str(e))

    def create_subscription(self, data):
        try:
            return self.client.subscription.create(data=data)
        except Exception as e:
            raise HTTPException(500, str(e))

    def cancel_subscription(self, subscription_id):
        try:
            return self.client.subscription.cancel(subscription_id)
        except Exception as e:
            raise HTTPException(500, str(e))

    def fetch_subscription(self, subscription_id):
        try:
            return self.client.subscription.fetch(subscription_id)
        except Exception as e:
            raise HTTPException(500, str(e))

    def create_invoice(self, subscription_id, amount, description):
        try:
            data = {
                "subscription_id": subscription_id,
                "amount": int(amount * 100),
                "description": description
            }
            return self.client.invoice.create(data=data)
        except Exception as e:
            raise HTTPException(500, str(e))

    def verify_signature(self, payment_id, order_id, signature):
        try:
            self.client.utility.verify_payment_signature({
                "razorpay_payment_id": payment_id,
                "razorpay_order_id": order_id,
                "razorpay_signature": signature
            })
            return True
        except razorpay.errors.SignatureVerificationError:
            return False
        except Exception as e:
            raise HTTPException(500, str(e))

    def verify_webhook(self, payload, signature):
        try:
            # ✅ FIX: decode bytes to string before verification
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")

            self.client.utility.verify_webhook_signature(
                payload,
                signature,
                settings.razorpay_webhook_secret
            )
            return True
        except razorpay.errors.SignatureVerificationError:
            print(f"❌ Webhook signature verification failed")
            return False
        except Exception as e:
            print(f"🔴 verify_webhook error: {e}")
            raise HTTPException(500, str(e))

    def create_order(
        self,
        amount: float,
        currency: str,
        receipt: Optional[str] = None,
        user_id: Optional[str] = None,
        plan_id: Optional[str] = None,
        billing_cycle: Optional[str] = "monthly"
    ) -> dict:
        data = {
            "amount": int(amount * 100),
            "currency": currency.upper(),
            "receipt": receipt or f"receipt_{int(datetime.utcnow().timestamp())}",
            "payment_capture": 1,
            "notes": {
                "user_id": user_id or "unknown",
                "plan_id": plan_id or "",
                "billing_cycle": billing_cycle or "monthly"
            }
        }

        try:
            return self.client.order.create(data=data)
        except Exception as e:
            raise HTTPException(500, f"Razorpay order creation failed: {str(e)}")


razorpay_service = RazorpayService()
