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


def test_pages_do_not_open_their_own_connections():
    for page in PAGES:
        text = _source(page)
        assert "mqtt.Client" not in text, f"{page} builds its own client"
        assert "get_mqtt" in text
