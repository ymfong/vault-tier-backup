# Roadmap

The guiding principle: **a backup only counts if you can prove you'll get your
data back.** Work is ordered so that the things that can silently cause total
data loss come first, and project polish comes last.

## Tier 0 — Data-safety foundations (must-have before trusting it)

These are the failure modes where the backup gives false confidence and then
fails you when it matters. Nothing else should ship before these.

- [x] **Password durability / key-loss safeguard.** *(done)* The first backup
  written to a location records a salted PBKDF2 verification token (never the
  password itself); every run and restore checks the current password against it
  and refuses to proceed on a mismatch, and a loud warning fires when a password
  is first registered. `check-key` verifies on demand. Still worth adding later:
  an explicit recovery-hint/escrow option. See `keyguard.py`.
- [x] **Prove it end-to-end (not dry-run).** *(done)* `tests/test_end_to_end.py`
  runs a real encrypted backup, confirms a wrong password can't extract, and
  asserts the restore is byte-for-byte identical to the source.
- [x] **Restore & list commands.** *(done)* `vault-tier-backup list`
  (`--contents`, `--tier`) and `vault-tier-backup restore <archive> [--to]
  [--member] [--deep]`. See `restore.py`.
- [x] **Offsite by default (3-2-1).** *(done)* `mirrors` config replicates the
  full tier tree (and key token) to extra destinations on other devices/network
  shares after each run — incremental, with offline mirrors skipped gracefully.
  When no mirror is set and backups share a volume with the source, every run
  warns. See `mirror.py`. Future: fold the OneDrive upload into this same mirror
  abstraction so cloud is just another destination.
- [x] **Silent-failure monitoring.** *(done)* Heartbeat/dead-man's-switch
  (`monitoring.heartbeat_url`, pings on success and `/fail`), failure alerting on
  by default (`alert_on_failure`), and a start-of-run staleness warning
  (`max_quiet_hours`). See `monitor.py`. **Tier 0 complete.**

## Tier 1 — Reliability & correctness

- [x] **Backup integrity verification.** *(done)* After writing each archive it's
  re-opened and every member is decrypted + CRC-checked (plus a member-count
  check); a failure raises before any move/prune/mirror, so a corrupt backup is
  never trusted and monitoring alerts. Toggle: `control.verify_backups`. See
  `archive.verify_zip`.
- [x] **Open / locked file handling.** *(done)* Each file is zipped
  independently — a locked file (open in Excel/Access) is retried, then skipped
  with a warning and reported in the logs/email summary, so one open file never
  abandons the whole backup. See `archive.py`. **Still open:** a file held
  *exclusively locked all day* needs Windows Volume Shadow Copy (VSS) for a
  consistent read — deferred as its own item (admin + COM/diskshadow, sizeable).
- [x] **Storage growth (recompression).** *(done)* Already-compressed formats
  (the rolled-up `.zip`s, media, archives) are now stored verbatim (ZIP_STORED)
  instead of re-deflated, so the zips-of-zips rollups no longer waste CPU for no
  gain. Daily runs already skip unchanged files via the mtime `max_age_days`
  filter. See `archive.ALREADY_COMPRESSED_EXTS`. **Still open:** true cross-backup
  dedup/incremental (only store changed *blocks*) — a larger feature, deferred.
- [x] **Pre-flight safety checks.** *(done)* Catch the silent failures a
  non-technical user never sees coming: a backup destination on the *same disk*
  as the source, an empty backup caused by a wrong path / wrong extensions (vs a
  normal quiet day), and a destination low on free space — each surfaced as a
  visible warning rather than a cheerful success. See `safety.py`.
- [x] **Restore fire-drill.** *(done)* `test-restore` actually restores the
  newest backup to a temp folder and confirms it comes out, so "I have backups"
  becomes "I have backups I've restored from". See `safety.test_restore`.
- **Consistent-copy of always-open files (VSS).** Use Volume Shadow Copy to read
  a point-in-time snapshot of files that are locked the whole time. Needs admin
  rights and VSS orchestration; the ceiling for open-file backup on Windows.

## Tier 2 — Usability

- [x] **Standalone Windows exe.** *(done)* `VaultTierBackup.exe` (PyInstaller,
  attached to each GitHub release) — download, double-click, the GUI opens; no
  Python, no pip, no terminal. Config lives in `%APPDATA%\vault-tier-backup`.
  CLI arguments fall through to the normal CLI, so the scheduled task the GUI
  registers runs through the same exe. Build: `packaging/exe_entry.py`.
  **Still open:** the exe is unsigned, so SmartScreen warns on first run —
  code-signing needs a paid certificate.
- [x] **Desktop GUI.** *(done)* `vault-tier-backup gui` — a Tkinter (built-in, no
  extra deps) app with a Settings tab (folders, file types, encryption/verify
  toggles, mirror, retention) and a Backups tab (status, archive list, one-click
  restore, restore fire-drill). Long operations run off the UI thread; safety
  warnings (same-disk) show inline. Form<->config mapping is pure and tested
  (`gui.config_to_form` / `apply_form_to_config`); the view builds headless-clean.
  Backs the Encrypt toggle with the real `control.encrypt` flag.
- [x] **Setup wizard.** *(done)* `vault-tier-backup init` walks the user through
  the essentials, writes a valid `config.json`, generates or collects the backup
  password, offers to set the env var, and prints next steps. Config-building is
  a pure, tested function (`wizard.build_config`). Starts in dry-run so the first
  run is a safe no-op.
- [x] **Built-in scheduling.** *(done)* `install-schedule` / `uninstall-schedule`
  register a daily job — Windows Task Scheduler (from an XML definition), or a
  printed `crontab` line on POSIX. See `schedule.py`. The `init` wizard points
  users straight to it. A missed run (PC off/asleep/logged out at the scheduled
  time) **catches up at the next opportunity** via `StartWhenAvailable` +
  `WakeToRun`, instead of being silently skipped — no stored Windows password
  needed, so the per-user `BACKUP_ZIP_PASSWORD` stays visible.
- **Cross-platform or explicit Windows scoping.** Today it's Windows-flavored
  (drive letters, Task Scheduler, Outlook COM). Either generalize paths/
  scheduling for Linux/macOS, or state the Windows-only scope plainly.

## Tier 3 — Project maturity

- **CI.** GitHub Actions running `pytest` on every push/PR.
- **PyPI release.** So `pip install vault-tier-backup` works without cloning.
- **Contributor docs.** CONTRIBUTING.md, issue/PR templates.

---

*Re-ranked honestly: password-safety and a real restore test come before
restore-as-a-feature; offsite and monitoring come before CI and PyPI. Anything
in Tier 3 is polish — it makes the repo look maintained, not the backups
safer.*
