import re
import os
import csv as csv_module
import json
import asyncio
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from functools import partial

import pandas as pd
from bs4 import BeautifulSoup
from bson import ObjectId
import google.generativeai as genai

from app.config import settings
from app.services.mongo import mongo

MAX_DESC_CHARS     = 800
MAX_JOBS_TO_GEMINI = 20

NAUKRI_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


# ─────────────────────────────────────────
# UTILS
# ─────────────────────────────────────────
def _clean(s: Any) -> str:
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _df_to_job_list(df: pd.DataFrame) -> List[Dict[str, Any]]:
    if df is None or df.empty:
        return []
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    jobs = []
    for _, row in df.iterrows():
        city  = _clean(row.get("city", ""))
        state = _clean(row.get("state", ""))
        loc   = _clean(row.get("location")) or ", ".join(filter(None, [city, state]))
        j = {
            "site":        _clean(row.get("site")),
            "title":       _clean(row.get("title")),
            "company":     _clean(row.get("company")),
            "location":    loc,
            "is_remote":   bool(row.get("is_remote")) if "is_remote" in df.columns else None,
            "job_type":    _clean(row.get("job_type")),
            "salary":      "",
            "experience":  "",
            "job_url":     _clean(row.get("job_url")),
            "date_posted": _clean(row.get("date_posted")),
            "description": _clean(row.get("description")),
        }
        if j["title"] and j["company"] and j["job_url"]:
            jobs.append(j)
    return jobs


# ─────────────────────────────────────────
# SYNC SCRAPERS
# ─────────────────────────────────────────
def _scrape_jobspy_sync(
    search_term:      str,
    location:         str,
    results_per_site: int,
    hours_old:        int,
    sites:            List[str],
    country_indeed:   str,
    is_remote:        Optional[bool],
    proxies:          Optional[List[str]],
) -> List[Dict[str, Any]]:
    try:
        from jobspy import scrape_jobs
        kwargs = dict(
            site_name                  = sites,
            search_term                = search_term,
            google_search_term         = f"{search_term} jobs near {location} since yesterday",
            location                   = location,
            results_wanted             = results_per_site,
            hours_old                  = hours_old,
            country_indeed             = country_indeed,
            linkedin_fetch_description = True,
            description_format         = "markdown",
            proxies                    = proxies,
            verbose                    = 0,
        )
        if is_remote is not None:
            kwargs["is_remote"] = is_remote

        df   = scrape_jobs(**kwargs)
        jobs = _df_to_job_list(df)
        print(f"[JobSpy] Scraped {len(jobs)} jobs")
        return jobs
    except Exception as e:
        import traceback
        print(f"[JobSpy Error] {e}")
        traceback.print_exc()
        return []


def _scrape_naukri_pypi_sync(search_term: str, pages: int) -> List[Dict[str, Any]]:
    try:
        from naukri_scraper.scraper import scrape_jobs as naukri_scrape
    except ImportError:
        print("[Naukri] naukri-scraper not installed. Run: pip install naukri-scraper")
        return []

    all_jobs = []
    for page in range(1, pages + 1):
        try:
            result = naukri_scrape(search_term, page)
            if not result:
                break

            csv_file = result[1] if isinstance(result, tuple) else None
            if not csv_file:
                break

            with open(csv_file, newline="", encoding="utf-8") as f:
                reader = csv_module.DictReader(f)
                for row in reader:
                    title   = _clean(row.get("Title", ""))
                    company = _clean(row.get("Company", ""))
                    url     = _clean(row.get("URL", ""))
                    if title and company and url:
                        all_jobs.append({
                            "site":        "naukri",
                            "title":       title,
                            "company":     company,
                            "location":    _clean(row.get("Location", "")),
                            "experience":  _clean(row.get("Experience", "")),
                            "salary":      _clean(row.get("Salary", "")),
                            "job_type":    "",
                            "is_remote":   None,
                            "job_url":     url,
                            "date_posted": _clean(row.get("Posted Date", "")),
                            "description": _clean(row.get("Description", "")),
                        })

            try:
                os.remove(csv_file)
            except Exception:
                pass

        except Exception as e:
            print(f"[Naukri PyPI page {page}] {e}")
            break

    print(f"[Naukri] PyPI returned {len(all_jobs)} jobs")
    return all_jobs


def _scrape_naukri_raw_sync(
    search_term: str,
    location:    str,
    pages:       int,
) -> List[Dict[str, Any]]:
    jobs         = []
    keyword_slug = search_term.strip().replace(" ", "-").lower()
    loc_slug     = location.strip().replace(" ", "-").lower()

    for page in range(1, pages + 1):
        url = f"https://www.naukri.com/{keyword_slug}-jobs-in-{loc_slug}-{page}"
        try:
            resp = requests.get(url, headers=NAUKRI_HEADERS, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")
            for article in soup.find_all("article", class_=lambda c: c and "jobTuple" in c):
                title_tag   = article.find("a", class_=lambda c: c and "title" in (c or ""))
                company_tag = article.find("a", class_=lambda c: c and "comp" in (c or "").lower())
                loc_tag     = article.find("li", class_=lambda c: c and "loc" in (c or "").lower())
                exp_tag     = article.find("li", class_=lambda c: c and "exp" in (c or "").lower())
                sal_tag     = article.find("li", class_=lambda c: c and "sal" in (c or "").lower())
                link        = title_tag["href"] if title_tag and title_tag.get("href") else ""
                title       = title_tag.get_text(strip=True) if title_tag else ""
                company     = company_tag.get_text(strip=True) if company_tag else ""
                if title and company and link:
                    jobs.append({
                        "site":        "naukri",
                        "title":       title,
                        "company":     company,
                        "location":    loc_tag.get_text(strip=True) if loc_tag else "",
                        "experience":  exp_tag.get_text(strip=True) if exp_tag else "",
                        "salary":      sal_tag.get_text(strip=True) if sal_tag else "",
                        "job_type":    "",
                        "is_remote":   None,
                        "job_url":     link,
                        "date_posted": "",
                        "description": "",
                    })
        except Exception as e:
            print(f"[Naukri Raw page {page}] {e}")

    print(f"[Naukri] Raw scraper returned {len(jobs)} jobs")
    return jobs


# ─────────────────────────────────────────
# GEMINI RANKING + SUMMARIZATION
# ─────────────────────────────────────────
def _rank_and_summarize_sync(
    resume_text: str,
    jobs:        List[Dict[str, Any]],
    top_n:       int,
) -> List[Dict[str, Any]]:

    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel(settings.gemini_model)

    compact = []
    for i, j in enumerate(jobs, start=1):
        compact.append({
            "id":          i,
            "title":       j.get("title", ""),
            "company":     j.get("company", ""),
            "location":    j.get("location", ""),
            "experience":  j.get("experience", ""),
            "salary":      j.get("salary", ""),
            "is_remote":   j.get("is_remote"),
            "job_type":    j.get("job_type", ""),
            "site":        j.get("site", ""),
            "job_url":     j.get("job_url", ""),
            "date_posted": j.get("date_posted", ""),
            "description": j.get("description", "")[:MAX_DESC_CHARS],
        })

    prompt = f"""
You are a senior ATS + technical recruiter.

TASK:
Given the candidate resume and a list of job posts, do two things:
1. Score each job for candidate fit (0–100)
2. Write a 1–2 line description_summary of the role — plain English for a job card UI.

Return ONLY valid JSON — no markdown, no extra text.

SCORING RULES:
- fit_score           : integer 0–100
- Reward              : matching skills, seniority, domain/tech stack
- Penalise            : key skills absent, over-seniority, wrong domain, location mismatch
- matched_keywords    : skills/tools in BOTH resume and JD
- missing_keywords    : skills/tools JD requires but absent from resume
- risk_flags          : e.g. "requires 5+ yrs", "on-site only", "niche domain mismatch"
- description_summary : 1–2 plain English sentences about the role

OUTPUT JSON SCHEMA (strict — return ONLY this):
{{
  "ranked": [
    {{
      "id": 1,
      "fit_score": 85,
      "best_role_label": "Full-stack Developer",
      "description_summary": "Build React + Node.js apps for fintech clients. Involves REST APIs, PostgreSQL, and CI/CD.",
      "matched_keywords": ["Node.js", "React", "PostgreSQL"],
      "missing_keywords": ["GraphQL"],
      "reasoning": "max 40 words",
      "risk_flags": []
    }}
  ]
}}

CANDIDATE RESUME:
\"\"\"{resume_text}\"\"\"

JOBS LIST:
{json.dumps(compact, ensure_ascii=False)}
""".strip()

    resp = model.generate_content(prompt)
    raw  = resp.text.strip()

    m = re.search(r"\{.*\}", raw, flags=re.S)
    if not m:
        raise RuntimeError(f"Gemini returned no JSON.\nRaw:\n{raw}")

    data   = json.loads(m.group(0))
    ranked = data.get("ranked", [])

    by_id    = {j["id"]: j for j in compact}
    enriched = []
    for item in ranked:
        base = by_id.get(item.get("id"))
        if base:
            enriched.append({**base, **item})

    enriched.sort(key=lambda x: _safe_int(x.get("fit_score"), 0), reverse=True)
    return enriched[:top_n]


# ─────────────────────────────────────────
# ASYNC SERVICE CLASS
# ─────────────────────────────────────────
class JobRecommendationService:

    # ── Auto-fetch latest resume_id for user ──────────
    async def get_resume_id_for_user(self, user_id: str) -> str:
        """
        Fetches the most recently uploaded resume_id from incoming_resumes.
        Controller calls this so frontend never needs to send resume_id.
        """
        doc = await mongo.incoming_resumes.find_one(
            {"user_id": user_id},
            sort=[("created_at", -1)]   # latest resume first
        )
        if not doc:
            raise ValueError(
                f"No resume found for user {user_id}. "
                f"Please upload a resume first via /api/resume/upload"
            )
        resume_id = str(doc["_id"])
        print(f"[Resume] Auto-fetched resume_id={resume_id} for user={user_id}")
        return resume_id

    # ── Fetch resume text from MongoDB ────────────────
    async def _get_resume_text(self, resume_id: str, user_id: str) -> str:
        doc = await mongo.incoming_resumes.find_one({
            "_id":     ObjectId(resume_id),
            "user_id": user_id,
        })
        if not doc:
            raise ValueError(f"Resume {resume_id} not found for user {user_id}")

        extracted = doc.get("extracted_data")
        if extracted and isinstance(extracted, dict):
            parts = []
            for key, val in extracted.items():
                if val:
                    if isinstance(val, list):
                        parts.append(f"{key}: {', '.join(str(v) for v in val)}")
                    elif isinstance(val, dict):
                        parts.append(f"{key}: {json.dumps(val)}")
                    else:
                        parts.append(f"{key}: {val}")
            if parts:
                return "\n".join(parts)

        for field in ["raw_text", "extracted_text", "content", "full_text", "text"]:
            if doc.get(field) and not str(doc[field]).startswith("[PDF_FILE"):
                return str(doc[field])

        raise ValueError(
            f"Resume {resume_id} has no extractable text. "
            f"Available fields: {list(doc.keys())}"
        )

    # ── Save to DB ────────────────────────────────────
    async def save_results(
        self,
        user_id:     str,
        resume_id:   str,
        search_term: str,
        location:    str,
        jobs:        List[Dict[str, Any]],
    ) -> str:
        now = datetime.now(timezone.utc)

        list_doc    = {
            "user_id":     user_id,
            "resume_id":   resume_id,
            "search_term": search_term,
            "location":    location,
            "total_jobs":  len(jobs),
            "created_at":  now,
        }
        list_result = await mongo.job_lists.insert_one(list_doc)
        list_id     = str(list_result.inserted_id)

        if jobs:
            job_docs = [
                {
                    "list_id":             list_id,
                    "user_id":             user_id,
                    "resume_id":           resume_id,
                    "created_at":          now,
                    "site":                j.get("site", ""),
                    "title":               j.get("title", ""),
                    "company":             j.get("company", ""),
                    "location":            j.get("location", ""),
                    "experience":          j.get("experience", ""),
                    "salary":              j.get("salary", ""),
                    "job_type":            j.get("job_type", ""),
                    "is_remote":           j.get("is_remote"),
                    "job_url":             j.get("job_url", ""),
                    "date_posted":         j.get("date_posted", ""),
                    "description":         j.get("description", ""),
                    "description_summary": j.get("description_summary", ""),
                    "fit_score":           _safe_int(j.get("fit_score"), 0),
                    "best_role_label":     j.get("best_role_label", ""),
                    "matched_keywords":    j.get("matched_keywords", []),
                    "missing_keywords":    j.get("missing_keywords", []),
                    "reasoning":           j.get("reasoning", ""),
                    "risk_flags":          j.get("risk_flags", []),
                }
                for j in jobs
            ]
            await mongo.listed_jobs.insert_many(job_docs)

        print(f"[DB] Saved list_id={list_id} | {len(jobs)} job cards → MongoDB")
        return list_id

    # ── Main recommend flow ───────────────────────────
    # resume_id passed from controller (fetched via get_resume_id_for_user)
    # payload no longer needs resume_id field
    async def recommend_jobs(
        self,
        user_id:   str,
        resume_id: str,       # ← passed from controller, NOT from payload
        payload:   Any,
    ) -> Dict[str, Any]:

        # 1. Get resume text using fetched resume_id
        resume_text = await self._get_resume_text(resume_id, user_id)

        loop = asyncio.get_event_loop()

        # 2. Scrape JobSpy + Naukri concurrently
        jobspy_task = loop.run_in_executor(
            None,
            partial(
                _scrape_jobspy_sync,
                payload.search_term,
                payload.location,
                payload.results_per_site,
                payload.hours_old,
                payload.sites,
                "India",
                payload.is_remote,
                None,
            )
        )

        naukri_task = (
            loop.run_in_executor(
                None,
                partial(_scrape_naukri_pypi_sync, payload.search_term, payload.naukri_pages)
            )
            if payload.include_naukri
            else asyncio.sleep(0)
        )

        jobs_jobspy, jobs_naukri = await asyncio.gather(jobspy_task, naukri_task)

        if not isinstance(jobs_naukri, list):
            jobs_naukri = []

        if payload.include_naukri and len(jobs_naukri) == 0:
            print("[Naukri] PyPI returned 0 jobs, falling back to raw scraper...")
            jobs_naukri = await loop.run_in_executor(
                None,
                partial(_scrape_naukri_raw_sync, payload.search_term, payload.location, payload.naukri_pages)
            )

        all_jobs      = jobs_jobspy + jobs_naukri
        total_scraped = len(all_jobs)
        print(f"[JobRecommend] Scraped {total_scraped} total ({len(jobs_jobspy)} JobSpy + {len(jobs_naukri)} Naukri)")

        if total_scraped == 0:
            return {
                "success":        False,
                "list_id":        "",
                "total_scraped":  0,
                "total_returned": 0,
                "jobs":           [],
            }

        # 3. Pre-filter: deduplicate by URL + cap to MAX_JOBS_TO_GEMINI
        seen_urls = set()
        filtered  = []
        for j in all_jobs:
            url = j.get("job_url", "")
            if url not in seen_urls and j.get("title"):
                seen_urls.add(url)
                filtered.append(j)

        filtered = filtered[:MAX_JOBS_TO_GEMINI]
        print(f"[JobRecommend] Sending {len(filtered)} jobs to Gemini (capped from {total_scraped})")

        # 4. Rank + summarize with Gemini
        top_jobs = await loop.run_in_executor(
            None,
            partial(_rank_and_summarize_sync, resume_text, filtered, payload.top_n)
        )

        # 5. Save to MongoDB — no CSV, no files
        list_id = await self.save_results(
            user_id     = user_id,
            resume_id   = resume_id,       # ← use fetched resume_id
            search_term = payload.search_term,
            location    = payload.location,
            jobs        = top_jobs,
        )

        return {
            "success":        True,
            "list_id":        list_id,
            "total_scraped":  total_scraped,
            "total_returned": len(top_jobs),
            "jobs":           top_jobs,
        }

    # ── Get all lists for user ────────────────────────
    async def get_all_lists(self, user_id: str) -> Dict[str, Any]:
        cursor = mongo.job_lists.find(
            {"user_id": user_id},
            sort=[("created_at", -1)]
        )
        lists = []
        async for doc in cursor:
            lists.append({
                "list_id":     str(doc["_id"]),
                "resume_id":   doc.get("resume_id", ""),
                "search_term": doc.get("search_term", ""),
                "location":    doc.get("location", ""),
                "total_jobs":  doc.get("total_jobs", 0),
                "created_at":  doc["created_at"].isoformat()
                               if hasattr(doc.get("created_at"), "isoformat") else "",
            })
        return {"success": True, "total": len(lists), "lists": lists}

    # ── Get all lists for a specific resume ───────────
    async def get_lists_by_resume(self, user_id: str, resume_id: str) -> Dict[str, Any]:
        cursor = mongo.job_lists.find(
            {"user_id": user_id, "resume_id": resume_id},
            sort=[("created_at", -1)]
        )
        lists = []
        async for doc in cursor:
            lists.append({
                "list_id":     str(doc["_id"]),
                "resume_id":   doc.get("resume_id", ""),
                "search_term": doc.get("search_term", ""),
                "location":    doc.get("location", ""),
                "total_jobs":  doc.get("total_jobs", 0),
                "created_at":  doc["created_at"].isoformat()
                               if hasattr(doc.get("created_at"), "isoformat") else "",
            })
        return {"success": True, "total": len(lists), "lists": lists}

    # ── Get one list with all job cards ──────────────
    async def get_list_by_id(self, user_id: str, list_id: str) -> Dict[str, Any]:
        meta = await mongo.job_lists.find_one({
            "_id":     ObjectId(list_id),
            "user_id": user_id,
        })
        if not meta:
            return {"success": False, "error": "List not found"}

        cursor = mongo.listed_jobs.find(
            {"list_id": list_id, "user_id": user_id},
            sort=[("fit_score", -1)]
        )
        jobs = []
        async for doc in cursor:
            doc.pop("_id", None)
            doc.pop("list_id", None)
            doc.pop("user_id", None)
            doc.pop("resume_id", None)
            doc.pop("created_at", None)
            jobs.append(doc)

        return {
            "success":     True,
            "list_id":     list_id,
            "resume_id":   meta.get("resume_id", ""),
            "search_term": meta.get("search_term", ""),
            "location":    meta.get("location", ""),
            "total_jobs":  meta.get("total_jobs", 0),
            "created_at":  meta["created_at"].isoformat()
                           if hasattr(meta.get("created_at"), "isoformat") else "",
            "jobs":        jobs,
        }

    # ── Delete list + all its job cards ──────────────
    async def delete_list(self, user_id: str, list_id: str) -> Dict[str, Any]:
        meta_del = await mongo.job_lists.delete_one({
            "_id":     ObjectId(list_id),
            "user_id": user_id,
        })
        if meta_del.deleted_count == 0:
            return {"success": False, "error": "List not found"}

        jobs_del = await mongo.listed_jobs.delete_many({
            "list_id": list_id,
            "user_id": user_id,
        })
        return {
            "success":      True,
            "message":      "List and all job cards deleted",
            "jobs_deleted": jobs_del.deleted_count,
        }

    # ── Default jobs (for users with no recommendations yet) ──
    async def get_default_jobs(
        self,
        user_id:   str,
        min_count: int = 10,
        max_days:  int = 30,
    ) -> Dict[str, Any]:

        # Check if this user already has personalized recommendations
        existing = await mongo.listed_jobs.find_one({"user_id": user_id})
        if existing:
            return {
                "success":             True,
                "has_recommendations": True,
                "message":             "You have personalized recommendations. Use GET /api/jobs/lists",
                "jobs":                [],
                "total":               0,
                "days_fetched":        0,
            }

        # Fetch day by day until we have min_count jobs
        collected   = []
        days_looked = 0
        now_utc     = datetime.now(timezone.utc)

        for day_offset in range(0, max_days):
            if len(collected) >= min_count:
                break

            target_date = now_utc - timedelta(days=day_offset)
            day_start   = target_date.replace(hour=0,  minute=0,  second=0,  microsecond=0)
            day_end     = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)

            need   = min_count - len(collected)

            # Pull globally — exclude requesting user's own jobs + deduplicate URLs
            seen_urls = [j["job_url"] for j in collected]
            cursor = mongo.listed_jobs.find(
                {
                    "created_at": {"$gte": day_start, "$lte": day_end},
                    "user_id":    {"$ne": user_id},
                    "job_url":    {"$nin": seen_urls},
                },
                sort=[("fit_score", -1), ("created_at", -1)]
            ).limit(need)

            day_jobs = []
            async for doc in cursor:
                doc.pop("_id", None)
                doc.pop("user_id", None)
                doc.pop("resume_id", None)
                doc.pop("list_id", None)
                if hasattr(doc.get("created_at"), "isoformat"):
                    doc["created_at"] = doc["created_at"].isoformat()
                day_jobs.append(doc)

            collected.extend(day_jobs)
            days_looked = day_offset + 1
            print(f"[DefaultJobs] Day -{day_offset}: fetched {len(day_jobs)} | total: {len(collected)}")

        return {
            "success":             True,
            "has_recommendations": False,
            "message":             f"Showing default jobs from last {days_looked} day(s)",
            "jobs":                collected[:min_count],
            "total":               len(collected[:min_count]),
            "days_fetched":        days_looked,
        }

    # ── Paginated all jobs with filters ──────────────
    async def get_all_listed_jobs(
        self,
        page:       int          = 1,
        limit:      int          = 10,
        search:     str          = "",
        site:       str          = "",
        is_remote:  Optional[bool] = None,
        min_score:  int          = 0,
        sort_by:    str          = "fit_score",
        sort_order: str          = "desc",
    ) -> Dict[str, Any]:

        query: Dict[str, Any] = {}

        if search:
            query["$or"] = [
                {"title":    {"$regex": search, "$options": "i"}},
                {"company":  {"$regex": search, "$options": "i"}},
                {"location": {"$regex": search, "$options": "i"}},
            ]

        if site:
            query["site"] = site.lower()

        if is_remote is not None:
            query["is_remote"] = is_remote

        if min_score > 0:
            query["fit_score"] = {"$gte": min_score}

        sort_dir   = -1 if sort_order == "desc" else 1
        sort_field = sort_by if sort_by in ("fit_score", "created_at", "date_posted") else "fit_score"

        page  = max(1, page)
        limit = max(1, min(limit, 100))
        skip  = (page - 1) * limit

        total_records = await mongo.listed_jobs.count_documents(query)
        total_pages   = (total_records + limit - 1) // limit

        cursor = mongo.listed_jobs.find(
            query,
            sort=[(sort_field, sort_dir)]
        ).skip(skip).limit(limit)

        jobs = []
        async for doc in cursor:
            doc["id"] = str(doc.pop("_id"))
            doc.pop("user_id",   None)
            doc.pop("resume_id", None)
            doc.pop("list_id",   None)
            if hasattr(doc.get("created_at"), "isoformat"):
                doc["created_at"] = doc["created_at"].isoformat()
            jobs.append(doc)

        return {
            "success":       True,
            "page":          page,
            "limit":         limit,
            "total_records": total_records,
            "total_pages":   total_pages,
            "has_next":      page < total_pages,
            "has_prev":      page > 1,
            "jobs":          jobs,
        }


job_recommendation_service = JobRecommendationService()
