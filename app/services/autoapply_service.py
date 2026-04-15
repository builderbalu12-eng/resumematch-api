import os
import tempfile
from datetime import datetime

from app.services.mongo import mongo
from app.services import simhacli_service


async def start_auto_apply(
    user_id: str,
    job_url: str,
    name: str,
    email: str,
    phone: str,
    cover_letter: str,
) -> str:
    """Start a SimhaCLI + Playwright job to auto-apply to a job posting."""
    job_id = simhacli_service.new_job_id()
    tmp_dir = tempfile.mkdtemp(prefix=f"apply_{user_id[:8]}_")

    prompt = (
        f"Use Playwright browser automation to apply to the job at this URL: {job_url} "
        f"Follow these steps carefully: "
        f"1. Navigate to the job URL and wait for the page to load. "
        f"2. Look for an 'Apply', 'Apply Now', or 'Easy Apply' button and click it. "
        f"3. If a login/sign-up form appears first, report that login is required and stop. "
        f"4. Fill in any form fields you find: "
        f"   - Name / Full Name: {name} "
        f"   - Email: {email} "
        f"   - Phone: {phone} "
        f"5. If there is a cover letter or message field, fill it with: {cover_letter[:500]} "
        f"6. If there is a resume upload field, note that the user should upload manually. "
        f"7. Look for a Submit or Apply button and click it. "
        f"8. Confirm submission was successful by checking for confirmation text. "
        f"9. Report each step as you complete it with a ✓ or ✗ prefix."
    )

    await simhacli_service.start(job_id, prompt, cwd=tmp_dir)

    await mongo.db["auto_apply_jobs"].insert_one({
        "jobId": job_id,
        "userId": user_id,
        "jobUrl": job_url,
        "applicantName": name,
        "applicantEmail": email,
        "status": "running",
        "createdAt": datetime.utcnow(),
    })

    return job_id


async def get_apply_status(job_id: str, user_id: str) -> dict:
    doc = await mongo.db["auto_apply_jobs"].find_one({"jobId": job_id, "userId": user_id})
    if not doc:
        return {"status": "not_found"}

    full_output = simhacli_service.get_result(job_id)
    error = simhacli_service.get_error(job_id)

    return {
        "jobId": job_id,
        "jobUrl": doc.get("jobUrl"),
        "status": doc.get("status"),
        "output": full_output,
        "error": error,
    }
