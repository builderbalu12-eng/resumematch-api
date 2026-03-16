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
/findleads &lt;city&gt; &lt;category&gt;
<i>Example: /findleads delhi jeweler</i>
Categories: restaurant, jeweler, salon, gym, clinic, clothing, bakery, hotel, realestate, carrepair, all

/myleads — View all saved leads
/myleads &lt;category&gt; — Filter by category

💳 <b>ACCOUNT</b>
/credits — Credit balance
/status  — Account info

⚙️ <b>SETUP</b>
/start &lt;token&gt; — Link your account
/help — Show this message

━━━━━━━━━━━━━━━━━━
💡 Each lead costs 2 credits."""

    @staticmethod
    def credits(credits: float, plan: str) -> str:
        return (
            f"💳 <b>Credits</b>\n\n"
            f"Balance: <b>{int(credits)} credits</b>\n"
            f"Plan: <b>{plan}</b>\n\n"
            f"💡 Each lead costs 2 credits."
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
    def my_leads_result(leads: list, total: int, category: Optional[str]) -> str:
        if not leads:
            cat = f" for <b>{category}</b>" if category else ""
            return (
                f"📋 No leads found{cat}.\n"
                f"Use /findleads &lt;city&gt; &lt;category&gt; to find some!"
            )

        lines = [f"📋 <b>Your Leads</b> (showing {len(leads)} of {total})\n"]
        for i, lead in enumerate(leads, 1):
            website = "✅" if lead.get("has_website") else "❌"
            address = (lead.get("address") or "")[:40]
            lines.append(
                f"{i}. <b>{lead.get('name', 'N/A')}</b>\n"
                f"   📍 {address}...\n"
                f"   {website} | ⭐ {lead.get('rating', 'N/A')} | 📞 {lead.get('phone', 'N/A')}\n"
            )
        return "\n".join(lines)

    @staticmethod
    def insufficient_credits(needed: int, have: int) -> str:
        return (
            f"❌ <b>Insufficient credits!</b>\n"
            f"Need: {needed} | Have: {have}\n\n"
            f"Buy more credits in the app 💳"
        )


message_builder = MessageBuilder()
