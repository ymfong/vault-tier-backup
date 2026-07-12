"""PyInstaller entry script for the standalone Windows build.

Build (from the repo root, inside the venv):

    pip install pyinstaller
    pyinstaller --onefile --noconsole --name VaultTierBackup --collect-all pywebview packaging/exe_entry.py

Output lands in dist/VaultTierBackup.exe. Double-click opens the GUI (config in
%APPDATA%\\vault-tier-backup); CLI arguments fall through to the normal CLI so
the scheduled task the GUI registers keeps working.
"""

import sys

from vault_tier_backup.app import main

if __name__ == "__main__":
    sys.exit(main() or 0)
