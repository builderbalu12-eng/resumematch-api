from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings


class MongoService:

    def __init__(self):
        self.client = None
        self.db     = None

    async def connect(self):
        try:
            self.client = AsyncIOMotorClient(settings.mongodb_url)
            self.db     = self.client[settings.mongodb_db_name]

            await self.client.admin.command('ping')
            print("MongoDB Atlas connected successfully")

            # ── Clients indexes ───────────────────────────
            await self.db.clients.create_index([("location", "2dsphere")])
            await self.db.clients.create_index([("owner_id", 1)])
            await self.db.clients.create_index([
                ("name", "text"), ("company", "text"),
                ("email", "text"), ("tags", "text")
            ])
            print("✅ Client indexes created")

            # ── Credits indexes ───────────────────────────
            await self.db.credits_log.create_index([("user_id", 1), ("created_at", -1)])
            await self.db.credits_on_features.create_index("feature", unique=True)
            print("✅ Credits indexes created")

            # ── Telegram bot: conversation state + job alerts ─────
            await self.db.telegram_conversations.create_index(
                [("chat_id", 1)], unique=True
            )
            await self.db.telegram_conversations.create_index(
                [("updated_at", 1)], expireAfterSeconds=7 * 24 * 3600
            )
            await self.db.job_alert_subscriptions.create_index(
                [("user_id", 1)], unique=True
            )
            await self.db.job_alert_subscriptions.create_index(
                [("is_active", 1), ("next_run_at", 1)]
            )
            print("✅ Telegram bot indexes created")

            # ── Chat sessions ─────────────────────────────
            await self.db.chat_sessions.create_index([("user_id", 1), ("session_id", 1)])
            await self.db.chat_sessions.create_index([("user_id", 1), ("updated_at", -1)])
            print("✅ Chat sessions indexes created")

        except Exception as e:
            print(f"MongoDB connection failed: {str(e)}")
            raise

    async def close(self):
        if self.client:
            self.client.close()

    @property
    def users(self):
        return self.db.users

    @property
    def resumes(self):
        return self.db.resumes

    @property
    def applications(self):
        return self.db.applications

    @property
    def resume_templates(self):
        return self.db.resume_templates

    @property
    def resume_content_schemas(self):
        return self.db.resume_content_schemas

    @property
    def user_resumes(self):
        return self.db.user_resumes

    @property
    def plans(self):
        return self.db.plans

    @property
    def subscriptions(self):
        return self.db.subscriptions

    @property
    def coupons(self):
        return self.db.coupons

    @property
    def payment_logs(self):
        return self.db.payment_logs

    @property
    def invoices(self):
        return self.db.invoices

    @property
    def openclaw_sessions(self):
        return self.db.openclaw_sessions

    @property
    def incoming_resumes(self):
        return self.db.incoming_resumes

    @property
    def listed_jobs(self):
        return self.db.listed_jobs

    @property
    def job_lists(self):
        return self.db.job_lists

    @property
    def billing_history(self):
        return self.db.billing_history

    @property
    def clients(self):
        return self.db.clients

    @property
    def credits_on_features(self):
        return self.db.credits_on_features

    @property
    def credits_log(self):                    # ✅ added
        return self.db.credits_log

    @property
    def telegram_conversations(self):
        return self.db.telegram_conversations

    @property
    def job_alert_subscriptions(self):
        return self.db.job_alert_subscriptions

    @property
    def chat_sessions(self):
        return self.db.chat_sessions

    @property
    def password_reset_tokens(self):
        return self.db.password_reset_tokens

    @property
    def coupon_usage_log(self):
        return self.db.coupon_usage_log

    @property
    def admin_settings(self):
        return self.db.admin_settings

    @property
    def daily_job_feed(self):
        return self.db.daily_job_feed

    @property
    def rapidapi_usage_log(self):
        return self.db.rapidapi_usage_log

    @property
    def job_evaluations(self):
        return self.db.job_evaluations

    @property
    def star_stories(self):
        return self.db.star_stories


mongo = MongoService()
