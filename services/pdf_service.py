"""PDF services: text extraction (input) and study-notes generation (output).

- extract_text / get_page_count: extract text from uploaded PDF/TXT files.
- build_pdf / safe_filename: generate a formatted PDF from AI study notes.
"""
import io
import os
import re

import config

# ── PDF text extraction (input) ─────────────────────────────────────────


def extract_text(stream, ext):
    """Extract text from PDF or TXT file with validation."""
    if ext == "txt":
        text = stream.read().decode("utf-8", errors="ignore")
    elif ext == "pdf":
        from pypdf import PdfReader
        try:
            reader = PdfReader(stream)
            # Validate page count
            if len(reader.pages) > config.MAX_PDF_PAGES:
                raise ValueError(f"PDF exceeds {config.MAX_PDF_PAGES} pages (has {len(reader.pages)}).")
            text = "\n".join((p.extract_text() or "") for p in reader.pages)
        except ValueError:
            raise
        except Exception:
            raise ValueError("Could not read this PDF (corrupt or encrypted).")
    else:
        raise ValueError("Unsupported file format.")

    text = text.strip()
    if not text:
        raise ValueError("No extractable text found (empty file or scanned PDF).")
    return text


def get_page_count(stream, ext):
    """Get PDF page count without extracting all text. Returns 1 for TXT."""
    if ext == "txt":
        return 1
    from pypdf import PdfReader
    try:
        return len(PdfReader(stream).pages)
    except Exception:
        raise ValueError("Could not read this PDF (corrupt or encrypted).")


# ── PDF generation (output) ────────────────────────────────────────────

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (HRFlowable, ListFlowable, ListItem,
                                Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

# ── Font registration (Unicode support) ─────────────────────────────────

_FONT_REGISTERED = False


def _register_fonts():
    """Register a Unicode TTF font so special characters render correctly.

    Falls back to ReportLab's built-in Helvetica if no system TTF is found.
    """
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return
    candidates = [
        # Windows
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        # macOS
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("NotesFont", path))
                _FONT_REGISTERED = True
                return
            except Exception:
                continue
    # Fallback: Helvetica (Latin-1 only, but always available)
    _FONT_REGISTERED = True


# ── Styles ──────────────────────────────────────────────────────────────

def _build_styles():
    """Create a consistent set of paragraph styles for the document."""
    _register_fonts()
    base = "NotesFont"
    ss = getSampleStyleSheet()

    styles = {
        "title": ParagraphStyle(
            "NotesTitle", parent=ss["Title"], fontName=base, fontSize=20,
            leading=26, alignment=TA_CENTER, spaceAfter=6,
            textColor=colors.HexColor("#1a1a2e")),
        "subtitle": ParagraphStyle(
            "NotesSubtitle", parent=ss["Normal"], fontName=base, fontSize=11,
            leading=15, alignment=TA_CENTER, spaceAfter=16,
            textColor=colors.HexColor("#555555")),
        "h1": ParagraphStyle(
            "NotesH1", parent=ss["Heading1"], fontName=base, fontSize=15,
            leading=20, spaceBefore=18, spaceAfter=8,
            textColor=colors.HexColor("#2c3e50")),
        "h2": ParagraphStyle(
            "NotesH2", parent=ss["Heading2"], fontName=base, fontSize=12.5,
            leading=17, spaceBefore=12, spaceAfter=6,
            textColor=colors.HexColor("#34495e")),
        "body": ParagraphStyle(
            "NotesBody", parent=ss["Normal"], fontName=base, fontSize=10.5,
            leading=15, alignment=TA_JUSTIFY, spaceAfter=6),
        "bullet": ParagraphStyle(
            "NotesBullet", parent=ss["Normal"], fontName=base, fontSize=10.5,
            leading=15, alignment=TA_LEFT, spaceAfter=3,
            leftIndent=18, bulletIndent=6),
        "formula": ParagraphStyle(
            "NotesFormula", parent=ss["Normal"], fontName=base, fontSize=11,
            leading=16, alignment=TA_CENTER, spaceBefore=4, spaceAfter=8,
            textColor=colors.HexColor("#2c3e50")),
        "definition_term": ParagraphStyle(
            "NotesDefTerm", parent=ss["Normal"], fontName=base, fontSize=10.5,
            leading=15, alignment=TA_LEFT, spaceAfter=2,
            textColor=colors.HexColor("#2c3e50")),
        "footer": ParagraphStyle(
            "NotesFooter", parent=ss["Normal"], fontName=base, fontSize=8.5,
            leading=11, alignment=TA_CENTER, textColor=colors.HexColor("#888888")),
    }
    return styles


# ── Helpers ─────────────────────────────────────────────────────────────

def _escape(text):
    """Escape XML special characters for ReportLab Paragraph markup."""
    text = str(text)
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def _inline_format(text):
    """Convert simple Markdown bold/italic to ReportLab inline markup."""
    text = _escape(text)
    # Bold: **text** -> <b>text</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # Italic: *text* -> <i>text</i>  (single asterisk, not double)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)
    # Inline code: `text` -> <font face="Courier">text</font>
    text = re.sub(r"`(.+?)`", r'<font face="Courier">\1</font>', text)
    return text


def _bullet_list(items, style):
    """Build a bulleted list flowable from a list of strings."""
    items = [ListItem(Paragraph(_inline_format(t), style), leftIndent=12)
             for t in items]
    return ListFlowable(items, bulletType="bullet", bulletFontSize=8,
                        leftIndent=18, spaceBefore=2, spaceAfter=6)


def _numbered_list(items, style):
    """Build a numbered list flowable from a list of strings."""
    items = [ListItem(Paragraph(_inline_format(t), style), leftIndent=12)
             for t in items]
    return ListFlowable(items, bulletType="1", bulletFontSize=9,
                        leftIndent=22, spaceBefore=2, spaceAfter=6)


def _make_table(rows, col_widths=None):
    """Build a styled table from a list of row lists."""
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, -1), "NotesFont"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTSIZE", (0, 1), (-1, -1), 9.5),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f8f9fa")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


# ── Page decoration ─────────────────────────────────────────────────────

def _on_page(canvas, doc):
    """Draw page number footer on every page."""
    canvas.saveState()
    canvas.setFont("NotesFont", 8.5)
    canvas.setFillColor(colors.HexColor("#888888"))
    page_num = canvas.getPageNumber()
    canvas.drawCentredString(A4[0] / 2, 1.2 * cm, f"Page {page_num}")
    # Header line
    canvas.setStrokeColor(colors.HexColor("#dee2e6"))
    canvas.setLineWidth(0.5)
    canvas.line(2 * cm, A4[1] - 1.5 * cm, A4[0] - 2 * cm, A4[1] - 1.5 * cm)
    canvas.restoreState()


# ── Main PDF builder ────────────────────────────────────────────────────

def build_pdf(summary, material_name):
    """Build a complete PDF document from a summary dict.

    Args:
        summary: dict with keys like title, overview, key_concepts, etc.
        material_name: str, used for the document header.

    Returns:
        bytes: the complete PDF file content.
    """
    _register_fonts()
    styles = _build_styles()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2.2 * cm, bottomMargin=2 * cm,
        title=str(summary.get("title", "Study Notes")),
        author="AI Study Assistant",
    )

    story = []

    # ── Title block ──────────────────────────────────────────────────
    title = str(summary.get("title", "Study Notes"))
    story.append(Paragraph(_escape(title), styles["title"]))
    story.append(Paragraph(_escape(material_name), styles["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1,
                            color=colors.HexColor("#2c3e50"),
                            spaceAfter=12))

    # ── Overview ─────────────────────────────────────────────────────
    overview = summary.get("overview")
    if overview:
        story.append(Paragraph("Overview", styles["h1"]))
        story.append(Paragraph(_inline_format(overview), styles["body"]))

    # ── Sections (title + content pairs) ─────────────────────────────
    for section in summary.get("sections", []):
        if isinstance(section, dict):
            story.append(Paragraph(_escape(section.get("title", "")), styles["h2"]))
            content = section.get("content", "")
            if content:
                story.append(Paragraph(_inline_format(content), styles["body"]))

    # ── Key Concepts ─────────────────────────────────────────────────
    key_concepts = summary.get("key_concepts", [])
    if key_concepts:
        story.append(Paragraph("Key Concepts", styles["h1"]))
        story.append(_bullet_list(key_concepts, styles["bullet"]))

    # ── Main Points ──────────────────────────────────────────────────
    main_points = summary.get("main_points", [])
    if main_points:
        story.append(Paragraph("Main Points", styles["h1"]))
        story.append(_bullet_list(main_points, styles["bullet"]))

    # ── Definitions (as a table) ─────────────────────────────────────
    definitions = summary.get("definitions", [])
    if definitions:
        story.append(Paragraph("Definitions", styles["h1"]))
        rows = [["Term", "Definition"]]
        for d in definitions:
            if isinstance(d, dict):
                rows.append([
                    Paragraph(_inline_format(d.get("term", "")), styles["definition_term"]),
                    Paragraph(_inline_format(d.get("meaning", "")), styles["body"]),
                ])
            else:
                rows.append([
                    Paragraph(_inline_format(d), styles["definition_term"]),
                    Paragraph("", styles["body"]),
                ])
        tbl = _make_table(rows, col_widths=[4.5 * cm, 12.5 * cm])
        story.append(tbl)
        story.append(Spacer(1, 8))

    # ── Formulas ─────────────────────────────────────────────────────
    formulas = summary.get("formulas", [])
    if formulas:
        story.append(Paragraph("Formulas", styles["h1"]))
        for f in formulas:
            story.append(Paragraph(_inline_format(f), styles["formula"]))

    # ── Examples ─────────────────────────────────────────────────────
    examples = summary.get("examples", [])
    if examples:
        story.append(Paragraph("Examples", styles["h1"]))
        story.append(_numbered_list(examples, styles["bullet"]))

    # ── Processes (step-by-step) ─────────────────────────────────────
    processes = summary.get("processes", [])
    if processes:
        story.append(Paragraph("Processes", styles["h1"]))
        story.append(_numbered_list(processes, styles["bullet"]))

    # ── Comparisons (as a table when possible) ───────────────────────
    comparisons = summary.get("comparisons", [])
    if comparisons:
        story.append(Paragraph("Comparisons", styles["h1"]))
        story.append(_bullet_list(comparisons, styles["bullet"]))

    # ── Advantages ───────────────────────────────────────────────────
    advantages = summary.get("advantages", [])
    if advantages:
        story.append(Paragraph("Advantages", styles["h1"]))
        story.append(_bullet_list(advantages, styles["bullet"]))

    # ── Disadvantages ────────────────────────────────────────────────
    disadvantages = summary.get("disadvantages", [])
    if disadvantages:
        story.append(Paragraph("Disadvantages", styles["h1"]))
        story.append(_bullet_list(disadvantages, styles["bullet"]))

    # ── Quick Revision ───────────────────────────────────────────────
    revision = summary.get("revision_notes", [])
    if revision:
        story.append(Spacer(1, 12))
        story.append(HRFlowable(width="100%", thickness=0.5,
                                color=colors.HexColor("#dee2e6"),
                                spaceAfter=8))
        story.append(Paragraph("Quick Revision", styles["h1"]))
        story.append(_bullet_list(revision, styles["bullet"]))

    # ── Build ────────────────────────────────────────────────────────
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes


def safe_filename(material_name):
    """Convert a material name into a safe PDF filename.

    Example: "Computer Networks 101" -> "Computer_Networks_101_Study_Notes.pdf"
    """
    name = re.sub(r"[^a-zA-Z0-9]+", "_", str(material_name)).strip("_")
    if not name:
        return "Study_Notes.pdf"
    return f"{name}_Study_Notes.pdf"
