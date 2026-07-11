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

- **Backup integrity verification.** After writing a zip, re-open and checksum
  it so corruption is caught immediately, not during an emergency restore.
- **Open / locked file handling.** An Excel or Access file open at run time may
  be locked or captured half-written on Windows (`.accdb` especially). Detect
  and handle (skip-with-warning, retry, or shadow-copy).
- **Storage growth.** Daily full zips of large files — then zips-of-zips in the
  rollups (re-compressing already-compressed data) — blow up storage. Consider
  incremental/dedup or at least skipping recompression.

## Tier 2 — Usability

- **Setup wizard.** Interactive prompts that write `config.json` and set the env
  vars, so non-technical users don't hand-edit JSON or run `setx`.
- **Built-in scheduling.** `--install-schedule` to register the Task Scheduler
  (or cron) entry, instead of relying on the user to wire it up correctly.
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
