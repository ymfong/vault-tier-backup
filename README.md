# vault-tier-backup

[![CI](https://github.com/ymfong/vault-tier-backup/actions/workflows/ci.yml/badge.svg)](https://github.com/ymfong/vault-tier-backup/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Automated, **encrypted**, **tiered** backups for important office files (Excel,
Access, or anything else you list) sitting on a local or network drive. If
you've ever had a shared spreadsheet get overwritten or corrupted with no way
to get an earlier version back, this is the problem it solves: it silently
keeps daily, weekly, monthly, and yearly encrypted snapshots, prunes old ones
on a retention schedule you set, and can optionally email you a summary or
push the monthly snapshot to OneDrive.

## Features
- Recursively collects files by extension from a source folder, skipping
  anything matching your configured skip keywords.
- Packs matches into an AES-encrypted ZIP (via [pyzipper](https://pypi.org/project/pyzipper/)).
- Rolls dailies into weeklies, weeklies into monthlies, monthlies into yearlies
  — storing already-compressed data (the rolled-up `.zip`s, media, archives)
  verbatim instead of wastefully re-compressing it.
- Configurable retention (how many of each tier to keep).
- Optional email notification after each run — SMTP (cross-platform) or
  Outlook COM automation (Windows + Outlook installed).
- Optional OneDrive upload of the monthly snapshot via Microsoft Graph.
- Integrity-checked: every archive is re-opened and CRC-verified right after
  writing, so corruption is caught immediately (a failed check aborts the run
  and alerts) rather than discovered during an emergency restore.
- `list` and `restore` commands to browse archives and pull files back out.
- Resilient to open files: a spreadsheet locked by Excel/Access is retried, then
  skipped with a warning if still busy — one open file never aborts the backup
  (see below).
- Password-loss safeguard: refuses to run if your password no longer matches the
  backups it would be written alongside (see below).
- Pre-flight safety checks that turn silent failures into visible warnings:
  flags a backup destination on the *same physical disk* as the source, warns
  when the source has *no matching files at all* (a wrong path or wrong file
  types) instead of cheerfully backing up nothing, and warns before a filling
  drive becomes a mid-write failure.
- `test-restore` fire-drill: actually restores your newest backup to a temp
  folder and confirms it comes out — a backup you've never restored from is a
  guess.
- `dry_run` mode: logs exactly what would happen without touching a single file.

## Install

**From GitHub (no clone needed):**

```bash
pip install "git+https://github.com/ymfong/vault-tier-backup.git"
```

**Or download a built package** from the
[Releases page](https://github.com/ymfong/vault-tier-backup/releases) and install
the wheel:

```bash
pip install vault_tier_backup-0.1.0-py3-none-any.whl
```

**From a clone (for development):**

```bash
git clone https://github.com/ymfong/vault-tier-backup.git
cd vault-tier-backup
pip install -e ".[dev]"     # includes pytest; run the suite with: pytest
```

If you plan to use Outlook (instead of SMTP) for email notifications, also
install the optional extra: `pip install -e ".[outlook]"` (Windows only).

Either way you get the `vault-tier-backup` command on your PATH.

## Quick start (recommended)

Run the interactive setup wizard — it asks a handful of questions, writes your
`config.json`, generates a strong backup password, and tells you exactly what to
do next:

```bash
vault-tier-backup init
```

It starts you in dry-run mode so your first `vault-tier-backup backup` is a safe
no-op you can inspect. Prefer to configure by hand? See below.

## Configure manually

1. Copy the example config and fill in your own paths:
   ```bash
   cp config.example.json config.json
   ```
   `config.json` is gitignored — it's meant to hold your real paths and is
   never committed.

2. Set the secrets `vault-tier-backup` needs as **environment variables**
   (never put these in `config.json`):

   | Variable | Required when |
   |---|---|
   | `BACKUP_ZIP_PASSWORD` | always (unless `dry_run: true`) |
   | `BACKUP_EMAIL_PASSWORD` | `email_enabled: true` and `email.method: "smtp"` |
   | `BACKUP_ONEDRIVE_CLIENT_SECRET` | `upload_to_cloud: true` |

   On Windows, set them so scheduled tasks can see them too:
   ```powershell
   setx BACKUP_ZIP_PASSWORD "your-password-here"
   ```

3. Key config fields (see `config.example.json` for the full shape):
   - `paths.backup_source` — folder to back up.
   - `paths.backup_root_exe` / `paths.backup_root_source` — where ZIPs land
     (local, and optionally a second "dual" copy elsewhere).
   - `backup.extensions` — which file types to include.
   - `backup.weekly_day` — 0=Monday … 6=Sunday.
   - `backup.weekly_full_backup` — if true, the weekly run captures every
     matching file rather than just recently-modified ones.
   - `control.dry_run` — leave `true` until you've verified the config; no
     files are written, moved, or deleted in dry-run mode, and no secrets are
     required.
   - `email.method` — `"smtp"` or `"outlook"`.
   - `control.verify_backups` — re-open and CRC-check each archive after writing
     (default true); a failed check aborts the run so a corrupt backup is never
     trusted or mirrored.
   - `retention.*` — how many daily/weekly/monthly/yearly archives to keep.
   - `mirrors` — extra destinations (another drive, external disk, network
     share) that every archive is replicated to after each run. **Set at least
     one on a different physical device** — see 3-2-1 below. Leave `[]` for none.
   - `monitoring.heartbeat_url` — a URL pinged after every successful run (see
     "Knowing it's still running" below). Empty to disable.
   - `monitoring.alert_on_failure` — email you when a run crashes (default true).
   - `monitoring.max_quiet_hours` — warn at the start of a run if this many hours
     have passed since the last success (e.g. 26 for a daily job).

## Usage

```bash
vault-tier-backup init                         # interactive first-time setup

vault-tier-backup                              # run a backup (uses ./config.json)
vault-tier-backup -c path/to/config.json       # use a specific config
vault-tier-backup backup --dry-run             # force dry-run regardless of config

vault-tier-backup list                         # show existing backups
vault-tier-backup list --contents              # ...and the files inside each
vault-tier-backup check-key                    # confirm your password still matches
vault-tier-backup test-restore                 # fire-drill: prove the newest backup restores

vault-tier-backup restore <archive.zip> --to ./restored
vault-tier-backup restore <archive.zip> --member report.xlsx --to ./restored
vault-tier-backup restore <weekly.zip> --deep --to ./restored   # unpack nested rollups

vault-tier-backup install-schedule             # register a daily run at 20:00
vault-tier-backup install-schedule --time 06:30
vault-tier-backup uninstall-schedule           # remove it
```

### Scheduling

The backup should run once a day; the weekly/monthly/yearly rollups happen
automatically based on the current date. Let the tool set that up for you:

```bash
vault-tier-backup install-schedule --time 20:00
```

- **Windows:** registers a daily Task Scheduler job (`schtasks`) that runs a
  launcher written next to your config. It runs as the current user, so the
  `BACKUP_ZIP_PASSWORD` you set with `setx` is visible to it. Verify with
  `schtasks /Query /TN vault-tier-backup`.
- **Linux/macOS:** writes an executable launcher and prints a ready `crontab -e`
  line to paste.

`list`, `restore`, and `check-key` are manual, on-demand commands.

## ⚠️ Your password is the only key

Backups are AES-encrypted with `BACKUP_ZIP_PASSWORD`. **If you lose that
password, every backup is permanently unrecoverable — there is no reset.**
Store it in a password manager the moment you set it.

To protect you from a subtler failure, the first backup written to a location
records a one-way verification token (a salted hash — never the password
itself). Every later run and every restore checks your current password against
it and **refuses to run on a mismatch**, so a typo'd or rotated password can't
silently produce backups you'll never be able to restore. Run
`vault-tier-backup check-key` any time to confirm your password still matches.

## 3-2-1: keep a copy offsite

A backup that lives on the same drive as the original isn't protection — one
disk failure, ransomware hit, or corruption takes both. Aim for the **3-2-1
rule**: 3 copies, on 2 kinds of media, with 1 offsite.

Set `mirrors` to one or more destinations on a *different physical device* (an
external disk, a second internal drive, a NAS/network share). After each run the
full tier tree — plus the key-verification token, so restores work straight from
the mirror — is replicated there. Syncing is incremental (only new/changed
archives) and a mirror that's offline is skipped with a warning rather than
failing the run. If no mirror is set and your backups share a volume with the
source, every run prints a warning so the gap stays visible.

## Knowing it's still running

A backup job that silently stops — machine off at run time, a disabled task, a
broken environment — is the most dangerous failure: you don't find out until you
need a restore that isn't there. Success emails can't catch this, because a run
that never happens sends nothing.

- **Heartbeat (dead-man's-switch).** Point `monitoring.heartbeat_url` at a check
  from a free service like [healthchecks.io](https://healthchecks.io) or a
  self-hosted Uptime Kuma. Each successful run pings it; a failed run pings
  `<url>/fail`. The service alerts **you** when an expected ping doesn't arrive —
  the only reliable way to detect a run that never fired, since the watchdog
  lives off the machine.
- **Failure alerts.** With `alert_on_failure` (default on), any crash emails you
  before the process exits non-zero.
- **Staleness warning.** Each run checks how long since the last success and
  warns if it exceeds `max_quiet_hours`.

## Files that are open during a backup

Excel and Access often hold a file open when a scheduled backup fires. This tool
handles that gracefully:

- Each file is added to the archive independently, so a locked one **never
  abandons the whole backup** — the rest still complete.
- A locked file is **retried** a couple of times (locks during a save are
  usually brief) before being given up on.
- Anything still locked is **skipped and reported** — counted in the logs and
  the email summary — so a file that couldn't be captured is visible, not
  silently missing.

**Limitation:** a file held open and *exclusively locked the entire time* (some
Access databases) still can't be read this way. Guaranteeing a consistent copy
of an always-open file needs Windows Volume Shadow Copy (VSS), which isn't
implemented yet — it's on the roadmap. For now, schedule backups for a time when
files are typically closed (overnight), and watch the skipped-file count.

## Platform notes
- OneDrive upload requires an Azure AD app registration (`client_id` /
  `tenant_id`, with the client secret set via `BACKUP_ONEDRIVE_CLIENT_SECRET`)
  with Microsoft Graph file-write permissions.
- Outlook email mode requires Windows + a signed-in desktop Outlook client;
  SMTP mode works anywhere.

## License
MIT — see [LICENSE](LICENSE).
