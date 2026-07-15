"""Desktop GUI (`vault-tier-backup gui`).

A friendly front end so a non-technical user never has to touch JSON or the
command line: pick folders, flip toggles, hit Save, and see their backups. It's a
thin view over the already-tested engine — every real operation (build config,
run backup, restore, schedule, fire-drill, safety checks) lives in the other
modules; this file only maps a form to/from the config and wires up buttons.

The window is pywebview rendering a self-contained HTML/CSS page (native window
chrome, Microsoft WebView2 inside — preinstalled on Windows 10/11). HTML/CSS is
used deliberately: the audience is non-technical users who read visual polish as
trustworthiness, and stock Tk widgets read as dated. Buttons call Python through
pywebview's js_api bridge; each bridge call runs on a worker thread, so long
backups never freeze the window.

The form<->config mapping, dashboard summary, and page builder are pure
functions so they can be tested headless; pywebview is only touched in
`launch()`.
"""

import json
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


# --- the page (pure: form seed in, HTML out) -----------------------------------

_PAGE = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  :root {
    --accent:#0e7f92; --accent-dark:#0b6575; --accent-tint:#e2f2f4;
    --ok:#0f9d6e; --ok-tint:#e9f8f1; --ok-ink:#0a6d4c;
    --warn-ink:#92400e; --warn-tint:#fffbeb; --warn-border:#fde68a;
    --bg:#f8fafb; --card:#ffffff; --border:#e3e7eb; --border2:#cdd3d9;
    --text:#1f2933; --muted:#98a2ad; --text2:#5c6873;
  }
  html,body { height:100%; }
  body {
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
    font-size:12.5px; line-height:1.4; color:var(--text); background:var(--card);
    -webkit-font-smoothing:antialiased;
  }
  .app { display:flex; height:100vh; }
  .sidebar { flex:0 0 330px; border-right:1px solid var(--border); display:flex; flex-direction:column; }
  .sbody { flex:1; overflow-y:auto; padding:16px 16px 6px; }
  .sfoot { padding:10px 16px 12px; border-top:1px solid var(--border); background:var(--card); }
  .main { flex:1; background:var(--bg); overflow-y:auto; padding:16px; }
  h1 { font-size:16px; font-weight:600; margin-bottom:12px; letter-spacing:-.2px; }
  .eyebrow { font-size:10px; font-weight:700; letter-spacing:.7px; text-transform:uppercase;
             color:var(--muted); margin:13px 0 6px; }
  .eyebrow:first-of-type { margin-top:0; }
  label.f { display:block; font-size:11.5px; font-weight:600; margin:8px 0 4px; }
  .row { display:flex; gap:6px; }
  input[type=text], select {
    width:100%; padding:6px 8px; border:1px solid var(--border2); border-radius:6px;
    font-size:12.5px; font-family:inherit; color:var(--text); background:var(--card); outline:none;
  }
  input[type=text]:focus, select:focus { border-color:var(--accent); box-shadow:0 0 0 2px var(--accent-tint); }
  .browse { padding:6px 10px; border:1px solid var(--border2); border-radius:6px; background:var(--card);
            font-size:12px; font-weight:600; color:var(--text); cursor:pointer; white-space:nowrap; }
  .browse:hover { background:var(--bg); }

  .toggle { display:flex; align-items:center; gap:9px; padding:5px 0; cursor:pointer; user-select:none; }
  .toggle input { display:none; }
  .sw { position:relative; flex:0 0 auto; width:34px; height:19px; border-radius:999px;
        background:var(--border2); transition:background .18s; }
  .sw::after { content:""; position:absolute; top:2px; left:2px; width:15px; height:15px;
               border-radius:50%; background:#fff; transition:left .18s; box-shadow:0 1px 2px rgba(0,0,0,.2); }
  .toggle input:checked + .sw { background:var(--ok); }
  .toggle input:checked + .sw::after { left:17px; }
  .tl strong { display:block; font-size:12.5px; font-weight:600; }
  .tl span { font-size:11px; color:var(--muted); }

  .keep { display:flex; gap:7px; }
  .keep div { flex:1; }
  .keep label { display:block; font-size:10px; color:var(--muted); margin-bottom:3px; }
  .keep input { width:100%; padding:5px; border:1px solid var(--border2); border-radius:6px;
                font-size:12.5px; text-align:center; }

  .banner { display:none; background:var(--warn-tint); border:1px solid var(--warn-border);
            color:var(--warn-ink); border-radius:7px; padding:8px 10px; font-size:11.5px;
            margin-bottom:9px; line-height:1.45; }

  .btns { display:flex; gap:6px; }
  .btns + .btns { margin-top:6px; }
  .btn { flex:1; padding:8px 8px; border-radius:7px; font-size:12.5px; font-weight:600;
         cursor:pointer; border:1px solid transparent; text-align:center; }
  .btn.solid { background:var(--accent); color:#fff; }
  .btn.solid:hover { background:var(--accent-dark); }
  .btn.line { background:var(--card); border-color:var(--border2); color:var(--text); }
  .btn.line:hover { background:var(--bg); }
  .btn:disabled { opacity:.5; cursor:default; }

  .status-card { background:var(--ok-tint); border:1px solid #d1fae5; border-radius:9px;
                 padding:10px 12px; margin-bottom:10px; }
  .status-card.none { background:#f1f5f9; border-color:var(--border); }
  .status-card .k { font-size:10px; font-weight:700; letter-spacing:.5px; text-transform:uppercase; color:var(--ok-ink); }
  .status-card .v { font-size:15px; font-weight:700; color:var(--ok-ink); margin-top:3px; }
  .status-card.none .k, .status-card.none .v { color:var(--text2); }

  .metrics { display:flex; gap:9px; margin-bottom:13px; }
  .metric { flex:1; background:var(--card); border:1px solid var(--border); border-radius:9px;
            padding:11px; text-align:center; }
  .metric .k { font-size:11px; color:var(--muted); margin-bottom:5px; }
  .metric .v { font-size:20px; font-weight:700; font-variant-numeric:tabular-nums; }

  .list { display:flex; flex-direction:column; gap:6px; }
  .item { background:var(--card); border:1px solid var(--border); border-radius:9px;
          padding:9px 11px; display:flex; align-items:center; justify-content:space-between; }
  .item .nm { font-weight:600; font-size:12.5px; }
  .badge { display:inline-block; font-size:9.5px; font-weight:700; letter-spacing:.3px;
           text-transform:uppercase; padding:2px 7px; border-radius:5px; margin-left:7px;
           background:var(--accent-tint); color:var(--accent-dark); vertical-align:1px; }
  .item .mt { font-size:11px; color:var(--muted); margin-top:2px; }
  .rbtn { padding:6px 12px; font-size:11.5px; font-weight:600; border:1px solid var(--border2);
          border-radius:7px; background:var(--card); color:var(--accent-dark); cursor:pointer; }
  .rbtn:hover { border-color:var(--accent); }
  .rbtn:disabled { opacity:.5; cursor:default; }
  .empty { color:var(--muted); padding:10px 2px; }

  .toast { position:fixed; right:16px; bottom:16px; max-width:400px; background:#1f2933; color:#fff;
           border-radius:8px; padding:10px 14px; font-size:11.5px; line-height:1.45; white-space:pre-wrap;
           box-shadow:0 8px 24px rgba(0,0,0,.25); opacity:0; transition:opacity .25s; pointer-events:none; }
  .toast.show { opacity:1; }
  .toast.err { background:#7f1d1d; }
  .toast.ok { background:#065f46; }

  .overlay { display:none; position:fixed; inset:0; background:rgba(15,23,32,.55);
             align-items:center; justify-content:center; z-index:50; }
  .overlay.show { display:flex; }
  .modal { background:var(--card); border-radius:11px; padding:18px; width:340px;
           box-shadow:0 18px 50px rgba(0,0,0,.3); }
  .modal h2 { font-size:14px; margin-bottom:7px; }
  .modal p { font-size:11.5px; color:var(--text2); line-height:1.45; margin-bottom:10px; }
  .modal input[type=password] { width:100%; padding:7px 9px; border:1px solid var(--border2);
           border-radius:6px; font-size:12.5px; }
  .modal .chk { display:flex; gap:7px; align-items:flex-start; font-size:11px; color:var(--text2);
                margin:10px 0 13px; line-height:1.4; }
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
   <div class="sbody">
    <h1>Settings</h1>

    <p class="eyebrow">Folders</p>
    <label class="f">Back up from</label>
    <div class="row"><input type="text" id="source"><button class="browse" onclick="pick('source')">Browse…</button></div>
    <label class="f">Save backups to</label>
    <div class="row"><input type="text" id="dest"><button class="browse" onclick="pick('dest')">Browse…</button></div>

    <p class="eyebrow">Backup</p>
    <label class="f">File types</label>
    <input type="text" id="extensions">
    <label class="f">Weekly rollup day</label>
    <select id="weekly_day"></select>

    <p class="eyebrow">Protection</p>
    <label class="toggle"><input type="checkbox" id="encrypt"><span class="sw"></span>
      <span class="tl"><strong>Encrypt backups</strong><span>AES password lock — keep the password safe</span></span></label>
    <label class="toggle"><input type="checkbox" id="verify"><span class="sw"></span>
      <span class="tl"><strong>Verify after write</strong><span>Catch corruption early</span></span></label>
    <label class="f">Offsite mirror (another drive/device)</label>
    <div class="row"><input type="text" id="mirror" placeholder="none — recommended: add one"><button class="browse" onclick="pick('mirror')">Browse…</button></div>

    <p class="eyebrow">Keep how many</p>
    <div class="keep">
      <div><label>Daily</label><input type="number" min="0" id="daily_keep"></div>
      <div><label>Weekly</label><input type="number" min="0" id="weekly_keep"></div>
      <div><label>Monthly</label><input type="number" min="0" id="monthly_keep"></div>
      <div><label>Yearly</label><input type="number" min="0" id="yearly_keep"></div>
    </div>
   </div>

   <div class="sfoot">
    <div class="banner" id="banner"></div>
    <div class="btns">
      <button class="btn solid" id="b_save" onclick="doSave()">Save settings</button>
      <button class="btn line" id="b_dry" onclick="doBackup(true)">Test run</button>
    </div>
    <div class="btns">
      <button class="btn solid" id="b_run" onclick="doBackup(false)">Run backup now</button>
      <button class="btn line" id="b_sched" onclick="doSchedule()">Schedule daily</button>
    </div>
   </div>
  </aside>

  <main class="main">
    <h1>Dashboard</h1>
    <div class="status-card none" id="scard">
      <div class="k" id="s_k">Loading…</div>
      <div class="v" id="s_v"></div>
    </div>
    <div class="metrics">
      <div class="metric"><div class="k">Storage used</div><div class="v" id="m_size">–</div></div>
      <div class="metric"><div class="k">Archives</div><div class="v" id="m_count">–</div></div>
    </div>
    <p class="eyebrow">Recent backups</p>
    <div class="list" id="list"><div class="empty">Loading…</div></div>
    <div class="btns" style="max-width:360px">
      <button class="btn line" id="b_drill" onclick="doDrill()">Test restore (fire-drill)</button>
      <button class="btn line" id="b_refresh" onclick="refresh()">Refresh</button>
    </div>
  </main>
</div>

<div class="toast" id="toast"></div>

<div class="overlay" id="pwOverlay">
  <div class="modal">
    <h2>Backup password</h2>
    <p>Used to encrypt and restore your files. <strong>If it is lost, every encrypted
       backup is permanently unrecoverable</strong> — store it in a password manager.</p>
    <input type="password" id="pwInput" placeholder="Enter backup password">
    <label class="chk"><input type="checkbox" id="pwRemember" checked>
      Remember on this Windows account so scheduled backups can run automatically</label>
    <div class="btns" style="margin-top:0">
      <button class="btn line" onclick="pwCancel()">Cancel</button>
      <button class="btn solid" onclick="pwOk()">OK</button>
    </div>
  </div>
</div>

<script>
const FORM = __FORM_JSON__;
const WEEKDAYS = __WEEKDAYS_JSON__;
let pwResolve = null;

function $(id) { return document.getElementById(id); }
function api() { return window.pywebview.api; }

function friendlyName(name) {
  // "2026-07-11_20-00-00_daily.zip" -> "Sat, 11 Jul 2026 · 8:00 PM"
  const m = name.match(/^(\d{4})-(\d{2})-(\d{2})_(\d{2})-(\d{2})-(\d{2})_/);
  if (!m) return name.replace(/\.zip$/i, "");
  const d = new Date(+m[1], +m[2]-1, +m[3], +m[4], +m[5], +m[6]);
  const date = d.toLocaleDateString(undefined, {weekday:"short", day:"numeric", month:"short", year:"numeric"});
  const time = d.toLocaleTimeString(undefined, {hour:"numeric", minute:"2-digit"});
  return date + " · " + time;
}

function fillForm() {
  const sel = $("weekly_day");
  WEEKDAYS.forEach((d, i) => {
    const o = document.createElement("option");
    o.value = i; o.textContent = d;
    sel.appendChild(o);
  });
  $("source").value = FORM.source;
  $("dest").value = FORM.dest;
  $("extensions").value = FORM.extensions;
  sel.value = FORM.weekly_day;
  $("encrypt").checked = FORM.encrypt;
  $("verify").checked = FORM.verify;
  $("mirror").value = FORM.mirror;
  for (const t of ["daily","weekly","monthly","yearly"]) $(t + "_keep").value = FORM[t + "_keep"];
}

function collect() {
  return {
    source: $("source").value, dest: $("dest").value,
    extensions: $("extensions").value, weekly_day: parseInt($("weekly_day").value),
    encrypt: $("encrypt").checked, verify: $("verify").checked, mirror: $("mirror").value,
    daily_keep: parseInt($("daily_keep").value) || 0,
    weekly_keep: parseInt($("weekly_keep").value) || 0,
    monthly_keep: parseInt($("monthly_keep").value) || 0,
    yearly_keep: parseInt($("yearly_keep").value) || 0,
  };
}

function toast(msg, kind) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast show" + (kind ? " " + kind : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.className = "toast", 6000);
}

function setBusy(b) {
  for (const id of ["b_save","b_dry","b_run","b_sched","b_drill","b_refresh"]) $(id).disabled = b;
  document.querySelectorAll(".rbtn").forEach(x => x.disabled = b);
}

function showBanner(text) {
  const el = $("banner");
  el.textContent = text || "";
  el.style.display = text ? "block" : "none";
}

async function pick(id) {
  const p = await api().browse();
  if (p) { $(id).value = p; }
}

async function doSave() {
  const r = await api().save(collect());
  showBanner(r.warnings);
  toast("Settings saved.", "ok");
}

function askPassword() {
  return new Promise(res => {
    pwResolve = res;
    $("pwInput").value = "";
    $("pwOverlay").className = "overlay show";
    $("pwInput").focus();
  });
}
function pwOk() {
  $("pwOverlay").className = "overlay";
  if (pwResolve) pwResolve({ pw: $("pwInput").value, remember: $("pwRemember").checked });
}
function pwCancel() {
  $("pwOverlay").className = "overlay";
  if (pwResolve) pwResolve(null);
}

async function ensurePassword() {
  if (!(await api().needs_password($("encrypt").checked))) return true;
  const got = await askPassword();
  if (!got || !got.pw) { toast("Cancelled — no password."); return false; }
  await api().set_password(got.pw, got.remember);
  return true;
}

async function doBackup(dry) {
  setBusy(true);
  try {
    const r0 = await api().save(collect());
    showBanner(r0.warnings);
    if (!dry && !(await ensurePassword())) return;
    const msg = await api().run_backup(dry);
    toast(msg, "ok");
    await refresh();
  } catch (e) { toast("Backup failed: " + e, "err"); }
  finally { setBusy(false); }
}

async function doSchedule() {
  setBusy(true);
  try {
    await api().save(collect());
    const msg = await api().schedule_daily();
    toast(msg, "ok");
  } catch (e) { toast("Could not schedule: " + e, "err"); }
  finally { setBusy(false); }
}

async function doDrill() {
  setBusy(true);
  try {
    await api().save(collect());
    if (!(await ensurePassword())) return;
    const r = await api().fire_drill();
    toast(r.detail, r.ok ? "ok" : "err");
  } catch (e) { toast("Fire-drill failed: " + e, "err"); }
  finally { setBusy(false); }
}

async function doRestore(name) {
  setBusy(true);
  try {
    if (!(await ensurePassword())) return;
    const msg = await api().restore_one(name);
    if (msg) toast(msg, "ok");
  } catch (e) { toast("Restore failed: " + e, "err"); }
  finally { setBusy(false); }
}

async function refresh() {
  const d = await api().get_backups();
  showBanner(d.warnings);
  const sc = $("scard");
  if (d.latest) {
    sc.className = "status-card";
    $("s_k").textContent = "✓ Last backup";
    $("s_v").textContent = d.latest;
  } else {
    sc.className = "status-card none";
    $("s_k").textContent = "No backups yet";
    $("s_v").textContent = "Click “Run backup now” to create your first one";
  }
  $("m_size").textContent = d.total;
  $("m_count").textContent = d.count;
  const list = $("list");
  list.innerHTML = "";
  if (!d.entries.length) {
    list.innerHTML = '<div class="empty">No backups yet.</div>';
    return;
  }
  for (const e of d.entries) {
    const item = document.createElement("div");
    item.className = "item";
    const left = document.createElement("div");
    left.innerHTML = '<span class="nm"></span><span class="badge"></span><div class="mt"></div>';
    const nm = left.querySelector(".nm");
    nm.textContent = friendlyName(e.name);
    nm.title = e.name;  // raw filename on hover for anyone who wants it
    left.querySelector(".badge").textContent = e.tier;
    left.querySelector(".mt").textContent = e.size;
    const btn = document.createElement("button");
    btn.className = "rbtn";
    btn.textContent = "Restore";
    btn.onclick = () => doRestore(e.name);
    item.appendChild(left);
    item.appendChild(btn);
    list.appendChild(item);
  }
}

window.addEventListener("pywebviewready", async () => {
  fillForm();
  await refresh();
});
</script>
</body>
</html>
"""


def build_html(form_seed):
    """The full page with the saved settings embedded. Pure — testable without a
    window."""
    return _PAGE.replace("__FORM_JSON__", json.dumps(form_seed)).replace(
        "__WEEKDAYS_JSON__", json.dumps(WEEKDAYS)
    )


# --- pywebview bridge + window (only touched at runtime) -----------------------

class _Api:  # pragma: no cover - exercised through a live window
    """Methods callable from the page's JavaScript. pywebview runs each call on
    a worker thread, so long backups never freeze the window."""

    def __init__(self, config_path, config):
        # Underscore-prefixed on purpose: pywebview exposes every PUBLIC
        # attribute/method of this object to JavaScript, and trying to
        # serialize the native window object recurses forever.
        self._config_path = config_path
        self._config = config
        self._window = None  # set after the window exists

    # -- helpers --
    def _form(self):
        return config_to_form(self._config)

    def _dest_abspath(self):
        base = os.path.dirname(os.path.abspath(self._config_path))
        return os.path.join(base, self._form()["dest"])

    def _warnings(self):
        from . import mirror

        form = self._form()
        src = form["source"].strip()
        if not src:
            return ""
        problems = []
        if mirror.same_volume(self._dest_abspath(), src):
            problems.append(
                "⚠ Backup is on the SAME disk as the source — a disk failure "
                "loses both. Add an offsite mirror."
            )
        if not os.path.isdir(src):
            problems.append("⚠ Source folder does not exist.")
        return "   ".join(problems)

    # -- bridge methods (called from JS) --
    def browse(self):
        import webview

        picked = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return picked[0] if picked else None

    def save(self, form):
        apply_form_to_config(self._config, form)
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2)
        return {"warnings": self._warnings()}

    def needs_password(self, encrypt):
        return bool(encrypt) and not os.environ.get("BACKUP_ZIP_PASSWORD")

    def set_password(self, password, remember):
        os.environ["BACKUP_ZIP_PASSWORD"] = password
        if remember and os.name == "nt":
            import subprocess

            subprocess.run(
                ["setx", "BACKUP_ZIP_PASSWORD", password], check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

    def run_backup(self, dry):
        from .run import run_monitored

        run_monitored(self._config_path, dry_run_override=bool(dry))
        return "Dry run complete — nothing was written." if dry else "Backup completed."

    def schedule_daily(self):
        from . import schedule

        return schedule.install_schedule(self._config_path)

    def fire_drill(self):
        from . import safety

        pw = os.environ.get("BACKUP_ZIP_PASSWORD", "").encode()
        ok, detail = safety.test_restore(self._dest_abspath(), pw)
        return {"ok": ok, "detail": detail}

    def restore_one(self, name):
        import webview

        from . import restore

        picked = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        if not picked:
            return None
        dest_dir = picked[0]
        pw = os.environ.get("BACKUP_ZIP_PASSWORD", "")
        written = restore.restore_archive(self._dest_abspath(), name, dest_dir, pw)
        return f"Restored {len(written)} item(s) to {dest_dir}"

    def get_backups(self):
        from datetime import datetime

        from . import restore

        try:
            entries = restore.list_backups(self._dest_abspath())
        except Exception:
            entries = []
        summary = backup_summary(entries)
        latest = None
        if summary["latest"]:
            # Friendly, matching the list below (e.g. "Sat, Jul 11, 2026 · 8:00 PM").
            latest = datetime.fromtimestamp(summary["latest"]["mtime"]).strftime("%a, %b %d, %Y · %I:%M %p")
        return {
            "latest": latest,
            "count": summary["count"],
            "total": human_size(summary["total_bytes"]),
            "entries": [
                {
                    "tier": e["tier"],
                    "name": e["name"],
                    "size": human_size(e["size"]),
                    "when": datetime.fromtimestamp(e["mtime"]).strftime("%Y-%m-%d %H:%M"),
                }
                for e in entries
            ],
            "warnings": self._warnings(),
        }


def launch(config_path):  # pragma: no cover - requires a display
    import webview

    from . import config as config_mod

    # Load existing config or start from wizard defaults.
    if os.path.exists(config_path):
        config = config_mod.load_config(config_path)
    else:
        config = wizard.build_config({"source": ""})

    api = _Api(config_path, config)
    window = webview.create_window(
        "vault-tier-backup",
        html=build_html(config_to_form(config)),
        js_api=api,
        width=1000,
        height=720,
        min_size=(820, 560),
    )
    api._window = window
    webview.start()
    return 0
