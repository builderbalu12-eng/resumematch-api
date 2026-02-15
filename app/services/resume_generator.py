# app/services/resume_generator.py
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from io import BytesIO
from weasyprint import HTML
from typing import Dict, Any
from app.models.resume.template import TemplateOut  # your real model
from datetime import datetime


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
        HTML(string=html).write_pdf(pdf_buffer)
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