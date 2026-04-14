# OH — Operational Hub
# User Guide v1.3.0

> Version: April 2026 | Applies to: OH.exe (latest build)

---

## Table of Contents

1. [What is OH?](#1-what-is-oh)
2. [Installation & First Launch](#2-installation--first-launch)
3. [Interface Overview](#3-interface-overview)
4. [Accounts Tab](#4-accounts-tab)
5. [Account Detail Panel](#5-account-detail-panel)
6. [Sources Tab](#6-sources-tab)
7. [Source Profiles Tab](#7-source-profiles-tab)
8. [Fleet Tab](#8-fleet-tab)
9. [Cockpit — Daily Operations Overview](#9-cockpit--daily-operations-overview)
10. [Session Report](#10-session-report)
11. [Recommendations](#11-recommendations)
12. [Source Management](#12-source-management)
13. [Target Splitter — Distribute Sources](#13-target-splitter--distribute-sources)
14. [Settings Copier — Copy Settings Between Accounts](#14-settings-copier--copy-settings-between-accounts)
15. [Auto-Fix Proposals](#15-auto-fix-proposals)
16. [Operator Actions](#16-operator-actions)
17. [Settings](#17-settings)
18. [Auto-Update System](#18-auto-update-system)
19. [Keyboard Shortcuts](#19-keyboard-shortcuts)
20. [Data & Security](#20-data--security)
21. [FAQ](#21-faq)

---

## 1. What is OH?

OH (Operational Hub) is a desktop operations dashboard for managing Onimator bot campaigns at scale. It connects to the bot directory and gives operators a unified control center for:

- **Account monitoring** — status, activity, health scores, FBR analytics
- **Source management** — quality tracking, bulk operations, smart discovery
- **Session monitoring** — daily follow/like/DM/unfollow stats per account
- **Operator actions** — review flags, TB/limits tracking, audit trail
- **Recommendations** — automated suggestions prioritized by severity
- **Fleet management** — device-level metrics and account distribution
- **Daily operations** — Cockpit and Session Report for shift start

OH **never modifies** bot runtime files except `sources.txt` (always with backup) and `settings.db` (only via the Settings Copier, always with backup).

### Who is OH for?

OH is built for operators managing Instagram growth campaigns through the Onimator bot. Whether you manage 10 or 1000+ accounts across dozens of devices, OH provides the visibility and tools to work efficiently.

---

## 2. Installation & First Launch

### System Requirements
- Windows 10 or 11 (64-bit)
- No additional software needed — OH is a standalone .exe

### Installation

1. Copy the **OH folder** to your desktop (or any location)
2. Double-click **START.bat** to launch
   - START.bat automatically checks for updates before launching
   - If a new version is available, it downloads and applies it automatically
3. On first launch, OH creates its database at `%APPDATA%\OH\oh.db`

### First Time Setup

1. **Set the Onimator path** — enter the full path to your bot folder in the top bar (e.g., `C:\Users\Admin\Desktop\full_igbot_13.9.0`)
2. Click **Save**
3. Click **Scan & Sync** — OH discovers all devices and accounts
4. Click **Analyze FBR** — computes source quality metrics
5. Open **Cockpit** for your daily operations overview

### Optional Setup (in Settings tab)

- **HikerAPI Key** — required for Find Sources feature
- **Gemini API Key** — optional, enables AI-powered source scoring
- **FBR thresholds** — adjust quality thresholds (defaults: min 100 follows, min 10% FBR)
- **Auto-Scan** — enable automatic periodic Scan & Sync

---

## 3. Interface Overview

![OH Main Interface — Accounts Tab](screenshots/01_accounts_tab.png)

The OH interface consists of:

1. **Brand bar** (top) — Wizzysocial branding, "Check for Updates" button, build version
2. **Onimator Path bar** — set and save the bot folder path
3. **Tab bar** — Accounts, Sources, Source Profiles, Fleet, Settings
4. **Toolbar** — action buttons (Cockpit, Scan & Sync, Analyze FBR, etc.)
5. **Filter bar** — status, FBR state, device, search, tags, activity filters
6. **Data table** — main content area with sortable columns
7. **Status bar** — current status messages

---

## 4. Accounts Tab

The Accounts tab is the main view. It shows all discovered bot accounts in a comprehensive table.

![Accounts Tab with 132 accounts](screenshots/01_accounts_tab.png)

### Table Columns

| Column | Description |
|--------|-------------|
| **Username** | Instagram account name |
| **Device** | Phone/device the account runs on (with online indicator) |
| **Hours** | Working hours slot (e.g., 0-6, 6-12, 12-18, 18-24) |
| **Status** | Active or Removed |
| **Tags** | Bot tags and operator tags (TB, limits, SLAVE, etc.) |
| **Follow/Unfollow** | Whether follow/unfollow is enabled (Yes/No) |
| **DM/Day** | DM limit per day |
| **Follow Today** | Follows performed today |
| **Like Today** | Likes performed today |
| **Follow Limit / Like Limit** | Configured daily limits |
| **Review** | Review flag indicator |
| **Data DB / Sources.txt** | Whether key bot files exist |
| **Discovered / Last Seen** | Discovery date and last sync |
| **Active Sources** | Number of active sources |

### Filters

| Filter | Options | Use case |
|--------|---------|----------|
| **Status** | Active / Removed / All | Show only active accounts (default) |
| **FBR** | All / Needs attention / Never analyzed / Errors / No quality / Has quality | Find accounts needing FBR work |
| **Device** | Dropdown of all devices | Filter by specific phone |
| **Search** | Free text | Quick-find a username |
| **Tags** | All / TB / limits / SLAVE / START / PK / Custom | Filter by tag type |
| **Activity** | All / 0 actions / Has actions | Find inactive accounts |
| **Group** | All groups / specific group | Filter by account group |
| **Review only** | Checkbox | Show only flagged accounts |
| **Show orphans** | Checkbox | Show accounts not in any group |
| **Clear** | Button | Reset all filters |

### Toolbar Buttons

| Button | Function |
|--------|----------|
| **Cockpit** | Open daily operations overview |
| **Scan & Sync** | Scan bot folder and sync all data |
| **Analyze FBR** | Run FBR analysis for all accounts |
| **Refresh** | Refresh table from database (no scan) |
| **Session** | Open Session Report dialog |
| **Recs** | Open Recommendations dialog |
| **History** | Open operator action history |
| **Export CSV** | Export current view to CSV file |
| **Groups** | Manage account groups |
| **Report Problem** | Report a bug or issue |

### Bulk Actions

Select multiple accounts (Ctrl+Click or Shift+Click), then use the bulk action toolbar:
- **Set Review** / **Clear Review** for all selected
- **TB +1** / **Limits +1** for all selected
- **Add to Group** / **Remove from Group**
- **Bulk Find Sources** (for accounts below source threshold)

### Actions Menu

Click the **Actions** button in any row for account-specific options:
- **Open Folder** — open the account's bot folder in Explorer
- **View Sources** — see all sources with FBR data
- **Find Sources** — discover new sources (requires HikerAPI)
- **Copy Settings From This Account** — open the Settings Copier wizard with this account as the source (see [Section 14](#14-settings-copier--copy-settings-between-accounts))
- **Set/Clear Review** — flag the account for review
- **TB +1** / **Limits +1** — increase trust-boost or limits level
- **Trends** — view historical trends for the account

---

## 5. Account Detail Panel

Click any account row to select it, then press **Space** to open the detail panel on the right side of the screen.

### Summary Tab

Shows the complete operational profile of an account:

**Performance cards (4 colored tiles):**

| Card | Shows | When red |
|------|-------|----------|
| **Today's Activity** | Follow/Like/DM today vs limits | 0 actions in active slot |
| **FBR Status** | Quality sources, best FBR% | No quality sources |
| **Source Health** | Active source count | 0 sources or < 5 |
| **Account Health** | TB and Limits levels | TB >= 4 or Limits >= 4 |

**Configuration:** Follow/Unfollow enabled, daily limits, time slot, discovery dates, file status.

**FBR Snapshot:** Quality/Total sources, Best FBR%, highest volume, anomalies, last analysis date.

### Alerts Tab

Automatically generated issues sorted by severity:
- **CRITICAL** (red) — e.g., 0 actions in active slot, TB5
- **HIGH** (orange) — e.g., TB4, no sources
- **MEDIUM** (blue) — e.g., low follow count, limits 4
- **LOW** (gray) — e.g., FBR never analyzed

Each alert includes: title, details, recommended action, and action button.

### Panel Buttons

| Button | Function |
|--------|----------|
| **Set/Clear Review** | Flag or clear review |
| **TB +1** | Increase TB level |
| **Limits +1** | Increase Limits level |
| **Open Folder** | Open account folder |
| **Copy Diagnostic** | Copy full diagnostic report to clipboard |

---

## 6. Sources Tab

The Sources tab provides a global view of all sources across all accounts.

![Sources Tab — 10,273 sources with FBR metrics](screenshots/04_sources_tab.png)

### Features

- **Aggregated metrics** — see how each source performs across all accounts
- **Split view** — select a source to see per-account breakdown below
- **Filters** — search by name, min active accounts, min follows, FBR state
- **Sorting** — click any column header to sort

### Columns

| Column | Description |
|--------|-------------|
| **Source** | Instagram source username |
| **Active Accs** | Number of accounts currently using this source |
| **Hist. Accs** | Historical number of accounts that used this source |
| **Total Accs** | Total accounts (active + historical) |
| **Total Follows** | Sum of all follows from this source |
| **Followbacks** | Sum of all followbacks from this source |
| **Avg FBR %** | Average Follow-Back Rate |
| **Wtd FBR %** | Weighted FBR (accounts with more data have more weight) |
| **Quality** | Number of accounts where this source is "quality" (X/Y format) |
| **Last Updated** | Date of last FBR analysis |

### Source Actions

- **Refresh Sources** — reload source data
- **Delete Source** — remove selected source from all accounts
- **Bulk Delete Weak Sources** — remove sources below FBR threshold
- **Distribute Sources** — open the Target Splitter wizard to distribute sources across accounts (see [Section 13](#13-target-splitter--distribute-sources))
- **History** — view delete/restore history
- **Bulk Find Sources** — discover new sources for accounts below threshold
- **Discovery History** — view past bulk discovery runs

---

## 7. Source Profiles Tab

The Source Profiles tab shows indexed source profiles with niche classification and metadata.

![Source Profiles — 36 indexed profiles across 8 niches](screenshots/05_source_profiles_tab.png)

### What it shows

Each indexed source profile displays:
- **Niche** — classified category (fitness, fashion, photography, business, etc.)
- **Confidence %** — how confident the niche classification is
- **Language** — detected profile language
- **Location** — profile location if available
- **Followers** — total follower count
- **Accounts** — how many of your accounts use this source
- **FBR metrics** — Avg FBR%, Wtd FBR%, Quality count
- **Status** — Active/Inactive

### Filters

- Search by source name
- Filter by niche
- Filter by language
- Minimum FBR% threshold

### How to index sources

Go to **Settings** > **Source Indexing** > **Scan & Index Sources**. This fetches profile data from HikerAPI and classifies each source by niche.

---

## 8. Fleet Tab

The Fleet tab provides a device-level overview of your entire operation.

![Fleet Dashboard — 44 devices, 132 active accounts](screenshots/06_fleet_tab.png)

### Device Metrics

| Column | Description |
|--------|-------------|
| **Device** | Device name (phone model) |
| **Status** | Online/Offline |
| **Accounts** | Total accounts on device |
| **Active** | Active accounts |
| **Active %** | Percentage active |
| **Avg Health** | Average health score of accounts |
| **Avg FBR%** | Average FBR across accounts |
| **Avg Sources** | Average active sources per account |
| **Review** | Number of accounts flagged for review |
| **Last Sync** | Last synchronization timestamp |

### Device Detail

Select a device to see its accounts in the bottom panel with: username, status, health, active sources, best FBR%, and tags.

### Use cases

- Identify underperforming devices (low health, low FBR)
- Find devices with too many accounts
- Spot offline devices that need attention
- Compare device performance

---

## 9. Cockpit — Daily Operations Overview

The Cockpit is your starting point for every shift. It provides a prioritized summary of what needs attention.

**How to open:** Click **Cockpit** on the toolbar.

![Cockpit — 132 accounts, 9 CRITICAL, 57 HIGH](screenshots/08_cockpit.png)

### 5 Sections

| Section | What it shows |
|---------|---------------|
| **Do zrobienia teraz** (To do now) | Top critical/high priority issues — most urgent problems |
| **Konta do review** (Accounts for review) | Flagged accounts waiting for operator review |
| **Top rekomendacje** (Top recommendations) | Next most important recommendations |
| **Ostatnie source actions** (Recent source actions) | Recent source deletions/restorations |
| **Dzisiaj wykonano** (Done today) | Actions completed today by operators |

### Actions from Cockpit

- **Open Target** — jump to the specific account or source
- **Set Review** — flag an account directly from Cockpit
- **Open Report** — open Session Report
- **Open Recommendations** — open full recommendations list
- **Open Delete History** — view source operation history
- **Open Action History** — view all operator actions

### Recommended daily workflow

1. **Click Scan & Sync** to get fresh data
2. **Open Cockpit** to see the overview
3. Work through **"Do zrobienia teraz"** from top to bottom
4. Review flagged accounts in **"Konta do review"**
5. Check **Session Report** for detailed analysis if needed

---

## 10. Session Report

The Session Report provides a detailed analysis of today's bot activity across all accounts.

**How to open:** Click **Session** on the toolbar.

![Session Report — 132 active accounts, 68 with activity](screenshots/09_session_report.png)

### 8 Analysis Tabs

| Tab | Shows | Typical action |
|-----|-------|----------------|
| **Actions (checklist)** | Prioritized action list by severity | Work through from CRITICAL down |
| **0 Actions Today** | Accounts with zero activity | Check device, flag for review |
| **Devices** | Offline/problematic devices | Check physical phone |
| **Review** | Flagged accounts | Review, clear, or escalate |
| **Low Follow** | Low follow count vs limit | Check warmup, sources |
| **Low Like** | Low like count vs limit | Check configuration |
| **TB** | Accounts with trust-boost | TB+1, adjust warmup |
| **Limits** | Accounts with limits | Limits+1, replace sources |

### TB Warmup Guidelines

| Level | Follow/day | Like/day | Action |
|-------|-----------|----------|--------|
| TB1 | 5-10 | 10-20 | Light warmup |
| TB2 | 15-25 | 30-50 | Moderate warmup |
| TB3 | 30-45 | 50-80 | Standard operation |
| TB4 | 50-70 | 80-120 | Full operation, monitor |
| TB5 | — | — | Move account to different device |

### Copy Report

Click **"Copy Report to Clipboard"** to copy the entire report in text format — useful for sharing on Slack or Teams.

---

## 11. Recommendations

The Recommendations system automatically analyzes all accounts and sources, generating prioritized suggestions.

**How to open:** Click **Recs** on the toolbar.

![Recommendations — 358 items, sorted by severity](screenshots/10_recommendations.png)

### 6 Recommendation Types

| Type | Problem | Action |
|------|---------|--------|
| **Weak Source** | Source with low/zero FBR | Delete or replace |
| **Source Exhaustion** | Account has too few sources | Add new sources |
| **Low Like** | Zero likes despite activity | Check like configuration |
| **Limits Max** | Limits level 5 | Replace sources |
| **TB Max** | TB level 5 | Move account to another device |
| **Zero Actions** | No activity in active slot | Check device |

### Severity Levels

- **CRITICAL** (red) — immediate action required
- **HIGH** (orange) — should be addressed today
- **MEDIUM** (blue) — address when time permits
- **LOW** (gray) — informational, low priority

### Filters

- **All** — show everything
- **Critical + High** — urgent items only
- **Accounts only** — account-level recommendations
- **Sources only** — source-level recommendations

### Actions

| Button | Function |
|--------|----------|
| **Open Target** | Navigate to the account/source |
| **Delete Source** | Delete a weak source (with backup) |
| **Clean Sources** | Remove all non-quality sources from an account |
| **Apply Selected** | Flag selected accounts for review |
| **Delete History** | View source operation history |
| **Copy** | Copy recommendations to clipboard |

---

## 12. Source Management

### Viewing Sources

**Per account:** Actions > View Sources — shows all sources with FBR data for that specific account.

**Global view:** Sources tab — aggregated metrics across all accounts.

### Deleting Sources

**Single source:**
1. Sources tab > select source > "Delete Source"

**Bulk delete weak sources:**
1. Sources tab > "Bulk Delete Weak Sources"
2. Set FBR threshold
3. Preview affected sources
4. Confirm deletion

**Per account cleanup:**
1. Actions > View Sources > "Delete Selected" or "Remove Non-Quality"

Every deletion:
- Creates a backup (`sources.txt.bak`)
- Shows preview before deletion
- Records in history (who, when, how many)

### Restoring Sources

Sources tab > **History** > select operation > **Revert Selected**

### Finding New Sources

**Requires:** HikerAPI Key (configured in Settings)

1. Click Actions > **Find Sources** on an account
2. OH automatically:
   - Fetches the client's Instagram profile
   - Searches for similar profiles
   - Filters (min followers, not private)
   - Calculates engagement rate
   - AI scores relevance (optional, requires Gemini Key)
3. Shows top results with: username, followers, ER%, category, AI score
4. Select profiles > **Add Selected to sources.txt**

**Tip:** AI Score >= 7.0 (green) indicates a well-matched profile.

### Bulk Source Discovery

For accounts below the minimum source threshold:
1. Click **Bulk Find Sources** on the Sources tab
2. OH identifies accounts needing sources
3. Automatically discovers and adds top-ranked sources
4. Results shown in Discovery History

---

## 13. Target Splitter — Distribute Sources

The Target Splitter lets you distribute a set of source names across multiple accounts in a single operation. Instead of manually editing each account's sources.txt, you select the sources, pick the target accounts, choose a distribution strategy, preview the plan, and apply.

### How to access

**Sources tab** > click **"Distribute Sources"** on the toolbar.

If you select sources in the Sources tab before clicking, they are pre-filled into the wizard.

### 3-Step Wizard

#### Step 1: Select Sources

Paste or type source names into the text area, one per line. Duplicates and empty lines are automatically removed. The label below the text area shows how many valid sources were detected.

Click **"Next >"** to proceed (disabled until at least one valid source is entered).

#### Step 2: Select Target Accounts

A table shows all active accounts with their username, device, group, and current active source count. Use the filters at the top to narrow down by device, group, or search by username.

- **Select All / Deselect All** — toggle all visible accounts
- The label shows how many accounts are currently selected
- Click **"Next >"** to proceed (disabled until at least one account is selected)

#### Step 3: Preview & Apply

Choose a distribution strategy and review the plan before applying.

**Two strategies:**

| Strategy | How it works |
|----------|-------------|
| **Even split** | Distributes sources round-robin across selected accounts. Each account gets roughly the same number of new sources. |
| **Fill up** | Assigns each source to the account with the fewest active sources. Prioritizes accounts that need sources the most. |

Changing the strategy immediately recomputes the preview.

The preview table shows every source-to-account assignment with a status:
- **"Will add"** (green) — the source will be written to this account's sources.txt
- **"Already present"** (gray) — the source is already in this account, so it will be skipped

A summary line shows: total sources, total accounts, how many will be added, how many are already present, and the average sources per account.

Click **"Apply"** to execute. A confirmation dialog appears before any files are modified. After execution, the dialog shows the result: how many were added, skipped, or failed.

### Safety

- **Preview before execute** — you see the exact plan before anything is written
- **Backup** — sources.txt.bak is created before every modification
- **Duplicates skipped** — sources already present in an account are not re-added
- **Per-item error isolation** — one failing account does not abort the batch
- **Audit trail** — every change is logged in Operator Action History

---

## 14. Settings Copier — Copy Settings Between Accounts

The Settings Copier lets you copy bot configuration (follow limits, like limits, working hours, DM settings) from one account to one or more target accounts. This replaces the need to open each account's Onimator configuration individually.

### How to access

**Accounts tab** > click the **Actions** button on any account row > **"Copy Settings From This Account"**.

This opens the wizard with the selected account pre-filled as the source.

### What settings can be copied

| Setting | Description |
|---------|-------------|
| Follow limit / day | Daily follow limit |
| Like limit / day | Daily like limit |
| Unfollow limit / day | Daily unfollow limit |
| Working hours — start | Start of the working time slot |
| Working hours — end | End of the working time slot |
| Follow enabled | Whether follow is turned on |
| Unfollow enabled | Whether unfollow is turned on |
| Like enabled | Whether like is turned on |
| DM enabled | Whether DM is turned on |
| DM limit / day | Daily DM limit |

### 3-Step Wizard

#### Step 1: Select Source Account + Settings

Choose the source account from the dropdown. OH reads its settings.db and displays all copyable settings with their current values. Each setting has a checkbox — uncheck any setting you do not want to copy.

Click **"Next >>"** to proceed (disabled until a source is selected and at least one setting is checked).

#### Step 2: Select Targets + Preview Diff

All active accounts (except the source) are listed with checkboxes. Each row shows how many settings would change for that account.

- **Select All / Select None** — toggle all targets
- **Select Same Device** — select only accounts on the same device as the source
- Accounts with 0 differences are shown grayed out (identical configuration)

Click any target account to see a side-by-side diff in the preview table below. Changed values are shown in bold. Unchanged values are grayed out.

Click **"Apply to N account(s)"** to proceed. A confirmation dialog appears: "Apply N setting(s) to M account(s)? A backup of each settings.db will be created before writing."

#### Step 3: Results

After execution, the dialog shows a summary: how many accounts were updated successfully and how many failed. A results table lists each target account with its status (OK or FAILED) and the number of keys that were changed.

### Backup safety

Before writing to any account's settings.db, OH creates a full backup of the file (`settings.db.bak`). OH uses a read-modify-write approach: it reads the existing configuration, updates only the selected keys, and writes back the full configuration. Other settings that are not part of the copy operation are never touched.

If the bot is running and the settings.db file is locked, OH reports the error for that specific account and continues with the remaining targets.

### Important notes

- OH writes **only** to the `settings` JSON field in `accountsettings` — no other tables or fields are modified
- This is the only feature in OH that writes to settings.db files
- Every change is logged in Operator Action History with old and new values

---

## 15. Auto-Fix Proposals

OH can automatically detect common issues after every Scan & Sync and present them as proposals for your review. Nothing is executed without your explicit approval.

### How it works

1. After **Scan & Sync** completes, OH runs detection across all accounts
2. If issues are found, the **Auto-Fix Proposals** dialog appears
3. Each proposal is shown in a table with severity, type, target, and description
4. You review the proposals, check the ones you want to apply, and click **"Apply Selected"**
5. If you click **"Skip All"**, no changes are made

### Proposal types

| Type | Severity | What it detects | What it does when approved |
|------|----------|----------------|--------------------------|
| **Remove Weak Source** | HIGH | Sources with very low wFBR (below threshold) across multiple accounts | Removes the source from affected accounts' sources.txt |
| **Escalate TB** | MEDIUM | Accounts with zero actions for 2+ days | Increases the TB level by 1 |
| **Dead Device Alert** | INFO | Devices with zero active accounts today | Info-only — no action, just an alert |
| **Remove Duplicates** | LOW | Duplicate entries in an account's sources.txt | Removes duplicate lines |

### Dialog controls

- **Checkboxes** — each actionable proposal has a checkbox. HIGH severity proposals are checked by default, LOW are unchecked.
- **Select All / Deselect All** — convenience toggles
- **Apply Selected** — executes only the checked proposals (requires confirmation)
- **Skip All** — closes the dialog without executing anything
- Info-only proposals (Dead Device Alert) are shown with an info icon instead of a checkbox

### Configuring detection

In **Settings**, the Auto-Fix section controls which proposal types are detected:
- "Detect weak sources after Scan"
- "Detect TB escalation candidates"
- "Detect offline devices"
- "Detect duplicate sources"

If all toggles are off, no detection runs and no dialog appears. If detection runs but finds no issues, no dialog appears.

### Results

Applied proposals are logged in the `auto_fix_actions` table and shown in the Cockpit under "Auto-Fix Results (operator-approved)".

---

## 16. Operator Actions

### Review (Flagging Accounts)

- **Set Review** — flag an account with optional note (e.g., "follow pending", "try again later")
- **Clear Review** — clear the flag after resolving the issue
- Visible in the Review column and in the detail panel

### TB Tags (Trust-Boost)

Levels TB1-TB5. Each level represents a warmup stage after an action block.
- **TB +1** — increase level (e.g., TB2 > TB3)
- TB5 = account needs to be moved to a different device
- System warns when trying to exceed TB5

### Limits Tags

Levels 1-5. Each level represents source exhaustion.
- **Limits +1** — increase level
- Limits 5 = consider replacing all sources
- System warns when trying to exceed 5

### Groups

Organize accounts into named groups for easier management:
- Click **Groups** to create/manage groups
- Assign accounts to groups via bulk selection
- Filter by group in the filter bar

### Action History

Click **History** on the toolbar to see the complete operator audit trail:
- Who changed what, when
- Old and new values
- PC name of the operator

---

## 17. Settings

![Settings Tab](screenshots/07_settings_tab.png)

### Configuration Groups

| Group | Settings |
|-------|----------|
| **FBR Analysis** | Min follow count for quality (default: 100), Min FBR% for quality (default: 10%) |
| **Source Cleanup** | Weak source delete threshold (default: 5%), Min active sources warning (default: 5) |
| **Source Discovery** | Min sources for bulk discovery (default: 10), Auto-add top N results (default: 5) |
| **Auto-Scan** | Enable/disable automatic Scan & Sync, interval in hours |
| **Appearance** | Dark / Light theme |
| **Source Finder — API Keys** | HikerAPI Key, Gemini API Key |
| **Source Indexing** | Scan & Index all active sources |
| **Source Blacklist** | Manage sources that should never be added |
| **Campaign Templates** | Save/load preset configurations |
| **Error Reporting** | Report endpoint, auto crash reports |

---

## 18. Auto-Update System

OH includes an automatic update system to ensure you always have the latest version.

### How it works

**On launch via START.bat:**
1. START.bat checks for updates before launching OH
2. If a new version is available, it downloads and replaces OH.exe automatically
3. The downloaded file is verified against a **SHA256 checksum** to ensure integrity
4. Then launches the updated version

**Inside the app:**
1. OH checks for updates automatically 3 seconds after startup
2. If an update is found, a dialog shows the new version and changelog
3. Click "Download & Install" to update
4. The download is verified with a **SHA256 hash** before replacing the executable
5. OH closes, applies the update, and restarts

### Manual update check

Click the **"Check for Updates"** button in the top-right corner of the brand bar (visible from any tab).

### Options in update dialog

- **Download & Install** — download and apply the update
- **Skip This Version** — don't show this update again
- **Remind Me Later** — dismiss for now, check again on next launch

---

## 19. Keyboard Shortcuts

| Shortcut | Context | Action |
|----------|---------|--------|
| **Space** | Account table | Open/close detail panel |
| **Escape** | Panel / Dialog | Close panel or dialog |
| **Left / Right** | Detail panel open | Switch Summary / Alerts tabs |
| **Up / Down** | Account table | Navigate between accounts (panel follows) |
| **Ctrl+R** | Any view | Refresh current view |
| **Double-click** | Cockpit / Recs / Session | Navigate to account/source |

---

## 20. Data & Security

### Storage

- **Database:** `%APPDATA%\OH\oh.db` (SQLite, WAL mode)
- **Logs:** `%APPDATA%\OH\logs\oh.log` (rotating, 2 MB x 5 files)
- All data is stored locally on your machine

### Safety guarantees

- OH **never modifies** data.db or bot runtime files
- OH only writes to `sources.txt` (source management) and `settings.db` (Settings Copier)
- Before every sources.txt or settings.db change, a **backup** is created (`.bak`)
- Every deletion can be **reverted** from history
- All operator actions are **logged** with timestamp and PC name
- Operator tags (OP:) are **separate** from bot tags — no conflicts

### Network access

OH only connects to the internet for:
- **Update checks** — checks GitHub for new versions
- **HikerAPI calls** — only when you explicitly trigger Find Sources
- **Gemini API calls** — only for AI scoring (optional)
- **Error reports** — if configured and enabled

No account data is ever sent externally.

---

## 21. FAQ

**Q: Can OH break the bot?**
A: No. OH only modifies `sources.txt` (with backup) and `settings.db` (only via Settings Copier, with backup). It never touches data.db or other runtime files.

**Q: How do I undo a source deletion?**
A: Sources tab > History > select the operation > Revert Selected.

**Q: What does "Needs attention" mean in the FBR filter?**
A: The account was never analyzed OR has zero quality sources.

**Q: What should I do with a TB5 account?**
A: TB5 means maximum trust-boost level. The account should be moved to a different device.

**Q: How do I add new sources?**
A: Actions > Find Sources (requires HikerAPI Key in Settings). Or manually edit sources.txt.

**Q: Where are OH logs?**
A: `%APPDATA%\OH\logs\oh.log` — rotating at 2 MB, max 5 files.

**Q: Can I use OH while the bot is running?**
A: Yes. OH opens bot files in read-only mode. The only modification is to sources.txt (with backup).

**Q: How do I switch to light theme?**
A: Settings > Appearance > Theme > "light" > Save. Restart OH to apply.

**Q: How do I update OH?**
A: OH updates automatically when launched via START.bat. You can also click "Check for Updates" in the top-right corner.

**Q: Can I run OH on multiple PCs?**
A: Yes. Each PC gets its own database. Operator actions are tagged with the PC name for audit purposes.

**Q: How often should I run Scan & Sync?**
A: At least once at the start of each shift. You can also enable Auto-Scan in Settings to run it automatically every X hours.

**Q: How do I copy settings from one account to many others?**
A: Accounts tab > Actions > "Copy Settings From This Account". The wizard lets you select which settings to copy, pick target accounts, preview the diff, and apply.

**Q: How do I distribute sources across multiple accounts at once?**
A: Sources tab > "Distribute Sources". Paste source names, select target accounts, choose a strategy (Even split or Fill up), preview, and apply.

**Q: What happens if I skip the Auto-Fix dialog?**
A: Nothing is changed. Auto-Fix proposals are only suggestions. Clicking "Skip All" closes the dialog without any modifications.

**Q: Does Settings Copier modify the bot's runtime files?**
A: Yes, it writes to settings.db files. A backup (settings.db.bak) is created before every write. This is the only feature besides source management that modifies bot files.

---

*OH — Operational Hub v1.3.0 | Wizzysocial*
