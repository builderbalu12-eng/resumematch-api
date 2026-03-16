from app.services.telegram_service import telegram_service
from app.services.telegram.message_builder import message_builder
from app.services.mongo import mongo
from app.services.lead_finder import lead_finder
from app.services.credits_service import CreditsService

DEFAULT_LIMIT = 10

async def handle_find_leads(chat_id: str, text: str):
    user = await mongo.users.find_one({"telegram_chat_id": chat_id})
    if not user:
        await telegram_service.send_message(chat_id, message_builder.not_linked())
        return

    parts = text.strip().split()
    if len(parts) < 3:
        await telegram_service.send_message(
            chat_id,
            "⚠️ <b>Usage:</b> /findleads &lt;city&gt; &lt;category&gt;\n"
            "<i>Example: /findleads delhi jeweler</i>"
        )
        return

    city     = parts[1].lower()
    category = parts[2].lower()
    owner_id = str(user["_id"])

    credits_needed = DEFAULT_LIMIT * 2
    if user.get("credits", 0) < credits_needed:
        await telegram_service.send_message(
            chat_id,
            message_builder.insufficient_credits(credits_needed, int(user.get("credits", 0)))
        )
        return

    await telegram_service.send_message(
        chat_id,
        f"🔍 Searching <b>{category}</b> in <b>{city}</b>...\n⏳ Please wait 30-60 seconds."
    )

    saved = await lead_finder.find_and_save_leads(
        city=city, category=category, radius_km=5,
        owner_id=owner_id, mongo=mongo, limit=DEFAULT_LIMIT
    )

    actual_credits = len(saved) * 2
    if actual_credits > 0:
        await CreditsService.deduct_credits(user_id=owner_id, amount=float(actual_credits))

    await telegram_service.send_message(
        chat_id,
        message_builder.find_leads_result(saved, city, category, actual_credits)
    )


async def handle_my_leads(chat_id: str, text: str):
    user = await mongo.users.find_one({"telegram_chat_id": chat_id})
    if not user:
        await telegram_service.send_message(chat_id, message_builder.not_linked())
        return

    owner_id = str(user["_id"])
    parts    = text.strip().split()
    category = parts[1].lower() if len(parts) > 1 else None

    query = {"owner_id": owner_id}
    if category:
        query["category"] = category

    cursor = mongo.clients.find(query).sort("created_at", -1).limit(10)
    leads  = await cursor.to_list(length=10)
    total  = await mongo.clients.count_documents({"owner_id": owner_id})

    await telegram_service.send_message(
        chat_id,
        message_builder.my_leads_result(leads, total, category)
    )
