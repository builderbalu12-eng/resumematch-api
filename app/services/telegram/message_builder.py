# app/services/telegram/message_builder.py

from typing import Optional


class MessageBuilder:

    @staticmethod
    def not_linked() -> str:
        return (
            "❌ <b>No account linked.</b>\n"
            "Open the app → Profile → Connect Telegram."
        )

    @staticmethod
    def help() -> str:
        return """🤖 <b>LeadFinder Bot Commands:</b>

🔍 <b>LEADS</b>
/findleads &lt;city&gt; &lt;category&gt; [radius_km]
<i>Example: /findleads delhi jeweler</i>
<i>With radius: /findleads delhi jeweler 10</i>
Categories: restaurant, jeweler, salon, gym, clinic, clothing, bakery, hotel, realestate, carrepair, all

/myleads — View all leads
/myleads &lt;category&gt; — Filter by category
/myleads &lt;page&gt; — Go to page (e.g. /myleads 2)
/myleads &lt;category&gt; &lt;page&gt; — (e.g. /myleads gym 2)

📍 /listallcities — Cities with saved leads
📂 /listallcategories — All categories (✅ saved / 🔍 not yet)

💳 <b>ACCOUNT</b>
/credits — Credit balance
/status  — Account info

⚙️ <b>SETUP</b>
/start &lt;token&gt; — Link your account
/help — Show this message

━━━━━━━━━━━━━━━━━━
💡 Credit cost depends on your plan. Type /credits to check."""

    @staticmethod
    def credits(credits: float, plan: str, cost_per_lead: float = 0) -> str:
        cost_line = f"💡 Find Leads costs <b>{int(cost_per_lead)} credits</b> per lead." if cost_per_lead else ""
        return (
            f"💳 <b>Credits</b>\n\n"
            f"Balance: <b>{int(credits)} credits</b>\n"
            f"Plan: <b>{plan}</b>\n\n"
            f"{cost_line}"
        )

    @staticmethod
    def status(email: str, credits: float, plan: str) -> str:
        return (
            f"✅ <b>Account Info</b>\n\n"
            f"📧 Email: {email}\n"
            f"💳 Credits: {int(credits)}\n"
            f"📦 Plan: {plan}\n"
            f"🔗 Telegram: Connected ✅"
        )

    @staticmethod
    def find_leads_result(saved: list, city: str, category: str, credits_used: int) -> str:
        if not saved:
            return (
                f"😕 No new leads for <b>{category}</b> in <b>{city}</b>.\n"
                f"Already saved or try different city/category!"
            )

        lines = [f"✅ <b>{len(saved)} new leads!</b> ({credits_used} credits used)\n"]
        for i, lead in enumerate(saved[:5], 1):
            website = "✅ Website" if lead.get("has_website") else "❌ No Website"
            lines.append(
                f"{i}. <b>{lead.get('name', 'N/A')}</b>\n"
                f"   📞 {lead.get('phone', 'N/A')}\n"
                f"   {website} | ⭐ {lead.get('rating', 'N/A')}\n"
            )
        if len(saved) > 5:
            lines.append(f"...and {len(saved) - 5} more. View all in the app!")

        return "\n".join(lines)

    @staticmethod
    def my_leads_result(
        leads: list,
        total: int,
        category: Optional[str],
        page: int = 1,
        pages: int = 1
    ) -> str:
        if not leads:
            cat = f" for <b>{category}</b>" if category else ""
            return (
                f"📋 No leads found{cat}.\n"
                f"Use /findleads &lt;city&gt; &lt;category&gt; to find some!"
            )

        cat_label = f" [{category}]" if category else ""
        lines = [f"📋 <b>Your Leads{cat_label}</b> (page {page}/{pages} — {total} total)\n"]

        for i, lead in enumerate(leads, start=(page - 1) * 10 + 1):
            website = "✅" if lead.get("has_website") else "❌"
            address = (lead.get("address") or "")[:40]
            lines.append(
                f"{i}. <b>{lead.get('name', 'N/A')}</b>\n"
                f"   📍 {address}...\n"
                f"   {website} | ⭐ {lead.get('rating', 'N/A')} | 📞 {lead.get('phone', 'N/A')}\n"
            )

        if pages > 1:
            cat_arg = f" {category}" if category else ""
            if page < pages:
                lines.append(f"\n➡️ Next page: <code>/myleads{cat_arg} {page + 1}</code>")
            if page > 1:
                lines.append(f"⬅️ Prev page: <code>/myleads{cat_arg} {page - 1}</code>")

        return "\n".join(filter(None, lines))

    @staticmethod
    def insufficient_credits(needed: int, have: int) -> str:
        return (
            f"❌ <b>Insufficient credits!</b>\n"
            f"Need: {needed} | Have: {have}\n\n"
            f"Buy more credits in the app 💳"
        )


message_builder = MessageBuilder()
