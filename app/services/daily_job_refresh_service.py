"""
daily_job_refresh_service.py

Runs once daily (via APScheduler at 6 AM IST).
For every user, determines their job interests and fetches fresh jobs,
storing results in the `daily_job_feed` collection (TTL: 25 hours).

Interest priority:
  1. job_preferences embedded in user doc (desired_role + preferred_location)
  2. Last 3 distinct searches from job_lists
  3. Active job_alert_subscriptions
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Tuple

from app.services.mongo import mongo
from app.services.job_recommendation_service import job_recommendation_service
from app.models.job.listed_job import JobRecommendRequest


async def _get_user_interests(user: dict) -> List[Tuple[str, str, str]]:
    """
    Returns list of (search_term, location, work_type) tuples for a user.
    Max 3 interests returned.
    """
    results = []
    seen = set()

    # 1. Profile preferences (primary)
    prefs = user.get("job_preferences", {})
    role = (prefs.get("desired_role") or "").strip()
    loc  = (prefs.get("preferred_location") or "").strip()
    if role and loc:
        key = (role.lower(), loc.lower())
        seen.add(key)
        results.append((role, loc, prefs.get("work_type", "any")))

    # 2. Past searches fallback
    user_id = str(user["_id"])
    past = await mongo.job_lists.find(
        {"user_id": user_id},
        sort=[("created_at", -1)],
    ).limit(5).to_list(None)

    for p in past:
        term = (p.get("search_term") or "").strip()
        ploc = (p.get("location") or "").strip()
        if not term or not ploc:
            continue
        key = (term.lower(), ploc.lower())
        if key not in seen:
            seen.add(key)
            results.append((term, ploc, "any"))
        if len(results) >= 3:
            return results

    # 3. Active alert subscriptions fallback
    subs = await mongo.job_alert_subscriptions.find(
        {"user_id": user_id, "is_active": True}
    ).to_list(None)

    for s in subs:
        term = (s.get("search_term") or "").strip()
        sloc = (s.get("location") or "").strip()
        if not term or not sloc:
            continue
        key = (term.lower(), sloc.lower())
        if key not in seen:
            seen.add(key)
            results.append((term, sloc, "any"))
        if len(results) >= 3:
            return results

    return results


async def _fetch_and_store(user_id: str, search_term: str, location: str, work_type: str):
    """Scrape + rank jobs for one (user, search_term, location) and store in daily_job_feed."""
    try:
        is_remote = True if work_type == "remote" else (False if work_type == "on-site" else None)

        # Get resume_id for this user
        try:
            resume_id = await job_recommendation_service.get_resume_id_for_user(user_id)
        except Exception:
            print(f"[DailyCron] No resume for user {user_id}, skipping")
            return

        payload = JobRecommendRequest(
            search_term=search_term,
            location=location,
            sites=["indeed", "linkedin", "google"],
            is_remote=is_remote,
            results_per_site=15,
            hours_old=24,
            include_naukri=True,
            naukri_pages=1,
            top_n=10,
        )

        result = await job_recommendation_service.recommend_jobs(
            user_id=user_id,
            resume_id=resume_id,
            payload=payload,
        )

        jobs = result.get("jobs", [])
        if not jobs:
            return

        # Delete existing feed entry for this user+search to avoid duplicates
        await mongo.daily_job_feed.delete_many({
            "user_id": user_id,
            "search_term": search_term,
            "location": location,
        })

        # Insert fresh results
        await mongo.daily_job_feed.insert_one({
            "user_id": user_id,
            "search_term": search_term,
            "location": location,
            "jobs": jobs,
            "created_at": datetime.now(timezone.utc),
        })

        print(f"[DailyCron] Stored {len(jobs)} jobs for user {user_id} — '{search_term}' in {location}")

    except Exception as e:
        print(f"[DailyCron] Error for user {user_id} / '{search_term}': {e}")


async def run_daily_job_refresh():
    """Main entry point — called by APScheduler at 6 AM IST every day."""
    print("[DailyCron] Starting daily job refresh...")
    start = datetime.now(timezone.utc)

    try:
        users = await mongo.users.find({}).to_list(None)
        print(f"[DailyCron] Processing {len(users)} users")

        for user in users:
            user_id = str(user["_id"])
            interests = await _get_user_interests(user)

            if not interests:
                continue

            for search_term, location, work_type in interests:
                await _fetch_and_store(user_id, search_term, location, work_type)
                # Small delay to avoid hammering external APIs
                await asyncio.sleep(2)

    except Exception as e:
        print(f"[DailyCron] Fatal error: {e}")

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    print(f"[DailyCron] Done in {elapsed:.1f}s")


async def ensure_ttl_index():
    """Create TTL index on daily_job_feed.created_at — expire after 25 hours."""
    await mongo.daily_job_feed.create_index(
        "created_at",
        expireAfterSeconds=90000,  # 25 hours
        name="daily_job_feed_ttl",
    )
    print("[DailyCron] TTL index ensured on daily_job_feed")
