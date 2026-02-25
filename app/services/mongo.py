from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings


class MongoService:
    def __init__(self):
        self.client = None
        self.db = None

    async def connect(self):
        try:
            self.client = AsyncIOMotorClient(settings.mongodb_url)
            self.db = self.client[settings.mongodb_db_name]

            # Test connection
            await self.client.admin.command('ping')
            print("MongoDB Atlas connected successfully")
        except Exception as e:
            print(f"MongoDB connection failed: {str(e)}")
            raise  # let FastAPI know it failed

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


mongo = MongoService()