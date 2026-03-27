# OH — Feature Overview

This document explains what OH does in plain language. It is intended for operators and team members who use the tool day-to-day.

---

## What is OH?

OH (Operational Hub) is a desktop application that connects to the Onimator bot folder and gives you a single dashboard to see what is happening across all devices and accounts.

It does **not** run the bot. It reads the bot's files and shows you the data in an organized way.

---

## Accounts Tab

### Scan & Sync

Click **Scan & Sync** to make OH look at the bot folder and discover all devices and accounts.

After scanning, the Accounts table shows every account with:

- **Username** and **Device** — which phone the account runs on
- **Status** — active or removed
- **Follow / Unfollow / Limit per Day** — current bot configuration for the account
- **Data DB / Sources.txt** — whether the account has a data file and source list
- **Active Sources** — how many sources are currently assigned
- **Quality/Total** — how many sources meet the FBR quality threshold
- **Best FBR %** — the highest-performing source's FBR
- **Last FBR** — date of the most recent FBR analysis

### Analyze FBR

Click **Analyze FBR** to compute Follow-Back Rate for all accounts. This reads every account's `data.db` and calculates which sources are performing well and which are not.

### Per-account Sources button

Click **Sources** on any account row to open a detailed view showing all sources for that account with:

| Column | What it means |
|---|---|
| Source | The Instagram source account name |
| Status | Active + history, Active (new), or Historical only |
| sources.txt | Whether this source is in the active source list |
| data.db | Whether this source has historical follow data |
| Follows | Total users followed from this source |
| Follow-backs | How many of those followed back |
| FBR % | Follow-Back Rate (followbacks / follows) |
| Quality | Whether this source meets the quality thresholds |
| Used | Number of users already processed/checked by the bot from this source |
| Used % | What percentage of the source's total audience has been processed |

---

## Sources Tab

The Sources tab shows **all sources across all accounts** in one table.

### Global Sources table

Each row represents one source name. The columns show aggregated data:

- **Active / Historical / Total accounts** — how many accounts use this source
- **Total Follows / Followbacks** — summed across all accounts
- **Avg FBR %** — simple average across accounts
- **Wtd FBR %** — weighted by follow volume (high-volume accounts count more)
- **Quality** — how many accounts consider this source "quality"
- **Last Updated** — when this source was last analyzed

### Filters

You can filter the table by:
- Source name search
- Minimum active accounts
- Minimum follows
- FBR status (All / Performing / Needs attention / No FBR data / Active only)

### Detail pane

Click any source row to see the **per-account breakdown** at the bottom:

- Username, Device, Active/Historical status
- Follows, Followbacks, FBR % for that specific account
- **Used** — how many users that account has processed from this source
- **Used %** — percentage of total source audience processed by that account

### Source deletion

- **Delete Source** — removes the selected source from `sources.txt` for all active accounts
- **Bulk Delete Weak Sources** — removes all sources below the configured FBR threshold
- **History** — view all past deletions with timestamps and affected accounts

**Warning:** Deletion modifies bot files. Always check the confirmation dialog carefully.

---

## Settings Tab

| Setting | What it controls |
|---|---|
| Onimator path | The folder where the bot is installed. Must be set before anything else works. |
| Min follows for quality | How many follows a source needs before it can be called "quality" |
| Min FBR % for quality | The minimum follow-back rate for a source to be "quality" |
| Delete threshold | The FBR % at or below which sources are eligible for bulk deletion |
| Theme | Dark theme (default) |

---

## Logs

OH writes detailed logs to: `%APPDATA%\OH\logs\oh.log`

To open this folder: press `Win + R`, type `%APPDATA%\OH\logs`, press Enter.

Logs are useful when:
- Something looks wrong in the data
- A scan or FBR analysis fails
- You need to verify what happened during a source deletion
- You want to confirm Used % calculations

---

## Typical daily workflow

1. **Launch OH** (from Desktop shortcut or `python main.py`)
2. **Scan & Sync** to refresh account data
3. **Review the Accounts tab** — check for removed accounts, unusual limits
4. **Analyze FBR** to update follow-back analytics
5. **Check the Sources tab** — identify low-performing sources
6. **Delete weak sources** if the data supports it
7. **Review specific accounts** by clicking Sources on individual rows

---

## Key terms

| Term | Meaning |
|---|---|
| FBR | Follow-Back Rate — what percentage of followed users followed back |
| Quality source | A source that meets both the min follows and min FBR thresholds |
| Used count | Number of users from a source that the bot has already processed |
| Used % | Used count as a percentage of the source's total audience |
| Active source | Listed in `sources.txt` — the bot is currently using it |
| Historical source | Appears in `data.db` — the bot used it in the past |
| Weighted FBR | FBR weighted by follow volume — accounts with more follows influence the number more |
