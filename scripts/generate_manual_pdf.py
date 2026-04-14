"""
Generate OH team manual PDFs in English and Polish.

Usage:
    python scripts/generate_manual_pdf.py

Output:
    docs/OH_Manual_EN.pdf
    docs/OH_Manual_PL.pdf
"""

import os
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"


def _register_fonts():
    """Register Segoe UI if available, fallback to Helvetica."""
    segoe = r"C:\Windows\Fonts\segoeui.ttf"
    segoe_b = r"C:\Windows\Fonts\segoeuib.ttf"
    segoe_i = r"C:\Windows\Fonts\segoeuii.ttf"
    if os.path.exists(segoe):
        pdfmetrics.registerFont(TTFont("SegoeUI", segoe))
        if os.path.exists(segoe_b):
            pdfmetrics.registerFont(TTFont("SegoeUI-Bold", segoe_b))
        if os.path.exists(segoe_i):
            pdfmetrics.registerFont(TTFont("SegoeUI-Italic", segoe_i))
        return "SegoeUI", "SegoeUI-Bold", "SegoeUI-Italic"
    return "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"


FONT, FONT_B, FONT_I = _register_fonts()

# Colors
C_PRIMARY = colors.HexColor("#1a1a2e")
C_ACCENT = colors.HexColor("#6B70B8")
C_LIGHT_BG = colors.HexColor("#F0F1F8")
C_SUCCESS = colors.HexColor("#27AE60")
C_WARNING = colors.HexColor("#E67E22")
C_DANGER = colors.HexColor("#C0392B")
C_MUTED = colors.HexColor("#888888")
C_WHITE = colors.white
C_TABLE_HEADER = colors.HexColor("#32373c")
C_TABLE_ALT = colors.HexColor("#F8F9FF")


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

def _make_styles():
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        "DocTitle", fontName=FONT_B, fontSize=22, textColor=C_ACCENT,
        spaceAfter=4, alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        "DocSubtitle", fontName=FONT, fontSize=11, textColor=C_MUTED,
        spaceAfter=20, alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        "H1", fontName=FONT_B, fontSize=16, textColor=C_PRIMARY,
        spaceBefore=18, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        "H2", fontName=FONT_B, fontSize=13, textColor=C_ACCENT,
        spaceBefore=14, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        "H3", fontName=FONT_B, fontSize=11, textColor=C_PRIMARY,
        spaceBefore=10, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        "Body", fontName=FONT, fontSize=10, textColor=C_PRIMARY,
        spaceAfter=6, leading=14,
    ))
    styles.add(ParagraphStyle(
        "BodyBold", fontName=FONT_B, fontSize=10, textColor=C_PRIMARY,
        spaceAfter=6, leading=14,
    ))
    styles.add(ParagraphStyle(
        "OHBullet", fontName=FONT, fontSize=10, textColor=C_PRIMARY,
        leftIndent=16, spaceAfter=3, leading=13,
        bulletIndent=6, bulletFontName=FONT,
    ))
    styles.add(ParagraphStyle(
        "Small", fontName=FONT, fontSize=9, textColor=C_MUTED,
        spaceAfter=4, leading=12,
    ))
    styles.add(ParagraphStyle(
        "SmallItalic", fontName=FONT_I, fontSize=9, textColor=C_MUTED,
        spaceAfter=4, leading=12,
    ))
    return styles


def _hr():
    return HRFlowable(width="100%", thickness=0.5, color=C_MUTED, spaceAfter=8, spaceBefore=4)


def _spacer(h=6):
    return Spacer(1, h)


def _table(headers, rows, col_widths=None):
    """Create a styled table."""
    data = [headers] + rows
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), C_TABLE_HEADER),
        ("TEXTCOLOR", (0, 0), (-1, 0), C_WHITE),
        ("FONTNAME", (0, 0), (-1, 0), FONT_B),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTNAME", (0, 1), (-1, -1), FONT),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, C_MUTED),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), C_TABLE_ALT))
    t.setStyle(TableStyle(style))
    return t


# ---------------------------------------------------------------------------
# English manual content
# ---------------------------------------------------------------------------

def _build_english(s):
    """Return list of flowables for English manual."""
    f = []

    # Title page
    f.append(_spacer(60))
    f.append(Paragraph("OH — Operational Hub", s["DocTitle"]))
    f.append(Paragraph("Team Operations Manual", s["DocSubtitle"]))
    f.append(_spacer(20))
    f.append(Paragraph("Desktop dashboard for Onimator bot management at scale", s["Body"]))
    f.append(Paragraph("Version: April 2026", s["Small"]))
    f.append(PageBreak())

    # 1. What is OH
    f.append(Paragraph("1. What is OH?", s["H1"]))
    f.append(_hr())
    f.append(Paragraph(
        "OH (Operational Hub) is a desktop tool for managing Onimator campaigns. "
        "It connects to the bot folder and gives operators a single place to:", s["Body"]))
    for item in [
        "View all accounts — status, activity, tags, FBR, sources",
        "Analyze FBR (Follow-Back Rate) — which sources work, which don't",
        "Monitor sessions — how many follow/like/DM each account did today",
        "Manage sources — remove weak ones, add new ones, restore deleted",
        "Review accounts — flag problems, set TB/limits tags, add notes",
        "Get recommendations — system suggests what needs attention",
        "Daily overview — Cockpit shows what to do at shift start",
    ]:
        f.append(Paragraph(f"• {item}", s["OHBullet"]))
    f.append(_spacer())
    f.append(Paragraph(
        "<b>OH never modifies</b> bot files except sources.txt (and always creates a backup).",
        s["Body"]))

    # 2. First launch
    f.append(Paragraph("2. First Launch", s["H1"]))
    f.append(_hr())
    for i, step in enumerate([
        "Launch OH.exe",
        "Enter the Onimator folder path at the top (e.g. C:\\Users\\Admin\\Desktop\\full_igbot_13.9.0)",
        "Click <b>Save</b>",
        "Click <b>Scan &amp; Sync</b> — OH scans all devices and accounts",
        "Click <b>Cockpit</b> to see the operational overview",
    ], 1):
        f.append(Paragraph(f"{i}. {step}", s["Body"]))
    f.append(_spacer())
    f.append(Paragraph("Optional (in Settings):", s["BodyBold"]))
    for item in [
        "Enter <b>HikerAPI Key</b> to use 'Find Sources' feature",
        "Enter <b>Gemini API Key</b> for AI scoring when searching sources",
        "Adjust FBR thresholds (default: min 100 follows, min 10% FBR)",
    ]:
        f.append(Paragraph(f"• {item}", s["OHBullet"]))

    # 3. Daily review
    f.append(Paragraph("3. Daily Review — How to Start Your Shift", s["H1"]))
    f.append(_hr())

    f.append(Paragraph("Step 1: Scan &amp; Sync", s["H2"]))
    f.append(Paragraph("Click <b>Scan &amp; Sync</b> to fetch the latest data from the bot (sessions, tags, configs).", s["Body"]))

    f.append(Paragraph("Step 2: Cockpit", s["H2"]))
    f.append(Paragraph("Click <b>Cockpit</b>. You'll see 5 sections:", s["Body"]))
    f.append(_table(
        ["Section", "Shows"],
        [
            ["Urgent items", "Top 10 CRITICAL/HIGH problems"],
            ["Accounts to review", "Flagged accounts waiting for review"],
            ["Top recommendations", "Next most important suggestions"],
            ["Recent source actions", "Recent deletions/restorations"],
            ["Done today", "What the team already did today"],
        ],
        col_widths=[120, 340],
    ))

    f.append(Paragraph("Step 3: Session Report (if needed)", s["H2"]))
    f.append(Paragraph("Click <b>Session</b> for the full 8-section analysis: zero actions, devices, review, low follow/like, TB, limits.", s["Body"]))

    f.append(Paragraph("Step 4: Review accounts", s["H2"]))
    f.append(Paragraph("Click on accounts in the table — the <b>detail drawer</b> opens on the right with the full operational profile.", s["Body"]))

    # 4. Accounts tab
    f.append(Paragraph("4. Accounts Tab", s["H1"]))
    f.append(_hr())
    f.append(Paragraph("The main view. Table with 21 columns showing all accounts.", s["Body"]))

    f.append(Paragraph("Filters", s["H2"]))
    f.append(_table(
        ["Filter", "Options", "When to use"],
        [
            ["Status", "Active / Removed / All", "Default: Active only"],
            ["FBR", "All / Needs attention / Never analyzed / Errors / No quality / Has quality", "Find accounts needing FBR analysis"],
            ["Device", "List of all devices", "Filter by phone"],
            ["Search", "Type username", "Quick find"],
            ["Tags", "All / TB / limits / SLAVE / START / PK / Custom", "Filter by tags"],
            ["Activity", "All / 0 actions / Has actions", "Accounts with no activity today"],
            ["Review only", "Checkbox", "Only flagged accounts"],
        ],
        col_widths=[60, 200, 200],
    ))

    f.append(Paragraph("Toolbar Buttons", s["H2"]))
    f.append(_table(
        ["Button", "Action"],
        [
            ["Cockpit", "Open daily operations overview"],
            ["Scan & Sync", "Scan bot folder and synchronize"],
            ["Analyze FBR", "Run FBR analysis for all accounts"],
            ["Refresh", "Reload table from database (no scan)"],
            ["Session", "Open session report"],
            ["Recs", "Open recommendations"],
            ["History", "Open operator action audit trail"],
        ],
        col_widths=[100, 360],
    ))

    f.append(Paragraph("Actions Menu (per account row)", s["H2"]))
    f.append(Paragraph("Click 'Actions' button on any row:", s["Body"]))
    for item in [
        "<b>Open Folder</b> — opens account folder in Explorer",
        "<b>View Sources</b> — view sources with FBR data",
        "<b>Find Sources</b> — search for new similar sources (requires HikerAPI)",
        "<b>Set Review / Clear Review</b> — flag or unflag the account",
        "<b>TB +1</b> — increase trust-boost level",
        "<b>Limits +1</b> — increase limits level",
    ]:
        f.append(Paragraph(f"• {item}", s["OHBullet"]))

    # 5. Account detail panel
    f.append(Paragraph("5. Account Detail Panel (Drawer)", s["H1"]))
    f.append(_hr())
    f.append(Paragraph("<b>How to open:</b> Click any account in the table — the panel appears on the right side.", s["Body"]))

    f.append(Paragraph("Summary Tab", s["H2"]))
    f.append(Paragraph("4 performance cards:", s["Body"]))
    f.append(_table(
        ["Card", "Shows", "Red when"],
        [
            ["Today's Activity", "Follow/Like/DM counts vs limits", "Zero actions in active slot"],
            ["FBR Status", "Quality sources, best FBR%", "No quality sources"],
            ["Source Health", "Active source count", "0 sources or < 5"],
            ["Account Health", "TB and Limits levels", "TB >= 4 or Limits >= 4"],
        ],
        col_widths=[100, 190, 170],
    ))
    f.append(_spacer())
    f.append(Paragraph("Also shows: configuration (follow/unfollow enabled, limits, time slot, dates), FBR snapshot details.", s["Body"]))

    f.append(Paragraph("Alerts Tab", s["H2"]))
    f.append(Paragraph("Auto-generated alerts sorted by severity:", s["Body"]))
    for item in [
        "<b>CRITICAL</b> (red) — zero actions in active slot, TB5, device offline",
        "<b>HIGH</b> (orange) — TB4, no sources, action block",
        "<b>MEDIUM</b> (blue) — low follow, limits 4, low like",
        "<b>LOW</b> (gray) — never analyzed FBR, minor issues",
    ]:
        f.append(Paragraph(f"• {item}", s["OHBullet"]))
    f.append(_spacer())
    f.append(Paragraph("Each alert includes: title, details, recommended action, and an action button (e.g. 'TB +1').", s["Body"]))

    f.append(Paragraph("Footer Buttons", s["H2"]))
    f.append(_table(
        ["Button", "Action"],
        [
            ["Set Review / Clear Review", "Flag or clear the account review"],
            ["TB +1", "Increase trust-boost level"],
            ["Limits +1", "Increase limits level"],
            ["Open Folder", "Open account folder in Explorer"],
            ["Copy Diagnostic", "Copy full account report to clipboard"],
        ],
        col_widths=[150, 310],
    ))

    # 6. Recommendations
    f.append(Paragraph("6. Recommendations", s["H1"]))
    f.append(_hr())
    f.append(Paragraph("Click <b>Recs</b> in the toolbar. 6 recommendation types:", s["Body"]))
    f.append(_table(
        ["Type", "Problem", "Action"],
        [
            ["Weak Source", "Source with low FBR", "Remove or replace"],
            ["Source Exhaustion", "Too few sources on account", "Add new sources"],
            ["Low Like", "0 likes despite activity", "Check like config"],
            ["Limits Max", "Limits level 5", "Replace sources"],
            ["TB Max", "TB level 5", "Move account to another device"],
            ["Zero Actions", "0 actions in active slot", "Check device"],
        ],
        col_widths=[100, 180, 180],
    ))

    # 7. Source management
    f.append(Paragraph("7. Source Management", s["H1"]))
    f.append(_hr())
    f.append(Paragraph("Delete sources:", s["H2"]))
    for item in [
        "<b>Single:</b> Sources tab → select source → 'Delete Source'",
        "<b>Bulk:</b> 'Bulk Delete Weak Sources' → set FBR threshold → preview → confirm",
        "<b>Per account:</b> Actions → View Sources → 'Remove Non-Quality'",
    ]:
        f.append(Paragraph(f"• {item}", s["OHBullet"]))
    f.append(_spacer())
    f.append(Paragraph("Every deletion creates a backup (sources.txt.bak) and can be reverted from History.", s["Body"]))

    f.append(Paragraph("Find new sources:", s["H2"]))
    f.append(Paragraph("Actions → Find Sources → system searches similar profiles → select and add to sources.txt.", s["Body"]))

    # 8. Keyboard shortcuts
    f.append(Paragraph("8. Keyboard Shortcuts", s["H1"]))
    f.append(_hr())
    f.append(_table(
        ["Shortcut", "Where", "Action"],
        [
            ["Space", "Accounts table", "Toggle detail drawer open/close"],
            ["Escape", "Panel / dialog", "Close panel or dialog"],
            ["Left / Right", "Drawer open", "Switch Summary / Alerts tabs"],
            ["Up / Down", "Accounts table", "Navigate between accounts (drawer auto-updates)"],
            ["Ctrl+R", "Cockpit / Recs", "Refresh data"],
            ["Double-click", "Cockpit / Recs", "Navigate to account/source"],
        ],
        col_widths=[80, 120, 260],
    ))

    # 9. TB Warmup
    f.append(Paragraph("9. TB Warmup Procedure", s["H1"]))
    f.append(_hr())
    f.append(_table(
        ["Level", "Follow/day", "Like/day", "Notes"],
        [
            ["TB1", "5-10", "10-20", "Start slow warmup"],
            ["TB2", "15-25", "30-50", "Gradually increase"],
            ["TB3", "30-45", "50-80", "Monitor closely"],
            ["TB4", "50-70", "80-120", "Near normal levels"],
            ["TB5", "—", "—", "MOVE to another device"],
        ],
        col_widths=[50, 80, 80, 250],
    ))

    # 10. Safety
    f.append(Paragraph("10. Safety &amp; Backup", s["H1"]))
    f.append(_hr())
    for item in [
        "OH <b>never modifies</b> data.db, settings.db or bot runtime files",
        "Backup (sources.txt.bak) created before every deletion or restoration",
        "All deletions can be <b>reverted</b> from the History dialog",
        "All operator actions are <b>logged</b> with timestamp and machine name",
        "Operator tags (OP:) are <b>separate</b> from bot tags — never conflict",
    ]:
        f.append(Paragraph(f"• {item}", s["OHBullet"]))

    # 11. FAQ
    f.append(Paragraph("11. FAQ", s["H1"]))
    f.append(_hr())
    for q, a in [
        ("Can OH break the bot?", "No. OH only modifies sources.txt (with backup). Never touches data.db, settings.db or runtime config."),
        ("How to undo a source deletion?", "Sources tab → History → select operation → Revert Selected."),
        ("What does 'Needs attention' mean?", "Account was never analyzed OR has zero quality sources."),
        ("What to do when account has TB5?", "Account must be moved to another device. TB5 = maximum trust-boost level."),
        ("Where are OH logs?", "%APPDATA%\\OH\\logs\\oh.log — rotates at 2 MB, keeps 5 files."),
        ("Can I use OH while the bot is running?", "Yes. OH opens bot files in read-only mode. Only sources.txt is modified (with backup)."),
    ]:
        f.append(Paragraph(f"<b>Q: {q}</b>", s["BodyBold"]))
        f.append(Paragraph(f"A: {a}", s["Body"]))
        f.append(_spacer(4))

    return f


# ---------------------------------------------------------------------------
# Polish manual content
# ---------------------------------------------------------------------------

def _build_polish(s):
    """Return list of flowables for Polish manual."""
    f = []

    # Title page
    f.append(_spacer(60))
    f.append(Paragraph("OH — Operational Hub", s["DocTitle"]))
    f.append(Paragraph("Instrukcja obslugi dla zespolu", s["DocSubtitle"]))
    f.append(_spacer(20))
    f.append(Paragraph("Panel operacyjny do zarzadzania kampaniami Onimator na duzej skali", s["Body"]))
    f.append(Paragraph("Wersja: Kwiecien 2026", s["Small"]))
    f.append(PageBreak())

    # 1
    f.append(Paragraph("1. Co to jest OH?", s["H1"]))
    f.append(_hr())
    f.append(Paragraph(
        "OH (Operational Hub) to narzedzie desktopowe do zarzadzania kampaniami Onimator. "
        "Laczy sie z folderem bota i daje operatorom jedno miejsce do:", s["Body"]))
    for item in [
        "Podgladu wszystkich kont — status, aktywnosc, tagi, FBR, sources",
        "Analizy FBR (Follow-Back Rate) — ktore sources dzialaja, ktore nie",
        "Monitorowania sesji — ile follow/like/DM zrobilo konto dzisiaj",
        "Zarzadzania sources — usuwanie slabych, dodawanie nowych, przywracanie",
        "Review kont — flagowanie problemow, tagi TB/limits, notatki",
        "Rekomendacji — system podpowiada co wymaga uwagi",
        "Codziennego przegladu — Cockpit pokazuje co zrobic na poczatku zmiany",
    ]:
        f.append(Paragraph(f"\u2022 {item}", s["OHBullet"]))
    f.append(_spacer())
    f.append(Paragraph("<b>OH nigdy nie modyfikuje</b> plikow bota poza sources.txt (i zawsze robi backup).", s["Body"]))

    # 2
    f.append(Paragraph("2. Pierwsze uruchomienie", s["H1"]))
    f.append(_hr())
    for i, step in enumerate([
        "Uruchom OH.exe",
        "Na gorze wpisz sciezke do folderu Onimator (np. C:\\Users\\Admin\\Desktop\\full_igbot_13.9.0)",
        "Kliknij <b>Save</b>",
        "Kliknij <b>Scan &amp; Sync</b> — OH przeskanuje wszystkie urzadzenia i konta",
        "Kliknij <b>Cockpit</b> zeby zobaczyc podsumowanie operacyjne",
    ], 1):
        f.append(Paragraph(f"{i}. {step}", s["Body"]))
    f.append(_spacer())
    f.append(Paragraph("Opcjonalnie (w Settings):", s["BodyBold"]))
    for item in [
        "Wpisz <b>HikerAPI Key</b> aby uzywac 'Find Sources'",
        "Wpisz <b>Gemini API Key</b> aby wlaczyc AI scoring (opcjonalny)",
        "Ustaw progi FBR (domyslnie: min 100 follows, min 10% FBR)",
    ]:
        f.append(Paragraph(f"\u2022 {item}", s["OHBullet"]))

    # 3
    f.append(Paragraph("3. Codzienny przeglad — jak zaczac zmiane", s["H1"]))
    f.append(_hr())

    f.append(Paragraph("Krok 1: Scan &amp; Sync", s["H2"]))
    f.append(Paragraph("Kliknij <b>Scan &amp; Sync</b> aby pobrac najnowsze dane z bota.", s["Body"]))

    f.append(Paragraph("Krok 2: Cockpit", s["H2"]))
    f.append(Paragraph("Kliknij <b>Cockpit</b>. Zobaczysz 5 sekcji:", s["Body"]))
    f.append(_table(
        ["Sekcja", "Co pokazuje"],
        [
            ["Do zrobienia teraz", "Top 10 najpilniejszych problemow (CRITICAL/HIGH)"],
            ["Konta do review", "Oflagowane konta czekajace na przeglad"],
            ["Top rekomendacje", "Kolejne najwazniejsze zalecenia"],
            ["Ostatnie source actions", "Ostatnie usuniecia/przywrocenia sources"],
            ["Dzisiaj wykonano", "Co juz zrobil zespol dzisiaj"],
        ],
        col_widths=[130, 330],
    ))

    f.append(Paragraph("Krok 3: Session Report", s["H2"]))
    f.append(Paragraph("Kliknij <b>Session</b> aby zobaczyc pelny raport: konta z 0 akcjami, urzadzenia, review, niski follow/like, TB, limits.", s["Body"]))

    f.append(Paragraph("Krok 4: Przegladaj konta", s["H2"]))
    f.append(Paragraph("Klikaj na konta w tabeli — <b>panel szczegolowy</b> otwiera sie po prawej z pelnym profilem.", s["Body"]))

    # 4
    f.append(Paragraph("4. Zakladka Accounts — lista kont", s["H1"]))
    f.append(_hr())

    f.append(Paragraph("Filtry", s["H2"]))
    f.append(_table(
        ["Filtr", "Opcje", "Kiedy uzywac"],
        [
            ["Status", "Active / Removed / All", "Domyslnie: Active only"],
            ["FBR", "All / Needs attention / Never analyzed / Errors / No quality / Has quality", "Szukanie kont do analizy"],
            ["Device", "Lista urzadzen", "Filtrowanie po telefonie"],
            ["Search", "Wpisz username", "Szybkie znalezienie konta"],
            ["Tags", "All / TB / limits / SLAVE / START / PK / Custom", "Filtrowanie po tagach"],
            ["Activity", "All / 0 actions / Has actions", "Konta bez aktywnosci"],
            ["Review only", "Checkbox", "Tylko oflagowane"],
        ],
        col_widths=[60, 200, 200],
    ))

    f.append(Paragraph("Przyciski na pasku", s["H2"]))
    f.append(_table(
        ["Przycisk", "Co robi"],
        [
            ["Cockpit", "Otwiera podglad operacyjny"],
            ["Scan & Sync", "Skanuje folder bota i synchronizuje"],
            ["Analyze FBR", "Uruchamia analize FBR dla wszystkich kont"],
            ["Refresh", "Odswieza tabele z bazy (bez skanowania)"],
            ["Session", "Otwiera raport sesji"],
            ["Recs", "Otwiera rekomendacje"],
            ["History", "Otwiera historie akcji operatora"],
        ],
        col_widths=[100, 360],
    ))

    f.append(Paragraph("Menu akcji (przycisk 'Actions' w kazdym wierszu)", s["H2"]))
    for item in [
        "<b>Open Folder</b> — otwiera folder konta w Explorerze",
        "<b>View Sources</b> — podglad sources z FBR",
        "<b>Find Sources</b> — szukanie nowych sources (wymaga HikerAPI)",
        "<b>Set Review / Clear Review</b> — flagowanie konta",
        "<b>TB +1</b> — zwiekszenie poziomu TB",
        "<b>Limits +1</b> — zwiekszenie poziomu limits",
    ]:
        f.append(Paragraph(f"\u2022 {item}", s["OHBullet"]))

    # 5
    f.append(Paragraph("5. Panel szczegolowy konta (drawer)", s["H1"]))
    f.append(_hr())
    f.append(Paragraph("<b>Jak otworzyc:</b> Kliknij na dowolne konto w tabeli — panel pojawi sie po prawej.", s["Body"]))

    f.append(Paragraph("Zakladka Summary", s["H2"]))
    f.append(_table(
        ["Karta", "Co pokazuje", "Kiedy czerwona"],
        [
            ["Today's Activity", "Follow/Like/DM dzisiaj vs limity", "0 akcji w aktywnym slocie"],
            ["FBR Status", "Quality sources, best FBR%", "Brak quality sources"],
            ["Source Health", "Liczba aktywnych sources", "0 sources lub < 5"],
            ["Account Health", "Poziom TB i Limits", "TB >= 4 lub Limits >= 4"],
        ],
        col_widths=[100, 190, 170],
    ))

    f.append(Paragraph("Zakladka Alerts", s["H2"]))
    for item in [
        "<b>CRITICAL</b> (czerwone) — 0 akcji w aktywnym slocie, TB5, urzadzenie offline",
        "<b>HIGH</b> (pomaranczowe) — TB4, brak sources, action block",
        "<b>MEDIUM</b> (niebieskie) — niski follow, limits 4",
        "<b>LOW</b> (szare) — nigdy nie analizowano FBR",
    ]:
        f.append(Paragraph(f"\u2022 {item}", s["OHBullet"]))

    f.append(Paragraph("Przyciski na dole panelu", s["H2"]))
    f.append(_table(
        ["Przycisk", "Co robi"],
        [
            ["Set Review / Clear Review", "Flaguje lub czysci review"],
            ["TB +1", "Zwieksza poziom TB"],
            ["Limits +1", "Zwieksza poziom Limits"],
            ["Open Folder", "Otwiera folder konta"],
            ["Copy Diagnostic", "Kopiuje pelny raport do schowka"],
        ],
        col_widths=[150, 310],
    ))

    # 6
    f.append(Paragraph("6. Rekomendacje", s["H1"]))
    f.append(_hr())
    f.append(_table(
        ["Typ", "Problem", "Co robic"],
        [
            ["Weak Source", "Source z niskim FBR", "Usun lub wymien"],
            ["Source Exhaustion", "Za malo sources", "Dodaj nowe sources"],
            ["Low Like", "0 like mimo aktywnosci", "Sprawdz konfiguracje like"],
            ["Limits Max", "Limits level 5", "Wymien sources"],
            ["TB Max", "TB level 5", "Przenies konto"],
            ["Zero Actions", "0 akcji w aktywnym slocie", "Sprawdz urzadzenie"],
        ],
        col_widths=[100, 170, 190],
    ))

    # 7
    f.append(Paragraph("7. Zarzadzanie sources", s["H1"]))
    f.append(_hr())
    f.append(Paragraph("Usuwanie:", s["H2"]))
    for item in [
        "<b>Pojedynczo:</b> Zakladka Sources \u2192 zaznacz \u2192 'Delete Source'",
        "<b>Hurtowo:</b> 'Bulk Delete Weak Sources' \u2192 ustaw prog FBR \u2192 potwierdz",
        "<b>Per konto:</b> Actions \u2192 View Sources \u2192 'Remove Non-Quality'",
    ]:
        f.append(Paragraph(f"\u2022 {item}", s["OHBullet"]))
    f.append(Paragraph("Kazde usuniecie tworzy backup (sources.txt.bak) i mozna je cofnac z historii.", s["Body"]))
    f.append(Paragraph("Znajdowanie nowych:", s["H2"]))
    f.append(Paragraph("Actions \u2192 Find Sources \u2192 system szuka podobnych profili \u2192 zaznacz i dodaj do sources.txt.", s["Body"]))

    # 8
    f.append(Paragraph("8. Skroty klawiaturowe", s["H1"]))
    f.append(_hr())
    f.append(_table(
        ["Skrot", "Gdzie", "Co robi"],
        [
            ["Space", "Tabela kont", "Otwiera/zamyka panel szczegolowy"],
            ["Escape", "Panel / dialog", "Zamyka panel lub dialog"],
            ["Left / Right", "Panel otwarty", "Przelacza zakladki Summary/Alerts"],
            ["Up / Down", "Tabela kont", "Przechodzi miedzy kontami"],
            ["Ctrl+R", "Cockpit / Recs", "Odswieza dane"],
        ],
        col_widths=[80, 120, 260],
    ))

    # 9
    f.append(Paragraph("9. Procedura warmupu TB", s["H1"]))
    f.append(_hr())
    f.append(_table(
        ["Poziom", "Follow/dzien", "Like/dzien", "Uwagi"],
        [
            ["TB1", "5-10", "10-20", "Start wolnego warmupu"],
            ["TB2", "15-25", "30-50", "Stopniowe zwiekszanie"],
            ["TB3", "30-45", "50-80", "Monitoruj wnikliwie"],
            ["TB4", "50-70", "80-120", "Blisko normalnych limitow"],
            ["TB5", "\u2014", "\u2014", "PRZENIES na inne urzadzenie"],
        ],
        col_widths=[50, 80, 80, 250],
    ))

    # 10
    f.append(Paragraph("10. Bezpieczenstwo i backup", s["H1"]))
    f.append(_hr())
    for item in [
        "OH <b>nigdy nie modyfikuje</b> data.db, settings.db ani plikow runtime bota",
        "Backup (sources.txt.bak) tworzony przed kazda zmiana",
        "Wszystkie usuniecia mozna <b>cofnac</b> z dialogu History",
        "Wszystkie akcje operatora sa <b>logowane</b> z timestampem i nazwa komputera",
        "Tagi operatora (OP:) sa <b>oddzielone</b> od tagow bota",
    ]:
        f.append(Paragraph(f"\u2022 {item}", s["OHBullet"]))

    # 11
    f.append(Paragraph("11. FAQ", s["H1"]))
    f.append(_hr())
    for q, a in [
        ("Czy OH moze zepsuc bota?", "Nie. OH modyfikuje tylko sources.txt (z backupem). Nigdy nie rusza data.db ani konfiguracji."),
        ("Jak cofnac usuniecie source?", "Zakladka Sources \u2192 History \u2192 zaznacz \u2192 Revert Selected."),
        ("Co oznacza 'Needs attention'?", "Konto nigdy nie bylo analizowane LUB ma zero quality sources."),
        ("Co robic jak konto ma TB5?", "Konto wymaga przeniesienia na inne urzadzenie."),
        ("Gdzie sa logi OH?", "%APPDATA%\\OH\\logs\\oh.log \u2014 rotacja co 2 MB, max 5 plikow."),
        ("Czy moge uzywac OH z botem?", "Tak. OH otwiera pliki bota w read-only. Tylko sources.txt jest modyfikowany (z backupem)."),
    ]:
        f.append(Paragraph(f"<b>P: {q}</b>", s["BodyBold"]))
        f.append(Paragraph(f"O: {a}", s["Body"]))
        f.append(_spacer(4))

    return f


# ---------------------------------------------------------------------------
# Build PDFs
# ---------------------------------------------------------------------------

def _build_pdf(path, flowables, title):
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        topMargin=25 * mm,
        bottomMargin=20 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        title=title,
        author="Wizzysocial — OH Team",
    )
    doc.build(flowables)
    print(f"  Created: {path}  ({path.stat().st_size // 1024} KB)")


def main():
    print("Generating OH manuals...")
    styles = _make_styles()

    en_path = DOCS_DIR / "OH_Manual_EN.pdf"
    pl_path = DOCS_DIR / "OH_Manual_PL.pdf"

    _build_pdf(en_path, _build_english(styles), "OH — Operational Hub — Team Manual")
    _build_pdf(pl_path, _build_polish(styles), "OH — Operational Hub — Instrukcja obslugi")

    print("Done.")


if __name__ == "__main__":
    main()
