import json
import os
import tempfile
from datetime import datetime
from typing import Optional

from app.services.mongo import mongo
from app.services import simhacli_service


async def generate_portfolio(user_id: str, resume_json: dict) -> str:
    """
    Starts a SimhaCLI job to scaffold + deploy a portfolio site.
    Returns the job_id for SSE streaming.
    """
    job_id = simhacli_service.new_job_id()

    # Write resume JSON to a temp file SimhaCLI can read
    tmp_dir = tempfile.mkdtemp(prefix=f"portfolio_{user_id[:8]}_")
    resume_path = os.path.join(tmp_dir, "resume.json")
    with open(resume_path, "w") as f:
        json.dump(resume_json, f, indent=2, default=str)

    contact = resume_json.get("contact", {})
    name = f"{contact.get('firstName', '')} {contact.get('lastName', '')}".strip() or contact.get("name", "My Portfolio")
    email = contact.get("email", "")
    skills = ", ".join((resume_json.get("skills") or [])[:10])
    summary = resume_json.get("summary", "")[:300]

    prompt = (
        f"Create a professional portfolio website for {name}. "
        f"Read the resume data from the file 'resume.json' in the current directory. "
        f"Use React + Vite + Tailwind CSS. "
        f"Create these components: Hero (name, title, contact links), "
        f"About (summary), Experience (work history), Projects (project cards), "
        f"Skills (tag cloud), Contact (email button). "
        f"Make it dark-themed, modern, and responsive. "
        f"After scaffolding all files, run 'npm install' then 'npm run build'. "
        f"Then deploy to Vercel using the vercel CLI: 'vercel deploy --prod'. "
        f"Print the final deployed URL clearly at the end."
    )

    await simhacli_service.start(job_id, prompt, cwd=tmp_dir)
    return job_id


async def save_portfolio_url(user_id: str, url: str) -> None:
    await mongo.db["portfolios"].update_one(
        {"userId": user_id},
        {"$set": {"url": url, "updatedAt": datetime.utcnow()},
         "$setOnInsert": {"userId": user_id, "createdAt": datetime.utcnow()}},
        upsert=True,
    )


async def get_portfolio(user_id: str) -> Optional[dict]:
    doc = await mongo.db["portfolios"].find_one({"userId": user_id})
    if doc:
        doc.pop("_id", None)
    return doc
