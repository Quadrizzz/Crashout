# app/api/routes/report.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.deps import get_db
from app.db.models import User, Session, DatasetProfile, Message, AnalysisResult
from app.api.routes.auth import get_current_user
from app.llm import Gemini
from langchain_core.messages import HumanMessage, SystemMessage
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from io import BytesIO
import matplotlib
matplotlib.use("Agg")  # non-interactive backend — required for server use
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

router = APIRouter()

llm = Gemini(model="gemini-2.5-flash").llm

INDIGO = "#6366f1"
PURPLE = "#8b5cf6"
CHART_COLORS = ["#6366f1", "#8b5cf6", "#a78bfa", "#c4b5fd", "#ddd6fe"]
BG_COLOR = "#0f0f14"
GRID_COLOR = "#1f2937"
TEXT_COLOR = "#9ca3af"


def _render_chart(chart_config: dict) -> BytesIO | None:
    """Render a chart config to a PNG image buffer using matplotlib."""
    try:
        chart_type = chart_config.get("chart_type") or chart_config.get("type")
        data = chart_config.get("data", [])
        x_key = chart_config.get("x_axis_key") or chart_config.get("xKey")
        y_keys = chart_config.get("y_axis_keys") or [chart_config.get("yKey")]
        y_key = y_keys[0] if y_keys else None
        title = chart_config.get("title", "")

        if not data or not x_key or not y_key:
            return None

        x_vals = [str(d.get(x_key, "")) for d in data]
        y_vals = [float(d.get(y_key, 0)) for d in data]

        fig, ax = plt.subplots(figsize=(7, 3.2))
        fig.patch.set_facecolor("white")
        ax.set_facecolor("#fafafa")

        if chart_type == "bar":
            bars = ax.bar(x_vals, y_vals, color=INDIGO, edgecolor="white", linewidth=0.5, width=0.6)
            ax.set_xlabel(x_key, fontsize=8, color="#6b7280")
            ax.set_ylabel(y_key, fontsize=8, color="#6b7280")
            ax.tick_params(axis="x", rotation=20, labelsize=7)
            ax.tick_params(axis="y", labelsize=7)
            ax.grid(axis="y", color="#e5e7eb", linewidth=0.5)
            ax.set_axisbelow(True)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)

        elif chart_type in ("line", "area"):
            ax.plot(x_vals, y_vals, color=INDIGO, linewidth=2, marker="o", markersize=3)
            if chart_type == "area":
                ax.fill_between(range(len(x_vals)), y_vals, alpha=0.15, color=INDIGO)
            ax.set_xlabel(x_key, fontsize=8, color="#6b7280")
            ax.set_ylabel(y_key, fontsize=8, color="#6b7280")
            ax.tick_params(axis="x", rotation=20, labelsize=7)
            ax.tick_params(axis="y", labelsize=7)
            ax.grid(color="#e5e7eb", linewidth=0.5)
            ax.set_axisbelow(True)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)

        elif chart_type == "scatter":
            ax.scatter(x_vals, y_vals, color=INDIGO, alpha=0.7, s=30)
            ax.set_xlabel(x_key, fontsize=8, color="#6b7280")
            ax.set_ylabel(y_key, fontsize=8, color="#6b7280")
            ax.tick_params(labelsize=7)
            ax.grid(color="#e5e7eb", linewidth=0.5)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)

        elif chart_type == "pie":
            wedges, texts, autotexts = ax.pie(
                y_vals,
                labels=x_vals,
                colors=CHART_COLORS[:len(y_vals)],
                autopct="%1.1f%%",
                startangle=90,
                pctdistance=0.8,
            )
            for text in texts:
                text.set_fontsize(7)
            for autotext in autotexts:
                autotext.set_fontsize(6)
                autotext.set_color("white")
            ax.axis("equal")

        if title:
            ax.set_title(title, fontsize=9, color="#1e1b4b", fontweight="bold", pad=8)

        plt.tight_layout(pad=1.0)

        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        buf.seek(0)
        return buf

    except Exception as e:
        print(f"Chart render error: {e}")
        plt.close("all")
        return None


async def _generate_report_narrative(
    filename: str,
    profile: DatasetProfile,
    qa_pairs: list[dict],
) -> str:
    qa_text = "\n\n".join([
        f"Q: {pair['question']}\nA: {pair['answer']}"
        for pair in qa_pairs
    ])

    response = await llm.ainvoke([
        SystemMessage(content=(
            "You are a data analyst writing a professional analysis report. "
            "Given a dataset profile and a series of Q&A insights, write a concise "
            "executive summary and key findings section. Be factual and specific. "
            "Use plain text only — no markdown, no bullet symbols, no headers. "
            "Write in clear paragraphs."
        )),
        HumanMessage(content=(
            f"Dataset: {filename}\n"
            f"Rows: {profile.row_count}, Columns: {profile.column_count}\n"
            f"Summary: {profile.summary}\n\n"
            f"Analysis Q&A:\n{qa_text}\n\n"
            f"Write an executive summary (2-3 sentences) followed by key findings (3-5 sentences)."
        )),
    ])

    return response.content


def _build_pdf(
    filename: str,
    profile: DatasetProfile,
    narrative: str,
    qa_pairs: list[dict],
) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    title_style = ParagraphStyle(
        "Title", fontSize=20, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1e1b4b"), spaceAfter=10,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", fontSize=11, fontName="Helvetica",
        textColor=colors.HexColor("#6b7280"), spaceAfter=2,
    )
    section_style = ParagraphStyle(
        "Section", fontSize=13, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1e1b4b"), spaceBefore=14, spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "Body", fontSize=10, fontName="Helvetica",
        textColor=colors.HexColor("#374151"), leading=16, spaceAfter=6,
    )
    label_style = ParagraphStyle(
        "Label", fontSize=9, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#6366f1"), spaceAfter=2,
    )
    answer_style = ParagraphStyle(
        "Answer", fontSize=10, fontName="Helvetica",
        textColor=colors.HexColor("#374151"), leading=15, spaceAfter=6, leftIndent=10,
    )
    chart_note_style = ParagraphStyle(
        "ChartNote", fontSize=9, fontName="Helvetica-Oblique",
        textColor=colors.HexColor("#9ca3af"), spaceAfter=10, leftIndent=10,
    )
    footer_style = ParagraphStyle(
        "Footer", fontSize=8, fontName="Helvetica",
        textColor=colors.HexColor("#9ca3af"), alignment=TA_CENTER,
    )

    elements = []

    # header
    elements.append(Paragraph("Analysis Report", title_style))
    elements.append(Paragraph(filename, subtitle_style))
    elements.append(Spacer(1, 4 * mm))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#6366f1")))
    elements.append(Spacer(1, 6 * mm))

    # dataset overview
    elements.append(Paragraph("Dataset Overview", section_style))
    overview_data = [
        [Paragraph("Rows", label_style), Paragraph(f"{profile.row_count:,}", body_style)],
        [Paragraph("Columns", label_style), Paragraph(str(profile.column_count), body_style)],
        [Paragraph("Summary", label_style), Paragraph(profile.summary, body_style)],
    ]
    if profile.quality_flags:
        overview_data.append([
            Paragraph("Quality Flags", label_style),
            Paragraph("<br/>".join(profile.quality_flags), body_style)
        ])

    overview_table = Table(overview_data, colWidths=[40 * mm, 130 * mm])
    overview_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#6366f1")),
        ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#374151")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor("#f5f3ff"), colors.white]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    elements.append(overview_table)
    elements.append(Spacer(1, 4 * mm))

    # executive summary
    elements.append(Paragraph("Executive Summary", section_style))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e5e7eb")))
    elements.append(Spacer(1, 3 * mm))
    elements.append(Paragraph(narrative, body_style))
    elements.append(Spacer(1, 4 * mm))

    # Q&A insights with charts
    if qa_pairs:
        elements.append(Paragraph("Analysis Insights", section_style))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e5e7eb")))
        elements.append(Spacer(1, 3 * mm))

        for i, pair in enumerate(qa_pairs, 1):
            elements.append(Paragraph(f"Q{i}: {pair['question']}", label_style))
            elements.append(Paragraph(pair["answer"], answer_style))

            # render chart image if chart config exists
            if pair.get("chart_config"):
                chart_buf = _render_chart(pair["chart_config"])
                if chart_buf:
                    img = Image(chart_buf, width=170 * mm, height=78 * mm)
                    elements.append(img)
                    elements.append(Spacer(1, 3 * mm))
                elif pair.get("chart_title"):
                    elements.append(Paragraph(f"Chart: {pair['chart_title']}", chart_note_style))

            elements.append(Spacer(1, 2 * mm))

    # footer
    elements.append(Spacer(1, 8 * mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e5e7eb")))
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph("Generated by Crashout — AI Data Analysis", footer_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer


@router.get("/sessions/{session_id}/report")
async def generate_report(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session_result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == user.id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    profile_result = await db.execute(
        select(DatasetProfile).where(DatasetProfile.session_id == session_id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    messages_result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
    )
    messages = messages_result.scalars().all()

    # pair user questions with assistant answers + chart configs
    qa_pairs = []
    for i, msg in enumerate(messages):
        if msg.role == "user" and i + 1 < len(messages) and messages[i + 1].role == "assistant":
            assistant_msg = messages[i + 1]

            ar_result = await db.execute(
                select(AnalysisResult).where(AnalysisResult.message_id == assistant_msg.id)
            )
            ar = ar_result.scalar_one_or_none()

            chart_config = ar.chart_config if ar else None
            chart_title = None
            if chart_config:
                chart_title = chart_config.get("title") or chart_config.get("chart_title")

            qa_pairs.append({
                "question": msg.content,
                "answer": assistant_msg.content,
                "chart_config": chart_config,
                "chart_title": chart_title,
            })

    if not qa_pairs:
        raise HTTPException(status_code=400, detail="No analysis found for this session")

    narrative = await _generate_report_narrative(session.filename, profile, qa_pairs)
    pdf_buffer = _build_pdf(session.filename, profile, narrative, qa_pairs)

    filename = session.filename.rsplit(".", 1)[0]

    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}_report.pdf"'
        }
    )