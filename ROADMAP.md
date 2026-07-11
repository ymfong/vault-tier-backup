# Roadmap

The guiding principle: **a backup only counts if you can prove you'll get your
data back.** Work is ordered so that the things that can silently cause total
data loss come first, and project polish comes last.

## Tier 0 — Data-safety foundations (must-have before trusting it)

These are the failure modes where the backup gives false confidence and then
fails you when it matters. Nothing else should ship before these.

- **Password durability / key-loss safeguard.** The AES zip password lives only
  in `BACKUP_ZIP_PASSWORD`. If it's lost, forgotten, or the machine is
  reimaged, *every* backup ever made is permanently unrecoverable (AES-256 zips
  are not crackable). Add: refuse to run until the password is confirmed stored
  somewhere durable, a recovery-hint/escrow mechanism, and loud documentation.
- **Prove it end-to-end (not dry-run).** Everything so far is verified only in
  `dry_run: true`. Produce a real encrypted archive and confirm it decrypts and
  restores byte-for-byte. Until this is done we don't actually know the tool
  creates recoverable backups.
- **Restore & list commands.** `vault-tier-backup list` (see what's captured,
  when) and `vault-tier-backup restore <file> [--to <dir>]`. A backup tool with
  no easy restore path hasn't solved the pain point yet.
- **Offsite by default (3-2-1).** Source (`Z:\`) and backup root
  (`Z:\BACKUP_...`) are on the same volume today — if that drive dies (disk
  failure, ransomware, corruption), both die together. Make an offsite copy
  (OneDrive or another volume) a first-class, on-by-default target, not an
  optional monthly-only rollup.
- **Silent-failure monitoring.** Email is optional and off. If the scheduled
  job stops running, nobody learns until a restore emergency. Add a heartbeat /
  dead-man's-switch and turn failure alerting on by default — "no news is bad
  news."

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
