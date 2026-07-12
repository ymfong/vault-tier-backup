"""Desktop GUI (`vault-tier-backup gui`).

A friendly front end so a non-technical user never has to touch JSON or the
command line: pick folders, flip toggles, hit Save, and see their backups. It's a
thin view over the already-tested engine — every real operation (build config,
run backup, restore, schedule, fire-drill, safety checks) lives in the other
modules; this file only maps a form to/from the config and wires up buttons.

The form<->config mapping and dashboard summary are pure functions so they can be
tested headless; Tkinter is only touched inside `launch()`.
"""

import os

from . import wizard

WEEKDAYS = wizard.WEEKDAYS


# --- pure helpers (testable without a display) --------------------------------

def config_to_form(config):
    """Flatten a config dict into the flat values the form shows."""
    paths = config.get("paths", {})
    backup = config.get("backup", {})
    control = config.get("control", {})
    mirrors = config.get("mirrors", [])
    retention = config.get("retention", {})
    return {
        "source": paths.get("backup_source", ""),
        "dest": paths.get("backup_root_exe", "backup"),
        "extensions": ", ".join(backup.get("extensions", [])),
        "weekly_day": int(backup.get("weekly_day", 6)),
        "encrypt": bool(control.get("encrypt", True)),
        "verify": bool(control.get("verify_backups", True)),
        "mirror": mirrors[0] if mirrors else "",
        "daily_keep": int(retention.get("daily_keep", 7)),
        "weekly_keep": int(retention.get("weekly_keep", 5)),
        "monthly_keep": int(retention.get("monthly_keep", 12)),
        "yearly_keep": int(retention.get("yearly_keep", 2)),
    }


def apply_form_to_config(config, form):
    """Write the form's values back into a config dict (mutates and returns it).
    Starts from a complete config so nothing the form doesn't cover is lost."""
    config.setdefault("paths", {})
    config.setdefault("backup", {})
    config.setdefault("control", {})
    config.setdefault("retention", {})

    config["paths"]["backup_source"] = form["source"].strip()
    config["paths"]["backup_root_exe"] = form["dest"].strip() or "backup"

    exts = [
        e.strip() if e.strip().startswith(".") else "." + e.strip()
        for e in form["extensions"].split(",")
        if e.strip()
    ]
    config["backup"]["extensions"] = exts
    config["backup"]["weekly_day"] = int(form["weekly_day"])
    config["backup"]["dual_backup"] = False  # GUI uses one destination + mirror

    config["control"]["encrypt"] = bool(form["encrypt"])
    config["control"]["verify_backups"] = bool(form["verify"])

    mirror = form["mirror"].strip()
    config["mirrors"] = [mirror] if mirror else []

    for tier in ("daily", "weekly", "monthly", "yearly"):
        config["retention"][f"{tier}_keep"] = int(form[f"{tier}_keep"])
    return config


def backup_summary(entries):
    """Summarize the list from restore.list_backups for the dashboard."""
    total = sum(e["size"] for e in entries)
    return {
        "count": len(entries),
        "total_bytes": total,
        "latest": entries[0] if entries else None,  # list_backups is newest-first
    }


def human_size(num_bytes):
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


# --- Tkinter view (only touched at runtime) -----------------------------------

def launch(config_path):  # pragma: no cover - requires a display
    import json
    import threading
    import tkinter as tk
    from datetime import datetime
    from tkinter import filedialog, messagebox, simpledialog, ttk

    from . import config as config_mod
    from . import mirror, restore, safety, schedule
    from .run import run_monitored

    # Load existing config or start from wizard defaults.
    if os.path.exists(config_path):
        config = config_mod.load_config(config_path)
    else:
        config = wizard.build_config({"source": ""})
    form_seed = config_to_form(config)

    root = tk.Tk()
    root.title("vault-tier-backup")
    root.geometry("720x560")

    vars_ = {
        "source": tk.StringVar(value=form_seed["source"]),
        "dest": tk.StringVar(value=form_seed["dest"]),
        "extensions": tk.StringVar(value=form_seed["extensions"]),
        "weekly_day": tk.StringVar(value=WEEKDAYS[form_seed["weekly_day"]]),
        "encrypt": tk.BooleanVar(value=form_seed["encrypt"]),
        "verify": tk.BooleanVar(value=form_seed["verify"]),
        "mirror": tk.StringVar(value=form_seed["mirror"]),
        "daily_keep": tk.IntVar(value=form_seed["daily_keep"]),
        "weekly_keep": tk.IntVar(value=form_seed["weekly_keep"]),
        "monthly_keep": tk.IntVar(value=form_seed["monthly_keep"]),
        "yearly_keep": tk.IntVar(value=form_seed["yearly_keep"]),
    }

    def collect_form():
        return {
            "source": vars_["source"].get(),
            "dest": vars_["dest"].get(),
            "extensions": vars_["extensions"].get(),
            "weekly_day": WEEKDAYS.index(vars_["weekly_day"].get()),
            "encrypt": vars_["encrypt"].get(),
            "verify": vars_["verify"].get(),
            "mirror": vars_["mirror"].get(),
            "daily_keep": vars_["daily_keep"].get(),
            "weekly_keep": vars_["weekly_keep"].get(),
            "monthly_keep": vars_["monthly_keep"].get(),
            "yearly_keep": vars_["yearly_keep"].get(),
        }

    status = tk.StringVar(value="Ready.")

    def set_status(msg):
        status.set(msg)
        root.update_idletasks()

    def dest_abspath():
        base = os.path.dirname(os.path.abspath(config_path))
        return os.path.join(base, vars_["dest"].get())

    def check_warnings():
        """Surface the engine's safety findings as a banner."""
        src = vars_["source"].get().strip()
        if not src:
            return ""
        problems = []
        if mirror.same_volume(dest_abspath(), src):
            problems.append("⚠ Backup is on the SAME disk as the source — a disk failure loses both. Add an offsite mirror.")
        if not os.path.isdir(src):
            problems.append("⚠ Source folder does not exist.")
        return "  ".join(problems)

    def save_config():
        apply_form_to_config(config, collect_form())
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        banner.set(check_warnings())
        set_status(f"Saved {config_path}")

    def ensure_password():
        """For an encrypted run, make sure BACKUP_ZIP_PASSWORD is available."""
        if not vars_["encrypt"].get():
            return True
        if os.environ.get("BACKUP_ZIP_PASSWORD"):
            return True
        pw = simpledialog.askstring(
            "Backup password",
            "Enter the backup password (used to encrypt/restore your files).\n"
            "Store it somewhere durable — if it's lost, backups are unrecoverable.",
            show="*", parent=root,
        )
        if not pw:
            return False
        os.environ["BACKUP_ZIP_PASSWORD"] = pw
        if os.name == "nt" and messagebox.askyesno(
            "Remember password?",
            "Save this password to your Windows account so scheduled backups can "
            "use it? (Runs 'setx' — needed for automatic runs.)",
            parent=root,
        ):
            import subprocess
            subprocess.run(["setx", "BACKUP_ZIP_PASSWORD", pw], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    def run_in_thread(fn, on_done):
        def worker():
            try:
                result = fn()
                root.after(0, lambda: on_done(True, result))
            except Exception as e:
                root.after(0, lambda: on_done(False, str(e)))
        set_busy(True)
        threading.Thread(target=worker, daemon=True).start()

    def do_backup(dry):
        save_config()
        if not dry and not ensure_password():
            set_status("Cancelled — no password.")
            return

        def on_done(ok, result):
            set_busy(False)
            if ok:
                set_status("Dry run complete — see logs." if dry else "Backup complete.")
                refresh_backups()
                if not dry:
                    messagebox.showinfo("Done", "Backup completed.", parent=root)
            else:
                set_status("Backup failed.")
                messagebox.showerror("Backup failed", result, parent=root)

        set_status("Running…")
        run_in_thread(lambda: run_monitored(config_path, dry_run_override=dry), on_done)

    def do_test_restore():
        save_config()
        if not ensure_password():
            return

        def task():
            pw = os.environ.get("BACKUP_ZIP_PASSWORD", "").encode()
            ok, detail = safety.test_restore(dest_abspath(), pw)
            return ok, detail

        def on_done(ok, result):
            set_busy(False)
            if ok and result[0]:
                messagebox.showinfo("Restore fire-drill", result[1], parent=root)
            else:
                messagebox.showwarning("Restore fire-drill", result[1] if ok else result, parent=root)
            set_status("Ready.")

        set_status("Testing restore…")
        run_in_thread(task, on_done)

    def do_schedule():
        save_config()
        def on_done(ok, result):
            set_busy(False)
            if ok:
                messagebox.showinfo("Scheduled", result, parent=root)
            else:
                messagebox.showerror("Could not schedule", result, parent=root)
            set_status("Ready.")
        run_in_thread(lambda: schedule.install_schedule(config_path), on_done)

    def refresh_backups():
        for row in tree.get_children():
            tree.delete(row)
        try:
            entries = restore.list_backups(dest_abspath())
        except Exception:
            entries = []
        summary = backup_summary(entries)
        if summary["latest"]:
            ts = datetime.fromtimestamp(summary["latest"]["mtime"]).strftime("%Y-%m-%d %H:%M")
            dash.set(f"Last backup: {ts}   ·   {summary['count']} archives   ·   {human_size(summary['total_bytes'])}")
        else:
            dash.set("No backups yet — click “Run backup now”.")
        for e in entries:
            ts = datetime.fromtimestamp(e["mtime"]).strftime("%Y-%m-%d %H:%M")
            tree.insert("", "end", values=(e["tier"], e["name"], human_size(e["size"]), ts))

    def do_restore_selected():
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Restore", "Select a backup from the list first.", parent=root)
            return
        name = tree.item(sel[0])["values"][1]
        dest_dir = filedialog.askdirectory(title="Restore into which folder?")
        if not dest_dir:
            return
        if not ensure_password():
            return

        def task():
            pw = os.environ.get("BACKUP_ZIP_PASSWORD", "")
            return restore.restore_archive(dest_abspath(), name, dest_dir, pw)

        def on_done(ok, result):
            set_busy(False)
            if ok:
                messagebox.showinfo("Restored", f"Restored {len(result)} item(s) to\n{dest_dir}", parent=root)
            else:
                messagebox.showerror("Restore failed", result, parent=root)
            set_status("Ready.")

        set_status("Restoring…")
        run_in_thread(task, on_done)

    # --- layout ---
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=10, pady=10)

    # Settings tab
    s = ttk.Frame(nb, padding=14)
    nb.add(s, text="Settings")

    def folder_row(parent, label, var, r):
        ttk.Label(parent, text=label).grid(row=r, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=var, width=48).grid(row=r, column=1, sticky="we", pady=4, padx=6)
        ttk.Button(parent, text="Browse…",
                   command=lambda: var.set(filedialog.askdirectory() or var.get())).grid(row=r, column=2)

    folder_row(s, "Back up from", vars_["source"], 0)
    folder_row(s, "Save backups to", vars_["dest"], 1)
    ttk.Label(s, text="File types").grid(row=2, column=0, sticky="w", pady=4)
    ttk.Entry(s, textvariable=vars_["extensions"]).grid(row=2, column=1, sticky="we", pady=4, padx=6)
    ttk.Label(s, text="Weekly rollup day").grid(row=3, column=0, sticky="w", pady=4)
    ttk.Combobox(s, textvariable=vars_["weekly_day"], values=WEEKDAYS, state="readonly").grid(row=3, column=1, sticky="w", pady=4, padx=6)

    ttk.Checkbutton(s, text="Encrypt backups (AES — needs a password)", variable=vars_["encrypt"]).grid(row=4, column=1, sticky="w", pady=2)
    ttk.Checkbutton(s, text="Verify each backup after writing", variable=vars_["verify"]).grid(row=5, column=1, sticky="w", pady=2)
    folder_row(s, "Offsite mirror", vars_["mirror"], 6)

    keep = ttk.LabelFrame(s, text="Keep how many", padding=8)
    keep.grid(row=7, column=0, columnspan=3, sticky="we", pady=10)
    for i, tier in enumerate(("daily", "weekly", "monthly", "yearly")):
        ttk.Label(keep, text=tier.capitalize()).grid(row=0, column=i * 2, padx=(8, 2))
        ttk.Spinbox(keep, from_=0, to=999, width=5, textvariable=vars_[f"{tier}_keep"]).grid(row=0, column=i * 2 + 1)

    banner = tk.StringVar(value="")
    ttk.Label(s, textvariable=banner, foreground="#b45309", wraplength=660, justify="left").grid(row=8, column=0, columnspan=3, sticky="we", pady=6)

    btns = ttk.Frame(s)
    btns.grid(row=9, column=0, columnspan=3, sticky="we", pady=6)
    ttk.Button(btns, text="Save settings", command=save_config).pack(side="left")
    ttk.Button(btns, text="Test (dry run)", command=lambda: do_backup(True)).pack(side="left", padx=6)
    ttk.Button(btns, text="Run backup now", command=lambda: do_backup(False)).pack(side="left")
    ttk.Button(btns, text="Schedule daily", command=do_schedule).pack(side="left", padx=6)
    s.columnconfigure(1, weight=1)

    # Backups tab
    b = ttk.Frame(nb, padding=14)
    nb.add(b, text="Backups")
    dash = tk.StringVar(value="")
    ttk.Label(b, textvariable=dash, font=("", 10, "bold")).pack(anchor="w", pady=(0, 8))
    tree = ttk.Treeview(b, columns=("tier", "name", "size", "when"), show="headings", height=12)
    for col, w in (("tier", 70), ("name", 300), ("size", 90), ("when", 130)):
        tree.heading(col, text=col.capitalize())
        tree.column(col, width=w)
    tree.pack(fill="both", expand=True)
    rb = ttk.Frame(b)
    rb.pack(fill="x", pady=8)
    ttk.Button(rb, text="Restore selected…", command=do_restore_selected).pack(side="left")
    ttk.Button(rb, text="Test restore (fire-drill)", command=do_test_restore).pack(side="left", padx=6)
    ttk.Button(rb, text="Refresh", command=refresh_backups).pack(side="left")

    ttk.Label(root, textvariable=status, relief="sunken", anchor="w").pack(fill="x", side="bottom")

    all_buttons = [w for frame in (btns, rb) for w in frame.winfo_children()]

    def set_busy(busy):
        for w in all_buttons:
            w.configure(state="disabled" if busy else "normal")
        if busy:
            root.configure(cursor="watch")
        else:
            root.configure(cursor="")

    banner.set(check_warnings())
    refresh_backups()
    root.mainloop()
    return 0
