# Target Splitter — Distribute Sources Across Accounts

**Status**: Planned
**Priority**: High
**Origin**: OniHelper feature migration
**Estimated effort**: Medium (1 service, 1 dialog, integration into 2 tabs)

---

## Overview

Operators need to distribute a set of source names across multiple accounts. Today this is done manually in OniHelper or by hand-editing sources.txt files. Target Splitter brings this into OH with full preview, confirmation, backup, and audit trail.

**Critical rule**: OH never performs actions without operator approval. The flow is always: **preview -> confirm -> execute**.

## User Flow

```
1. Operator clicks "Distribute Sources" (Sources tab toolbar OR Accounts tab bulk menu)
2. Wizard Step 1: SELECT SOURCES
   - Text area to paste/type source names (one per line)
   - OR pre-filled from selected sources in the Sources tab
   - Shows count of valid sources after dedup + trim
3. Wizard Step 2: SELECT TARGET ACCOUNTS
   - Table of all active accounts (username, device, active source count)
   - Filters: by device, by group, by tag, search
   - Checkboxes to select/deselect; "Select All" / "Deselect All"
   - Shows count of selected accounts
4. Wizard Step 3: CHOOSE STRATEGY + PREVIEW
   - Strategy selector: "Even split" or "Fill up"
   - Preview table: source_name | target_account | device
   - Summary: "N sources -> M accounts, X sources per account (avg)"
   - Warnings if any source is already present in a target account (skip)
5. Operator clicks "Apply" (or goes back to adjust)
6. Execution: SourceRestorer writes to sources.txt files with backup
7. Results dialog: N added, N skipped (already present), N failed
```

## Architecture

### No New Database Tables

Reuses existing tables:
- `source_assignments` — updated via `mark_source_active()` after each successful write
- `operator_actions` — audit log entry for the distribute operation
- `delete_history` — **not used** (this is an additive operation, not a deletion)

### Layer Map

| Layer | File | What it does |
|-------|------|-------------|
| **model** | `oh/models/target_splitter.py` | `SplitPlan`, `SplitAssignment`, `SplitResult` dataclasses |
| **module** | *(none new)* | Reuses `oh/modules/source_restorer.py` for file writes |
| **service** | `oh/services/target_splitter_service.py` | Distribution algorithms + orchestration |
| **repository** | *(none new)* | Reuses `SourceAssignmentRepository`, `OperatorActionRepository` |
| **ui** | `oh/ui/target_splitter_dialog.py` | 3-step wizard dialog |

---

## Implementation Steps

### Step 1: Model — `oh/models/target_splitter.py`

Create pure dataclasses for the split plan and results.

```python
@dataclass
class SplitAssignment:
    """One source -> one account mapping in a distribution plan."""
    source_name: str
    account_id: int
    username: str
    device_id: str
    device_name: str
    skipped: bool = False       # True if source already present
    skip_reason: Optional[str] = None

@dataclass
class SplitPlan:
    """Complete distribution plan ready for operator review."""
    strategy: str               # "even_split" | "fill_up"
    sources: list[str]
    target_account_ids: list[int]
    assignments: list[SplitAssignment]
    skipped_count: int = 0      # pre-existing source-account pairs

    @property
    def effective_count(self) -> int:
        """Assignments that will actually be written (not skipped)."""
        return sum(1 for a in self.assignments if not a.skipped)

@dataclass
class SplitResult:
    """Outcome after executing a SplitPlan."""
    total_attempted: int = 0
    total_added: int = 0        # successfully written to sources.txt
    total_skipped: int = 0      # already present, no write needed
    total_failed: int = 0       # write error
    errors: list[str] = field(default_factory=list)

    @property
    def fully_succeeded(self) -> bool:
        return self.total_failed == 0

    def summary_line(self) -> str:
        parts = []
        if self.total_added:
            parts.append(f"{self.total_added} added")
        if self.total_skipped:
            parts.append(f"{self.total_skipped} already present")
        if self.total_failed:
            parts.append(f"{self.total_failed} failed")
        return " / ".join(parts) if parts else "No assignments to apply"
```

### Step 2: Service — `oh/services/target_splitter_service.py`

Pure logic layer. No UI imports. No direct file access (delegates to SourceRestorer).

**Constructor dependencies**:
- `SourceAssignmentRepository` — to check existing assignments + mark active after write
- `OperatorActionRepository` — to log the audit trail
- `AccountRepository` — to look up account details for the plan

**Public methods**:

#### `compute_plan(sources, account_ids, strategy, bot_root) -> SplitPlan`

Read-only. Computes the distribution and marks which assignments would be skipped (source already in account's sources.txt or already active in source_assignments).

Algorithm for **"even_split"**:
1. Deduplicate and strip source names
2. Assign sources round-robin across selected accounts
3. For each (source, account) pair, check `source_assignments` is_active — if already active, mark `skipped=True`

Algorithm for **"fill_up"**:
1. Get active source counts per account via `get_active_source_counts()`
2. For each source, assign to the account with the fewest active sources (among selected accounts)
3. After each assignment, increment that account's count in the working map
4. Same skip check as above

**Important**: The plan is deterministic and side-effect-free. The operator sees the exact plan before anything is written.

#### `execute_plan(plan, bot_root) -> SplitResult`

Writes to disk. Only called after operator confirms.

For each non-skipped assignment in `plan.assignments`:
1. Call `SourceRestorer.restore_source(device_id, username, device_name, source_name)`
2. If `restored=True`: call `mark_source_active(account_id, source_name)`, increment `total_added`
3. If `already_present=True`: increment `total_skipped` (defensive — plan already filtered these)
4. If `error`: increment `total_failed`, collect error message
5. Per-item errors do NOT abort the batch (standard OH pattern)

After all writes:
- Log one `OperatorActionRecord` per account touched:
  - `action_type = "distribute_sources"`
  - `new_value` = comma-separated list of sources added to that account
  - `note` = strategy name + total source count

Return `SplitResult`.

#### `get_accounts_with_source_counts(account_ids) -> list[tuple[AccountRecord, int]]`

Helper for the UI to show active source counts next to each account in the selection step.

### Step 3: Dialog — `oh/ui/target_splitter_dialog.py`

A `QDialog` with a `QStackedWidget` for 3 wizard pages. Follows the same dialog patterns as `DeleteConfirmDialog` and `BulkActionDialog`.

**Page 1: Select Sources**
- `QPlainTextEdit` for pasting source names (one per line)
- `QLabel` showing "N valid sources" (updated on text change, after dedup/strip)
- If opened from Sources tab with pre-selected sources, pre-populate the text area
- "Next >" button (disabled if 0 valid sources)

**Page 2: Select Target Accounts**
- `QTableWidget` with columns: [Checkbox, Username, Device, Group, Active Sources]
- Filter row: device combo, group combo, search field
- "Select All" / "Deselect All" buttons
- `QLabel` showing "N accounts selected"
- "< Back" and "Next >" buttons (Next disabled if 0 accounts selected)
- Account data loaded via `AccountRepository.get_all_active()` + `SourceAssignmentRepository.get_active_source_counts()`

**Page 3: Preview + Apply**
- Strategy combo: "Even split" / "Fill up" (default: Even split)
- Changing strategy recomputes the plan (calls `compute_plan()`)
- Preview table: [Source, Account, Device, Status]
  - Status column: "Will add" (green) or "Already present" (gray)
- Summary label: "N sources -> M accounts, X will be added, Y already present"
- Warning if any account will end up with 0 new sources after skip filtering
- "< Back" and "Apply" buttons
- Apply button is green (additive operation, not destructive)
- Apply button disabled during execution, progress shown

**After execution**:
- Replace preview with result summary
- Show `SplitResult.summary_line()`
- "Close" button replaces "Apply"

**Dialog dimensions**: min 700x500, resizable.

### Step 4: Integration — Sources Tab

In `oh/ui/sources_tab.py`, add a toolbar button:

```
[Refresh Sources]  [Delete Source]  [Bulk Delete...]  [Distribute Sources]  ...
```

**Button**: "Distribute Sources"
- Always enabled (sources can be typed manually)
- If sources are selected in the table, pass them as pre-fill to the dialog
- On click: open `TargetSplitterDialog` with `pre_selected_sources=<selected source names>`
- After dialog closes with success: call `self._on_refresh()` to reload the sources table

### Step 5: Integration — Main Window

In `oh/ui/main_window.py`:

1. Import `TargetSplitterService`
2. Instantiate it alongside other services in `__init__`:
   ```python
   self._target_splitter_service = TargetSplitterService(
       assignment_repo=SourceAssignmentRepository(conn),
       operator_action_repo=operator_action_repo,
       account_repo=self._accounts,
   )
   ```
3. Pass it to `SourcesTab` as a new constructor parameter:
   ```python
   self._sources_tab = SourcesTab(
       ...,
       target_splitter_service=self._target_splitter_service,
   )
   ```
4. Also expose it for the Accounts tab bulk action (future integration point)

### Step 6: Operator Action Audit

Add a new action type constant in `oh/models/operator_action.py`:

```python
ACTION_DISTRIBUTE_SOURCES = "distribute_sources"
```

The service logs one `OperatorActionRecord` per account that received at least one new source:
- `action_type`: `"distribute_sources"`
- `old_value`: `None`
- `new_value`: comma-separated source names added (e.g., `"source1, source2, source3"`)
- `note`: `"Even split: 10 sources across 5 accounts"` (strategy summary)

These appear in the existing Operator Action History dialog without any changes.

---

## Safety Measures

1. **Preview before execute** — operator sees exact plan, can go back and adjust
2. **Backup before write** — SourceRestorer creates sources.txt.bak before every modification (existing behavior)
3. **Skip duplicates** — sources already present in an account are not re-added
4. **Per-item error isolation** — one failing account does not abort the batch
5. **Audit trail** — every change logged in operator_actions
6. **source_assignments updated** — OH database stays in sync with disk state
7. **Read-only plan computation** — `compute_plan()` never writes to disk

## Edge Cases

| Scenario | Handling |
|----------|----------|
| Source already in account | Marked "skipped" in preview, not written |
| Account has no sources.txt | SourceRestorer creates the file (existing behavior) |
| sources.txt write fails | Error collected, other accounts continue |
| 0 valid sources entered | "Next" button disabled, cannot proceed |
| 0 accounts selected | "Next" button disabled, cannot proceed |
| All assignments skipped | Apply button shows "Nothing to apply", disabled |
| Operator closes dialog mid-wizard | No changes made (writes only happen on Apply) |
| Very large distribution (100+ accounts) | Use WorkerThread to avoid UI freeze |

## Testing Checklist

- [ ] Even split distributes sources round-robin correctly
- [ ] Fill up prioritizes accounts with fewest sources
- [ ] Sources already present are correctly identified and skipped
- [ ] SourceRestorer is called with correct arguments
- [ ] source_assignments is updated after successful writes
- [ ] operator_actions audit entries are created
- [ ] Dialog pre-fills sources from Sources tab selection
- [ ] Back/Next navigation works correctly
- [ ] Strategy change recomputes the preview
- [ ] Error in one account does not abort the batch
- [ ] Empty source list / empty account list blocks progression

## File Changes Summary

| Action | File |
|--------|------|
| **CREATE** | `oh/models/target_splitter.py` |
| **CREATE** | `oh/services/target_splitter_service.py` |
| **CREATE** | `oh/ui/target_splitter_dialog.py` |
| **MODIFY** | `oh/models/operator_action.py` — add `ACTION_DISTRIBUTE_SOURCES` |
| **MODIFY** | `oh/ui/sources_tab.py` — add "Distribute Sources" toolbar button |
| **MODIFY** | `oh/ui/main_window.py` — instantiate + wire `TargetSplitterService` |

## Next Agent

Run `/coder` to implement this plan.
