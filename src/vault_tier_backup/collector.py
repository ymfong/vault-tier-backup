import os
from datetime import datetime, timedelta


def should_skip(path, skip_keywords):
    """Return True if path contains any skip keyword."""
    path_lower = path.lower()
    return any(keyword in path_lower for keyword in skip_keywords)


def get_files_to_backup(
    base_path,
    extensions,
    backup_roots,
    skip_keywords,
    days_limit=None,
    include_subfolders=True,
    full_backup_mode=False,
):
    files = []
    backup_roots = [os.path.abspath(r) for r in backup_roots]
    base_path = os.path.abspath(base_path)

    if include_subfolders:
        for root, dirs, filenames in os.walk(base_path):
            root_abs = os.path.abspath(root)
            if should_skip(root_abs, skip_keywords):
                print(f"[SKIP] Folder skipped: {root_abs}")
                continue
            if any(root_abs.startswith(br) for br in backup_roots):
                continue
            depth = os.path.relpath(root_abs, base_path).count(os.sep)
            for f in filenames:
                full_path = os.path.join(root, f)

                if full_backup_mode:
                    rel_path = os.path.relpath(full_path, base_path)
                    size_bytes = os.path.getsize(full_path)
                    print(f"[FULL] Include: {rel_path}")
                    files.append((full_path, rel_path, size_bytes, depth))
                    continue

                if should_skip(full_path, skip_keywords):
                    print(f"[SKIP] File skipped: {full_path}")
                    continue

                if f.endswith(extensions):
                    if days_limit:
                        mod_time = datetime.fromtimestamp(os.path.getmtime(full_path))
                        if datetime.now() - mod_time > timedelta(days=days_limit):
                            continue
                    rel_path = os.path.relpath(full_path, base_path)
                    size_bytes = os.path.getsize(full_path)
                    files.append((full_path, rel_path, size_bytes, depth))
    else:
        for f in os.listdir(base_path):
            full_path = os.path.join(base_path, f)
            if os.path.isfile(full_path):
                if should_skip(full_path, skip_keywords):
                    print(f"[SKIP] Folder skipped: {full_path}")
                    continue
                if f.endswith(extensions):
                    if days_limit:
                        mod_time = datetime.fromtimestamp(os.path.getmtime(full_path))
                        if datetime.now() - mod_time > timedelta(days=days_limit):
                            continue
                    rel_path = f
                    size_bytes = os.path.getsize(full_path)
                    files.append((full_path, rel_path, size_bytes, 0))
    return files
