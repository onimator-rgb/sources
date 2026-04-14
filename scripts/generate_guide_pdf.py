"""
Generate OH User Guide PDFs with screenshots embedded.

Usage:
    python scripts/generate_guide_pdf.py

Output:
    docs/OH_User_Guide_EN.pdf
    docs/OH_User_Guide_PL.pdf
    + copies to OH_Distribution/
"""
import os
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, Image, KeepTogether,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
SCREENSHOT_DIR = DOCS_DIR / "screenshots"
DIST_DIR = Path(__file__).resolve().parent.parent / "OH_Distribution"

# Colors
C_BG = colors.HexColor("#1a1a2e")
C_ACCENT = colors.HexColor("#6B70B8")
C_LIGHT_BG = colors.HexColor("#F0F1F8")
C_WHITE = colors.white
C_TABLE_HEADER = colors.HexColor("#32373c")
C_TABLE_ALT = colors.HexColor("#F8F9FF")
C_MUTED = colors.HexColor("#888888")
C_SUCCESS = colors.HexColor("#27AE60")
C_DANGER = colors.HexColor("#C0392B")

# Fonts
def _register_fonts():
    segoe = r"C:\Windows\Fonts\segoeui.ttf"
    segoe_b = r"C:\Windows\Fonts\segoeuib.ttf"
    if os.path.exists(segoe):
        pdfmetrics.registerFont(TTFont("SegoeUI", segoe))
        if os.path.exists(segoe_b):
            pdfmetrics.registerFont(TTFont("SegoeUI-Bold", segoe_b))
        return "SegoeUI", "SegoeUI-Bold"
    return "Helvetica", "Helvetica-Bold"

FONT, FONT_B = _register_fonts()

PAGE_W, PAGE_H = A4
MARGIN = 20 * mm
CONTENT_W = PAGE_W - 2 * MARGIN


def make_styles():
    s = getSampleStyleSheet()

    s.add(ParagraphStyle("Title2", fontName=FONT_B, fontSize=22, spaceAfter=6,
                          textColor=C_BG, alignment=TA_CENTER))
    s.add(ParagraphStyle("Subtitle", fontName=FONT, fontSize=11, spaceAfter=12,
                          textColor=C_MUTED, alignment=TA_CENTER))
    s.add(ParagraphStyle("H1", fontName=FONT_B, fontSize=16, spaceBefore=18, spaceAfter=8,
                          textColor=C_ACCENT, borderWidth=0))
    s.add(ParagraphStyle("H2", fontName=FONT_B, fontSize=13, spaceBefore=12, spaceAfter=6,
                          textColor=C_BG))
    s.add(ParagraphStyle("H3", fontName=FONT_B, fontSize=11, spaceBefore=8, spaceAfter=4,
                          textColor=C_BG))
    s.add(ParagraphStyle("Body", fontName=FONT, fontSize=9.5, leading=14, spaceAfter=4))
    s.add(ParagraphStyle("BulletOH", fontName=FONT, fontSize=9.5, leading=14, spaceAfter=2,
                          leftIndent=12, bulletIndent=0))
    s.add(ParagraphStyle("TCell", fontName=FONT, fontSize=8.5, leading=11))
    s.add(ParagraphStyle("TCellB", fontName=FONT_B, fontSize=8.5, leading=11, textColor=C_WHITE))
    s.add(ParagraphStyle("Footer", fontName=FONT, fontSize=7, textColor=C_MUTED, alignment=TA_CENTER))
    return s


def md_to_elements(md_text: str, styles) -> list:
    """Convert markdown to reportlab flowables."""
    elements = []
    lines = md_text.split("\n")
    i = 0
    in_table = False
    table_rows = []

    def flush_table():
        nonlocal table_rows, in_table
        if not table_rows:
            return
        # Build table
        data = []
        for row_cells in table_rows:
            data.append([Paragraph(c.strip(), styles["TCell"]) for c in row_cells])

        # Style header row
        if data:
            data[0] = [Paragraph(c.strip() if isinstance(c, str) else c.text,
                                  styles["TCellB"]) for c in table_rows[0]]

        n_cols = max(len(r) for r in data) if data else 1
        col_w = CONTENT_W / n_cols

        t = Table(data, colWidths=[col_w] * n_cols, repeatRows=1)
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), C_TABLE_HEADER),
            ("TEXTCOLOR", (0, 0), (-1, 0), C_WHITE),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
        for r in range(1, len(data)):
            if r % 2 == 0:
                style_cmds.append(("BACKGROUND", (0, r), (-1, r), C_TABLE_ALT))
        t.setStyle(TableStyle(style_cmds))
        elements.append(t)
        elements.append(Spacer(1, 6))
        table_rows = []
        in_table = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            if in_table:
                flush_table()
            i += 1
            continue

        # Table separator line (|---|---|)
        if re.match(r"^\|[\s\-:|]+\|$", stripped):
            i += 1
            continue

        # Table row
        if stripped.startswith("|") and stripped.endswith("|"):
            in_table = True
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            # Clean markdown bold
            cells = [re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", c) for c in cells]
            table_rows.append(cells)
            i += 1
            continue

        if in_table:
            flush_table()

        # Headings
        if stripped.startswith("# ") and not stripped.startswith("## "):
            # Top-level title
            text = stripped.lstrip("# ").strip()
            elements.append(Paragraph(text, styles["Title2"]))
            i += 1
            continue

        if stripped.startswith("## "):
            text = stripped.lstrip("## ").strip()
            # Clean anchors
            text = re.sub(r"\[.*?\]\(#.*?\)", "", text).strip()
            elements.append(Spacer(1, 4))
            elements.append(HRFlowable(width="100%", thickness=1, color=C_ACCENT, spaceAfter=4))
            elements.append(Paragraph(text, styles["H1"]))
            i += 1
            continue

        if stripped.startswith("### "):
            text = stripped.lstrip("### ").strip()
            elements.append(Paragraph(text, styles["H2"]))
            i += 1
            continue

        if stripped.startswith("#### "):
            text = stripped.lstrip("#### ").strip()
            elements.append(Paragraph(text, styles["H3"]))
            i += 1
            continue

        # Image
        img_match = re.match(r"!\[.*?\]\((.+?)\)", stripped)
        if img_match:
            img_path = DOCS_DIR / img_match.group(1)
            if img_path.exists():
                img = Image(str(img_path), width=CONTENT_W, height=CONTENT_W * 0.58)
                img.hAlign = "CENTER"
                elements.append(Spacer(1, 4))
                elements.append(img)
                elements.append(Spacer(1, 4))
            i += 1
            continue

        # Blockquote
        if stripped.startswith("> "):
            text = stripped.lstrip("> ").strip()
            text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
            elements.append(Paragraph(f"<i>{text}</i>", styles["Body"]))
            i += 1
            continue

        # Horizontal rule
        if stripped in ("---", "***", "___"):
            elements.append(HRFlowable(width="100%", thickness=0.5, color=C_MUTED, spaceAfter=6))
            i += 1
            continue

        # Bullet list
        if stripped.startswith("- ") or stripped.startswith("* "):
            text = stripped[2:].strip()
            text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
            text = re.sub(r"`(.+?)`", r"<font face='Courier' size='8'>\1</font>", text)
            elements.append(Paragraph(f"&bull; {text}", styles["BulletOH"]))
            i += 1
            continue

        # Numbered list
        num_match = re.match(r"^(\d+)\.\s+(.+)", stripped)
        if num_match:
            text = num_match.group(2)
            text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
            text = re.sub(r"`(.+?)`", r"<font face='Courier' size='8'>\1</font>", text)
            elements.append(Paragraph(f"{num_match.group(1)}. {text}", styles["BulletOH"]))
            i += 1
            continue

        # TOC links (skip)
        if re.match(r"^\d+\.\s+\[", stripped):
            i += 1
            continue

        # Regular paragraph
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", stripped)
        text = re.sub(r"`(.+?)`", r"<font face='Courier' size='8'>\1</font>", text)
        elements.append(Paragraph(text, styles["Body"]))
        i += 1

    if in_table:
        flush_table()

    return elements


def build_pdf(md_file: Path, output: Path, title: str):
    print(f"\nBuilding: {output.name}")

    md_text = md_file.read_text(encoding="utf-8")
    styles = make_styles()

    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=title,
        author="Wizzysocial",
    )

    elements = []

    # Cover
    elements.append(Spacer(1, 40))
    elements.append(Paragraph("OH — Operational Hub", styles["Title2"]))
    elements.append(Paragraph(title, styles["Subtitle"]))
    elements.append(Spacer(1, 8))
    elements.append(HRFlowable(width="60%", thickness=2, color=C_ACCENT, spaceAfter=8))
    elements.append(Paragraph("v1.1.0 | April 2026", styles["Subtitle"]))
    elements.append(Paragraph("Wizzysocial", styles["Subtitle"]))
    elements.append(Spacer(1, 20))

    # Add screenshot on cover
    cover_img = SCREENSHOT_DIR / "01_accounts_tab.png"
    if cover_img.exists():
        img = Image(str(cover_img), width=CONTENT_W * 0.85, height=CONTENT_W * 0.85 * 0.58)
        img.hAlign = "CENTER"
        elements.append(img)

    elements.append(PageBreak())

    # Content
    content_elements = md_to_elements(md_text, styles)
    elements.extend(content_elements)

    # Build
    doc.build(elements)
    size_kb = output.stat().st_size / 1024
    print(f"  Saved: {output} ({size_kb:.0f} KB)")


def main():
    en_md = DOCS_DIR / "OH_User_Guide.md"
    pl_md = DOCS_DIR / "OH_Podrecznik_Uzytkownika.md"

    en_pdf = DOCS_DIR / "OH_User_Guide_EN.pdf"
    pl_pdf = DOCS_DIR / "OH_User_Guide_PL.pdf"

    if en_md.exists():
        build_pdf(en_md, en_pdf, "User Guide")
    else:
        print(f"  Missing: {en_md}")

    if pl_md.exists():
        build_pdf(pl_md, pl_pdf, "Podrecznik uzytkownika")
    else:
        print(f"  Missing: {pl_md}")

    # Copy to distribution
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    for pdf in [en_pdf, pl_pdf]:
        if pdf.exists():
            import shutil
            dest = DIST_DIR / pdf.name
            shutil.copy2(str(pdf), str(dest))
            print(f"  Copied to: {dest}")

    print("\nDone!")


if __name__ == "__main__":
    main()
