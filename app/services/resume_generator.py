# app/services/resume_generator.py
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4

from app.models.resume.template import TemplateOut  # your real model
from datetime import datetime
import json
import logging
from typing import Dict, Any, Optional
from app.config import settings

logger = logging.getLogger(__name__)


def _call_ai(prompt, temperature=1.0, max_tokens=8192):
    from app.services.ai_provider_service import call_ai
    return call_ai(prompt, temperature=temperature, max_tokens=max_tokens)

class ResumeGenerator:
    """
    Dynamic resume PDF generator.
    - Uses template.section_order to determine order
    - Uses content keys to render sections
    - Applies global template styling (margins, colors, alignment)
    - No hard-coded section names except for header logic
    """

    @staticmethod
    async def generate_resume(
        resume_data: Dict,
        template_data: Dict,
        format: str = "pdf"
    ) -> StreamingResponse:
        if format != "pdf":
            raise HTTPException(400, "Only PDF format is supported in this version")

        # Load models
        template = TemplateOut(**template_data)
        content = resume_data.get("content", {})
        personal_info = content.get("personal_info", {})
        full_name = personal_info.get("full_name", "Resume")

        # Build dynamic HTML
        html = f"""
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                @page {{
                    size: A4;
                    margin: {template.margins.top}in {template.margins.right}in 
                            {template.margins.bottom}in {template.margins.left}in;
                }}
                body {{
                    font-family: Arial, Helvetica, sans-serif;
                    font-size: 11pt;
                    line-height: 1.4;
                    color: #333;
                    margin: 0;
                }}
                .header {{
                    text-align: {template.header_alignment};
                    margin-bottom: 25px;
                }}
                h1 {{
                    color: {template.primary_color};
                    font-size: 24pt;
                    margin: 0 0 5px 0;
                }}
                .title {{
                    font-size: 14pt;
                    color: {template.secondary_color or '#555'};
                    margin: 0 0 8px 0;
                }}
                .contact {{
                    font-size: 10pt;
                    color: {template.secondary_color or '#777'};
                }}
                h2 {{
                    color: {template.primary_color};
                    font-size: 16pt;
                    border-bottom: 1px solid {template.primary_color}80;
                    padding-bottom: 4px;
                    margin: 25px 0 10px 0;
                }}
                .section-item {{
                    margin-bottom: 12px;
                }}
                .item-title {{
                    font-weight: bold;
                    margin-bottom: 2px;
                }}
                .dates {{
                    font-style: italic;
                    color: #555;
                    font-size: 10pt;
                    margin-bottom: 4px;
                }}
                ul {{
                    margin: 4px 0 8px 20px;
                    padding-left: 0;
                }}
                li {{
                    margin-bottom: 4px;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>{full_name}</h1>
                <div class="title">{personal_info.get("title", "")}</div>
                <div class="contact">
                    {personal_info.get("email", "")} • {personal_info.get("phone", "")} • {personal_info.get("location", "")}
                </div>
            </div>

            <!-- Render sections dynamically from template order -->
        """

        # Use section_order from template
        section_order = template.section_order or []

        for section_name in section_order:
            if section_name not in content or not content[section_name]:
                continue

            # Human-readable title
            section_title = section_name.replace("_", " ").title()
            html += f'<h2>{section_title}</h2>'

            items = content[section_name]
            if not isinstance(items, list):
                items = [items]  # handle single-object sections

            for item in items:
                html += '<div class="section-item">'

                # Generic rendering for most sections
                if isinstance(item, dict):
                    # Try common keys
                    if "title" in item or "degree" in item or "name" in item:
                        title_key = next((k for k in ["title", "degree", "name"] if k in item), None)
                        if title_key:
                            html += f'<div class="item-title">{item[title_key]}</div>'

                    if "company" in item or "institution" in item:
                        org = item.get("company") or item.get("institution", "")
                        html += f'<div>{org}</div>'

                    if "dates" in item:
                        html += f'<div class="dates">{item["dates"]}</div>'

                    if "bullets" in item and isinstance(item["bullets"], list):
                        html += '<ul>'
                        for bullet in item["bullets"]:
                            html += f'<li>{bullet}</li>'
                        html += '</ul>'

                    elif "description" in item:
                        if isinstance(item["description"], list):
                            html += '<ul>'
                            for line in item["description"]:
                                html += f'<li>{line}</li>'
                            html += '</ul>'
                        else:
                            html += f'<p>{item["description"]}</p>'

                    else:
                        # Fallback: show all key-value pairs
                        for k, v in item.items():
                            if k not in ["title", "degree", "name", "company", "institution", "dates", "bullets", "description"]:
                                html += f'<div><strong>{k.replace("_", " ").title()}:</strong> {v}</div>'

                else:
                    # Simple string/number
                    html += f'<p>{item}</p>'

                html += '</div>'

        html += """
        </body>
        </html>
        """

        # Generate PDF
        pdf_buffer = BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = [Paragraph(html, styles["Normal"])]
        doc.build(story)
        pdf_buffer.seek(0)

        # Filename
        filename = f"{full_name.replace(' ', '_')}_Resume.pdf"

        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    # ── Add these inside class ResumeGenerator ───────────────────────────────

    @staticmethod
    async def enhance_resume_content(
        resume_data: Dict,
        job_description: Optional[str] = None,
        tone: str = "professional",
        focus_quantifiable: bool = True
    ) -> Dict:
        """
        Use Gemini to improve/enrich resume content:
        - Make bullets more impactful
        - Add quantifiable achievements when possible
        - Tailor to job description if provided
        - Adjust tone (professional / confident / concise / creative)
        Returns updated resume_data dict (same structure)
        """
        content = resume_data.get("content", {})
        if not content:
            raise HTTPException(400, "No resume content provided")

        # Flatten content for prompt (or send sections separately)
        resume_text = json.dumps(content, indent=2)

        prompt = f"""You are an expert resume writer.
    Improve this resume content to be more impactful, ATS-friendly and recruiter-attractive.
    Rules:
    - Use strong action verbs
    - Quantify achievements wherever logical (add realistic numbers if missing but plausible)
    - Keep factual – do NOT invent experience
    - { "Tailor to this job description by emphasizing matching keywords/skills:" + job_description if job_description else ""}
    - Use {tone} tone
    - Keep structure identical (same keys)

    Return ONLY valid JSON with the improved "content" object. No extra text.

    Current content:
    {resume_text}
    """

        try:
            improved = _call_ai(prompt, temperature=0.25, max_tokens=3000)
            improved_content = improved.get("content", improved)  # in case model returns flat dict

            # Merge back (preserve original structure where possible)
            resume_data["content"] = improved_content
            return resume_data

        except Exception as e:
            logger.exception("Content enhancement failed")
            raise HTTPException(500, f"AI enhancement failed: {str(e)}")


    @staticmethod
    async def generate_ats_optimized_version(
        resume_data: Dict,
        job_description: str,
        max_bullets_per_role: int = 6
    ) -> Dict:
        """
        Create ATS-safe version:
        - Heavy keyword inclusion from job desc
        - Simple formatting assumptions
        - Limit bullets to avoid dilution
        Returns modified copy of resume_data
        """
        # First extract keywords via Gemini (or use previous parse-job endpoint)
        parse_prompt = f"""Extract important keywords, skills, technologies from this job description.
    Return ONLY JSON: {{"keywords": list[str], "must_have_skills": list[str]}}

    Job: {job_description}
    """

        keywords_data = _call_ai(parse_prompt, temperature=0.1, max_tokens=600)
        keywords = set(keywords_data.get("keywords", []) + keywords_data.get("must_have_skills", []))

        # Now enhance content with keywords
        content = resume_data.get("content", {})
        for section in content.values():
            if isinstance(section, list):
                for item in section:
                    if isinstance(item, dict) and "bullets" in item:
                        item["bullets"] = [
                            bullet for bullet in item["bullets"][:max_bullets_per_role]
                            # Simple heuristic: inject keywords if missing (careful!)
                        ]  # → here you can call Gemini per section if needed

        # Or full re-generation similar to enhance_resume_content but stricter
        resume_data["content"] = await ResumeGenerator.enhance_resume_content(
            resume_data,
            job_description=job_description,
            tone="concise",
            focus_quantifiable=True
        )["content"]

        resume_data["ats_optimized"] = True  # flag
        return resume_data


    @staticmethod
    async def generate_html_preview(
        resume_data: Dict,
        template_data: Dict,
        inline_css: bool = True
    ) -> str:
        """
        Generate HTML string for frontend preview (without PDF conversion)
        Useful for instant preview before final PDF download
        """
        # Reuse most of your existing HTML building logic
        # ... (extract the HTML construction part into a helper)
        # For simplicity, return the same html string you build in generate_resume

        # Example (you can refactor your current html building code into this method)
        template = TemplateOut(**template_data)
        # ... build html the same way ...

        return html  # just the <html>...</html> string


    @staticmethod
    async def generate_resume_docx(
        resume_data: Dict,
        template_data: Dict
    ) -> StreamingResponse:
        """
        Future: support DOCX export (many ATS prefer .docx over PDF in 2025–2026)
        Requires python-docx or mammoth + styling approximation
        """
        raise HTTPException(501, "DOCX export not implemented yet")
        # Placeholder – implement later with:
        # from docx import Document
        # doc = Document()
        # ... build paragraphs, runs with styles ...


    @staticmethod
    def validate_resume_data(resume_data: Dict) -> None:
        """
        Basic validation before generation
        Prevents common WeasyPrint crashes or ugly PDFs
        """
        content = resume_data.get("content", {})
        if not content.get("personal_info", {}).get("full_name"):
            raise HTTPException(400, "Full name is required")
        # Add more: email format, dates consistency, etc.