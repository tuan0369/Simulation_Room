"""Smoke tests for the dashboard pages.

A running Streamlit server proves nothing: page scripts execute per session, so
a broken page only fails when someone opens it. `AppTest` runs each page
headlessly and surfaces the exception here instead.

These also pin the skill conventions the rebuild exists to satisfy, so the
Project-1 patterns cannot creep back in.
"""
from pathlib import Path

import pytest

from streamlit.testing.v1 import AppTest

PAGES = [
    "dashboard/app_pages/building_overview.py",
    "dashboard/app_pages/room_console.py",
    "dashboard/app_pages/predictive_maintenance.py",
    "dashboard/app_pages/ecosystem.py",
]
SOURCES = PAGES + ["dashboard/streamlit_app.py", "dashboard/lib/mqtt_client.py",
                   "dashboard/lib/ui.py"]


def run(path, **state):
    app = AppTest.from_file(path, default_timeout=30)
    app.session_state["selected_room"] = state.get("selected_room", "f1/lab-a")
    return app.run()


@pytest.mark.parametrize("page", PAGES)
def test_page_runs_without_exception(page):
    app = run(page)
    assert not app.exception, (
        f"{page} raised: "
        f"{[str(e.value) for e in app.exception]}"
    )


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_something(page):
    app = run(page)
    rendered = (len(app.markdown) + len(app.metric) + len(app.dataframe)
                + len(app.info) + len(app.warning) + len(app.caption))
    assert rendered > 0, f"{page} rendered nothing at all"


def test_entry_point_runs():
    app = AppTest.from_file("dashboard/streamlit_app.py", default_timeout=30).run()
    assert not app.exception


def test_pages_survive_an_empty_store():
    """With no simulator running the pages must say so, not crash."""
    for page in PAGES:
        app = run(page)
        assert not app.exception, f"{page} crashed with no telemetry"


# ── Skill conventions ───────────────────────────────────────────────────────

def _source(path):
    return Path(path).read_text(encoding="utf-8")


@pytest.mark.parametrize("path", SOURCES)
def test_no_deprecated_container_width(path):
    """`use_container_width` is deprecated; the skill requires width=."""
    text = _source(path)
    assert "use_container_width=True" not in text, f"{path} uses a deprecated arg"


@pytest.mark.parametrize("path", SOURCES)
def test_no_deprecated_components_v1(path):
    assert "components.v1" not in _source(path), f"{path} uses deprecated v1"


@pytest.mark.parametrize("path", SOURCES)
def test_no_css_injection(path):
    """The skill says style with native elements and config.toml, not CSS
    blobs. Project 1's app.py injected a <style> block; that is what this
    rebuild replaces."""
    text = _source(path)
    assert "unsafe_allow_html=True" not in text, f"{path} injects raw HTML"
    assert "<style>" not in text, f"{path} injects CSS"


def test_multipage_uses_app_pages_not_pages():
    """`pages/` collides with Streamlit's legacy auto-discovery."""
    assert Path("dashboard/app_pages").is_dir()
    assert not Path("dashboard/pages").exists()
    entry = _source("dashboard/streamlit_app.py")
    assert "st.navigation" in entry and "st.Page" in entry


def test_single_cached_mqtt_client():
    """One connection for the whole app, surviving reruns and navigation."""
    text = _source("dashboard/lib/mqtt_client.py")
    assert "@st.cache_resource" in text
    assert text.count("mqtt.Client(") == 1


@pytest.mark.parametrize("path", SOURCES)
def test_modules_used_are_imported(path):
    """Catches the NameError class of bug that AppTest cannot.

    A page only executes the branches its default state reaches, so a missing
    import inside a conditional survives a green smoke test and then crashes
    the first time a user clicks something. `json.dumps` in the automation
    handler did exactly that: the branch runs only when the level CHANGES.
    """
    import ast
    tree = ast.parse(_source(path))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.asname or a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(a.asname or a.name for a in node.names)

    assigned = {n.id for node in ast.walk(tree)
                if isinstance(node, ast.Assign)
                for n in ast.walk(node.targets[0]) if isinstance(n, ast.Name)}
    assigned |= {n.id for node in ast.walk(tree)
                 if isinstance(node, (ast.For, ast.comprehension))
                 for n in ast.walk(getattr(node, "target", node))
                 if isinstance(n, ast.Name)}

    stdlib = {"json", "os", "math", "time", "random", "datetime", "pathlib",
              "collections", "threading", "re", "itertools", "functools"}
    used = {node.value.id for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)}

    for name in used & stdlib:
        if name in assigned:
            continue
        assert name in imported, (
            f"{path} uses {name}.* but never imports {name}")


def test_automation_is_one_control_in_one_place():
    """Two different things called 'auto' on two pages is the confusion this
    replaced: the climate mode lived on the console and auto-remediation on the
    maintenance page."""
    console = _source("dashboard/app_pages/room_console.py")
    maintenance = _source("dashboard/app_pages/predictive_maintenance.py")

    for level in ("Manual", "Auto climate", "Full auto"):
        assert level in console, f"{level} missing from the automation control"
    assert "cmd/autofix" in console, "the console cannot change autonomy"
    assert "st.toggle(" not in maintenance, (
        "the maintenance page still owns a second automation switch")


def test_full_auto_is_not_the_default():
    """Autonomy over physical equipment must be opted into. Folding
    auto-remediation into the default climate mode would have silently turned
    it on for everyone."""
    from building_twin import BuildingTwin
    from building import load_building
    assert BuildingTwin(load_building()).auto_fix is False
    console = _source("dashboard/app_pages/room_console.py")
    # The level shown is derived from live state, never hardcoded to Full auto.
    assert 'default=current' in console


def test_ac_buttons_sit_with_the_other_actions():
    """Switching the AC is an action, not a mode — it belongs beside the
    remedies rather than next to the automation switch."""
    console = _source("dashboard/app_pages/room_console.py")
    actions_start = console.index('st.markdown("**Actions**")')
    assert console.index('"AC on"') > actions_start
    assert console.index('"replace_filter"') > actions_start


def test_manual_only_controls_are_disabled_under_automation():
    console = _source("dashboard/app_pages/room_console.py")
    assert "disabled=not is_manual" in console


def test_ac_buttons_follow_the_chosen_level_not_the_confirmed_one():
    """They must react to the level the operator just picked. Reading the
    confirmed MQTT mode left them greyed out for a full round-trip after
    switching to Manual, so Manual appeared not to work at all."""
    console = _source("dashboard/app_pages/room_console.py")
    assert "is_manual = (level or current) == \"Manual\"" in console
    # …and the actions block must come after the control that sets `level`.
    assert console.index("is_manual =") > console.index("level = st.segmented_control")


def test_pages_do_not_open_their_own_connections():
    for page in PAGES:
        text = _source(page)
        assert "mqtt.Client" not in text, f"{page} builds its own client"
        assert "get_mqtt" in text
