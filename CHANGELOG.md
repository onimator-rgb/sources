# Changelog

All notable changes to OH are documented here.

## 2026-03-27

### Added
- **Source usage metrics** — Used count and Used % columns in per-account Sources dialog and global Sources detail pane
- Used count reads `sources/{name}.db` (COUNT of processed users per source)
- Used % derived from `.stm/{name}-total-followed-percent.txt` + follow count
- Tooltips show derived total follower count on hover

### Fixed
- **Empty columns in Sources dialog** — `setSortingEnabled(True)` was called before row insertion, causing Qt to re-sort mid-fill and place column values in wrong rows. Moved to after the loop.

## 2026-03-26

### Added
- **FBR analytics** — per-account and batch Follow-Back Rate computation from `data.db`
- Persisted FBR snapshots with timestamps
- Quality thresholds (configurable min follows + min FBR %)
- Anomaly detection for inconsistent followback data
- **Global Sources tab** — aggregated cross-account source view with filters
- Per-source detail pane with per-account FBR breakdown
- Average FBR and volume-weighted FBR metrics
- **Source deletion** — single and bulk delete from `sources.txt` across accounts
- Confirmation dialogs with affected account list
- Full deletion history with viewer
- **Per-account Sources dialog** — merged view of sources.txt + data.db with FBR columns
- **Settings tab** — bot root path, FBR thresholds, delete threshold, theme
- **EXE packaging** — PyInstaller spec for single-file `dist/OH.exe`
- Desktop shortcut creation script
- Dark theme with Wizzysocial branding
- Rotating log file at `%APPDATA%\OH\logs\oh.log`

## 2026-03-25

### Added
- **Initial release** — account discovery, device registry, sync, and base UI
- Scan & Sync workflow reading bot directory structure
- Account table with status, config, and file presence columns
- OH internal SQLite database with migrations
