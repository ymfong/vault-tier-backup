"""GUI form<->config mapping and dashboard summary (pure, headless).

The Tkinter view itself needs a display and isn't unit-tested here; all logic it
relies on lives in these pure helpers, which are.
"""

from vault_tier_backup import gui, wizard


def test_gui_module_imports_without_display():
    # Importing the module must not require tkinter/a display (launch does).
    assert hasattr(gui, "launch")


def test_config_to_form_round_trips_through_apply():
    config = wizard.build_config({
        "source": "D:\\Data",
        "mirrors": ["E:\\Bak"],
        "extensions": [".xlsx", ".accdb"],
        "weekly_day": 2,
    })
    form = gui.config_to_form(config)
    assert form["source"] == "D:\\Data"
    assert form["mirror"] == "E:\\Bak"
    assert form["extensions"] == ".xlsx, .accdb"
    assert form["weekly_day"] == 2
    assert form["encrypt"] is True

    # Flip some values in the form and write them back.
    form["encrypt"] = False
    form["mirror"] = ""
    form["extensions"] = "xlsx, docx"   # note: no leading dots
    gui.apply_form_to_config(config, form)

    assert config["control"]["encrypt"] is False
    assert config["mirrors"] == []
    assert config["backup"]["extensions"] == [".xlsx", ".docx"]  # dots normalized
    assert config["backup"]["dual_backup"] is False              # GUI single-dest model


def test_apply_form_keeps_untouched_config_sections():
    config = wizard.build_config({"source": "D:\\Data"})
    form = gui.config_to_form(config)
    gui.apply_form_to_config(config, form)
    # Sections the form doesn't edit must survive.
    assert "cloud" in config
    assert "monitoring" in config
    assert "email" in config


def test_backup_summary():
    entries = [
        {"name": "b.zip", "size": 100, "mtime": 200, "tier": "daily", "path": "b"},
        {"name": "a.zip", "size": 50, "mtime": 100, "tier": "daily", "path": "a"},
    ]
    summary = gui.backup_summary(entries)
    assert summary["count"] == 2
    assert summary["total_bytes"] == 150
    assert summary["latest"]["name"] == "b.zip"  # first = newest


def test_backup_summary_empty():
    summary = gui.backup_summary([])
    assert summary["count"] == 0 and summary["latest"] is None


def test_human_size_rounds():
    assert gui.human_size(0) == "0 B"
    assert gui.human_size(2048) == "2.0 KB"
