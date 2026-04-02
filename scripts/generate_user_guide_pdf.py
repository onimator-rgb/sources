"""
Generate professional PDF user manual with real screenshots from OH.
Usage: python scripts/generate_user_guide_pdf.py
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["QT_QPA_PLATFORM"] = "windows"

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
DIST_DIR = PROJECT_DIR / "OH_Distribution"
SCREENS_DIR = SCRIPT_DIR / "_screens"
OUTPUT_PDF = DIST_DIR / "OH_User_Guide.pdf"
SCREENS_DIR.mkdir(parents=True, exist_ok=True)
DIST_DIR.mkdir(parents=True, exist_ok=True)


def take_screenshots():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFont
    from oh.db.connection import get_connection, close_connection
    from oh.db.migrations import run_migrations
    from oh.repositories.settings_repo import SettingsRepository
    from oh.ui.style import get_stylesheet, apply_palette, set_current_theme

    app = QApplication(sys.argv)
    app.setApplicationName("OH")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 11))

    conn = get_connection()
    run_migrations(conn)
    settings = SettingsRepository(conn)
    settings.seed_defaults()
    theme = settings.get("theme") or "dark"
    set_current_theme(theme)
    apply_palette(app, theme)
    app.setStyleSheet(get_stylesheet(theme))

    from oh.repositories.account_repo import AccountRepository
    from oh.repositories.delete_history_repo import DeleteHistoryRepository
    from oh.repositories.device_repo import DeviceRepository
    from oh.repositories.fbr_snapshot_repo import FBRSnapshotRepository
    from oh.repositories.source_assignment_repo import SourceAssignmentRepository
    from oh.repositories.source_search_repo import SourceSearchRepository
    from oh.repositories.source_profile_repo import SourceProfileRepository
    from oh.repositories.bulk_discovery_repo import BulkDiscoveryRepository
    from oh.repositories.blacklist_repo import BlacklistRepository
    from oh.repositories.sync_repo import SyncRepository
    from oh.repositories.operator_action_repo import OperatorActionRepository
    from oh.repositories.session_repo import SessionRepository
    from oh.repositories.tag_repo import TagRepository
    from oh.services.fbr_service import FBRService
    from oh.services.operator_action_service import OperatorActionService
    from oh.services.recommendation_service import RecommendationService
    from oh.services.global_sources_service import GlobalSourcesService
    from oh.services.scan_service import ScanService
    from oh.services.session_service import SessionService
    from oh.services.source_delete_service import SourceDeleteService
    from oh.services.source_finder_service import SourceFinderService
    from oh.services.bulk_discovery_service import BulkDiscoveryService
    try:
        from oh.services.account_detail_service import AccountDetailService
    except ImportError:
        AccountDetailService = None
    from oh.ui.main_window import MainWindow

    ar = SourceAssignmentRepository(conn)
    acr = AccountRepository(conn)
    tr = TagRepository(conn)
    ss = SessionService(session_repo=SessionRepository(conn), tag_repo=tr, account_repo=acr)
    scs = ScanService(account_repo=acr, device_repo=DeviceRepository(conn),
                      sync_repo=SyncRepository(conn), session_service=ss)
    spr = SourceProfileRepository(conn)
    fsr = FBRSnapshotRepository(conn)
    fs = FBRService(snapshot_repo=fsr, account_repo=acr, settings_repo=settings,
                    assignment_repo=ar, source_profile_repo=spr)
    gs = GlobalSourcesService(account_repo=acr, assignment_repo=ar)
    dhr = DeleteHistoryRepository(conn)
    sds = SourceDeleteService(assignment_repo=ar, history_repo=dhr, settings_repo=settings,
                              global_sources_service=gs, fbr_snapshot_repo=fsr)
    oar = OperatorActionRepository(conn)
    oas = OperatorActionService(account_repo=acr, tag_repo=tr, action_repo=oar)
    ssr = SourceSearchRepository(conn)
    sfs = SourceFinderService(search_repo=ssr, account_repo=acr, settings_repo=settings,
                              source_profile_repo=spr)
    bdr = BulkDiscoveryRepository(conn)
    bds = BulkDiscoveryService(bulk_repo=bdr, source_finder_service=sfs,
                               account_repo=acr, assignment_repo=ar, settings_repo=settings)
    rs = RecommendationService(global_sources_service=gs, account_repo=acr, tag_repo=tr,
                               settings_repo=settings, source_profile_repo=spr)
    ads = None
    if AccountDetailService:
        try:
            ads = AccountDetailService(operator_action_repo=oar, settings_repo=settings)
        except Exception:
            pass
    blr = BlacklistRepository(conn)

    w = MainWindow(conn, scs, fs, gs, sds, session_service=ss,
                   operator_action_service=oas, operator_action_repo=oar,
                   tag_repo=tr, recommendation_service=rs,
                   source_finder_service=sfs, bulk_discovery_service=bds,
                   account_detail_service=ads, blacklist_repo=blr)
    w.resize(1400, 800)
    w.show()

    screens = {}

    def capture():
        app.processEvents()
        time.sleep(0.5)

        tab_names = [
            (0, "accounts"), (1, "sources"), (2, "source_profiles"),
            (3, "fleet"), (4, "settings"),
        ]
        for idx, name in tab_names:
            w._tabs.setCurrentIndex(idx)
            app.processEvents()
            time.sleep(0.5)
            w.grab().save(str(SCREENS_DIR / f"{idx+1:02d}_{name}.png"))
            screens[name] = SCREENS_DIR / f"{idx+1:02d}_{name}.png"
            print(f"  Captured: {name}")

        # Drawer
        w._tabs.setCurrentIndex(0)
        app.processEvents()
        time.sleep(0.3)
        if w._table.rowCount() > 0:
            w._table.selectRow(0)
            app.processEvents()
            time.sleep(0.3)
            try:
                mi = w._table.model().index(0, 0)
                w._table.clicked.emit(mi)
                app.processEvents()
                time.sleep(0.6)
                w.grab().save(str(SCREENS_DIR / "06_drawer.png"))
                screens["drawer"] = SCREENS_DIR / "06_drawer.png"
                print("  Captured: drawer")
            except Exception as e:
                print(f"  Drawer failed: {e}")

        print(f"\n  {len(screens)} screenshots saved")
        generate_pdf(screens)
        w.close()
        app.quit()

    QTimer.singleShot(1500, capture)
    app.exec()
    close_connection()


def generate_pdf(screens):
    from fpdf import FPDF
    print("\nGenerating PDF...")

    class M(FPDF):
        def header(self):
            if self.page_no() > 1:
                self.set_font("Helvetica", "", 8)
                self.set_text_color(130, 130, 130)
                self.cell(0, 8, "OH - Operational Hub | User Guide v1.0", align="L")
                self.ln(10)

        def footer(self):
            self.set_y(-15)
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(150, 150, 150)
            self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

        def ch(self, t):
            self.add_page()
            self.set_font("Helvetica", "B", 20)
            self.set_text_color(40, 40, 40)
            self.cell(0, 14, t, new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(70, 130, 220)
            self.set_line_width(0.7)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
            self.ln(6)

        def sh(self, t):
            self.ln(2)
            self.set_font("Helvetica", "B", 13)
            self.set_text_color(55, 55, 55)
            self.cell(0, 9, t, new_x="LMARGIN", new_y="NEXT")
            self.ln(1)

        def p(self, t):
            self.set_font("Helvetica", "", 10)
            self.set_text_color(60, 60, 60)
            self.multi_cell(0, 5.5, t)
            self.ln(2)

        def bl(self, t):
            self.set_font("Helvetica", "", 10)
            self.set_text_color(60, 60, 60)
            self.cell(0, 5.5, f"  -  {t}", new_x="LMARGIN", new_y="NEXT")

        def img(self, path, cap=""):
            if not Path(path).exists():
                return
            if self.get_y() > 155:
                self.add_page()
            w = self.w - self.l_margin - self.r_margin - 2
            self.set_draw_color(180, 180, 180)
            y0 = self.get_y()
            self.image(str(path), x=self.l_margin + 1, w=w)
            self.rect(self.l_margin, y0 - 1, w + 2, self.get_y() - y0 + 2)
            if cap:
                self.set_font("Helvetica", "I", 9)
                self.set_text_color(110, 110, 110)
                self.cell(0, 6, cap, align="C", new_x="LMARGIN", new_y="NEXT")
            self.ln(4)

    pdf = M()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(True, 20)

    # Cover
    pdf.add_page()
    pdf.ln(50)
    pdf.set_font("Helvetica", "B", 42)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(0, 20, "OH", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 22)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 14, "Operational Hub", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)
    pdf.set_draw_color(70, 130, 220)
    pdf.set_line_width(1)
    pdf.line(60, pdf.get_y(), pdf.w - 60, pdf.get_y())
    pdf.ln(8)
    pdf.set_font("Helvetica", "", 16)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(0, 10, "User Guide", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(30)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(130, 130, 130)
    pdf.cell(0, 7, "Campaign Operations Dashboard", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, "Version 1.0 | April 2026", align="C", new_x="LMARGIN", new_y="NEXT")

    # 1. Getting Started
    pdf.ch("1. Getting Started")
    pdf.p("OH (Operational Hub) is a desktop dashboard for managing Onimator bot campaigns "
           "at scale. It provides a unified control center for devices, accounts, sources, "
           "FBR analytics, session monitoring, and operational recommendations.")
    pdf.sh("System Requirements")
    pdf.bl("Windows 10 or 11 (64-bit)")
    pdf.bl("Onimator bot installed on the same machine")
    pdf.bl("No additional software needed")

    # 2. Setup
    pdf.ch("2. Initial Setup")
    pdf.sh("Step 1: Set Bot Path")
    pdf.p("Enter the full path to your Onimator folder at the top and click Save.")
    pdf.sh("Step 2: Scan & Sync")
    pdf.p("Click Scan & Sync to discover all devices and accounts from bot files.")
    pdf.sh("Step 3: Analyze FBR")
    pdf.p("Click Analyze FBR to compute Follow-Back Rate for all accounts.")
    pdf.sh("Step 4: API Keys (Optional)")
    pdf.p("Settings > Source Finder: enter HikerAPI key for source discovery. "
           "Gemini key is optional for AI scoring.")

    # 3. Accounts
    pdf.ch("3. Accounts Tab")
    pdf.p("Main view with all accounts in a sortable table with Health Score, FBR, sessions.")
    if "accounts" in screens:
        pdf.img(screens["accounts"], "Accounts Tab")
    pdf.sh("Health Score (0-100)")
    pdf.p("Composite metric: FBR quality 30% + activity 20% + sources 15% + "
           "stability 15% + regularity 10% + review 10%.")
    pdf.bl("Green (70+): healthy")
    pdf.bl("Yellow (40-69): needs attention")
    pdf.bl("Red (<40): investigate immediately")
    pdf.sh("Toolbar")
    pdf.bl("Scan & Sync, Analyze FBR, Cockpit, Recommendations, Session Report, Export CSV")

    # 4. Sources
    pdf.ch("4. Sources Tab")
    pdf.p("Global source aggregation with FBR metrics, trends, and management tools.")
    if "sources" in screens:
        pdf.img(screens["sources"], "Sources Tab")
    pdf.sh("Key Features")
    pdf.bl("FBR trend indicators (hover Wtd FBR% for 14-day change)")
    pdf.bl("Single and bulk source deletion with revert")
    pdf.bl("Bulk Find Sources wizard for under-sourced accounts")

    # 5. Source Profiles
    pdf.ch("5. Source Profiles")
    pdf.p("Source health dashboard with niche classification, language, and FBR stats.")
    if "source_profiles" in screens:
        pdf.img(screens["source_profiles"], "Source Profiles Tab")
    pdf.sh("20 Niche Categories")
    pdf.p("fitness, beauty, fashion, food, nutrition, wellness, photography, wedding, "
           "real estate, automotive, education, coaching, business, travel, interior, "
           "medical, pet, art, sport, lifestyle")

    # 6. Fleet
    pdf.ch("6. Fleet Dashboard")
    pdf.p("Device-level metrics with per-device account breakdown.")
    if "fleet" in screens:
        pdf.img(screens["fleet"], "Fleet Dashboard")

    # 7. Settings
    pdf.ch("7. Settings")
    if "settings" in screens:
        pdf.img(screens["settings"], "Settings (scrollable)")
    pdf.sh("Sections")
    pdf.bl("FBR Analysis: quality thresholds")
    pdf.bl("Source Cleanup: weak source removal threshold")
    pdf.bl("Source Discovery: bulk discovery settings")
    pdf.bl("Auto-Scan: periodic automatic scanning (1-24h)")
    pdf.bl("Updates: auto-update configuration")
    pdf.bl("Appearance: dark/light theme")
    pdf.bl("API Keys: HikerAPI + Gemini")
    pdf.bl("Source Indexing: bulk index all sources")
    pdf.bl("Source Blacklist: excluded sources")
    pdf.bl("Campaign Templates: preset configurations")

    # 8. Drawer
    pdf.ch("8. Account Detail Drawer")
    pdf.p("Click any account to open the detail drawer with 4 tabs.")
    if "drawer" in screens:
        pdf.img(screens["drawer"], "Account Detail Drawer")
    pdf.sh("Tabs")
    pdf.bl("Summary: identity, performance cards, config, FBR, peer comparison")
    pdf.bl("Alerts: auto-generated alerts + contextual action cards")
    pdf.bl("Sources: all sources with FBR and quality flags")
    pdf.bl("History: unified timeline of actions, FBR, sessions")
    pdf.sh("Quick Actions")
    pdf.bl("Row 1: Set Review | TB +1 | Limits +1")
    pdf.bl("Row 2: Open Folder | Copy Diagnostic | Export Profile")

    # 9. Workflow
    pdf.ch("9. Daily Workflow")
    pdf.sh("Morning (10-15 min)")
    pdf.bl("Open Cockpit for urgent items")
    pdf.bl("Sort by Health ascending, review worst accounts")
    pdf.bl("Set review flags as needed")
    pdf.sh("Weekly")
    pdf.bl("Analyze FBR, Bulk Delete Weak Sources")
    pdf.bl("Bulk Find Sources for under-sourced accounts")
    pdf.bl("Check Fleet tab, Source Profiles for niche mismatches")
    pdf.sh("Tips")
    pdf.bl("10+ sources per account, remove FBR < 3%")
    pdf.bl("Match source niche to account niche")
    pdf.bl("Use Source Blacklist for competitors")

    # 10. Shortcuts
    pdf.ch("10. Keyboard Shortcuts")
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(50, 7, "Key", border=1)
    pdf.cell(0, 7, "Action", border=1, new_x="LMARGIN", new_y="NEXT")
    for k, a in [("Space", "Toggle drawer"), ("Escape", "Close drawer/dialog"),
                  ("Left/Right", "Switch drawer tabs"), ("Up/Down", "Navigate accounts"),
                  ("Ctrl+R", "Refresh")]:
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(50, 7, k, border=1)
        pdf.cell(0, 7, a, border=1, new_x="LMARGIN", new_y="NEXT")

    # 11. Troubleshooting
    pdf.ch("11. Troubleshooting")
    for prob, sol in [
        ("Bot Root Not Set", "Enter Onimator path at top, click Save."),
        ("Scan finds no devices", "Check path. Run Onimator at least once."),
        ("0 quality sources", "Accounts need followback data. Lower Min FBR% in Settings."),
        ("API Key Required", "Settings > API Keys, enter HikerAPI key, Save."),
        ("Irrelevant source results", "Ensure client profile has clear bio/category."),
        ("OH.exe won't start", "Right-click > Run as administrator. Check antivirus."),
        ("Auto-scan not working", "Settings > Auto-Scan > enable, set interval, Save."),
    ]:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(170, 60, 60)
        pdf.cell(0, 6, f"Problem: {prob}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(60, 60, 60)
        pdf.multi_cell(0, 5.5, f"Solution: {sol}")
        pdf.ln(2)

    pdf.sh("Data Locations")
    pdf.bl("Database: %APPDATA%\\OH\\oh.db")
    pdf.bl("Logs: %APPDATA%\\OH\\logs\\oh.log")

    pdf.output(str(OUTPUT_PDF))
    sz = OUTPUT_PDF.stat().st_size // 1024
    print(f"\nPDF: {OUTPUT_PDF} ({sz} KB, {pdf.pages_count} pages)")


if __name__ == "__main__":
    print("OH User Guide PDF Generator")
    print("=" * 40)
    take_screenshots()
    print("Done!")
