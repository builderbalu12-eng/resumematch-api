import os
import tempfile
from datetime import datetime
from typing import Optional

from app.services.mongo import mongo
from app.services import simhacli_service


async def generate_interview_prep(
    user_id: str,
    company: str,
    job_title: str,
    matched_keywords: list,
    resume_summary: str,
    resume_skills: list,
) -> str:
    """Start a SimhaCLI job to generate personalised interview Q&A."""
    job_id = simhacli_service.new_job_id()

    tmp_dir = tempfile.mkdtemp(prefix=f"interview_{user_id[:8]}_")
    output_file = os.path.join(tmp_dir, f"prep_{job_id[:8]}.md")

    skills_str = ", ".join(resume_skills[:15])
    keywords_str = ", ".join(matched_keywords[:15])

    prompt = (
        f"Do the following tasks in order: "
        f"1. web_search '{company} software engineering interview questions 2025' "
        f"2. web_search '{company} engineering culture values team' "
        f"3. web_search '{job_title} technical interview questions' "
        f"4. Based on all research, generate exactly 20 personalised interview questions "
        f"   and detailed model answers for a candidate applying to {company} as {job_title}. "
        f"   Candidate background: skills are [{skills_str}], "
        f"   matched keywords: [{keywords_str}], "
        f"   summary: {resume_summary[:200]}. "
        f"   Structure the output as clean Markdown with 4 sections: "
        f"   ## Behavioral (5 Q&A), ## Technical (7 Q&A), "
        f"   ## Role-Specific (5 Q&A), ## Questions to Ask Them (3 Q&A). "
        f"5. write_file 'prep_{job_id[:8]}.md' with the full markdown content."
    )

    await simhacli_service.start(job_id, prompt, cwd=tmp_dir)

    # Store job metadata so we can retrieve the result later
    await mongo.db["interview_preps"].insert_one({
        "jobId": job_id,
        "userId": user_id,
        "company": company,
        "jobTitle": job_title,
        "outputFile": output_file,
        "status": "running",
        "createdAt": datetime.utcnow(),
    })

    return job_id


async def get_prep_result(job_id: str) -> Optional[str]:
    """Read the generated markdown file after SimhaCLI completes."""
    doc = await mongo.db["interview_preps"].find_one({"jobId": job_id})
    if not doc:
        return None

    output_file = doc.get("outputFile", "")
    if output_file and os.path.exists(output_file):
        with open(output_file, "r") as f:
            content = f.read()
        # Also update status
        await mongo.db["interview_preps"].update_one(
            {"jobId": job_id},
            {"$set": {"status": "done", "content": content}}
        )
        return content

    # Fallback: content stored in DB
    return doc.get("content")
