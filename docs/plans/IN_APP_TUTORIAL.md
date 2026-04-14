# In-App Tutorial & Help System

> **Priority: MEDIUM** | Author: Planner agent | Date: 2026-04-06

---

## Problem

New OH operators have no guided introduction to the tool. The interface has many features (Cockpit, FBR analysis, source management, Auto-Fix, Fleet monitoring) and new users must discover them by trial and error. After updates, there is no way to communicate what changed. This slows onboarding and leads to underuse of powerful features.

## Solution

Four non-intrusive help features that guide new users and keep existing users informed:

1. **First-Run Onboarding Wizard** -- walks through initial setup (path, first scan)
2. **What's New Dialog** -- shows changes after version updates
3. **Context Help Buttons** -- "?" icons next to complex sections with popup explanations
4. **Interactive Guided Tour** -- translucent overlay highlighting UI elements one by one

**Critical constraint:** Everything is optional. Every dialog has Skip/Dismiss. All features can be disabled in Settings. Nothing blocks normal workflow.

---

## Architecture

### Layer mapping

| Layer | File | Responsibility |
|-------|------|----------------|
| **UI** | `oh/ui/onboarding_dialog.py` | First-run wizard (QDialog + QStackedWidget) |
| **UI** | `oh/ui/whats_new_dialog.py` | Post-update changelog dialog |
| **UI** | `oh/ui/help_button.py` | Reusable HelpButton widget with popup |
| **UI** | `oh/ui/guided_tour.py` | Full-window overlay tour with spotlight |
| **UI** | `oh/ui/main_window.py` | Integration: trigger dialogs, place help buttons, add tour button |
| **UI** | `oh/ui/settings_tab.py` | Toggle for help tips, tour reset button |
| **Repo** | `oh/repositories/settings_repo.py` | New config defaults (no schema change) |

### Settings keys (all stored in oh_config)

| Key | Default | Purpose |
|-----|---------|---------|
| `onboarding_done` | `"0"` | Set to `"1"` after wizard is completed or skipped |
| `last_seen_version` | `""` | Tracks which version the user last saw What's New for |
| `show_help_tips` | `"1"` | Show/hide "?" help buttons throughout the UI |
| `tour_completed` | `"0"` | Set to `"1"` after tour is completed or skipped |

No database migration needed -- `seed_defaults()` handles new keys automatically.

### Trigger flow on startup

```
main.py
  └─ window.show()
       └─ QTimer.singleShot(500, _check_onboarding)
            │
            ├─ IF bot_root_path is empty AND onboarding_done != "1"
            │    → show OnboardingDialog (modal)
            │    → on finish/skip: set onboarding_done = "1"
            │
            └─ THEN (after onboarding closes OR if skipped):
                 └─ _check_whats_new()
                      └─ IF BUILD_VERSION != last_seen_version
                           AND WHATS_NEW has entry for BUILD_VERSION
                           → show WhatsNewDialog (modal)
                           → on close: set last_seen_version = BUILD_VERSION
```

---

## Feature 1: First-Run Onboarding Wizard

### File: `oh/ui/onboarding_dialog.py`

### Class: `OnboardingDialog(QDialog)`

### Design

- Modal QDialog, fixed size ~600x450
- QStackedWidget with 4 pages
- Bottom bar: page indicator dots + "Skip" (left) + "Back" / "Next"/"Finish" (right)
- Consistent with dark/light theme via `sc()` colors and app stylesheet

### Pages

**Page 0 -- Welcome**
- Logo (if available) centered, 64px height
- Title: "Welcome to OH" (styled heading)
- Subtitle: "Operational Hub for managing Onimator campaigns at scale."
- Brief 3-line description of what OH does
- Buttons: "Let's Get Started" (primary), "Skip Setup" (secondary)

**Page 1 -- Set Bot Path**
- Title: "Connect to Onimator"
- Description: "Select the folder where your Onimator installation lives. OH will read device and account data from this folder."
- QLineEdit + Browse button (reuse the same pattern as `_make_settings_bar`)
- Validation: check folder exists and contains expected subfolder structure (e.g., has at least one subfolder with `data.db` or known bot files)
- Show green checkmark label when valid, red warning when invalid
- If path already set in settings, pre-fill it

**Page 2 -- First Scan**
- Title: "Discover Your Accounts"
- Description: "OH will scan the Onimator folder to find all devices, accounts, and their current state. This usually takes a few seconds."
- Large "Scan & Sync" QPushButton (centered, prominent)
- Progress indicator (QLabel showing status text)
- After scan completes: show summary ("Found X devices, Y accounts")
- "Next" button enabled only after scan completes (or user clicks "Skip this step")

**Page 3 -- Done**
- Title: "You're All Set"
- Summary of what was configured
- Tips section (3 bullet points):
  - "Open Cockpit at the start of each shift for a daily overview"
  - "Run Analyze FBR regularly to track source quality"
  - "Check the Sources tab to manage source assignments across accounts"
- "Take a Tour" button (secondary) -- launches guided tour after dialog closes
- "Open Cockpit Now" button (secondary)
- "Finish" button (primary)
- Checkbox: "Don't show this again" (pre-checked)

### Behavior

- On any page, "Skip" button closes the dialog and sets `onboarding_done = "1"`
- "Finish" on last page sets `onboarding_done = "1"`
- The bot_root_path is saved immediately when validated on Page 1 (same as main settings bar behavior)
- If user clicks "Take a Tour", store that intent and launch tour after dialog closes
- If user clicks "Open Cockpit Now", emit a signal that MainWindow catches to open CockpitDialog

### Signals

```python
tour_requested = Signal()     # user wants to start guided tour
cockpit_requested = Signal()  # user wants to open Cockpit
```

### Constructor

```python
def __init__(self, settings_repo: SettingsRepository, scan_service: ScanService, parent=None)
```

### Integration in `main_window.py`

```python
# In MainWindow.__init__, after existing QTimer.singleShot(3000, self._check_for_updates):
QTimer.singleShot(500, self._check_onboarding)

def _check_onboarding(self) -> None:
    bot_root = self._settings.get_bot_root()
    onboarding_done = self._settings.get("onboarding_done") or "0"
    if not bot_root and onboarding_done != "1":
        dlg = OnboardingDialog(self._settings, self._scan_service, parent=self)
        dlg.tour_requested.connect(self._start_guided_tour)
        dlg.cockpit_requested.connect(self._on_cockpit)
        dlg.exec()
    self._check_whats_new()
```

---

## Feature 2: What's New Dialog

### File: `oh/ui/whats_new_dialog.py`

### Class: `WhatsNewDialog(QDialog)`

### Design

- Modal QDialog, ~500x400
- Header with version number
- Scrollable list of changes
- Single "Got it" button

### Content structure

```python
WHATS_NEW: dict = {
    "1.4.0": [
        ("Target Splitter", "Distribute sources evenly across accounts. Sources tab > Distribute Sources."),
        ("Settings Copier", "Copy bot settings from one account to others. Accounts > Actions > Copy Settings."),
        ("Auto-Fix Proposals", "OH detects issues and shows proposals for your review. Nothing changes without approval."),
        ("Improved Security", "Application is now compiled to native code. Updates verified with SHA256."),
    ],
    # Future versions add entries here. Older entries are kept for reference.
}
```

### Layout

- Title label: "What's New in OH v{version}" (styled as heading)
- QScrollArea containing a QVBoxLayout of change items
- Each item: QFrame with title (bold) + description (normal), separated by subtle border
- Bottom bar: "Got it" QPushButton (primary, centered)

### Constructor

```python
def __init__(self, version: str, parent=None)
```

### Behavior

- Dialog only shown if `WHATS_NEW` has an entry for the current version
- On "Got it" click: dialog accepts, caller sets `last_seen_version`
- If version not found in `WHATS_NEW`, dialog is never shown (no empty state)

### Integration in `main_window.py`

```python
def _check_whats_new(self) -> None:
    try:
        from oh.version import BUILD_VERSION
    except ImportError:
        return
    last_seen = self._settings.get("last_seen_version") or ""
    if last_seen == BUILD_VERSION:
        return
    from oh.ui.whats_new_dialog import WhatsNewDialog, WHATS_NEW
    if BUILD_VERSION not in WHATS_NEW:
        return
    dlg = WhatsNewDialog(BUILD_VERSION, parent=self)
    dlg.exec()
    self._settings.set("last_seen_version", BUILD_VERSION)
```

---

## Feature 3: Context Help Buttons

### File: `oh/ui/help_button.py`

### Classes

**`HelpButton(QToolButton)`** -- small "?" button that shows a help popup on click.

**`HelpPopup(QFrame)`** -- frameless popup showing help text, auto-hides.

### HelpButton design

- Fixed size 20x20, round border, "?" text
- Styled with `sc()` colors: border matches `border`, text matches `text_secondary`
- Hover: border and text brighten to `text`
- Cursor: PointingHandCursor
- On click: create and show HelpPopup positioned near the button

### HelpPopup design

- QFrame with `WindowFlags = Popup` (auto-closes on click outside)
- Max width 320px, word-wrap enabled
- Background: `bg_note`, border: `border`, text: `text`
- Title (optional, bold) + body text
- Auto-hide timer: 10 seconds via QTimer.singleShot
- Positioned below the HelpButton, offset slightly right
- If popup would go off-screen, adjust position upward

### Constructor

```python
class HelpButton(QToolButton):
    def __init__(self, title: str, text: str, parent=None)
```

### Visibility control

- HelpButton checks `show_help_tips` setting before showing
- When `show_help_tips = "0"`, all HelpButtons hide themselves (setVisible(False))
- Need a class-level method to toggle all instances:

```python
@classmethod
def set_all_visible(cls, visible: bool) -> None:
    for ref in cls._instances:
        btn = ref()
        if btn is not None:
            btn.setVisible(visible)
```

Use `weakref` list to track instances.

### Placement locations

| Location | Widget/Method | Title | Help Text |
|----------|--------------|-------|-----------|
| Cockpit button area | `_make_toolbar()` | "Cockpit" | "Daily operations overview. Start each shift here. Shows action items, flagged accounts, and recommendations." |
| Analyze FBR button | `_make_toolbar()` | "FBR Analysis" | "Computes Follow-Back Rate for all sources across all accounts. Shows which sources bring followers back and which should be replaced." |
| Sources tab header | `_build_ui()` near tabs | "Sources" | "Global view of all sources across all accounts. See weighted FBR, usage counts, and manage sources in bulk." |
| Fleet tab header | `_build_ui()` near tabs | "Fleet" | "Device-level overview. See which phones are online, total accounts per device, and daily action totals." |
| Auto-Fix group | `settings_tab.py _build_ui()` | "Auto-Fix" | "OH detects issues after each Scan & Sync and shows proposals for your review. No changes are made without your approval." |
| FBR Analysis group | `settings_tab.py _build_ui()` | "FBR Settings" | "Set the minimum follow count and FBR percentage to classify a source as quality. Sources below these thresholds are flagged." |

### Integration

In `main_window.py`, add HelpButton instances inline next to relevant widgets in `_make_toolbar()` and `_build_ui()`. Example:

```python
from oh.ui.help_button import HelpButton

# In _make_toolbar(), after cockpit_btn:
lo.addWidget(HelpButton(
    "Cockpit",
    "Daily operations overview. Start each shift here.\n"
    "Shows action items, flagged accounts, and recommendations.",
))
```

In `settings_tab.py`, add HelpButton to group box titles or next to group labels.

### Settings toggle in SettingsTab

Add a checkbox in the Appearance group:

```python
self._help_tips_check = QCheckBox("Show help tips (?)")
self._help_tips_check.setToolTip("Show contextual help buttons throughout the interface")
app_form.addRow("", self._help_tips_check)
```

On save, update `show_help_tips` and call `HelpButton.set_all_visible(checked)`.

---

## Feature 4: Interactive Guided Tour

### File: `oh/ui/guided_tour.py`

### Classes

**`TourStep`** -- dataclass defining one step of the tour.

**`GuidedTourOverlay(QWidget)`** -- full-window overlay with spotlight and tooltip card.

### TourStep dataclass

```python
@dataclass
class TourStep:
    widget_name: str       # objectName of the target widget
    title: str             # step title shown in tooltip card
    description: str       # explanation text
    position: str = "bottom"  # tooltip position relative to widget: top/bottom/left/right
```

### Tour steps (defined as constant list)

```python
TOUR_STEPS = [
    TourStep("settingsBar",  "Set Your Bot Path",      "Point OH to your Onimator installation folder. Click Browse to select it, then Save.", "bottom"),
    TourStep("scanBtn",      "Scan & Sync",            "Discovers all devices and accounts from the bot folder. Run this to populate OH with your data.", "bottom"),
    TourStep("cockpitBtn",   "Daily Cockpit",          "Your shift dashboard. Shows critical issues, flagged accounts, and top recommendations.", "bottom"),
    TourStep("filterBar",    "Filter Accounts",        "Filter by status, FBR state, device, tags, or search by username. Combine filters to narrow down.", "bottom"),
    TourStep("accountTable", "Account Table",          "All your accounts at a glance. Click a row to select, press Space to open the detail panel.", "top"),
    TourStep("sourcesTab",   "Global Sources",         "Manage sources across all accounts. See weighted FBR, delete weak sources, distribute new ones.", "bottom"),
    TourStep("settingsTabW", "Settings & Configuration", "Configure FBR thresholds, API keys, auto-fix rules, and appearance.", "bottom"),
]
```

### GuidedTourOverlay design

- Inherits QWidget, parented to MainWindow
- Fills entire MainWindow geometry
- Raised above all other widgets (raise_() + setWindowFlags if needed)
- setAttribute(WA_TransparentForMouseEvents, False) -- captures all clicks

### Painting

```
paintEvent:
  1. Fill entire widget with semi-transparent black (rgba 0,0,0,180))
  2. Find target widget by objectName using self.parent().findChild(QWidget, name)
  3. Map target widget's rect to overlay coordinates
  4. Clear (cut out) the target rect area → shows the actual widget underneath
  5. Draw a subtle border (2px, highlight color) around the cutout
```

### Tooltip card

- A child QFrame of the overlay (not a separate window)
- White/dark background (theme-aware via `sc()`)
- Max width 360px
- Contains:
  - Step counter: "Step 3 of 7" (muted text, top)
  - Title (bold, 14px)
  - Description (normal, 12px, word-wrap)
  - Button row: "Back" (secondary) | "Next" (primary) | "Skip Tour" (text link)
  - On last step: "Finish" instead of "Next", plus "Don't show again" QCheckBox
- Positioned relative to the target widget based on `position` field
- Clamp to overlay bounds so card never goes off-screen

### Navigation

```python
def _go_to_step(self, index: int) -> None:
    self._current = index
    step = TOUR_STEPS[index]
    target = self.parent().findChild(QWidget, step.widget_name)
    if target is None or not target.isVisible():
        # Skip to next visible step
        if index < len(TOUR_STEPS) - 1:
            self._go_to_step(index + 1)
        else:
            self._finish()
        return
    self._highlight_widget = target
    self._update_card(step)
    self.update()  # trigger repaint
```

### Signals

```python
tour_finished = Signal()  # emitted on Finish or Skip
```

### Behavior

- "Skip Tour" at any step: close overlay, set `tour_completed = "1"`
- "Finish" on last step: close overlay, set `tour_completed = "1"`
- "Don't show again" checkbox only on last step (controls `tour_completed`)
- Escape key closes the tour (same as Skip)
- If a target widget is not found (e.g., tab not visible), skip that step silently

### Constructor

```python
def __init__(self, settings_repo: SettingsRepository, parent: QWidget)
```

### Required objectNames

These must be set in `main_window.py` on the relevant widgets so `findChild` can locate them:

```python
# In _make_settings_bar():
frame.setObjectName("settingsBar")          # already exists

# In _make_toolbar():
self._scan_btn.setObjectName("scanBtn")
# cockpit button needs objectName:
cockpit_btn.setObjectName("cockpitBtn")

# In _build_ui() or _make_filter_bar():
# filter bar frame needs objectName:
filter_frame.setObjectName("filterBar")

# Account table:
self._table.setObjectName("accountTable")

# Tab widgets -- use tab bar or specific tab widget names
# For sources/settings tabs, set objectName on the tab widget entries
```

### Integration

**Brand bar** -- add "Take a Tour" button next to "Check for Updates":

```python
# In _make_brand_bar(), before ver_lbl:
tour_btn = QPushButton("Take a Tour")
tour_btn.setFixedHeight(22)
# ... same styling as update_btn ...
tour_btn.clicked.connect(self._start_guided_tour)
lo.addWidget(tour_btn)
```

**MainWindow method:**

```python
def _start_guided_tour(self) -> None:
    from oh.ui.guided_tour import GuidedTourOverlay
    overlay = GuidedTourOverlay(self._settings, parent=self)
    overlay.tour_finished.connect(overlay.deleteLater)
    overlay.show()
    overlay.raise_()
```

**SettingsTab** -- add "Reset Tour" button in Appearance group so user can re-trigger tour:

```python
self._reset_tour_btn = QPushButton("Reset Tour")
self._reset_tour_btn.setFixedWidth(120)
self._reset_tour_btn.setToolTip("Show the guided tour again on next 'Take a Tour' click")
self._reset_tour_btn.clicked.connect(self._on_reset_tour)
app_form.addRow("Guided Tour:", self._reset_tour_btn)

def _on_reset_tour(self) -> None:
    self._settings.set("tour_completed", "0")
    QMessageBox.information(self, "Tour Reset", "The guided tour will be available again from the brand bar.")
```

---

## Implementation Steps

### Step 1: Settings defaults (5 min)

**File:** `oh/repositories/settings_repo.py`

Add 4 new entries to `_CONFIG_DEFAULTS`:

```python
("onboarding_done",    "0",  "Whether the first-run onboarding wizard has been completed"),
("last_seen_version",  "",   "Last version for which What's New was shown"),
("show_help_tips",     "1",  "Show contextual help buttons (?) in the UI"),
("tour_completed",     "0",  "Whether the guided tour has been completed"),
```

No migration needed -- `seed_defaults()` uses INSERT OR IGNORE.

### Step 2: HelpButton widget (45 min)

**New file:** `oh/ui/help_button.py`

1. Implement `HelpPopup(QFrame)`:
   - Popup window flag, styled background/border via `sc()`
   - Title label (bold, optional) + body label (word-wrap)
   - QTimer.singleShot(10000, self.close) for auto-hide
   - Position calculation relative to parent button

2. Implement `HelpButton(QToolButton)`:
   - 20x20 fixed size, "?" text, round border
   - Track instances via `weakref.ref` list
   - `set_all_visible(cls, visible)` class method
   - On click: instantiate HelpPopup, position it, show it
   - On init: check `show_help_tips` setting if settings_repo passed, else always visible

### Step 3: OnboardingDialog (90 min)

**New file:** `oh/ui/onboarding_dialog.py`

1. Create `OnboardingDialog(QDialog)` with QStackedWidget (4 pages)
2. Page 0 (Welcome): logo + title + description + buttons
3. Page 1 (Set Path): QLineEdit + Browse + validation label
4. Page 2 (First Scan): scan button + status label + result summary
5. Page 3 (Done): summary + tips + action buttons + checkbox
6. Bottom navigation: dot indicators + Skip/Back/Next/Finish
7. Signals: `tour_requested`, `cockpit_requested`
8. Scan runs via `WorkerThread` to avoid blocking UI

### Step 4: WhatsNewDialog (30 min)

**New file:** `oh/ui/whats_new_dialog.py`

1. Define `WHATS_NEW` dict constant with v1.4.0 entries
2. Create `WhatsNewDialog(QDialog)`:
   - Version header
   - Scrollable list of (title, description) items styled as cards
   - "Got it" button
3. Theme-aware styling via `sc()`

### Step 5: GuidedTourOverlay (120 min)

**New file:** `oh/ui/guided_tour.py`

1. Define `TourStep` dataclass
2. Define `TOUR_STEPS` constant list (7 steps)
3. Implement `GuidedTourOverlay(QWidget)`:
   - `paintEvent`: semi-transparent overlay + spotlight cutout
   - Tooltip card as child QFrame with step counter, title, description, buttons
   - Navigation: `_go_to_step()`, `_next()`, `_back()`, `_skip()`, `_finish()`
   - Position calculation for tooltip card (below/above/left/right of target)
   - Escape key handling
   - `tour_finished` signal

### Step 6: Integration in main_window.py (60 min)

1. **Set objectNames** on key widgets:
   - `self._scan_btn.setObjectName("scanBtn")` (in `_make_toolbar`)
   - Cockpit button: `cockpit_btn.setObjectName("cockpitBtn")`
   - Filter bar frame: `filter_frame.setObjectName("filterBar")`
   - Account table: `self._table.setObjectName("accountTable")`

2. **Add HelpButton instances** in `_make_toolbar()`:
   - Next to Cockpit button
   - Next to Analyze FBR button

3. **Add "Take a Tour" button** in `_make_brand_bar()`:
   - Same visual style as "Check for Updates"
   - Calls `self._start_guided_tour()`

4. **Add startup checks**:
   - `QTimer.singleShot(500, self._check_onboarding)`
   - `_check_onboarding()` method: checks settings, shows wizard if needed, then calls `_check_whats_new()`
   - `_check_whats_new()` method: compares version, shows dialog if needed
   - `_start_guided_tour()` method: creates and shows overlay

5. **Connect onboarding signals**:
   - `tour_requested` -> `_start_guided_tour`
   - `cockpit_requested` -> `_on_cockpit`

### Step 7: Integration in settings_tab.py (30 min)

1. **Add help tips toggle** in Appearance group:
   - QCheckBox "Show help tips (?)"
   - Load from `show_help_tips` setting
   - On save: update setting + call `HelpButton.set_all_visible()`

2. **Add HelpButton instances** next to group boxes:
   - Auto-Fix group
   - FBR Analysis group

3. **Add tour reset** in Appearance group:
   - "Reset Tour" button
   - Sets `tour_completed = "0"` + confirmation message

### Step 8: Testing (30 min)

1. **Manual testing checklist:**
   - [ ] First launch with no bot_root_path: wizard appears
   - [ ] Skip button on every wizard page works, sets onboarding_done
   - [ ] Browse + validate path on Page 1
   - [ ] Scan on Page 2 runs and shows results
   - [ ] Finish on Page 3 sets onboarding_done
   - [ ] Second launch: wizard does NOT appear
   - [ ] Version change: What's New dialog appears
   - [ ] "Got it" sets last_seen_version
   - [ ] Help buttons visible, click shows popup
   - [ ] Popup auto-hides after 10s
   - [ ] Disable help tips in Settings: all "?" buttons hide
   - [ ] "Take a Tour" button starts overlay
   - [ ] Tour highlights correct widgets
   - [ ] Next/Back navigation works
   - [ ] Skip closes tour
   - [ ] Finish on last step sets tour_completed
   - [ ] Reset Tour in Settings re-enables tour
   - [ ] Dark theme: all dialogs/overlays look correct
   - [ ] Light theme: all dialogs/overlays look correct

2. **Unit tests** (`tests/test_help_system.py`):
   - HelpButton instance tracking and set_all_visible
   - WHATS_NEW dict structure validation
   - TourStep dataclass instantiation
   - OnboardingDialog page navigation (if QApplication available)

---

## File change summary

| File | Action | Scope |
|------|--------|-------|
| `oh/repositories/settings_repo.py` | EDIT | Add 4 entries to `_CONFIG_DEFAULTS` |
| `oh/ui/help_button.py` | NEW | HelpButton + HelpPopup widgets (~120 lines) |
| `oh/ui/onboarding_dialog.py` | NEW | OnboardingDialog with 4-page wizard (~300 lines) |
| `oh/ui/whats_new_dialog.py` | NEW | WhatsNewDialog + WHATS_NEW constant (~120 lines) |
| `oh/ui/guided_tour.py` | NEW | GuidedTourOverlay + TourStep (~280 lines) |
| `oh/ui/main_window.py` | EDIT | Add startup checks, help buttons, tour button, objectNames (~60 lines added) |
| `oh/ui/settings_tab.py` | EDIT | Add help tips toggle, help buttons, tour reset (~30 lines added) |
| `tests/test_help_system.py` | NEW | Basic unit tests (~60 lines) |

**Estimated total: ~970 lines of new code, ~90 lines of edits to existing files.**

---

## Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Tour overlay obscures critical UI during operation | Tour is never auto-triggered during normal use; only on explicit "Take a Tour" click |
| Onboarding blocks fast operators | Skip button on every page; dismissed in one click |
| Widget objectNames change breaks tour | Tour silently skips steps where target widget is not found |
| Performance of overlay painting | QPainter with simple rect operations; no complex compositing |
| Help popups overlap each other | HelpPopup uses Popup window flag; only one can be open at a time (Qt handles this) |

---

## Handoff

Next agent: **/coder** -- implement the plan following the step order above. Start with Step 1 (settings defaults) and Step 2 (HelpButton) as they have no dependencies, then proceed sequentially through Steps 3-7.
