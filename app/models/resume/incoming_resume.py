# app/models/resume/incoming_resume.py
from pydantic import BaseModel
from datetime import datetime
from typing import Dict, Optional

class IncomingResume(BaseModel):
    user_id: str
    raw_input: str                    # base64 or plain text (for debugging)
    extracted_data: Dict              # whatever Claude returns (no fixed schema)
    created_at: datetime
    updated_at: datetime
    master_resume_text: Optional[str] = None  # raw text explicitly saved by user (free, no AI)