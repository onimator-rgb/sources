# Settings Copier — Copy Bot Settings Between Accounts

> **Priority: HIGH** | Author: Planner agent | Date: 2026-04-06

---

## Problem

Operators managing 100+ accounts frequently need to apply the same bot configuration (follow limits, like limits, working hours, DM settings) across multiple accounts. Today this requires opening each account's Onimator configuration individually — a slow, error-prone process that scales linearly with account count.

OniHelper (Onimator's helper tool) already provides this capability, but OH operators should not need a separate tool for a core operational task.

## Solution

A **Settings Copier** wizard dialog that lets the operator:
1. Select a source account (copy FROM)
2. Select one or more target accounts (copy TO)
3. Preview a side-by-side diff of current vs. new values
4. Toggle individual settings on/off via checkboxes
5. Apply with full backup, transaction safety, and audit logging

**This is the first time OH writes to bot settings.db files.** The implementation must be conservative: backup before write, transactional, per-key updates only (never overwrite the entire JSON blob).

---

## Architecture

### Layer mapping

| Layer | File | Responsibility |
|-------|------|----------------|
| **Model** | `oh/models/settings_copy.py` | Dataclasses for settings snapshot, diff, and copy result |
| **Module** | `oh/modules/settings_copier.py` | Read source settings.db, write to target settings.db (with backup + transaction) |
| **Service** | `oh/services/settings_copier_service.py` | Orchestrate: read source, build diff, execute copy, log audit trail |
| **UI** | `oh/ui/settings_copier_dialog.py` | 3-step wizard: select source/targets, preview diff, show results |

### Data flow

```
UI (wizard dialog)
  │
  ├─ Step 1: User picks source account
  │    → service.read_source_settings(account_id) → module reads settings.db (ro)
  │
  ├─ Step 2: User picks target accounts
  │    → service.preview_diff(source_id, target_ids, selected_keys)
  │    → module reads each target's settings.db (ro) → returns list of diffs
  │
  ├─ Step 3: User reviews diff, toggles checkboxes, clicks Apply
  │    → service.apply_copy(source_id, target_ids, selected_keys)
  │    → module writes each target's settings.db (backup → transaction → update JSON keys)
  │    → service logs to operator_actions
  │
  └─ Results summary shown in dialog
```

---

## Implementation Steps

### Step 1: Model — `oh/models/settings_copy.py`

Create pure dataclasses (no I/O, no logic):

```python
from dataclasses import dataclass, field
from typing import Optional

# Keys in settings.db → accountsettings.settings JSON that are safe to copy
COPYABLE_SETTINGS = {
    "default_action_limit_perday": "Follow limit / day",
    "like_limit_perday": "Like limit / day",
    "unfollow_limit_perday": "Unfollow limit / day",
    "start_time": "Working hours — start",
    "end_time": "Working hours — end",
    "follow_enabled": "Follow enabled",
    "unfollow_enabled": "Unfollow enabled",
    "like_enabled": "Like enabled",
    "dm_enabled": "DM enabled",
    "dm_limit_perday": "DM limit / day",
}

@dataclass
class SettingsSnapshot:
    """All copyable settings for one account, read from settings.db."""
    account_id: int
    username: str
    device_id: str
    device_name: Optional[str]
    values: dict  # key → value (from COPYABLE_SETTINGS keys)
    raw_json: Optional[dict] = None  # full JSON blob (for reference, never written)
    error: Optional[str] = None

@dataclass
class SettingsDiffEntry:
    """One setting key comparison: source value vs. target value."""
    key: str
    display_name: str
    source_value: object
    target_value: object
    is_different: bool  # True if source != target

@dataclass
class SettingsDiff:
    """Full diff for one target account."""
    target_account_id: int
    target_username: str
    target_device_name: Optional[str]
    entries: list  # list[SettingsDiffEntry]
    different_count: int = 0  # how many entries have is_different=True

@dataclass
class SettingsCopyResult:
    """Result of copying settings to one target account."""
    target_account_id: int
    target_username: str
    target_device_name: Optional[str]
    success: bool
    backed_up: bool
    keys_written: list  # list[str] — keys that were actually changed
    error: Optional[str] = None

@dataclass
class SettingsCopyBatchResult:
    """Aggregate result for the entire copy operation."""
    source_username: str
    total_targets: int
    success_count: int
    fail_count: int
    results: list  # list[SettingsCopyResult]
```

**Coder notes:**
- `COPYABLE_SETTINGS` is the allowlist — only these keys can be copied. Start conservative. More keys can be added later after verifying the settings.db JSON schema across real installations.
- The dict keys must match exactly what Onimator stores in `accountsettings.settings` JSON.
- If we discover additional keys during implementation (by inspecting real settings.db files), add them to `COPYABLE_SETTINGS` with clear display names.

---

### Step 2: Module — `oh/modules/settings_copier.py`

This module handles all settings.db file I/O. Follow the pattern of `source_deleter.py`:
- Stateless (re-reads file on every call)
- Backup before write
- Per-item errors don't abort batch
- Never raises to caller

```
class SettingsCopierModule:
    def __init__(self, bot_root: str) -> None

    def read_settings(self, device_id: str, username: str) -> SettingsSnapshot
        """Read all copyable settings from one account's settings.db (read-only)."""

    def write_settings(self, device_id: str, username: str,
                       updates: dict) -> SettingsCopyResult
        """Write specific keys to one account's settings.db.

        SAFETY:
        1. Read current JSON blob from accountsettings
        2. Create backup: settings.db.bak (copy the entire file)
        3. Merge only the specified keys into the JSON blob
        4. Write back the full JSON blob in a transaction
        5. Return result with backup/success status
        """
```

**Coder notes — CRITICAL safety requirements:**

1. **Backup**: Before any write, copy `settings.db` to `settings.db.bak` using `shutil.copy2()`. This preserves the entire SQLite file (not just the JSON blob). Log warning but proceed even if backup fails (matches `source_deleter.py` pattern).

2. **Read-modify-write, not overwrite**: Read the full JSON blob, `json.loads()` it, update only the requested keys, `json.dumps()` it back. Never replace the whole blob with just the copied keys — Onimator stores many other keys we don't touch.

3. **Transaction**: Use a single `UPDATE accountsettings SET settings = ? WHERE rowid = (SELECT rowid FROM accountsettings LIMIT 1)` inside a transaction. Do NOT open with `?mode=ro` for writes — use normal `sqlite3.connect()` with `timeout=10`.

4. **File locking**: Onimator may be running. Use `timeout=10` on the SQLite connection to wait for any locks. If the write fails due to `SQLITE_BUSY`, report the error gracefully — the operator can retry.

5. **Never create rows**: Only UPDATE existing rows. If `accountsettings` has no rows, report error — don't INSERT.

6. **Validate before write**: After reading the source JSON, verify the keys exist in `COPYABLE_SETTINGS`. Reject unknown keys.

---

### Step 3: Service — `oh/services/settings_copier_service.py`

Orchestrator that combines the module with repositories.

```
class SettingsCopierService:
    def __init__(self,
                 account_repo: AccountRepository,
                 action_repo: OperatorActionRepository,
                 settings_repo: SettingsRepository) -> None

    def read_source_settings(self, account_id: int) -> SettingsSnapshot
        """Read copyable settings from the source account.
        Resolves bot_root from settings_repo, account path from account_repo."""

    def preview_diff(self, source_snapshot: SettingsSnapshot,
                     target_account_ids: list,
                     selected_keys: list) -> list[SettingsDiff]
        """Build a diff for each target: current value vs. source value.
        Only includes keys from selected_keys that are in COPYABLE_SETTINGS."""

    def apply_copy(self, source_snapshot: SettingsSnapshot,
                   target_account_ids: list,
                   selected_keys: list) -> SettingsCopyBatchResult
        """Execute the copy operation.
        For each target:
          1. Build updates dict (only selected keys where value differs)
          2. Call module.write_settings()
          3. Log to operator_actions (one row per target account)
        Returns aggregate result."""
```

**Coder notes:**
- Use `account_repo.get_by_id()` to resolve `device_id` and `username` for path construction.
- Use `settings_repo.get_bot_root()` to get the Onimator folder path.
- Log to `operator_actions` with `action_type = "copy_settings"` — add this constant to `oh/models/operator_action.py`.
- `old_value` = JSON of the target's previous values for changed keys.
- `new_value` = JSON of the new values that were written.
- `note` = f"Copied from {source_username}: {len(keys_written)} settings"

---

### Step 4: Add action type constant

In `oh/models/operator_action.py`, add:

```python
ACTION_COPY_SETTINGS = "copy_settings"
```

No schema change needed — `action_type` is a TEXT column.

---

### Step 5: UI — `oh/ui/settings_copier_dialog.py`

A QDialog with a 3-step wizard layout. Follow existing dialog patterns (e.g., `delete_confirm_dialog.py`, `bulk_action_dialog.py`).

#### Step 1: Select Source Account

```
+----------------------------------------------------+
|  Copy Settings — Step 1 of 3                       |
|                                                     |
|  Source account:  [ComboBox: username @ device]      |
|                                                     |
|  Settings to copy:                                  |
|  +------------------------------------------------+|
|  | [x] Follow limit / day          150             ||
|  | [x] Like limit / day            200             ||
|  | [x] Working hours — start       06:00           ||
|  | [x] Working hours — end         12:00           ||
|  | [x] Follow enabled              True            ||
|  | [ ] Unfollow enabled            False           ||
|  | ...                                             ||
|  +------------------------------------------------+|
|                                                     |
|                            [Cancel]  [Next >>]      |
+----------------------------------------------------+
```

- ComboBox populated from `account_repo` — only active accounts with settings.db.
- On source selection change, call `service.read_source_settings()` and populate the settings table.
- All checkboxes checked by default. Operator can uncheck settings they don't want to copy.
- "Next" is disabled until source is selected and at least one setting is checked.

#### Step 2: Select Targets + Preview Diff

```
+----------------------------------------------------+
|  Copy Settings — Step 2 of 3                       |
|                                                     |
|  Select target accounts:                            |
|  [Select All] [Select None] [Select Same Device]   |
|  +------------------------------------------------+|
|  | [x] user1 @ Device-A    3 changes              ||
|  | [x] user2 @ Device-A    5 changes              ||
|  | [ ] user3 @ Device-B    0 changes (identical)  ||
|  | [x] user4 @ Device-B    2 changes              ||
|  +------------------------------------------------+|
|                                                     |
|  Preview (user1 @ Device-A):                        |
|  +------------------------------------------------+|
|  | Setting           | Current | New               ||
|  | Follow limit/day  | 100     | 150  (changed)    ||
|  | Like limit/day    | 200     | 200  (same)       ||
|  | Start time        | 08:00   | 06:00 (changed)   ||
|  +------------------------------------------------+|
|                                                     |
|                   [<< Back]  [Cancel]  [Apply >>]   |
+----------------------------------------------------+
```

- Target list excludes the source account.
- Accounts with 0 differences are shown but unchecked and grayed out.
- Clicking a target account in the list updates the diff preview table below.
- "N changes" badge computed from `preview_diff()`.
- Changed values highlighted (e.g., bold or colored).
- "Apply" button shows count: "Apply to N account(s)".
- "Apply" is disabled if no targets are checked.

#### Step 3: Results

```
+----------------------------------------------------+
|  Copy Settings — Results                            |
|                                                     |
|  Copied settings from source_user:                  |
|    5 / 6 accounts updated successfully              |
|    1 failed (Device-C/user5: SQLITE_BUSY)           |
|                                                     |
|  +------------------------------------------------+|
|  | Account          | Status  | Keys Changed       ||
|  | user1 @ Dev-A    | OK      | 3                  ||
|  | user2 @ Dev-A    | OK      | 5                  ||
|  | user4 @ Dev-B    | OK      | 2                  ||
|  | user5 @ Dev-C    | FAILED  | settings.db locked ||
|  +------------------------------------------------+|
|                                                     |
|                                          [Close]    |
+----------------------------------------------------+
```

**Coder notes:**
- Use `QStackedWidget` for the 3 steps (not separate dialogs).
- Source account ComboBox: format as `"{username}  ({device_name})"`.
- Diff table: use green/bold for changed values, gray for unchanged.
- Use `WorkerThread` for the apply step (writing to multiple settings.db files may take time if devices are on network paths).
- Cancel button always available. Back button on steps 2 and 3.
- On Apply click, show a brief confirmation: "Apply {N} settings to {M} accounts?" (matching OH's never-act-without-approval rule).

---

### Step 6: Integration — Main Window + Accounts Tab

Two entry points:

#### A. Context menu on single account row (right-click Actions menu)

In `oh/ui/main_window.py`, inside the existing account context menu builder, add:

```
"Copy Settings From This Account"  →  opens wizard with this account pre-selected as source
```

This goes in the existing `_build_context_menu()` or equivalent method, alongside existing actions like "Set Review", "TB +1", etc.

#### B. Bulk action from multi-select

When multiple accounts are selected, add to the bulk action menu:

```
"Paste Settings To Selected"  →  opens wizard at Step 2 with selected accounts as targets
```

This requires the operator to have previously opened the wizard for a source account, OR the wizard prompts them to select a source first.

**Simpler approach for v1**: Always open the full 3-step wizard. The entry points just pre-fill:
- "Copy Settings From This Account" → pre-selects source in Step 1
- "Paste Settings To Selected" → pre-selects targets in Step 2 (source must be chosen in Step 1)

---

### Step 7: Service Registration

In `main_window.py` where services are instantiated (the `__init__` method), add:

```python
from oh.services.settings_copier_service import SettingsCopierService

self._settings_copier_service = SettingsCopierService(
    account_repo=self._account_repo,
    action_repo=self._action_repo,
    settings_repo=self._settings_repo,
)
```

Pass this service to the dialog when opening it.

---

## File Change Summary

| Action | File | Description |
|--------|------|-------------|
| **CREATE** | `oh/models/settings_copy.py` | Dataclasses for snapshot, diff, copy result |
| **CREATE** | `oh/modules/settings_copier.py` | Read/write settings.db with backup + transaction |
| **CREATE** | `oh/services/settings_copier_service.py` | Orchestrate copy: read, diff, apply, audit |
| **CREATE** | `oh/ui/settings_copier_dialog.py` | 3-step wizard dialog |
| **EDIT** | `oh/models/operator_action.py` | Add `ACTION_COPY_SETTINGS` constant |
| **EDIT** | `oh/ui/main_window.py` | Register service, add context menu entries, open dialog |

---

## Safety Checklist

- [ ] settings.db.bak created before every write (shutil.copy2)
- [ ] Only COPYABLE_SETTINGS keys are written — never arbitrary keys
- [ ] JSON blob is read-modify-write, never replaced wholesale
- [ ] SQLite write uses transaction with timeout=10
- [ ] Per-account errors collected, never abort the batch
- [ ] Operator sees full diff preview before any write happens
- [ ] Operator must click Apply to execute (never auto-apply)
- [ ] All changes logged to operator_actions with old/new values
- [ ] Source account's settings.db is never written to (read-only)
- [ ] Accounts with identical settings shown as "no changes" (not skipped silently)

---

## Edge Cases to Handle

1. **settings.db missing** on target → report error for that account, skip it
2. **accountsettings table empty** on target → report error, skip (never INSERT)
3. **settings.db locked** (Onimator running) → timeout after 10s, report SQLITE_BUSY
4. **Source and target are same account** → exclude from target list
5. **Key missing in source JSON** → skip that key (don't copy null/missing values)
6. **Key missing in target JSON** → add it to the target's JSON (it's a valid key that Onimator recognizes)
7. **Backup fails** (permissions) → log warning, still proceed with write (matches source_deleter pattern)
8. **Network path** (bot_root on mapped drive) → longer timeout, WorkerThread prevents UI freeze
9. **All values identical** → show "no changes needed" message, disable Apply

---

## Testing Plan

| Test | What to verify |
|------|---------------|
| `test_read_settings_snapshot` | Module reads all COPYABLE_SETTINGS keys from a test settings.db |
| `test_read_missing_settings_db` | Returns error snapshot, never raises |
| `test_write_creates_backup` | settings.db.bak exists after write |
| `test_write_preserves_other_keys` | Keys NOT in updates dict remain unchanged in JSON blob |
| `test_write_only_updates_specified_keys` | Only the requested keys change |
| `test_write_transaction_rollback` | If UPDATE fails, original file is unchanged |
| `test_diff_identifies_changes` | Diff correctly marks changed vs. identical values |
| `test_diff_excludes_source` | Source account never appears in target list |
| `test_batch_partial_failure` | One target fails, others succeed, batch reports both |
| `test_audit_trail` | operator_actions gets one row per target with correct old/new values |

---

## Out of Scope (future enhancements)

- **Settings templates** — save a named configuration and apply it without a source account
- **Settings history** — track what settings each account had over time
- **Settings scheduler** — apply settings at specific times (e.g., night mode limits)
- **Reverse copy** — copy from multiple sources to normalize across fleet
- **Auto-detect optimal settings** — use session/FBR data to recommend limits

---

## Execution Order

1. Step 1 — Model (dataclasses, constants)
2. Step 2 — Module (read/write with safety)
3. Step 4 — Action type constant
4. Step 3 — Service (orchestrator)
5. Step 5 — UI dialog
6. Step 6+7 — Integration into main window

**Estimated effort**: Medium. ~4 new files, ~2 edits. The module write logic is the highest-risk piece and should be carefully tested before wiring up the UI.

**Next agent**: `/coder` to implement the plan.
