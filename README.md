# vault-tier-backup

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
- Rolls dailies into weeklies, weeklies into monthlies, monthlies into yearlies.
- Configurable retention (how many of each tier to keep).
- Optional email notification after each run — SMTP (cross-platform) or
  Outlook COM automation (Windows + Outlook installed).
- Optional OneDrive upload of the monthly snapshot via Microsoft Graph.
- `dry_run` mode: logs exactly what would happen without touching a single file.

## Install

```bash
pip install -e .
# or, without installing the package:
pip install -r requirements.txt
```

If you plan to use Outlook (instead of SMTP) for email notifications, also
install the optional extra: `pip install -e .[outlook]` (Windows only).

## Configure

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
   - `retention.*` — how many daily/weekly/monthly/yearly archives to keep.

## Usage

```bash
vault-tier-backup                       # uses ./config.json
vault-tier-backup -c path/to/config.json
vault-tier-backup --dry-run             # force dry-run regardless of config
```

Schedule it (Windows Task Scheduler, cron, etc.) to run once a day — the
weekly/monthly/yearly rollups happen automatically based on the current date.

## Platform notes
- OneDrive upload requires an Azure AD app registration (`client_id` /
  `tenant_id`, with the client secret set via `BACKUP_ONEDRIVE_CLIENT_SECRET`)
  with Microsoft Graph file-write permissions.
- Outlook email mode requires Windows + a signed-in desktop Outlook client;
  SMTP mode works anywhere.

## License
MIT — see [LICENSE](LICENSE).
