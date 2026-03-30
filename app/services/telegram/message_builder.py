# app/services/telegram/message_builder.py

import html as html_lib
from typing import Any, Dict, List, Optional


class MessageBuilder:

    @staticmethod
    def main_menu_reply_keyboard() -> dict:
        return {
            "keyboard": [
                [{"text": "🔍 Find Jobs"}, {"text": "🔔 Daily Alerts"}],
            ],
            "resize_keyboard": True,
        }

    @staticmethod
    def resume_required() -> str:
        return (
            "📄 <b>No resume on file.</b>\n\n"
            "Upload your resume in the app first. "
            "Job matches use your CV (same as the web API)."
        )

    @staticmethod
    def not_linked() -> str:
        return (
            "❌ <b>No account linked.</b>\n"
            "Open the app → Profile → Connect Telegram."
        )

    @staticmethod
    def help() -> str:
        return """🤖 <b>ZenLead / ResumeMatch Bot</b>

💼 <b>JOBS</b> (requires app account + resume upload)
🔍 <b>Find Jobs</b> — button flow, or:
<code>/findjobs Title | Location</code>
<code>/myalerts</code> — show daily alert subscription
<code>/stopalerts</code> — turn off daily alerts
<code>/cancel</code> — cancel a multi-step prompt

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

    @staticmethod
    def daily_alert_confirmed(
        search_term: str,
        location: str,
        hour: int,
        minute: int,
        tz_name: str,
        next_run_iso: str,
    ) -> str:
        t = f"{hour:02d}:{minute:02d}"
        return (
            "✅ <b>Subscribed!</b>\n\n"
            f"Title: <b>{html_lib.escape(search_term)}</b>\n"
            f"Location: <b>{html_lib.escape(location)}</b>\n"
            f"Time: <b>{t}</b> ({html_lib.escape(tz_name)})\n"
            f"Next run (UTC): <code>{html_lib.escape(next_run_iso)}</code>\n\n"
            "You’ll get a Telegram message around that time each day "
            "(worker must be running)."
        )

    @staticmethod
    def my_alert_status(sub: Optional[Dict[str, Any]]) -> str:
        if not sub:
            return "No active daily alert. Tap <b>🔔 Daily Alerts</b> to set one up."
        st = html_lib.escape(str(sub.get("search_term") or ""))
        loc = html_lib.escape(str(sub.get("location") or ""))
        tz = html_lib.escape(str(sub.get("timezone") or ""))
        h = int(sub.get("alert_hour", 0))
        m = int(sub.get("alert_minute", 0))
        t = f"{h:02d}:{m:02d}"
        nxt = sub.get("next_run_at")
        nxt_s = nxt.isoformat() if hasattr(nxt, "isoformat") else str(nxt or "")
        return (
            "🔔 <b>Your daily alert</b>\n\n"
            f"Title: <b>{st}</b>\n"
            f"Location: <b>{loc}</b>\n"
            f"Time: <b>{t}</b> ({tz})\n"
            f"Next: <code>{html_lib.escape(nxt_s)}</code>\n\n"
            "<code>/stopalerts</code> to disable."
        )

    @staticmethod
    def format_job_results_telegram(
        jobs: List[Dict[str, Any]],
        list_id: str,
        search_term: str,
        location: str,
        header_prefix: str = "",
    ) -> List[str]:
        jobs = jobs or []
        header = header_prefix or ""
        header += (
            f"✅ <b>Top {len(jobs)} jobs</b>\n"
            f"{html_lib.escape(search_term)} · {html_lib.escape(location)}\n"
        )
        if list_id:
            header += f"<code>{html_lib.escape(list_id)}</code>\n"
        header += "\n"

        blocks: List[str] = []
        for i, j in enumerate(jobs[:20], 1):
            title = html_lib.escape(str(j.get("title") or ""))
            company = html_lib.escape(str(j.get("company") or ""))
            loc = html_lib.escape(str(j.get("location") or ""))
            url = str(j.get("job_url") or "").strip()
            site = html_lib.escape(str(j.get("site") or ""))
            score = j.get("fit_score")
            score_s = f" · match {score}" if score is not None else ""
            if url:
                safe = html_lib.escape(url, quote=True)
                link_line = f'<a href="{safe}">Apply</a>'
            else:
                link_line = "No link"
            blocks.append(
                f"{i}. <b>{title}</b>{score_s}\n"
                f"🏢 {company}\n"
                f"📍 {loc} · {site}\n"
                f"🔗 {link_line}\n"
            )

        max_len = 3800
        chunks: List[str] = []
        cur = header
        for block in blocks:
            if len(cur) + len(block) + 1 > max_len:
                chunks.append(cur.rstrip())
                cur = block + "\n"
            else:
                cur += block + "\n"
        if cur.strip():
            chunks.append(cur.rstrip())
        return chunks if chunks else [header + "No results."]


message_builder = MessageBuilder()
