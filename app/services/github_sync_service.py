import json
import os
import tempfile
from datetime import datetime
from typing import List, Optional

from bson import ObjectId

from app.services.mongo import mongo
from app.services import simhacli_service


async def start_github_sync(user_id: str, github_username: str, current_skills: list) -> str:
    """Start a SimhaCLI job to sync GitHub repos → resume suggestions."""
    job_id = simhacli_service.new_job_id()
    tmp_dir = tempfile.mkdtemp(prefix=f"ghsync_{user_id[:8]}_")
    output_file = os.path.join(tmp_dir, f"suggestions_{job_id[:8]}.json")

    skills_str = ", ".join(current_skills[:20])

    prompt = (
        f"Do the following in order: "
        f"1. web_fetch 'https://api.github.com/users/{github_username}/repos?sort=updated&per_page=10&type=owner' "
        f"2. For the top 5 most recently updated repos, web_fetch their README from "
        f"   'https://raw.githubusercontent.com/{github_username}/{{repo_name}}/main/README.md' "
        f"3. Also web_fetch 'https://api.github.com/users/{github_username}' for profile info "
        f"4. Analyze all the repos and READMEs. The user's current resume skills are: [{skills_str}]. "
        f"   Find: new projects worth adding to the resume, new technologies/skills not in the list above. "
        f"5. write_file 'suggestions_{job_id[:8]}.json' with a JSON array of suggestions, each object: "
        f'   {{"type": "new_project" or "new_skill", "title": "...", "description": "...", "tech": ["..."], "repo": "..."}} '
        f"   Output ONLY valid JSON array, no extra text."
    )

    await simhacli_service.start(job_id, prompt, cwd=tmp_dir)

    await mongo.db["github_sync_jobs"].insert_one({
        "jobId": job_id,
        "userId": user_id,
        "githubUsername": github_username,
        "outputFile": output_file,
        "status": "running",
        "createdAt": datetime.utcnow(),
    })

    return job_id


async def save_github_username(user_id: str, github_username: str) -> None:
    await mongo.db["github_connections"].update_one(
        {"userId": user_id},
        {"$set": {"githubUsername": github_username, "updatedAt": datetime.utcnow()},
         "$setOnInsert": {"userId": user_id, "createdAt": datetime.utcnow()}},
        upsert=True,
    )


async def get_github_username(user_id: str) -> Optional[str]:
    doc = await mongo.db["github_connections"].find_one({"userId": user_id})
    return doc.get("githubUsername") if doc else None


async def parse_and_save_suggestions(job_id: str) -> List[dict]:
    """Parse SimhaCLI output JSON and store as pending suggestions."""
    doc = await mongo.db["github_sync_jobs"].find_one({"jobId": job_id})
    if not doc:
        return []

    output_file = doc.get("outputFile", "")
    content = ""
    if output_file and os.path.exists(output_file):
        with open(output_file, "r") as f:
            content = f.read()
    else:
        full = simhacli_service.get_result(job_id) or ""
        # Try to extract JSON array from SimhaCLI output
        import re
        match = re.search(r'\[[\s\S]*\]', full)
        content = match.group(0) if match else "[]"

    try:
        suggestions = json.loads(content)
        if not isinstance(suggestions, list):
            suggestions = []
    except Exception:
        suggestions = []

    user_id = doc["userId"]
    for s in suggestions:
        await mongo.db["github_suggestions"].insert_one({
            "userId": user_id,
            "jobId": job_id,
            "type": s.get("type", "new_project"),
            "title": s.get("title", ""),
            "description": s.get("description", ""),
            "tech": s.get("tech", []),
            "repo": s.get("repo", ""),
            "status": "pending",
            "createdAt": datetime.utcnow(),
        })

    await mongo.db["github_sync_jobs"].update_one(
        {"jobId": job_id}, {"$set": {"status": "done"}}
    )
    return suggestions


async def get_pending_suggestions(user_id: str) -> List[dict]:
    cursor = mongo.db["github_suggestions"].find(
        {"userId": user_id, "status": "pending"}
    ).sort("createdAt", -1).limit(20)
    docs = await cursor.to_list(20)
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


async def update_suggestion_status(suggestion_id: str, user_id: str, status: str) -> None:
    await mongo.db["github_suggestions"].update_one(
        {"_id": ObjectId(suggestion_id), "userId": user_id},
        {"$set": {"status": status}}
    )
