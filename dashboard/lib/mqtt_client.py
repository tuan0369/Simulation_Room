"""One MQTT client and one telemetry store for the whole dashboard.

`@st.cache_resource` means this survives reruns *and* page navigation, so
switching pages never opens a second broker connection. Project 1 already
learned that lesson for a single page; with four pages it matters more.

The store is written from paho's background thread and read from Streamlit's
script thread, so every access takes the lock.
"""
from __future__ import annotations

import json
import os
import threading
from collections import deque
from datetime import datetime

import paho.mqtt.client as mqtt
import streamlit as st

BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "localhost")
BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))
TOPIC_ROOT = "twin"

SENSORS = ("temperature", "humidity", "occupancy")
HISTORY = 240          # ~12 min of temperature at 3 s
ADVISORY_LOG = 50


def _blank_room() -> dict:
    return {
        "temperature": deque(maxlen=HISTORY),
        "humidity": deque(maxlen=HISTORY // 2),
        "occupancy": deque(maxlen=HISTORY),
        "hvac": {},
        "ac": {},
        "health": {},
        "risk": {},
    }


@st.cache_resource
def get_mqtt():
    """The single client + store for the app."""
    store = {
        "rooms": {},
        "floors": {},
        "building": {},
        "occupancy": {},
        "autofix": {},
        "advisories": deque(maxlen=ADVISORY_LOG),
        "status": "unknown",
        "messages": 0,
        "lock": threading.Lock(),
    }

    def room(store_, twin_id):
        return store_["rooms"].setdefault(twin_id, _blank_room())

    def on_connect(client, userdata, flags, reason_code, properties):
        client.subscribe(f"{TOPIC_ROOT}/#")

    def on_message(client, userdata, msg):
        parts = msg.topic.split("/")
        try:
            payload = msg.payload.decode()
        except UnicodeDecodeError:
            return

        with store["lock"]:
            store["messages"] += 1

            if msg.topic == f"{TOPIC_ROOT}/building/status":
                store["status"] = payload
                return
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                return

            # twin/building/<what>. Routed explicitly: an earlier catch-all
            # wrote every unrecognised building topic into store["building"],
            # so publishing twin/building/autofix silently clobbered the
            # building summary.
            if len(parts) == 3 and parts[1] == "building":
                what = parts[2]
                if what == "advisory":
                    store["advisories"].appendleft(data)
                elif what in ("summary", "occupancy", "autofix"):
                    store["building" if what == "summary" else what] = data
                return

            # twin/<floor>/summary
            if len(parts) == 3 and parts[2] == "summary":
                store["floors"][parts[1]] = data
                return

            if len(parts) < 4:
                return
            twin_id = f"{parts[1]}/{parts[2]}"
            leaf = "/".join(parts[3:])

            if leaf in SENSORS:
                try:
                    ts = datetime.fromisoformat(
                        data["timestamp"].replace("Z", "+00:00"))
                except (KeyError, ValueError):
                    return
                room(store, twin_id)[leaf].append((ts, data["value"]))
            elif leaf == "hvac/state":
                room(store, twin_id)["hvac"] = data
            elif leaf == "ac/detail":
                room(store, twin_id)["ac"] = data
            elif leaf == "health/telemetry":
                room(store, twin_id)["health"] = data
            elif leaf == "health/risk":
                room(store, twin_id)["risk"] = data

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER_HOST, BROKER_PORT)
    client.loop_start()
    return client, store


# ── Read helpers (all take the lock) ────────────────────────────────────────

def snapshot(store) -> dict:
    """A consistent copy of everything the pages render from."""
    with store["lock"]:
        rooms = {}
        for tid, r in store["rooms"].items():
            rooms[tid] = {
                "temperature": list(r["temperature"]),
                "humidity": list(r["humidity"]),
                "occupancy": list(r["occupancy"]),
                "hvac": dict(r["hvac"]),
                "ac": dict(r["ac"]),
                "health": dict(r["health"]),
                "risk": dict(r["risk"]),
            }
        return {
            "rooms": rooms,
            "floors": {k: dict(v) for k, v in store["floors"].items()},
            "building": dict(store["building"]),
            "occupancy": dict(store["occupancy"]),
            "autofix": dict(store["autofix"]),
            "advisories": list(store["advisories"]),
            "status": store["status"],
            "messages": store["messages"],
        }


def latest(series):
    return series[-1][1] if series else None


def publish(client, twin_id: str, suffix: str, payload: dict):
    client.publish(f"{TOPIC_ROOT}/{twin_id}/{suffix}", json.dumps(payload))
