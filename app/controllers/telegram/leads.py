from app.services.telegram_service import telegram_service
from app.services.telegram.message_builder import message_builder
from app.services.mongo import mongo
from app.services.lead_finder import lead_finder, ALL_CATEGORIES
from app.services.credits_service import CreditsService


DEFAULT_LIMIT = 10


async def _get_saved_cities(owner_id: str) -> list:
    return await mongo.clients.distinct("location.city", {"owner_id": owner_id})


async def _get_saved_categories(owner_id: str) -> list:
    return await mongo.clients.distinct("category", {"owner_id": owner_id})


async def handle_find_leads(chat_id: str, text: str):
    user = await mongo.users.find_one({"telegram_chat_id": chat_id})
    if not user:
        await telegram_service.send_message(chat_id, message_builder.not_linked())
        return

    parts = text.strip().split()
    if len(parts) < 3:
        await telegram_service.send_message(
            chat_id,
            "⚠️ <b>Usage:</b> /findleads &lt;city&gt; &lt;category&gt; [radius_km]\n"
            "<i>Example: /findleads delhi bakery</i>\n"
            "<i>With radius: /findleads delhi bakery 10</i>\n\n"
            "📍 /listallcities — See saved cities\n"
            "📂 /listallcategories — See all categories"
        )
        return

    city      = parts[1].lower()
    category  = parts[2].lower()
    radius_km = float(parts[3]) if len(parts) > 3 else 5
    owner_id  = str(user["_id"])

    # ── Validate category ─────────────────────────────
    if category != "all" and category not in ALL_CATEGORIES:
        cats = ", ".join(ALL_CATEGORIES)
        await telegram_service.send_message(
            chat_id,
            f"❌ <b>Unknown category:</b> <i>{category}</i>\n\n"
            f"📂 Valid categories:\n<code>{cats}</code>\n\n"
            f"Or type /listallcategories"
        )
        return

    # ── Fetch cost dynamically from DB ────────────────
    cost_per_lead  = await CreditsService.get_feature_cost("find_leads")
    credits_needed = DEFAULT_LIMIT * cost_per_lead

    if user.get("credits", 0) < credits_needed:
        await telegram_service.send_message(
            chat_id,
            message_builder.insufficient_credits(int(credits_needed), int(user.get("credits", 0)))
        )
        return

    await telegram_service.send_message(
        chat_id,
        f"🔍 Searching <b>{category}</b> in <b>{city}</b> (radius: {radius_km}km)...\n"
        f"⏳ Please wait 30-60 seconds."
    )

    saved = await lead_finder.find_and_save_leads(
        city=city, category=category, radius_km=radius_km,
        owner_id=owner_id, mongo=mongo, limit=DEFAULT_LIMIT
    )

    # ── Deduct + log ──────────────────────────────────
    actual_credits = len(saved) * cost_per_lead
    if actual_credits > 0:
        await CreditsService.deduct_credits(user_id=owner_id, amount=float(actual_credits))
        await CreditsService.log_deduction(
            user_id=owner_id,
            amount=float(actual_credits),
            feature="find_leads",
            function_name="handle_find_leads",
            description=f"Found {len(saved)} leads in {city} [{category}]"
        )

    if not saved:
        await telegram_service.send_message(
            chat_id,
            f"😕 <b>No new leads</b> for <b>{category}</b> in <b>{city}</b>.\n\n"
            f"📋 View already saved:\n"
            f"<code>/myleads {category}</code>\n\n"
            f"💡 <b>Try a bigger radius:</b>\n"
            f"<code>/findleads {city} {category} 10</code> — 10km\n"
            f"<code>/findleads {city} {category} 15</code> — 15km\n"
            f"<code>/findleads {city} {category} 20</code> — 20km"
        )
        return

    await telegram_service.send_message(
        chat_id,
        message_builder.find_leads_result(saved, city, category, int(actual_credits))
    )


async def handle_my_leads(chat_id: str, text: str):
    user = await mongo.users.find_one({"telegram_chat_id": chat_id})
    if not user:
        await telegram_service.send_message(chat_id, message_builder.not_linked())
        return

    owner_id = str(user["_id"])
    parts    = text.strip().split()

    # /myleads          → all,    page 1
    # /myleads 2        → all,    page 2
    # /myleads bakery   → bakery, page 1
    # /myleads bakery 2 → bakery, page 2
    category = None
    page     = 1

    if len(parts) == 2:
        if parts[1].isdigit():
            page = int(parts[1])
        else:
            category = parts[1].lower()

    elif len(parts) >= 3:
        category = parts[1].lower()
        page     = int(parts[2]) if parts[2].isdigit() else 1

    skip  = (page - 1) * 10
    query = {"owner_id": owner_id}
    if category:
        query["category"] = category

    cursor = mongo.clients.find(query).sort("created_at", -1).skip(skip).limit(10)
    leads  = await cursor.to_list(length=10)
    total  = await mongo.clients.count_documents(query)
    pages  = (total + 9) // 10

    await telegram_service.send_message(
        chat_id,
        message_builder.my_leads_result(leads, total, category, page, pages)
    )


async def handle_list_cities(chat_id: str):
    user = await mongo.users.find_one({"telegram_chat_id": chat_id})
    if not user:
        await telegram_service.send_message(chat_id, message_builder.not_linked())
        return

    owner_id = str(user["_id"])
    cities   = await mongo.clients.distinct("location.city", {"owner_id": owner_id})

    if not cities:
        await telegram_service.send_message(
            chat_id,
            "📍 No cities saved yet.\nUse /findleads to start finding leads!"
        )
        return

    city_list = "\n".join([f"• {c}" for c in sorted(cities) if c])
    await telegram_service.send_message(
        chat_id,
        f"📍 <b>Cities with saved leads:</b>\n\n{city_list}"
    )


async def handle_list_categories(chat_id: str):
    user = await mongo.users.find_one({"telegram_chat_id": chat_id})
    if not user:
        await telegram_service.send_message(chat_id, message_builder.not_linked())
        return

    owner_id   = str(user["_id"])
    saved_cats = await mongo.clients.distinct("category", {"owner_id": owner_id})
    all_cats   = ALL_CATEGORIES

    lines = ["📂 <b>All Supported Categories:</b>\n"]
    for cat in sorted(all_cats):
        tag = "✅" if cat in saved_cats else "🔍"
        lines.append(f"{tag} {cat}")

    lines.append("\n✅ = already have leads | 🔍 = not searched yet")

    await telegram_service.send_message(chat_id, "\n".join(lines))
