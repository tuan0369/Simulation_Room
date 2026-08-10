"""Static checks on the 3D building view.

WebGL cannot be verified without a browser, so these check what is checkable:
that the page reads the same layout the simulator does, subscribes to topics
that actually exist, and references assets that are really served.
"""
import re
from pathlib import Path

import pytest

from building import load_building

PAGE = Path("room3d/building3d.html")
HTML = PAGE.read_text(encoding="utf-8")
MODULE = re.search(r'<script type="module">(.*?)</script>', HTML, re.S).group(1)


def test_page_exists_where_the_dashboard_points():
    dashboard = Path("dashboard/app_pages/building_overview.py").read_text(
        encoding="utf-8")
    assert "/room3d/building3d.html" in dashboard
    assert PAGE.exists()


def test_geometry_is_read_from_the_shared_layout():
    """Hardcoding room geometry here is how the picture drifts from the
    physics. It must fetch the same file the simulator loads."""
    assert "/data/building_layout.json" in MODULE
    for room in load_building().all_rooms():
        assert room.room_id not in MODULE, (
            f"{room.room_id} is hardcoded; it should come from the layout file")


def test_vendored_libraries_are_referenced_not_cdn():
    assert "/room3d/vendor/three.module.js" in MODULE
    assert "/room3d/vendor/mqtt.min.js" in HTML
    assert "unpkg.com" not in HTML and "cdn." not in HTML


def test_vendored_libraries_exist():
    assert Path("room3d/vendor/three.module.js").exists()
    assert Path("room3d/vendor/mqtt.min.js").exists()


def test_browser_side_urls_stay_localhost():
    """Evaluated in the user's browser against published ports, not inside a
    container — so these must NOT be rewritten to the service name."""
    assert "ws://localhost:9001" in MODULE
    assert "mosquitto:9001" not in MODULE


def test_subscribes_to_topics_the_simulator_publishes():
    assert "twin/#" in MODULE
    for leaf in ("temperature", "occupancy", "hvac/state", "health/risk"):
        assert leaf in MODULE, f"{leaf} is never read"


def test_risk_halo_is_driven_by_the_alert_flag():
    """The amber halo must follow the published alert, not a threshold
    re-implemented here — the model's threshold is cost-derived and ships with
    each score."""
    assert "risk.alert" in MODULE
    assert "halo.visible" in MODULE


def test_failures_are_visible_rather_than_blank():
    """A module that throws leaves an empty page, which is the hardest failure
    to diagnose inside a dashboard iframe."""
    assert "fatal(" in MODULE
    assert "Could not load" in MODULE


def test_floor_isolation_controls_exist():
    for button in ("b-all", "b-f1", "b-f2"):
        assert button in HTML


@pytest.mark.parametrize("floor_id", ["f1", "f2"])
def test_layout_floors_are_addressable(floor_id):
    assert load_building().floor(floor_id) is not None
