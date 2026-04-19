# Job Fetching Architecture

## How Jobs Are Displayed

Jobs reach users in two ways: **on-demand** (when the user asks Nova) and **automated daily cron** (runs every morning for all users).

---

## 1. On-Demand Search (User-Triggered via Chat)

**Trigger**: User sends a message like "find me jobs as software engineer in bangalore"

**Flow**:
1. Nova (AI) extracts `role` and `location` via function calling
2. `_handle_find_jobs(role, location, user_id)` runs the 5-level fallback chain
3. Top 5 results returned in the chat as job cards
4. **Credits deducted**: 1 credit per job returned (5 jobs = 5 credits)

### 5-Level Fallback Chain

| Level | Function | Source | Notes |
|-------|----------|--------|-------|
| 1 | `_scrape_jsearch(role, city)` | JSearch RapidAPI | Primary — aggregates LinkedIn, Indeed, Glassdoor, Naukri, ZipRecruiter and more |
| 2 | `_scrape_naukri_raw_sync(role, city)` | Naukri HTML scrape | Indian jobs, direct HTML parsing |
| 3 | `_scrape_jobspy_sync(role, city)` | JobSpy library | Indeed-only on cloud (others blocked) |
| 4 | `_scrape_jsearch(role, "india")` | JSearch RapidAPI | Broadened to all of India if city fails |
| 5 | `_scrape_jsearch(first_keyword, "india")` | JSearch RapidAPI | Single-word broad search as last resort |

If all 5 levels return nothing → returns direct search links to Naukri and LinkedIn (no credits deducted).

### Source Tag on Job Cards

The chip shown on each job card (e.g. "LinkedIn", "Indeed") comes from JSearch's `job_publisher` field — the actual board where the job was originally posted. JSearch is just the aggregator API; it is never shown as the source.

---

## 2. Daily Cron Job (Automated — All Users)

**Schedule**: Every day at **6:00 AM IST** (Asia/Kolkata timezone)

**Mechanism**: APScheduler `AsyncIOScheduler` — started automatically when the FastAPI server boots (`main.py` startup event)

**Service file**: `app/services/daily_job_refresh_service.py` → `run_daily_job_refresh()`

### What It Does Per User

For every user in the database:

1. **Find job interests** (in priority order):
   - `job_preferences.desired_role` + `preferred_location` saved in user profile ← PRIMARY
   - Last 3 distinct search terms from `job_lists` collection ← FALLBACK
   - Active `job_alert_subscriptions` ← FALLBACK

2. **Scrape jobs** for each interest using `recommend_jobs()`:
   - Uses same JSearch → JobSpy → Naukri pipeline
   - Ranks results with AI (match score vs. resume if available)

3. **Store results** in `daily_job_feed` collection with **25-hour TTL** (auto-deleted after ~1 day)

**This runs for all users**, not just active ones. Users with no saved preferences get no feed (nothing to search for).

---

## 3. Database Collections

| Collection | What's Stored | TTL |
|---|---|---|
| `job_lists` | Search session metadata (search term, timestamp, user) | None — permanent |
| `listed_jobs` | Full ranked job cards per search session | None — permanent |
| `daily_job_feed` | Auto-cron job feed per user per day | **25 hours** (auto-deleted) |
| `rapidapi_usage_log` | JSearch API call count + rate limit tracking | None |

---

## 4. All Job-Related API Routes

| Method | Path | Triggered By |
|--------|------|-------------|
| `POST` | `/api/jobs/recommend` | On-demand: user chat "find me jobs" or direct API call |
| `GET` | `/api/jobs/lists` | Frontend fetching past search sessions |
| `GET` | `/api/jobs/lists/resume/{resume_id}` | Search sessions for a specific resume |
| `GET` | `/api/jobs/lists/{list_id}` | Full job cards for a session |
| `DELETE` | `/api/jobs/lists/{list_id}` | Delete a search session + its jobs |
| `GET` | `/api/jobs/default` | Default feed for new users (pulls from daily_job_feed or global pool) |
| `GET` | `/api/jobs/all` | Paginated all jobs with filters |

---

## 5. Scraping Functions Reference

| Function | File | Source | Cloud Status |
|---|---|---|---|
| `_scrape_jsearch()` | `job_recommendation_service.py` | JSearch RapidAPI | ✅ Works — aggregates LinkedIn/Indeed/Glassdoor/Naukri |
| `_scrape_naukri_raw_sync()` | `job_recommendation_service.py` | Naukri HTML | ⚠️ Inconsistent — blocks scrapers periodically |
| `_scrape_naukri_pypi_sync()` | `job_recommendation_service.py` | Naukri PyPI pkg | ⚠️ Inconsistent |
| `_scrape_jobspy_sync()` | `job_recommendation_service.py` | JobSpy (Indeed) | ⚠️ Indeed-only on cloud; LinkedIn/Glassdoor blocked |

**Primary source is JSearch.** The others are fallbacks only.

---

## 6. Credit Billing

| Feature | Cost | When Deducted |
|---|---|---|
| `find_jobs` (chat) | 1 credit per job returned | After successful scrape, before returning to user |
| `find_leads` | 1 credit per lead returned | Same pattern |
| Daily cron refresh | **Free** | No credits charged for background refresh |

---

## 7. Key Files

```
resumematch-api/
├── app/main.py                              — APScheduler startup
├── app/services/
│   ├── job_recommendation_service.py        — All scraping functions + _map_jsearch_job
│   ├── daily_job_refresh_service.py         — Cron logic (per-user daily refresh)
│   └── chat/
│       └── ai_chat_service.py               — _handle_find_jobs (5-level fallback)
└── app/routers/
    └── job_routes.py                        — All /api/jobs/* endpoints
```
