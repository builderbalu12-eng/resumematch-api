import asyncio
from app.services.mongo import mongo

async def fix():
    await mongo.connect()

    # Delete all leads with category "all" — they're incorrectly categorized
    result = await mongo.clients.delete_many({
        "owner_id": "698eee23a96223a7383d52b8",
        "category": "all"
    })
    print(f"Deleted {result.deleted_count} bad leads")

asyncio.run(fix())
