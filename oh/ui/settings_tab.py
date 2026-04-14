"""
SettingsTab — configurable OH settings exposed to operators.

Groups:
  FBR Analysis           — follow count threshold, quality FBR%
  Source Cleanup         — weak-source delete threshold, min source count warning
  Source Finder API Keys — HikerAPI and Gemini API keys
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QPushButton, QLabel, QDoubleSpinBox, QSpinBox, QComboBox, QCheckBox,
    QLineEdit, QProgressBar, QMessageBox, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QScrollArea,
)
from PySide6.QtCore import Qt, Signal

from oh.repositories.settings_repo import SettingsRepository
from oh.ui.style import sc


class SettingsTab(QWidget):
    settings_saved = Signal()

    def __init__(self, settings_repo: SettingsRepository, source_finder_service=None, blacklist_repo=None, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings_repo
        self._source_finder_service = source_finder_service
        self._blacklist_repo = blacklist_repo
        self._index_worker = None  # WorkerThread for source indexing
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(12)

        # -- FBR Analysis group --
        fbr_group = QGroupBox("FBR Analysis")
        fbr_form  = QFormLayout(fbr_group)
        fbr_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._min_follows_spin = QSpinBox()
        self._min_follows_spin.setRange(1, 999_999)
        self._min_follows_spin.setFixedWidth(100)
        self._min_follows_spin.setToolTip(
            "Sources with fewer follows than this are excluded from quality analysis."
        )
        fbr_form.addRow("Min follow count for quality:", self._min_follows_spin)

        self._min_fbr_spin = QDoubleSpinBox()
        self._min_fbr_spin.setRange(0.0, 100.0)
        self._min_fbr_spin.setDecimals(1)
        self._min_fbr_spin.setSuffix("  %")
        self._min_fbr_spin.setFixedWidth(100)
        self._min_fbr_spin.setToolTip(
            "A source is considered 'quality' if its FBR% meets or exceeds this value."
        )
        fbr_form.addRow("Min FBR% for quality:", self._min_fbr_spin)

        outer.addWidget(fbr_group)

        # -- Source Cleanup group --
        sc_group = QGroupBox("Source Cleanup")
        sc_form  = QFormLayout(sc_group)
        sc_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._delete_thresh_spin = QDoubleSpinBox()
        self._delete_thresh_spin.setRange(0.0, 100.0)
        self._delete_thresh_spin.setDecimals(1)
        self._delete_thresh_spin.setSuffix("  %")
        self._delete_thresh_spin.setFixedWidth(100)
        self._delete_thresh_spin.setToolTip(
            "Bulk 'delete weak sources' removes sources whose weighted FBR is\n"
            "at or below this threshold (only sources with sufficient follow data\n"
            "and at least one active account are affected)."
        )
        sc_form.addRow("Weak source delete threshold:", self._delete_thresh_spin)

        self._min_src_spin = QSpinBox()
        self._min_src_spin.setRange(0, 999)
        self._min_src_spin.setFixedWidth(100)
        self._min_src_spin.setToolTip(
            "Accounts with fewer active sources than this are highlighted in the\n"
            "Accounts tab as potentially under-resourced."
        )
        sc_form.addRow("Min active sources (warning threshold):", self._min_src_spin)

        outer.addWidget(sc_group)

        # -- Source Discovery group --
        sd_group = QGroupBox("Source Discovery")
        sd_form  = QFormLayout(sd_group)
        sd_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._bulk_min_src_spin = QSpinBox()
        self._bulk_min_src_spin.setRange(1, 50)
        self._bulk_min_src_spin.setFixedWidth(100)
        self._bulk_min_src_spin.setToolTip(
            "Accounts with fewer active sources than this will qualify for bulk source discovery."
        )
        sd_form.addRow("Min sources for bulk discovery:", self._bulk_min_src_spin)

        self._bulk_top_n_spin = QSpinBox()
        self._bulk_top_n_spin.setRange(1, 10)
        self._bulk_top_n_spin.setFixedWidth(100)
        self._bulk_top_n_spin.setToolTip(
            "Number of top-ranked discovered profiles to auto-add per account."
        )
        sd_form.addRow("Auto-add top N results:", self._bulk_top_n_spin)

        sd_hint = QLabel(
            "Accounts with fewer active sources than the threshold will be included in bulk discovery."
        )
        sd_hint.setWordWrap(True)
        sd_hint.setStyleSheet(f"color: {sc('text_secondary').name()}; font-size: 11px;")
        sd_form.addRow("", sd_hint)

        outer.addWidget(sd_group)

        # -- Auto-Scan group --
        auto_group = QGroupBox("Auto-Scan")
        auto_form = QFormLayout(auto_group)
        auto_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._auto_scan_check = QCheckBox("Enable automatic Scan && Sync")
        self._auto_scan_check.setToolTip("Run Scan & Sync automatically at the configured interval")
        auto_form.addRow("", self._auto_scan_check)

        self._auto_scan_interval = QComboBox()
        self._auto_scan_interval.addItems(["1", "2", "4", "6", "12", "24"])
        self._auto_scan_interval.setFixedWidth(80)
        self._auto_scan_interval.setToolTip("Hours between automatic scans")
        auto_form.addRow("Interval (hours):", self._auto_scan_interval)

        auto_hint = QLabel("Auto-scan runs Scan & Sync in the background. The timer resets on manual scan.")
        auto_hint.setWordWrap(True)
        auto_hint.setStyleSheet(f"color: {sc('text_secondary').name()}; font-size: 11px;")
        auto_form.addRow("", auto_hint)

        outer.addWidget(auto_group)

        # -- Auto-Fix (Self-Healing) group --
        af_group = QGroupBox("Auto-Fix (Self-Healing)")
        af_form = QFormLayout(af_group)
        af_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._af_source_cleanup = QCheckBox("Detect weak sources after Scan")
        self._af_source_cleanup.setToolTip(
            "Detect sources with wFBR near 0% and sufficient follow data.\n"
            "Proposals are shown for operator review before any removal.\n"
            "Always creates a backup before removing."
        )
        af_form.addRow("", self._af_source_cleanup)

        self._af_tb_escalation = QCheckBox("Detect TB escalation candidates")
        self._af_tb_escalation.setToolTip(
            "Detect accounts with 0 actions for 2+ consecutive days\n"
            "in their active time slot. Proposed for operator review.\n"
            "Accounts reaching TB4+ are also flagged for review."
        )
        af_form.addRow("", self._af_tb_escalation)

        self._af_dead_device = QCheckBox("Detect offline devices")
        self._af_dead_device.setToolTip(
            "After Scan & Sync, flag devices where all accounts\n"
            "had 0 actions today. Shown as alert in Cockpit."
        )
        af_form.addRow("", self._af_dead_device)

        self._af_duplicate_cleanup = QCheckBox("Detect duplicate sources")
        self._af_duplicate_cleanup.setToolTip(
            "Detect duplicate entries (same source, different casing)\n"
            "in sources.txt files. Proposed for operator review.\n"
            "Creates backup before changes."
        )
        af_form.addRow("", self._af_duplicate_cleanup)

        af_hint = QLabel(
            "Issues are detected after each Scan & Sync and shown for operator review. "
            "No changes are made without explicit approval."
        )
        af_hint.setWordWrap(True)
        af_hint.setStyleSheet(f"color: {sc('text_secondary').name()}; font-size: 11px;")
        af_form.addRow("", af_hint)

        outer.addWidget(af_group)

        # -- Appearance group --
        app_group = QGroupBox("Appearance")
        app_form  = QFormLayout(app_group)
        app_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["dark", "light"])
        self._theme_combo.setFixedWidth(100)
        self._theme_combo.setToolTip(
            "Switch between dark and light mode.\n"
            "Change takes effect after restarting OH."
        )
        app_form.addRow("Theme:", self._theme_combo)

        self._help_tips_check = QCheckBox("Show context help buttons (?)")
        self._help_tips_check.setToolTip(
            "Show contextual help buttons throughout the interface"
        )
        app_form.addRow("", self._help_tips_check)

        self._reset_tour_btn = QPushButton("Restart Guided Tour")
        self._reset_tour_btn.setFixedWidth(160)
        self._reset_tour_btn.setToolTip(
            "Show the guided tour again from the brand bar"
        )
        self._reset_tour_btn.clicked.connect(self._on_reset_tour)
        app_form.addRow("Guided Tour:", self._reset_tour_btn)

        outer.addWidget(app_group)

        # -- Source Finder — API Keys group --
        sf_group = QGroupBox("Source Finder — API Keys")
        sf_form  = QFormLayout(sf_group)
        sf_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._hiker_key_edit = QLineEdit()
        self._hiker_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._hiker_key_edit.setFixedWidth(300)
        self._hiker_key_edit.setPlaceholderText("Enter HikerAPI key")
        sf_form.addRow("HikerAPI Key:", self._hiker_key_edit)

        self._gemini_key_edit = QLineEdit()
        self._gemini_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._gemini_key_edit.setFixedWidth(300)
        self._gemini_key_edit.setPlaceholderText("Enter Gemini API key")
        sf_form.addRow("Gemini API Key:", self._gemini_key_edit)

        sf_hint = QLabel(
            "Keys are stored locally. HikerAPI is required for source discovery, "
            "Gemini is optional for AI scoring."
        )
        sf_hint.setWordWrap(True)
        sf_hint.setStyleSheet(f"color: {sc('text_secondary').name()}; font-size: 11px;")
        sf_form.addRow("", sf_hint)

        outer.addWidget(sf_group)

        # -- Source Indexing group --
        idx_group = QGroupBox("Source Indexing")
        idx_lo = QVBoxLayout(idx_group)

        idx_desc = QLabel(
            "Scan all active sources from bot accounts and index them into the database.\n"
            "This fetches profile data from HikerAPI and classifies each source by niche.\n"
            "Sources already indexed will be skipped."
        )
        idx_desc.setWordWrap(True)
        idx_desc.setStyleSheet(f"color: {sc('text_secondary').name()}; font-size: 11px;")
        idx_lo.addWidget(idx_desc)

        idx_btn_row = QHBoxLayout()
        self._index_btn = QPushButton("Scan & Index Sources")
        self._index_btn.setFixedHeight(32)
        self._index_btn.setToolTip("Fetch profile data for all active sources and classify their niche")
        self._index_btn.clicked.connect(self._on_index_sources)
        idx_btn_row.addWidget(self._index_btn)

        self._index_progress = QProgressBar()
        self._index_progress.setFixedHeight(20)
        self._index_progress.setVisible(False)
        idx_btn_row.addWidget(self._index_progress, stretch=1)
        idx_lo.addLayout(idx_btn_row)

        self._index_status = QLabel("")
        self._index_status.setStyleSheet(f"color: {sc('text_secondary').name()}; font-size: 11px;")
        idx_lo.addWidget(self._index_status)

        outer.addWidget(idx_group)

        # -- Source Blacklist group --
        bl_group = QGroupBox("Source Blacklist")
        bl_lo = QVBoxLayout(bl_group)

        bl_desc = QLabel("Sources in the blacklist will never be added during source discovery.")
        bl_desc.setWordWrap(True)
        bl_desc.setStyleSheet(f"color: {sc('text_secondary').name()}; font-size: 11px;")
        bl_lo.addWidget(bl_desc)

        bl_input_row = QHBoxLayout()
        self._bl_input = QLineEdit()
        self._bl_input.setPlaceholderText("Enter source username to blacklist...")
        self._bl_input.setFixedHeight(28)
        bl_input_row.addWidget(self._bl_input, stretch=1)

        self._bl_add_btn = QPushButton("Add")
        self._bl_add_btn.setFixedHeight(28)
        self._bl_add_btn.clicked.connect(self._on_add_blacklist)
        bl_input_row.addWidget(self._bl_add_btn)

        self._bl_remove_btn = QPushButton("Remove Selected")
        self._bl_remove_btn.setFixedHeight(28)
        self._bl_remove_btn.clicked.connect(self._on_remove_blacklist)
        bl_input_row.addWidget(self._bl_remove_btn)

        bl_lo.addLayout(bl_input_row)

        self._bl_list = QTableWidget(0, 3)
        self._bl_list.setHorizontalHeaderLabels(["Source", "Reason", "Added"])
        self._bl_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._bl_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._bl_list.setMaximumHeight(150)
        self._bl_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        bl_lo.addWidget(self._bl_list)

        self._bl_status = QLabel("")
        self._bl_status.setStyleSheet(f"color: {sc('text_secondary').name()}; font-size: 11px;")
        bl_lo.addWidget(self._bl_status)

        outer.addWidget(bl_group)

        # -- Campaign Templates group --
        tpl_group = QGroupBox("Campaign Templates")
        tpl_lo = QVBoxLayout(tpl_group)
        tpl_desc = QLabel("Save and manage preset configurations for new client campaigns.")
        tpl_desc.setWordWrap(True)
        tpl_desc.setStyleSheet(f"color: {sc('text_secondary').name()}; font-size: 11px;")
        tpl_lo.addWidget(tpl_desc)

        self._templates_btn = QPushButton("Manage Templates")
        self._templates_btn.setFixedHeight(32)
        self._templates_btn.clicked.connect(self._on_manage_templates)
        tpl_lo.addWidget(self._templates_btn)

        outer.addWidget(tpl_group)

        # -- Warmup Templates group --
        wt_group = QGroupBox("Warmup Templates")
        wt_lo = QVBoxLayout(wt_group)
        wt_desc = QLabel("Manage warmup presets used for account onboarding.")
        wt_desc.setWordWrap(True)
        wt_desc.setStyleSheet(f"color: {sc('text_secondary').name()}; font-size: 11px;")
        wt_lo.addWidget(wt_desc)

        self._warmup_templates_btn = QPushButton("Manage Warmup Templates")
        self._warmup_templates_btn.setFixedHeight(32)
        self._warmup_templates_btn.clicked.connect(self._on_manage_warmup_templates)
        wt_lo.addWidget(self._warmup_templates_btn)

        outer.addWidget(wt_group)

        # -- Error Reporting group --
        err_group = QGroupBox("Error Reporting")
        err_form = QFormLayout(err_group)
        err_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._report_endpoint_edit = QLineEdit()
        self._report_endpoint_edit.setPlaceholderText("Discord webhook URL or custom endpoint...")
        err_form.addRow("Report endpoint:", self._report_endpoint_edit)

        self._auto_crash_check = QCheckBox("Automatically send crash reports")
        self._auto_crash_check.setToolTip(
            "When enabled, unhandled crashes are automatically reported "
            "(only technical data — no account/client info)."
        )
        err_form.addRow("", self._auto_crash_check)

        outer.addWidget(err_group)

        # -- Save button --
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("Save Settings")
        save_btn.setFixedHeight(30)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        outer.addLayout(btn_row)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {sc('success').name()}; font-size: 11px;")
        outer.addWidget(self._status_label, alignment=Qt.AlignmentFlag.AlignRight)

        outer.addStretch()

        scroll.setWidget(content)
        root.addWidget(scroll)

    def _load(self) -> None:
        min_f, min_fbr = self._settings.get_fbr_thresholds()
        self._min_follows_spin.setValue(min_f)
        self._min_fbr_spin.setValue(min_fbr)
        self._delete_thresh_spin.setValue(self._settings.get_weak_source_threshold())
        self._min_src_spin.setValue(self._settings.get_min_source_count_warning())
        current_theme = self._settings.get("theme") or "dark"
        idx = self._theme_combo.findText(current_theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        self._bulk_min_src_spin.setValue(int(self._settings.get("min_source_for_bulk_discovery") or "10"))
        self._bulk_top_n_spin.setValue(int(self._settings.get("bulk_auto_add_top_n") or "5"))
        self._auto_scan_check.setChecked(self._settings.get("auto_scan_enabled") == "1")
        interval = self._settings.get("auto_scan_interval_hours") or "6"
        idx = self._auto_scan_interval.findText(interval)
        if idx >= 0:
            self._auto_scan_interval.setCurrentIndex(idx)
        self._hiker_key_edit.setText(self._settings.get("hiker_api_key") or "")
        self._gemini_key_edit.setText(self._settings.get("gemini_api_key") or "")
        self._report_endpoint_edit.setText(self._settings.get("report_endpoint") or "")
        self._auto_crash_check.setChecked(self._settings.get("auto_send_crashes") != "0")
        self._af_source_cleanup.setChecked(self._settings.get("auto_fix_source_cleanup") != "0")
        self._af_tb_escalation.setChecked(self._settings.get("auto_fix_tb_escalation") != "0")
        self._af_dead_device.setChecked(self._settings.get("auto_fix_dead_device_alert") != "0")
        self._af_duplicate_cleanup.setChecked(self._settings.get("auto_fix_duplicate_cleanup") != "0")
        self._help_tips_check.setChecked((self._settings.get("show_help_tips") or "1") != "0")
        self._load_blacklist()

    def _save(self) -> None:
        self._settings.set("min_follows_threshold",        str(self._min_follows_spin.value()))
        self._settings.set("min_fbr_threshold",            str(self._min_fbr_spin.value()))
        self._settings.set("weak_source_delete_threshold", str(self._delete_thresh_spin.value()))
        self._settings.set("min_source_count_warning",     str(self._min_src_spin.value()))

        self._settings.set("min_source_for_bulk_discovery", str(self._bulk_min_src_spin.value()))
        self._settings.set("bulk_auto_add_top_n", str(self._bulk_top_n_spin.value()))

        self._settings.set("auto_scan_enabled", "1" if self._auto_scan_check.isChecked() else "0")
        self._settings.set("auto_scan_interval_hours", self._auto_scan_interval.currentText())

        self._settings.set("auto_fix_source_cleanup", "1" if self._af_source_cleanup.isChecked() else "0")
        self._settings.set("auto_fix_tb_escalation", "1" if self._af_tb_escalation.isChecked() else "0")
        self._settings.set("auto_fix_dead_device_alert", "1" if self._af_dead_device.isChecked() else "0")
        self._settings.set("auto_fix_duplicate_cleanup", "1" if self._af_duplicate_cleanup.isChecked() else "0")

        self._settings.set("hiker_api_key",  self._hiker_key_edit.text().strip())
        self._settings.set("gemini_api_key", self._gemini_key_edit.text().strip())


        self._settings.set("report_endpoint", self._report_endpoint_edit.text().strip())
        self._settings.set("auto_send_crashes", "1" if self._auto_crash_check.isChecked() else "0")

        show_tips = self._help_tips_check.isChecked()
        self._settings.set("show_help_tips", "1" if show_tips else "0")
        from oh.ui.help_button import HelpButton
        HelpButton.set_all_visible(show_tips)

        new_theme = self._theme_combo.currentText()
        old_theme = self._settings.get("theme") or "dark"
        self._settings.set("theme", new_theme)

        if new_theme != old_theme:
            self._status_label.setText(
                f"Settings saved. Theme changed to '{new_theme}' — restart OH to apply."
            )
        else:
            self._status_label.setText("Settings saved.")

        self.settings_saved.emit()

    def _on_index_sources(self) -> None:
        """Start scanning and indexing all active sources."""
        if self._source_finder_service is None:
            QMessageBox.warning(self, "Not Available", "Source finder service not initialized.")
            return

        hiker_key = self._settings.get("hiker_api_key") or ""
        if not hiker_key:
            QMessageBox.warning(
                self, "API Key Required",
                "HikerAPI key is not configured.\nEnter it above and save first.",
            )
            return

        bot_root = self._settings.get("bot_root_path") or ""
        if not bot_root:
            QMessageBox.warning(self, "Bot Root Not Set", "Set the Onimator path first.")
            return

        self._index_btn.setEnabled(False)
        self._index_btn.setText("Scanning...")
        self._index_progress.setVisible(True)
        self._index_progress.setRange(0, 0)  # indeterminate initially
        self._index_status.setText("Starting source scan...")

        from oh.ui.workers import WorkerThread
        self._index_worker = WorkerThread(
            self._source_finder_service.scan_and_index_sources,
            bot_root,
        )
        self._index_worker.result.connect(self._on_index_complete)
        self._index_worker.error.connect(self._on_index_error)
        self._index_worker.start()

    def _on_index_complete(self, result) -> None:
        """Handle source indexing completion."""
        self._index_btn.setEnabled(True)
        self._index_btn.setText("Scan & Index Sources")
        self._index_progress.setVisible(False)
        self._index_worker = None

        indexed, skipped, failed, errors = result
        total = indexed + skipped + failed
        msg = f"Done: {indexed} indexed, {skipped} already known, {failed} failed (of {total} sources)"
        self._index_status.setText(msg)

        if errors:
            detail = "\n".join(errors[:10])
            if len(errors) > 10:
                detail += f"\n... and {len(errors) - 10} more"
            QMessageBox.information(
                self, "Source Indexing Complete",
                f"{msg}\n\nErrors:\n{detail}",
            )
        else:
            QMessageBox.information(self, "Source Indexing Complete", msg)

    def _on_index_error(self, error_msg: str) -> None:
        """Handle source indexing error."""
        self._index_btn.setEnabled(True)
        self._index_btn.setText("Scan & Index Sources")
        self._index_progress.setVisible(False)
        self._index_worker = None
        self._index_status.setText(f"Error: {error_msg}")
        QMessageBox.critical(self, "Indexing Failed", f"Source indexing failed:\n\n{error_msg}")


    # ------------------------------------------------------------------
    # Guided Tour
    # ------------------------------------------------------------------

    def _on_reset_tour(self) -> None:
        self._settings.set("tour_completed", "0")
        QMessageBox.information(
            self, "Tour Reset",
            "The guided tour will be available again from the brand bar."
        )

    # ------------------------------------------------------------------
    # Campaign Templates
    # ------------------------------------------------------------------

    def _on_manage_templates(self) -> None:
        from oh.ui.campaign_templates_dialog import CampaignTemplatesDialog
        from oh.repositories.campaign_template_repo import CampaignTemplateRepository
        conn = self._settings._conn
        repo = CampaignTemplateRepository(conn)
        dlg = CampaignTemplatesDialog(repo, parent=self)
        dlg.exec()

    # ------------------------------------------------------------------
    # Warmup Templates
    # ------------------------------------------------------------------

    def _on_manage_warmup_templates(self) -> None:
        from oh.ui.warmup_templates_dialog import WarmupTemplatesDialog
        from oh.repositories.warmup_template_repo import WarmupTemplateRepository
        conn = self._settings._conn
        repo = WarmupTemplateRepository(conn)
        dlg = WarmupTemplatesDialog(repo, parent=self)
        dlg.exec()

    # ------------------------------------------------------------------
    # Source Blacklist
    # ------------------------------------------------------------------

    def _on_add_blacklist(self) -> None:
        name = self._bl_input.text().strip()
        if not name or self._blacklist_repo is None:
            return
        self._blacklist_repo.add(name)
        self._bl_input.clear()
        self._load_blacklist()

    def _on_remove_blacklist(self) -> None:
        if self._blacklist_repo is None:
            return
        selected = self._bl_list.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        name_item = self._bl_list.item(row, 0)
        if name_item:
            self._blacklist_repo.remove(name_item.text())
            self._load_blacklist()

    def _load_blacklist(self) -> None:
        if self._blacklist_repo is None:
            self._bl_status.setText("Blacklist not available")
            return
        items = self._blacklist_repo.get_all()
        self._bl_list.setRowCount(len(items))
        for i, item in enumerate(items):
            self._bl_list.setItem(i, 0, QTableWidgetItem(item["source_name"]))
            self._bl_list.setItem(i, 1, QTableWidgetItem(item.get("reason", "")))
            self._bl_list.setItem(i, 2, QTableWidgetItem(item.get("added_at", "")[:10]))
        self._bl_status.setText(f"{len(items)} sources blacklisted")
