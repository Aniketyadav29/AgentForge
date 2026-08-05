"""Create downloadable PDF versions of Markdown research reports."""

from __future__ import annotations

import io
import re
from html import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _pdf_safe(text: str) -> str:
    replacements = str.maketrans({
        "–": "-",
        "—": "-",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "…": "...",
        "•": "-",
    })
    return text.translate(replacements).encode("latin-1", "replace").decode("latin-1")


def _inline_markup(text: str) -> str:
    safe_text = escape(_pdf_safe(text.strip()))
    safe_text = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', safe_text)
    safe_text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe_text)
    safe_text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<link href="\2" color="#1f5f99">\1</link>', safe_text)
    return safe_text


def _page_chrome(canvas, document) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#d7dde5"))
    canvas.line(document.leftMargin, 0.68 * inch, A4[0] - document.rightMargin, 0.68 * inch)
    canvas.setFillColor(colors.HexColor("#52616f"))
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(document.leftMargin, 0.46 * inch, "AgentForge Research Export")
    canvas.drawRightString(A4[0] - document.rightMargin, 0.46 * inch, f"Page {document.page}")
    canvas.restoreState()


def _build_table(lines: list[str], styles: dict) -> Table | None:
    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells):
            continue
        rows.append([Paragraph(_inline_markup(cell), styles["table"]) for cell in cells])
    if not rows:
        return None

    column_count = max(len(row) for row in rows)
    normalized_rows = [row + [Paragraph("", styles["table"])] * (column_count - len(row)) for row in rows]
    usable_width = A4[0] - 1.45 * inch
    table = Table(normalized_rows, colWidths=[usable_width / column_count] * column_count, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf2f8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#183b56")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c7d3df")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def build_research_pdf(title: str, markdown: str) -> bytes:
    """Render a Markdown research report as a paginated PDF document."""
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=27,
        textColor=colors.HexColor("#17324d"),
        spaceAfter=16,
    ))
    styles.add(ParagraphStyle(
        name="ReportHeading1",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=19,
        textColor=colors.HexColor("#17324d"),
        spaceBefore=16,
        spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="ReportHeading2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#24567a"),
        spaceBefore=12,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="ReportBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=10,
        leading=15,
        textColor=colors.HexColor("#28343f"),
        spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="ReportTable",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#28343f"),
    ))
    styles.add(ParagraphStyle(
        name="ReportList",
        parent=styles["ReportBody"],
        leftIndent=18,
        firstLineIndent=-10,
        spaceAfter=4,
    ))

    stream = io.BytesIO()
    document = SimpleDocTemplate(
        stream,
        pagesize=A4,
        rightMargin=0.72 * inch,
        leftMargin=0.72 * inch,
        topMargin=0.72 * inch,
        bottomMargin=0.85 * inch,
        title=_pdf_safe(title),
        author="AgentForge",
    )
    style_map = {
        "title": styles["ReportTitle"],
        "heading1": styles["ReportHeading1"],
        "heading2": styles["ReportHeading2"],
        "body": styles["ReportBody"],
        "list": styles["ReportList"],
        "table": styles["ReportTable"],
    }
    story = [Paragraph(_inline_markup(title), style_map["title"]), Spacer(1, 4)]
    lines = markdown.splitlines()
    index = 0

    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue
        if line.startswith("|"):
            table_lines = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index])
                index += 1
            table = _build_table(table_lines, style_map)
            if table:
                story.extend([table, Spacer(1, 10)])
            continue
        if re.fullmatch(r"[-*_]{3,}", line):
            story.append(Spacer(1, 8))
            index += 1
            continue
        if line.startswith("### "):
            story.append(Paragraph(_inline_markup(line[4:]), style_map["heading2"]))
            index += 1
            continue
        if line.startswith("## "):
            story.append(Paragraph(_inline_markup(line[3:]), style_map["heading1"]))
            index += 1
            continue
        if line.startswith("# "):
            story.append(Paragraph(_inline_markup(line[2:]), style_map["title"]))
            index += 1
            continue
        if re.match(r"^[-*+]\s+", line):
            while index < len(lines) and re.match(r"^[-*+]\s+", lines[index].strip()):
                item_text = re.sub(r"^[-*+]\s+", "", lines[index].strip())
                story.append(Paragraph(f"- {_inline_markup(item_text)}", style_map["list"]))
                index += 1
            story.append(Spacer(1, 4))
            continue
        if re.match(r"^\d+\.\s+", line):
            while index < len(lines) and re.match(r"^\d+\.\s+", lines[index].strip()):
                item_text = lines[index].strip()
                story.append(Paragraph(_inline_markup(item_text), style_map["list"]))
                index += 1
            story.append(Spacer(1, 4))
            continue

        paragraph_lines = [line]
        index += 1
        while index < len(lines):
            next_line = lines[index].strip()
            if not next_line or next_line.startswith("#") or next_line.startswith("|") or re.match(r"^[-*+]\s+|^\d+\.\s+|^[-*_]{3,}$", next_line):
                break
            paragraph_lines.append(next_line)
            index += 1
        story.append(Paragraph(_inline_markup(" ".join(paragraph_lines)), style_map["body"]))

    document.build(story, onFirstPage=_page_chrome, onLaterPages=_page_chrome)
    return stream.getvalue()
