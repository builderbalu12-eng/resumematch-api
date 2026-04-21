# TODO: Razorpay disabled — migrating to Cashfree
# Original Razorpay implementation commented out below.
# Replace this stub with cashfree_service.py when ready.

# import razorpay
# from fastapi import HTTPException
# from app.config import settings
# from datetime import datetime
# from typing import Optional
#
#
# class RazorpayService:
#     def __init__(self):
#         self.client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
#
#     def create_plan(self, data): ...
#     def create_subscription(self, data): ...
#     def cancel_subscription(self, subscription_id): ...
#     def fetch_subscription(self, subscription_id): ...
#     def create_invoice(self, subscription_id, amount, description): ...
#     def verify_signature(self, payment_id, order_id, signature): ...
#     def verify_webhook(self, payload, signature): ...
#     def create_order(self, amount, currency, receipt=None, user_id=None, plan_id=None, billing_cycle="monthly"): ...

from fastapi import HTTPException


class RazorpayService:
    """Stub — Razorpay disabled. Cashfree integration pending."""

    def _unavailable(self):
        raise HTTPException(503, "Payment gateway not configured. Cashfree integration coming soon.")

    def create_plan(self, data):
        self._unavailable()

    def create_subscription(self, data):
        self._unavailable()

    def cancel_subscription(self, subscription_id):
        self._unavailable()

    def fetch_subscription(self, subscription_id):
        self._unavailable()

    def create_invoice(self, subscription_id, amount, description):
        self._unavailable()

    def verify_signature(self, payment_id, order_id, signature):
        return False

    def verify_webhook(self, payload, signature):
        return False

    def create_order(self, amount, currency, receipt=None, user_id=None, plan_id=None, billing_cycle="monthly"):
        self._unavailable()


razorpay_service = RazorpayService()
