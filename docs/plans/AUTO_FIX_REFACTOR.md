# Plan: Auto-Fix Refactor — From Auto-Execute to Proposal-Based Model

**Status**: READY FOR IMPLEMENTATION
**Priority**: HIGH — safety-critical change
**Principle**: OH must NEVER perform actions without operator approval.

---

## Problem

`AutoFixService.run_all()` currently **executes** fixes immediately after Scan & Sync:
- Deletes weak sources from `sources.txt`
- Escalates TB levels
- Flags dead devices
- Removes duplicate sources

This violates the core principle that OH should never modify bot state without explicit operator confirmation.

## Target Architecture

```
Scan & Sync completes
    |
    v
AutoFixService.detect_all()  -- detect issues, return proposals (NO side effects)
    |
    v
AutoFixProposalDialog        -- operator reviews proposals with checkboxes
    |
    v
Operator clicks "Apply Selected"
    |
    v
AutoFixService.execute_proposals()  -- execute only approved proposals
    |
    v
Results logged to auto_fix_actions table (existing)
```

---

## Files to Modify

| File | Change |
|------|--------|
| `oh/models/auto_fix.py` | **NEW** — `AutoFixProposal` dataclass |
| `oh/services/auto_fix_service.py` | Split `run_all()` into `detect_all()` + `execute_proposals()` |
| `oh/ui/auto_fix_dialog.py` | **NEW** — `AutoFixProposalDialog` with checkboxes |
| `oh/ui/main_window.py` | Show proposal dialog after sync instead of auto-executing |
| `oh/ui/settings_tab.py` | Update checkbox labels from "Auto-remove" to "Detect" |
| `oh/ui/cockpit_dialog.py` | No changes needed — already shows `auto_fix_lines` from result |

---

## Implementation Steps

### Step 1: Create `AutoFixProposal` model

**File**: `oh/models/auto_fix.py` (new)

```python
from dataclasses import dataclass
from typing import Optional, Callable, Any

# Proposal type constants
FIX_SOURCE_CLEANUP     = "source_cleanup"
FIX_TB_ESCALATION      = "tb_escalation"
FIX_DEAD_DEVICE        = "dead_device"
FIX_DUPLICATE_CLEANUP  = "duplicate_cleanup"

# Severity for display ordering
FIX_SEV_HIGH   = "HIGH"
FIX_SEV_MEDIUM = "MEDIUM"
FIX_SEV_LOW    = "LOW"

FIX_TYPE_LABELS = {
    FIX_SOURCE_CLEANUP:    "Remove Weak Source",
    FIX_TB_ESCALATION:     "Escalate TB",
    FIX_DEAD_DEVICE:       "Dead Device Alert",
    FIX_DUPLICATE_CLEANUP: "Remove Duplicates",
}

@dataclass
class AutoFixProposal:
    """A proposed auto-fix action awaiting operator approval."""
    fix_type:    str                # FIX_* constant
    severity:    str                # FIX_SEV_* constant
    target:      str                # username, device_name, or source_name
    description: str                # human-readable explanation
    detail:      str                # additional context (e.g., "wFBR=0.2%, 150 follows")
    execute:     Optional[Callable] # callable that performs the fix; None for info-only (dead_device)
    metadata:    Optional[dict] = None  # extra data for logging after execution

    @property
    def is_actionable(self) -> bool:
        """True if this proposal can be executed (has a callable)."""
        return self.execute is not None

    @property
    def type_label(self) -> str:
        return FIX_TYPE_LABELS.get(self.fix_type, self.fix_type)
```

**Key decisions**:
- `execute` is a zero-arg callable that performs the action and returns an `int` (items affected). Set to `None` for info-only proposals (dead device detection).
- `metadata` carries data needed for `_log_action()` after execution.
- Dataclass, no I/O — follows project model conventions.

---

### Step 2: Refactor `AutoFixService` — split detect vs execute

**File**: `oh/services/auto_fix_service.py`

#### 2a. Add `detect_all()` method

New method that returns `List[AutoFixProposal]` without executing anything. Each existing `_auto_*` method gets a `_detect_*` counterpart:

| Old method (executes)            | New method (detects)                | Returns |
|----------------------------------|-------------------------------------|---------|
| `_auto_cleanup_sources()`        | `_detect_weak_sources()`            | List of proposals, one per source |
| `_auto_escalate_tb()`            | `_detect_tb_candidates()`           | List of proposals, one per account |
| `_detect_dead_devices()`         | `_detect_dead_devices_proposals()`  | List of proposals, one per device |
| `_clean_duplicate_sources()`     | `_detect_duplicate_sources()`       | List of proposals, one per account |

```python
def detect_all(self, bot_root: str) -> List[AutoFixProposal]:
    """Detect all auto-fix candidates. Returns proposals — does NOT execute."""
    proposals = []

    if self._settings.get("auto_fix_source_cleanup") == "1":
        try:
            proposals.extend(self._detect_weak_sources(bot_root))
        except Exception as exc:
            logger.error("Source cleanup detection failed: %s", exc, exc_info=True)

    if self._settings.get("auto_fix_tb_escalation") == "1":
        try:
            proposals.extend(self._detect_tb_candidates())
        except Exception as exc:
            logger.error("TB escalation detection failed: %s", exc, exc_info=True)

    if self._settings.get("auto_fix_dead_device_alert") == "1":
        try:
            proposals.extend(self._detect_dead_devices_proposals())
        except Exception as exc:
            logger.error("Dead device detection failed: %s", exc, exc_info=True)

    if self._settings.get("auto_fix_duplicate_cleanup") == "1":
        try:
            proposals.extend(self._detect_duplicate_sources(bot_root))
        except Exception as exc:
            logger.error("Duplicate detection failed: %s", exc, exc_info=True)

    return proposals
```

#### 2b. Detection methods — pattern for each type

Each `_detect_*` method reuses the existing query/analysis logic but instead of executing, wraps the action in a lambda stored in the proposal's `execute` field.

**Example for source cleanup** (most complex):

```python
def _detect_weak_sources(self, bot_root: str) -> List[AutoFixProposal]:
    """Find sources eligible for cleanup. Returns proposals."""
    proposals = []
    threshold = float(self._settings.get("auto_fix_source_threshold") or "0.5")
    min_follows = int(self._settings.get("min_follows_threshold") or "100")
    min_source_warning = int(self._settings.get("min_source_count_warning") or "5")

    rows = self._conn.execute(
        """SELECT sf.source_name, sf.weighted_fbr_pct, sf.total_follows,
                  sf.total_accounts_used
           FROM source_fbr_stats sf
           WHERE sf.weighted_fbr_pct IS NOT NULL
             AND sf.weighted_fbr_pct <= ?
             AND sf.total_follows >= ?
             AND sf.total_accounts_used > 0
           ORDER BY sf.weighted_fbr_pct ASC""",
        (threshold, min_follows),
    ).fetchall()

    for row in rows:
        source_name = row["source_name"]
        assignments = self._assignments.get_active_assignments_for_source(source_name)
        eligible = self._filter_eligible_assignments(assignments, min_source_warning)
        if not eligible:
            continue

        n_accounts = len(eligible)
        wfbr = row["weighted_fbr_pct"]

        # Closure captures all needed state
        def make_executor(src=source_name, accs=eligible, br=bot_root, w=wfbr):
            def _execute():
                return self._execute_source_cleanup(br, src, accs, w)
            return _execute

        proposals.append(AutoFixProposal(
            fix_type=FIX_SOURCE_CLEANUP,
            severity=FIX_SEV_HIGH,
            target=source_name,
            description=f"Remove '{source_name}' from {n_accounts} account(s)",
            detail=f"wFBR={wfbr:.1f}%, {row['total_follows']} follows",
            execute=make_executor(),
            metadata={"source_name": source_name, "wfbr": wfbr, "accounts": n_accounts},
        ))

    return proposals
```

**Important pattern**: Use a factory function (`make_executor`) for lambdas inside loops to avoid late-binding closure bugs.

#### 2c. Execution helpers

Each `_execute_*` method is extracted from the current `_auto_*` body. It performs the action and returns items affected count. Example:

```python
def _execute_source_cleanup(self, bot_root, source_name, eligible, wfbr):
    """Execute source removal. Returns number of accounts cleaned."""
    from oh.modules.source_deleter import SourceDeleter
    deleter = SourceDeleter(bot_root)
    removed = 0
    for acc_id, device_id, username, device_name in eligible:
        try:
            fr = deleter.remove_source(device_id, username, device_name, source_name)
            if fr.removed:
                self._assignments.mark_source_inactive(acc_id, source_name)
                removed += 1
        except Exception as exc:
            logger.warning("Cleanup %s from %s failed: %s", source_name, username, exc)
    if removed:
        self._log_action("source_cleanup", None, None,
                         f"Removed '{source_name}' (wFBR={wfbr:.1f}%) from {removed} account(s)",
                         removed)
    return removed
```

#### 2d. Add `execute_proposals()` method

```python
def execute_proposals(self, proposals: List[AutoFixProposal]) -> AutoFixResult:
    """Execute a list of approved proposals. Returns summary."""
    result = AutoFixResult()
    for p in proposals:
        if not p.is_actionable:
            # Info-only proposals (dead device) — just log
            if p.fix_type == FIX_DEAD_DEVICE:
                result.dead_devices.append(p.target)
                self._log_action("dead_device", None, None, p.description, 0)
            continue
        try:
            count = p.execute()
            self._update_result(result, p.fix_type, p.target, count)
        except Exception as exc:
            logger.error("Auto-fix execution failed for %s: %s", p.target, exc)
            result.errors.append(f"{p.type_label} ({p.target}): {exc}")
    return result
```

#### 2e. Keep `run_all()` as deprecated fallback

Mark it deprecated but keep for backward compat. It should internally call `detect_all()` + `execute_proposals()`. This ensures nothing breaks if called from an unexpected path.

#### 2f. Helper: `_filter_eligible_assignments()`

Extract the per-assignment eligibility check (active account, above min source count) into a reusable method used by both detect and the existing code.

---

### Step 3: Create `AutoFixProposalDialog`

**File**: `oh/ui/auto_fix_dialog.py` (new)

A modal QDialog that shows detected proposals for operator review.

**Layout**:
```
+-----------------------------------------------------------+
|  Auto-Fix Proposals (N issues detected)                    |
+-----------------------------------------------------------+
|  [x] HIGH  Remove Weak Source  '@travel_tips'              |
|            wFBR=0.2%, 150 follows — from 3 account(s)      |
|  [x] HIGH  Remove Weak Source  '@food_page'                |
|            wFBR=0.0%, 200 follows — from 2 account(s)      |
|  [x] MED   Escalate TB         'user_abc'                  |
|            0 actions for 2+ days — TB3 -> TB4               |
|  [ ] LOW   Remove Duplicates   'user_xyz'                  |
|            4 duplicate source entries                       |
|  [i] ---   Dead Device Alert   'Samsung_A52'               |
|            0 active accounts today (5 total)                |
+-----------------------------------------------------------+
|  [Select All] [Deselect All]    [Skip All] [Apply Selected]|
+-----------------------------------------------------------+
```

**Key UI elements**:

1. **QTableWidget** with columns: Checkbox, Severity, Type, Target, Description
2. Each row has a checkbox (checked by default for HIGH, unchecked for LOW)
3. Info-only proposals (dead device) shown with info icon, no checkbox
4. **"Apply Selected"** button — executes checked proposals via `AutoFixService.execute_proposals()`
5. **"Skip All"** button — closes dialog without executing anything
6. **"Select All" / "Deselect All"** — convenience toggles
7. Dialog returns the `AutoFixResult` from execution (or empty result if skipped)

**Implementation details**:
- Extends `QDialog`
- Constructor takes `List[AutoFixProposal]` and `AutoFixService` reference
- Severity column uses color coding from `oh/ui/style.py` (`sc("high")`, `sc("medium")`, etc.)
- `apply_selected()` collects checked proposals, calls `auto_fix_service.execute_proposals(checked)`
- Stores result in `self.result` accessible after `exec()` returns
- Keyboard: Enter = Apply Selected, Escape = Skip All
- Size: ~700x400, modal

```python
class AutoFixProposalDialog(QDialog):
    def __init__(self, proposals: List[AutoFixProposal],
                 auto_fix_service, parent=None):
        super().__init__(parent)
        self._proposals = proposals
        self._service = auto_fix_service
        self.result = AutoFixResult()  # empty until Apply
        self._checkboxes = []  # list of QCheckBox widgets
        self.setWindowTitle(f"Auto-Fix Proposals ({len(proposals)} issues)")
        self.setMinimumSize(700, 400)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        # ... table with checkboxes, buttons ...
        pass

    def _apply_selected(self):
        selected = [p for p, cb in zip(self._proposals, self._checkboxes)
                    if cb.isChecked()]
        if selected:
            self.result = self._service.execute_proposals(selected)
        self.accept()

    def _skip_all(self):
        self.reject()
```

---

### Step 4: Update `main_window.py` — show dialog after sync

**File**: `oh/ui/main_window.py`

Replace the current auto-execute block (around line 1958-1970) with:

```python
# Detect auto-fix proposals (no execution)
if self._auto_fix_service:
    bot_root = self._settings.get_bot_root() or ""
    if bot_root:
        try:
            proposals = self._auto_fix_service.detect_all(bot_root)
            if proposals:
                from oh.ui.auto_fix_dialog import AutoFixProposalDialog
                dlg = AutoFixProposalDialog(
                    proposals, self._auto_fix_service, parent=self
                )
                dlg.exec()
                fix_result = dlg.result
                self._last_auto_fix_result = fix_result
                if fix_result.has_actions:
                    self._refresh_table()
                    lines = fix_result.summary_lines()
                    auto_fix_msg = "  |  Auto-fix: " + "; ".join(lines)
                    logger.info("Auto-fix applied: %s", "; ".join(lines))
        except Exception as exc:
            logger.warning("Auto-fix detection failed: %s", exc)
```

**Key change**: `run_all()` replaced with `detect_all()` + dialog + `execute_proposals()`.

The rest of the sync completion flow stays the same — Cockpit still shows `auto_fix_lines` from the result.

---

### Step 5: Update Settings tab labels

**File**: `oh/ui/settings_tab.py`

Update checkbox labels to reflect the proposal-based model:

| Old label | New label |
|-----------|-----------|
| "Auto-remove weak sources after Scan" | "Detect weak sources after Scan" |
| "Auto-escalate TB for inactive accounts" | "Detect TB escalation candidates" |
| "Detect offline devices" | "Detect offline devices" (no change) |
| "Auto-remove duplicate sources" | "Detect duplicate sources" |

Update tooltips similarly — replace "Automatically remove/escalate" with "Detect and propose for operator review".

---

### Step 6: Update Cockpit auto-fix banner text

**File**: `oh/ui/cockpit_dialog.py`

Minor wording change in the auto-fix banner (line 189):
- Old: `"Auto-Fix Results"`
- New: `"Auto-Fix Results (operator-approved)"`

This makes it clear in Cockpit that displayed actions were explicitly approved.

---

## What Does NOT Change

- **Database schema** — `auto_fix_actions` table stays as-is. Approved proposals log there.
- **Settings keys** — `auto_fix_source_cleanup`, `auto_fix_tb_escalation`, etc. Same keys, same semantics (enable/disable detection per type).
- **Cockpit display** — Still shows `auto_fix_lines` from the result. Data comes from approved proposals now.
- **`get_recent_actions()`** — Unchanged, still reads from `auto_fix_actions`.

## Testing Checklist

- [ ] Scan & Sync with all auto-fix toggles ON: proposal dialog appears with correct items
- [ ] Select some proposals, apply: only selected ones execute
- [ ] Skip all: nothing executes, no entries in `auto_fix_actions`
- [ ] Dead device proposals show as info-only (no checkbox)
- [ ] Cockpit shows approved actions correctly
- [ ] Settings toggles still control which proposal types are detected
- [ ] Scan & Sync with all toggles OFF: no dialog appears
- [ ] Scan & Sync with no issues detected: no dialog appears
- [ ] `run_all()` backward compat: still works if called (detect + execute all)

## Implementation Order

1. Step 1 — model (no dependencies)
2. Step 2 — service refactor (depends on model)
3. Step 3 — dialog (depends on model + service)
4. Step 4 — main_window integration (depends on dialog)
5. Step 5 — settings labels (independent, can be done anytime)
6. Step 6 — cockpit banner text (independent)

## Next Agent

Hand off to **/coder** for implementation.
