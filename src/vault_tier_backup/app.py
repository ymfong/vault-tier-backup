"""Entry point for the standalone (PyInstaller) build.

Double-clicking the exe (no arguments) opens the desktop GUI with the config in
a stable per-user location — %APPDATA%\\vault-tier-backup on Windows — instead
of wherever the exe happens to sit (Downloads, a USB stick), so settings and
the backup destination don't move around with the file.

Any arguments fall through to the normal CLI, which is what the scheduled task
the GUI registers relies on: it runs `VaultTierBackup.exe -c <config> backup`.
(The windowed build has no console, so CLI output is invisible — backup runs
log to files under the backup root, which is what matters for scheduled use.)
"""

import os
import sys


def default_config_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    cfg_dir = os.path.join(base, "vault-tier-backup")
    os.makedirs(cfg_dir, exist_ok=True)
    return os.path.join(cfg_dir, "config.json")


def main():
    if len(sys.argv) > 1:
        from .run import main as cli_main
        return cli_main()
    from . import gui
    return gui.launch(default_config_path())


if __name__ == "__main__":
    sys.exit(main() or 0)
