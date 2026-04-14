# Warmup Templates — Implementation Plan

**Feature**: 1-click warmup presets for accounts
**Status**: PLANNED
**Priority**: HIGH (client-requested)
**Estimated tasks**: 8

---

## Summary

Operators frequently set initial follow/like limits and auto-increment values when onboarding new accounts. Currently this requires manually editing settings.db per account. This feature adds predefined warmup templates that can be deployed to one or many accounts in a single click, writing the correct initial limits and auto-increment config directly to the bot's settings.db.

The bot already handles daily auto-increment — OH just needs to SET the initial values and enable the auto-increment toggles.

---

## Architecture Decision: Separate table (not extending campaign_templates)

The existing `campaign_templates` table (migration 012) stores campaign-level config: niche, language, min_sources, tb_level, limits_level. It has `follow_limit` and `like_limit` but these are OH-level target values, NOT bot settings.db keys.

Warmup templates need completely different fields:
- `follow_start`, `follow_increment`, `follow_cap`
- `like_start`, `like_increment`, `like_cap`
- `auto_increment_enabled`
- `enable_follow`, `enable_like`

These map 1:1 to specific settings.db JSON keys. Extending campaign_templates would create a confusing hybrid. **Decision: Create a new `warmup_templates` table** in migration 015.

---

## Bot settings.db keys written by warmup deploy

| Template field | settings.db key | Type | Notes |
|---|---|---|---|
| follow_start | `default_action_limit_perday` | int | Starting follow limit |
| like_start | `like_limit_perday` | int | Starting like limit |
| follow_increment | `auto_increment_action_limit_by` | str | Daily increase amount |
| like_increment | `auto_increment_like_limit_perday_increase` | str | Daily increase amount |
| like_cap | `auto_increment_like_limit_perday_increase_limit` | str | Max like limit |
| auto_increment_enabled | `enable_auto_increment_follow_limit_perday` | bool | Toggle follow auto-increment |
| auto_increment_enabled | `enable_auto_increment_like_limit_perday` | bool | Toggle like auto-increment |
| enable_follow | `enable_follow_joborders` | bool | Enable follow action |
| enable_like | `enable_likepost` | bool | Enable like action |

**Note**: There is no `auto_increment_follow_cap` key visible in settings.db — the bot may not have one. The follow cap is controlled by the bot's internal limits. We store it in the template for operator reference but do NOT write it to settings.db unless the key is confirmed to exist. This needs verification during implementation.

---

## COPYABLE_SETTINGS allowlist expansion

The `COPYABLE_SETTINGS` dict in `oh/models/settings_copy.py` currently does NOT include the auto-increment keys. We must add them:

```python
# New keys to add to COPYABLE_SETTINGS:
"enable_auto_increment_follow_limit_perday": "Auto-increment follow enabled",
"enable_auto_increment_like_limit_perday": "Auto-increment like enabled",
"auto_increment_action_limit_by": "Follow daily increase",
"auto_increment_like_limit_perday_increase": "Like daily increase",
"auto_increment_like_limit_perday_increase_limit": "Like auto-increment cap",
"enable_follow_joborders": "Follow action enabled",
"enable_likepost": "Like action enabled",
```

This also benefits the Settings Copier feature (it can now copy these keys too).

---

## Default templates (pre-seeded)

| Name | Follow start | Follow incr | Follow cap* | Like start | Like incr | Like cap | Auto-incr |
|---|---|---|---|---|---|---|---|
| Conservative | 5 | 5 | 40 | 10 | 5 | 60 | ON |
| Moderate | 15 | 10 | 70 | 30 | 10 | 100 | ON |
| Aggressive | 40 | 15 | 150 | 60 | 20 | 200 | ON |

*Follow cap is stored in the template for display but may not be writable to settings.db (see note above).

---

## Tasks

### Task 1: Migration 015 — warmup_templates table
**File**: `oh/db/migrations.py`

```sql
CREATE TABLE IF NOT EXISTS warmup_templates (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT    NOT NULL UNIQUE,
    description         TEXT,
    follow_start        INTEGER NOT NULL DEFAULT 10,
    follow_increment    INTEGER NOT NULL DEFAULT 5,
    follow_cap          INTEGER NOT NULL DEFAULT 50,
    like_start          INTEGER NOT NULL DEFAULT 20,
    like_increment      INTEGER NOT NULL DEFAULT 5,
    like_cap            INTEGER NOT NULL DEFAULT 80,
    auto_increment      INTEGER NOT NULL DEFAULT 1,
    enable_follow       INTEGER NOT NULL DEFAULT 1,
    enable_like         INTEGER NOT NULL DEFAULT 1,
    is_default          INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_warmup_templates_name
    ON warmup_templates(name);
```

Add `(15, "warmup_templates", _MIGRATION_015_SQL)` to the `_MIGRATIONS` list.

The `is_default` column marks the 3 pre-seeded templates so they can be distinguished from custom ones (operators can still edit them).

**Pre-seed**: After the CREATE TABLE, insert the 3 default templates:
```sql
INSERT INTO warmup_templates (name, description, follow_start, follow_increment, follow_cap,
    like_start, like_increment, like_cap, auto_increment, enable_follow, enable_like,
    is_default, created_at, updated_at)
VALUES
    ('Conservative', 'New or personal accounts — gentle ramp-up', 5, 5, 40, 10, 5, 60, 1, 1, 1, 1, '{now}', '{now}'),
    ('Moderate', 'Established accounts — balanced growth', 15, 10, 70, 30, 10, 100, 1, 1, 1, 1, '{now}', '{now}'),
    ('Aggressive', 'Mature accounts with high followers — fast scaling', 40, 15, 150, 60, 20, 200, 1, 1, 1, 1, '{now}', '{now}');
```

Note: The `{now}` placeholders must be replaced with UTC ISO timestamps. Since migrations use raw SQL via `_run_sql_statements`, we need to use SQLite's `datetime('now')` function instead:
```sql
INSERT INTO warmup_templates (..., created_at, updated_at)
VALUES (..., datetime('now'), datetime('now')), ...;
```

---

### Task 2: Model — WarmupTemplate dataclass
**File**: `oh/models/warmup_template.py` (NEW)

```python
@dataclass
class WarmupTemplate:
    name:             str
    follow_start:     int = 10
    follow_increment: int = 5
    follow_cap:       int = 50
    like_start:       int = 20
    like_increment:   int = 5
    like_cap:         int = 80
    auto_increment:   bool = True
    enable_follow:    bool = True
    enable_like:      bool = True
    is_default:       bool = False
    description:      Optional[str] = None
    created_at:       Optional[str] = None
    updated_at:       Optional[str] = None
    id:               Optional[int] = None
```

Add a helper method to convert a template to a settings.db update dict:

```python
def to_bot_settings(self) -> dict:
    """Convert template fields to settings.db key-value pairs."""
    settings = {
        "default_action_limit_perday": self.follow_start,
        "like_limit_perday": self.like_start,
        "enable_auto_increment_follow_limit_perday": self.auto_increment,
        "enable_auto_increment_like_limit_perday": self.auto_increment,
        "auto_increment_action_limit_by": str(self.follow_increment),
        "auto_increment_like_limit_perday_increase": str(self.like_increment),
        "auto_increment_like_limit_perday_increase_limit": str(self.like_cap),
        "enable_follow_joborders": self.enable_follow,
        "enable_likepost": self.enable_like,
    }
    return settings
```

Also add a `to_preview_lines()` method that returns human-readable summary lines for the confirmation dialog:

```python
def to_preview_lines(self) -> List[str]:
    lines = [
        f"Follow: start {self.follow_start}/day, +{self.follow_increment}/day, cap {self.follow_cap}",
        f"Like: start {self.like_start}/day, +{self.like_increment}/day, cap {self.like_cap}",
        f"Auto-increment: {'ON' if self.auto_increment else 'OFF'}",
    ]
    return lines
```

---

### Task 3: Repository — WarmupTemplateRepository
**File**: `oh/repositories/warmup_template_repo.py` (NEW)

Follow the exact pattern of `CampaignTemplateRepository`:
- `__init__(self, conn: sqlite3.Connection)`
- `create(template) -> WarmupTemplate`
- `update(template) -> None`
- `delete(template_id) -> None`
- `get_all() -> List[WarmupTemplate]`
- `get_by_id(template_id) -> Optional[WarmupTemplate]`
- `get_by_name(name) -> Optional[WarmupTemplate]`
- `_from_row(row) -> WarmupTemplate` (static)

Standard CRUD — nothing unusual.

---

### Task 4: Expand COPYABLE_SETTINGS allowlist
**File**: `oh/models/settings_copy.py`

Add the 7 new keys to `COPYABLE_SETTINGS`:

```python
COPYABLE_SETTINGS = {
    # ... existing keys ...
    "enable_auto_increment_follow_limit_perday": "Auto-increment follow enabled",
    "enable_auto_increment_like_limit_perday": "Auto-increment like enabled",
    "auto_increment_action_limit_by": "Follow daily increase",
    "auto_increment_like_limit_perday_increase": "Like daily increase",
    "auto_increment_like_limit_perday_increase_limit": "Like auto-increment cap",
    "enable_follow_joborders": "Follow action enabled",
    "enable_likepost": "Like action enabled",
}
```

This is required because `SettingsCopierModule.write_settings()` validates all keys against this allowlist before writing.

---

### Task 5: Service — WarmupTemplateService
**File**: `oh/services/warmup_template_service.py` (NEW)

Orchestrates template CRUD + deploy operations. Combines:
- `WarmupTemplateRepository` (template CRUD in oh.db)
- `SettingsCopierModule` (read/write settings.db)
- `AccountRepository` (resolve account paths)
- `OperatorActionRepository` (audit trail)
- `SettingsRepository` (get bot_root)

**Methods**:

```python
class WarmupTemplateService:
    def __init__(self, warmup_repo, account_repo, action_repo, settings_repo):
        ...

    def get_all_templates(self) -> List[WarmupTemplate]:
        """Return all warmup templates, ordered by name."""

    def save_template(self, template: WarmupTemplate) -> WarmupTemplate:
        """Create or update a template. Returns the saved template."""

    def delete_template(self, template_id: int) -> None:
        """Delete a template. Raises if it's a default template? Or allows it."""

    def preview_deploy(
        self,
        template: WarmupTemplate,
        account_ids: List[int],
    ) -> List[WarmupDeployPreview]:
        """
        For each target account, read current settings and build a preview
        showing what will change. Uses SettingsCopierModule.read_settings().
        Returns list of WarmupDeployPreview (one per account).
        """

    def apply_deploy(
        self,
        template: WarmupTemplate,
        account_ids: List[int],
    ) -> WarmupDeployBatchResult:
        """
        Deploy the template to all target accounts.
        For each account:
          1. Read current settings (for audit old_value)
          2. Build updates dict from template.to_bot_settings()
          3. Call SettingsCopierModule.write_settings() (backup + write)
          4. Log to operator_actions audit trail
        Returns aggregate result.
        """
```

**New models** (add to `oh/models/warmup_template.py`):

```python
@dataclass
class WarmupDeployPreview:
    """Preview of what warmup deploy will change for one account."""
    account_id: int
    username: str
    device_name: Optional[str]
    current_values: dict    # current settings.db values for the warmup keys
    new_values: dict        # what the template will set
    changes: List[str]      # human-readable list of changes
    error: Optional[str] = None

@dataclass
class WarmupDeployResult:
    """Result of deploying warmup template to one account."""
    account_id: int
    username: str
    device_name: Optional[str]
    success: bool
    backed_up: bool
    keys_written: List[str]
    error: Optional[str] = None

@dataclass
class WarmupDeployBatchResult:
    """Aggregate result for the entire warmup deploy operation."""
    template_name: str
    total_targets: int
    success_count: int
    fail_count: int
    results: List[WarmupDeployResult]
```

**Audit trail**: Add new action type constant:
- File: `oh/models/operator_action.py`
- Add: `ACTION_APPLY_WARMUP = "apply_warmup"`

---

### Task 6: UI — WarmupTemplatesDialog (template editor)
**File**: `oh/ui/warmup_templates_dialog.py` (NEW)

Follow the pattern of `CampaignTemplatesDialog` — split-panel: template list on left, editor form on right.

**Left panel**: Table with columns: Name, Follow (start/incr/cap), Like (start/incr/cap), Auto-incr
**Right panel**: Editor form with:
- Name (QLineEdit)
- Description (QTextEdit, max 50px height)
- Follow Start (QSpinBox, range 1-500)
- Follow Increment (QSpinBox, range 1-50)
- Follow Cap (QSpinBox, range 10-1000)
- Like Start (QSpinBox, range 1-500)
- Like Increment (QSpinBox, range 1-50)
- Like Cap (QSpinBox, range 10-1000)
- Auto-increment (QCheckBox, default checked)
- Enable Follow (QCheckBox, default checked)
- Enable Like (QCheckBox, default checked)

**Buttons**: New, Delete, Save Template, Close

**Constructor**: Takes `WarmupTemplateRepository` (or `WarmupTemplateService`).

**Access point**: Add a "Manage Warmup Templates" button in the Settings tab, below the existing groups.

---

### Task 7: UI — WarmupDeployDialog (deploy wizard)
**File**: `oh/ui/warmup_deploy_dialog.py` (NEW)

2-step wizard (simpler than Settings Copier's 3-step — no "select source" needed):

**Step 1: Select template + target accounts**
- Template dropdown (QComboBox) listing all warmup templates
- Below the dropdown: read-only preview of the selected template's settings (from `to_preview_lines()`)
- Account table with checkboxes (same pattern as SettingsCopierDialog step 2)
- Quick-select buttons: Select All, Select None, Select Same Device, Select Group (if groups exist)
- For each account row, show current follow/like limits (read from the preview)

**Step 2: Results**
- Summary: "Applied {template_name} to X/Y accounts"
- Table: Account, Device, Status, Keys Changed

**Confirmation**: Before applying, show a QMessageBox:
```
Apply warmup template "Conservative" to 5 account(s)?

Settings to apply:
  Follow: start 5/day, +5/day, cap 40
  Like: start 10/day, +5/day, cap 60
  Auto-increment: ON

A backup of each settings.db will be created before writing.
```

**Constructor**:
```python
def __init__(
    self,
    service: WarmupTemplateService,
    accounts: List[AccountRecord],
    pre_selected_account_ids: Optional[List[int]] = None,
    pre_selected_template_name: Optional[str] = None,
    parent: Optional[QWidget] = None,
)
```

**Background execution**: Use `WorkerThread` for the `apply_deploy` call, same as SettingsCopierDialog.

---

### Task 8: Integration — Wire into existing UI
**Files modified**:
- `oh/ui/settings_tab.py` — Add "Warmup Templates" group with "Manage Templates" button
- `oh/ui/main_window.py` — Add "Apply Warmup Template" to Accounts tab Actions menu + toolbar
- `oh/ui/cockpit_dialog.py` — Optionally add warmup deploy shortcut (stretch goal)

#### Settings tab integration
Add a new QGroupBox "Warmup Templates" in `_build_ui()`:
```
[Warmup Templates]
  Manage warmup presets used for account onboarding.
  [Manage Templates]  ← opens WarmupTemplatesDialog
```

This requires passing the `WarmupTemplateRepository` (or service) to `SettingsTab.__init__`.

#### Accounts tab integration (main_window.py)
Add to the Actions menu / right-click context menu:
- "Apply Warmup Template..." menu item
- When clicked with 1+ accounts selected: open `WarmupDeployDialog` with those accounts pre-selected
- When clicked with no selection: open `WarmupDeployDialog` with all accounts

Keyboard shortcut: `Ctrl+W` (if available).

#### Service wiring (main_window.py)
In `MainWindow.__init__` or wherever services are created:
1. Create `WarmupTemplateRepository(conn)`
2. Create `WarmupTemplateService(warmup_repo, account_repo, action_repo, settings_repo)`
3. Pass to UI components

---

## Safety checklist

- [x] All settings.db writes go through `SettingsCopierModule.write_settings()` which backs up first
- [x] All keys validated against `COPYABLE_SETTINGS` allowlist before write
- [x] Operator sees preview before any write (confirmation dialog with exact values)
- [x] Audit logged to `operator_actions` with old_value and new_value JSON
- [x] Per-account errors do not abort the batch
- [x] Background thread for deploy (UI stays responsive)
- [x] No auto-actions — operator must click and confirm

---

## Files created (NEW)
1. `oh/models/warmup_template.py`
2. `oh/repositories/warmup_template_repo.py`
3. `oh/services/warmup_template_service.py`
4. `oh/ui/warmup_templates_dialog.py`
5. `oh/ui/warmup_deploy_dialog.py`

## Files modified
1. `oh/db/migrations.py` — migration 015
2. `oh/models/settings_copy.py` — expand COPYABLE_SETTINGS
3. `oh/models/operator_action.py` — add ACTION_APPLY_WARMUP
4. `oh/ui/settings_tab.py` — add Warmup Templates group
5. `oh/ui/main_window.py` — wire service, add menu items

---

## Execution order

```
Task 1 (migration)  ──┐
Task 2 (model)      ──┼── can be done in parallel
Task 3 (repository) ──┘
         │
Task 4 (COPYABLE_SETTINGS) ── depends on knowing the keys (Task 2)
         │
Task 5 (service) ── depends on Tasks 1-4
         │
Task 6 (template editor UI) ──┐── depend on Task 5
Task 7 (deploy wizard UI)   ──┘
         │
Task 8 (integration / wiring) ── depends on Tasks 6-7
```

**Recommended batch order for /coder**:
1. Tasks 1 + 2 + 3 + 4 together (model layer + migration + allowlist)
2. Task 5 (service)
3. Tasks 6 + 7 (UI dialogs)
4. Task 8 (wiring)

---

## Next agent: `/coder`
