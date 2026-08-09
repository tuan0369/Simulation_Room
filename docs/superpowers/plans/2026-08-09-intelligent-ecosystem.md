# Project 2 — Intelligent Ecosystem & Strategic Optimization

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **REQUIRED SUB-SKILL for every Streamlit change:** `developing-with-streamlit` (see Task 0 Step 3 — the symlink is currently broken and must be repaired before dashboard work starts).

**Predecessor:** [2026-07-16-digital-twin-lab.md](2026-07-16-digital-twin-lab.md) (Project 1 — complete). This plan extends that codebase; it does not replace it. Note that the Project-1 plan document is a historical record written *before* execution: the shipped code has since gained a PID controller, variable-speed AC (1500 W → 3500 W), occupancy up to 30, auto mode, and the `cmd/setpoint`, `cmd/timescale`, `cmd/mode`, `ac/detail` topics. **Where the Project-1 plan and the shipped code disagree, the code wins.**

**Due:** 16 Aug 2026.

**Branching:** `main` mirrors `origin/main` (the GitHub baseline) and is never committed to directly. All Project-2 work lands on **`project-2-ecosystem`**. Keep `main` pristine so the Project-1 submission stays reproducible from it.

**Runtime:** everything runs in Docker (see Task 0). There is no host Python on the dev machine and none is required.

## Progress

| Task | Status | Commit | Tests |
|---|---|---|---|
| 0. Dockerize the environment | ✅ done | `7397b95`, `44f9449`, `e7ff738` | 38 |
| 1. Building layout dataset + loader | ✅ done | `f12eb70` | 60 |
| 2. HVAC health model (AI4I-calibrated) | ✅ done | `dd35407` | 86 |
| 3. Room twin refactor | ✅ done | `5f2597c` | 113 |
| 4. Occupancy twin | ✅ done | `see log` | 133 |
| 5. Floor + building twins | ⬜ next | | |
| 6. Dataset generator | ⬜ | | |
| 7. ML notebooks | ⬜ | | |
| 8. Live inference | ⬜ | | |
| 9. Multipage dashboard | ⬜ | | |
| 10. Multi-floor 3D view | ⬜ | | |
| 11. Ecosystem / governance / ROI docs | ⬜ | | |
| 12. Executive pitch | ⬜ | | |
| 13. README + final integration | ⬜ | | |

Keep this table current — the Project-1 plan's checkboxes were never ticked and it stopped being a usable record of what shipped.

---

## Goal

Extend the single-room Smart Lab Digital Twin into an **Intelligent Autonomous Ecosystem**: a 2-floor / 6-room smart facility of interacting sub-twins, with a machine-learning model predicting HVAC equipment failure (fan-motor overheating, filter clogging), federated coordination between twins, and the governance / ROI / roadmap deliverables required by the brief.

## Assignment requirement → task map

| Brief requirement | Delivered by |
|---|---|
| Predictive Intelligence (ML predicting fan motor overheating) | Task 2 (failure physics), Task 6 (dataset), Task 7 (notebooks), Task 8 (live inference) |
| Ecosystem Integration (multi-twin architecture, data flows) | Task 1, 3, 4, 5 (code), Task 11 (`docs/ecosystem.md`) |
| Governance & Ethics (cybersecurity, ROI, transparency, bias) | Task 7 Step 6 (bias audit + explainability), Task 11 (`docs/governance.md`) |
| Strategic Roadmap (ROI calc, pilot → full deployment) | Task 11 (`docs/roi_roadmap.md`) |
| **Deliverable:** Predictive Model Output (notebooks) | Task 7 → `ml/notebooks/*.ipynb`, `ml/models/model_card.md` |
| **Deliverable:** Integrated Ecosystem Diagram (centralized vs federated) | Task 11 → `docs/ecosystem.md` mermaid diagrams |
| **Deliverable:** Executive Pitch (business value, security, ethics) | Task 12 → `report/pitch/` |
| *(Our own goal)* Expand scale: more rooms, more floors | Task 1, 3, 9, 10 |

---

## Architecture decisions (locked before implementation)

### Building layout — 2 floors × 3 rooms = 6 room twins

| Twin ID | Floor | Name | Area | Max occupancy | Thermal character |
|---|---|---|---|---|---|
| `f1/lab-a` | 1 | Wet Lab A | 60 m² | 30 | High equipment load, existing Project-1 room |
| `f1/lab-b` | 1 | Dry Lab B | 45 m² | 20 | Moderate load |
| `f1/server-room` | 1 | Server Room | 20 m² | 4 | Constant 4 kW IT load, 24/7 AC, no occupancy dependence |
| `f2/lab-c` | 2 | Teaching Lab C | 70 m² | 30 | Bursty occupancy (class schedule) |
| `f2/meeting-room` | 2 | Meeting Room | 30 m² | 16 | Bursty, poor insulation (glass wall) |
| `f2/office` | 2 | Open Office | 55 m² | 24 | Steady daytime occupancy |

Floor 2 receives more solar gain (higher `T_outdoor` coupling). Adjacent rooms are thermally coupled through shared walls; each floor has a corridor node.

### Topic namespace (breaking change from Project 1)

```
twin/{floor}/{room}/temperature|humidity|occupancy      # sensors (as Project 1 payload spec)
twin/{floor}/{room}/hvac/state                          # retained
twin/{floor}/{room}/ac/detail                           # retained
twin/{floor}/{room}/health/telemetry                    # NEW: motor_temp, fan_rpm, vibration, clog, power_w
twin/{floor}/{room}/health/risk                         # NEW: ML output — failure prob + RUL
twin/{floor}/{room}/cmd/hvac|occupancy|setpoint|mode    # commands
twin/{floor}/{room}/cmd/maintenance                     # NEW: {"action": "replace_filter"|"service_motor"}
twin/{floor}/summary                                    # NEW: floor twin aggregate (retained)
twin/{floor}/cmd/power_budget                           # NEW: building → floor kW cap
twin/building/summary                                   # NEW: building twin aggregate (retained)
twin/building/advisory                                  # NEW: coordination decisions + maintenance work orders
twin/building/cmd/timescale                             # global sim speed
twin/building/status                                    # LWT online/offline
```

`{floor}` ∈ `f1|f2`. Project-1 topics (`twin/room1/*`) are **retired**; `f1/lab-a` is their successor. The Project-1 demo video and report keep their own historical value and are not re-recorded.

### Coordination strategy — federated with hierarchical supervision

This is the answer to the brief's "centralized vs. federated" question, and it must be argued in `docs/ecosystem.md`:

- **Room twins** run an autonomous fast loop (1 s): local PID, local safety limits. They stay correct even if the floor/building twins die.
- **Floor twins** run a slow loop (10 s): aggregate the floor, enforce an electrical demand cap by nudging room setpoints (not by seizing control), publish `twin/{floor}/summary`.
- **Building twin** runs the slowest loop (30 s): global energy budget, demand-response, and converts ML risk scores into maintenance work orders.
- Control authority **degrades gracefully downward**: supervisors advise, rooms decide. A centralized design would put all 6 PID loops in one process — one crash stops all cooling, and every occupancy record leaves the room. Federated keeps occupancy data room-local and publishes only aggregates, which is also the privacy argument in `docs/governance.md`.

### Predictive target — HVAC equipment degradation

Each room's HVAC unit carries a health model (`simulator/hvac_health.py`) with four coupled degradation states:

- `filter_clog` (0–1): accumulates with airflow-hours × dust load (dust ∝ occupancy); reset by `replace_filter`.
- `fan_rpm`: fan compensates for clogging to hold airflow → `rpm = base_rpm × (1 + CLOG_RPM_GAIN × filter_clog)`.
- `motor_temp` (°C): rises with rpm² (torque) and duty cycle, sheds heat to room air → **fan motor overheating**, the brief's named failure mode.
- `bearing_wear` (0–1) → `vibration_mm_s` (ISO 10816 band).

**Failure rules are calibrated against UCI AI4I 2020**, not invented. See Task 2.

---

## Global constraints

- Repo root = `c:\Users\tuann\Simulation_Room`. Keep the existing top-level layout; new dirs are `data/`, `ml/`, `dashboard/app_pages/`, `dashboard/lib/`.
- **Everything runs in Docker.** The canonical test command for every task is:
  ```powershell
  docker compose run --rm sim pytest -v
  ```
  Never assume a host Python interpreter exists — it does not.
- **Every task ends with all tests green.** The 38 existing tests must be migrated, not deleted — a test may change its topic string, but its physical assertion must survive.
- **No hard-coded `localhost` in Python.** Inside containers the broker is reachable as `mosquitto`, not `localhost`. All broker hosts come from `MQTT_BROKER_HOST` (default `localhost`, so host-side runs still work). Browser-side URLs (`ws://localhost:9001` in the 3D view, the dashboard's `st.iframe` to `:8000`) **stay `localhost`** — those resolve in the user's browser against published ports, not inside a container.
- Physics remains deterministic and test-locked. No pure-random behaviour in any `step_*` function; randomness enters only through an injected `random.Random`.
- `paho-mqtt` stays on `mqtt.CallbackAPIVersion.VERSION2`.
- Dashboard: exactly one MQTT client for the whole app (`@st.cache_resource`), one model load (`@st.cache_resource`), regardless of page navigation.
- ML must be reproducible: fixed seeds, `data/` inputs committed (except the large generated CSV), `ml/models/*.joblib` committed with a `model_card.md`.
- **No leakage in the ML pipeline**: the train/test split is by *time and by room*, never a random row shuffle — consecutive telemetry rows are near-duplicates and a random split would inflate scores to a meaningless ~0.99.
- Commit after every task.

---

## Task 0: Dockerize the environment (BLOCKER — nothing else can run)

**Why this exists:** the dev machine has no working Python (`python` resolves to the Microsoft Store stub), no `uv`, and no `.venv`. Rather than installing a host toolchain, we extend the Docker setup the project already uses so the entire twin — simulator, dashboard, 3D server, notebooks, tests — runs in containers. One `docker compose up` starts the facility.

Two consequences fall out of this and must be handled here, not discovered later:

1. `.agents/skills/developing-with-streamlit` and `.claude/skills/developing-with-streamlit` are **dangling symlinks** to `../../.venv/lib/python3.12/site-packages/...` — a POSIX path from the original macOS machine. It cannot resolve on Windows, and with no host `.venv` at all it now resolves nowhere. Fix it permanently rather than papering over it.
2. `BROKER_HOST = "localhost"` is hard-coded in `simulator/publisher.py` and `dashboard/app.py`. Inside a container that points at the container itself. This must become configurable **before** any service is containerized, or every service silently fails to connect.

**Files:**
- Create: `Dockerfile`
- Modify: `docker-compose.yml` (add services; **the `mosquitto` service stays byte-identical**)
- Create: `.dockerignore`
- Modify: `pyproject.toml` (ML dependency group, `requires-python`)
- Modify: `.gitignore`
- Modify: `simulator/publisher.py`, `dashboard/app.py` (broker host from env)
- Replace: `.agents/skills/developing-with-streamlit`, `.claude/skills/developing-with-streamlit`

- [ ] **Step 0: Enable the WSL2 backend (needs admin + reboot — USER ACTION)**

Docker Desktop 4.85.0 is already installed at `%LOCALAPPDATA%\Programs\DockerDesktop` and the CLI works (`docker --version` → 29.6.2), but the **engine cannot start**: `Microsoft-Windows-Subsystem-Linux` and `VirtualMachinePlatform` are both disabled (`InstallState: 2`). Firmware virtualization *is* available (`HypervisorPresent: True`), so only the Windows features are missing.

In an **elevated** PowerShell:
```powershell
wsl --install
```
Then **reboot**. After the reboot, verify in a fresh shell:
```powershell
wsl --status
docker info --format '{{.ServerVersion}} {{.OSType}}'   # engine must respond
```
If `docker` is not found, the install added `%LOCALAPPDATA%\Programs\DockerDesktop\resources\bin` to the **User** PATH — open a new terminal so it is picked up.

- [ ] **Step 1: Fix `requires-python` and add ML dependencies**

`pyproject.toml` currently declares `requires-python = ">=3.9"`, which is **wrong** — `publisher.py` uses PEP 604 syntax (`timestamp: str | None = None`) in a runtime-evaluated signature, which raises `TypeError` on 3.9. Set it to match reality:

```toml
requires-python = ">=3.12"

[dependency-groups]
dev = [
    "pytest>=8.0.0",
]
ml = [
    "scikit-learn>=1.5",
    "pandas>=2.2",
    "joblib>=1.4",
    "jupyter>=1.1",
    "matplotlib>=3.9",
    "altair>=5.4",
]
```

The project is already a **virtual** uv project (`source = { virtual = "." }` in `uv.lock`), so `uv sync` needs no build backend. Regenerate the lock inside the container in Step 3.

- [ ] **Step 2: Write the `Dockerfile`**

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/simulator:/app

# Dependency layer: cached unless pyproject/uv.lock change
COPY pyproject.toml uv.lock ./
RUN uv sync --all-groups

COPY . .
```

`UV_PROJECT_ENVIRONMENT=/opt/venv` puts the venv **outside** `/app` so the bind-mount in Step 3 cannot shadow it — mounting the repo over `/app` would otherwise hide a `/app/.venv` and break every container. `PYTHONPATH` includes `simulator/` because the existing tests import `physics` and `publisher` as top-level modules.

**Why not `--frozen` yet:** the committed `uv.lock` was resolved against `requires-python = ">=3.9"` and has no `ml` group, so `--frozen` would fail the build on a lock/manifest mismatch. Step 8 regenerates the lock inside the container and then switches this line to `uv sync --frozen --all-groups`, which is what we actually want for reproducible builds.

`.dockerignore`:
```
.git
.venv
data/building_telemetry.csv
data/telemetry_raw/
report/
room3d/vendor/
**/__pycache__/
.pytest_cache/
```

- [ ] **Step 3: Extend `docker-compose.yml`**

Leave the `mosquitto` service exactly as it is. Add:

```yaml
services:
  mosquitto:
    # ... unchanged ...

  sim:
    build: .
    depends_on: [mosquitto]
    environment:
      MQTT_BROKER_HOST: mosquitto
    volumes:
      - .:/app
    command: python simulator/publisher.py

  dashboard:
    build: .
    depends_on: [mosquitto]
    environment:
      MQTT_BROKER_HOST: mosquitto
    ports:
      - "8501:8501"
    volumes:
      - .:/app
    command: >
      streamlit run dashboard/streamlit_app.py
      --server.address=0.0.0.0 --server.port=8501

  room3d:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - .:/app
    command: python -m http.server 8000 --directory room3d

  jupyter:
    build: .
    profiles: ["ml"]          # opt-in: `docker compose --profile ml up -d jupyter`
    ports:
      - "127.0.0.1:8888:8888"
    volumes:
      - .:/app
    command: >
      jupyter lab --ip=0.0.0.0 --port=8888 --no-browser
      --allow-root --NotebookApp.token=''
```

Notes that will otherwise cost debugging time:
- `--server.address=0.0.0.0` is mandatory; Streamlit binds loopback by default and the published port would connect to nothing.
- Until Task 9 creates `dashboard/streamlit_app.py`, point the `dashboard` command at the existing `dashboard/app.py`.
- `jupyter` runs tokenless, so its port is bound to `127.0.0.1` explicitly and it sits behind an opt-in profile — it does not start with `docker compose up`. A tokenless notebook server reachable on a LAN is remote code execution for anyone on that network; record it in `docs/governance.md` as a known pilot-posture weakness alongside the anonymous broker.

- [ ] **Step 4: Make the broker host configurable**

In `simulator/publisher.py` and `dashboard/app.py`, replace the hard-coded constant:

```python
import os
BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "localhost")
```

The `localhost` default preserves host-side and Project-1 behaviour. **Do not** touch `ws://localhost:9001` in `room3d/room3d.html` or the `st.iframe` URL — those are evaluated by the browser, where `localhost` is correct.

- [ ] **Step 5: Repair the Streamlit skill link (platform-independent)**

A symlink into a venv cannot survive a cross-platform repo. Delete both symlinks and replace each with a real directory containing a pointer file, so the repo stops carrying a broken link:

`.agents/skills/developing-with-streamlit/SKILL_LOCATION.md`:
```markdown
# developing-with-streamlit

This skill ships inside the installed `streamlit` package. Resolve it inside the container:

    docker compose run --rm sim python -c "import streamlit,pathlib;print(pathlib.Path(streamlit.__file__).parent/'.agents'/'skills'/'developing-with-streamlit')"

Read `SKILL.md` there, then follow its routing table into `references/`.
Rules that bind this repo's dashboard code: prefer native Streamlit elements over
CSS injection; `st.navigation` + `st.Page` + `app_pages/` for multipage;
`width="stretch"` (never `use_container_width`); `st.iframe` (never
`st.components.v1.*`); `st.cache_resource` for the MQTT client and the ML model.
```

Mirror the identical file into `.claude/skills/developing-with-streamlit/`.

- [ ] **Step 6: Add generated artifacts to `.gitignore`**

```
data/building_telemetry.csv
data/telemetry_raw/
ml/notebooks/.ipynb_checkpoints/
.venv/
```

- [ ] **Step 7: Verify the Project-1 baseline passes inside Docker**

```powershell
docker compose build
docker compose up -d mosquitto
docker compose run --rm sim pytest -v      # expect 38 passed
docker compose up -d sim dashboard room3d
```

Then confirm end to end: the dashboard at `http://localhost:8501` shows live telemetry, and `docker compose logs sim` shows the publish loop. **This is the gate for the whole plan — if 38 tests do not pass here, stop and fix before Task 1.**

- [ ] **Step 8: Regenerate the lockfile, then freeze the build**

The lock must be re-resolved for `requires-python = ">=3.12"` and the new `ml` group. Do it in-container (the repo is bind-mounted, so the updated lock lands in the working tree):

```powershell
docker compose run --rm sim uv lock
```

Then change the Dockerfile's `RUN uv sync --all-groups` to `RUN uv sync --frozen --all-groups`, rebuild, and re-run the tests to confirm the frozen lock resolves cleanly:

```powershell
docker compose build --no-cache sim
docker compose run --rm sim pytest -v      # still 38 passed
```

- [ ] **Step 9: Commit**

```powershell
git add Dockerfile .dockerignore docker-compose.yml pyproject.toml uv.lock .gitignore .agents .claude simulator/publisher.py dashboard/app.py
git commit -m "chore: dockerize full stack, add ml deps, fix broken streamlit skill symlink"
```

---

## Task 1: Building layout dataset + config module — TDD

**Files:**
- Create: `data/building_layout.json`
- Create: `simulator/building.py`
- Test: `simulator/tests/test_building.py`

**Interfaces:**
- Produces: `RoomConfig` (dataclass: `twin_id, floor, room_id, name, area_m2, volume_m3, max_occupancy, heat_capacity, base_equipment_w, insulation_k, neighbours: list[str], solar_gain`), `FloorConfig` (`floor_id, name, rooms, power_budget_kw`), `BuildingConfig` (`floors, outdoor_profile`), and loaders `load_building(path) -> BuildingConfig`, `BuildingConfig.room(twin_id) -> RoomConfig`, `BuildingConfig.all_rooms() -> list[RoomConfig]`.
- Consumed by: every subsequent simulator task, the dataset generator, the dashboard, and the 3D view (which fetches the same JSON so geometry never drifts from physics).

**Design note — "find or generate a dataset":** `data/building_layout.json` *is* the building dataset. It is a machine-readable facility description (floors, rooms, geometry, thermal constants, adjacency graph, occupancy schedules) authored from typical university-lab values, and it is the single source of truth consumed by the simulator, the dashboard, and the 3D renderer alike. The *telemetry* dataset is generated from it in Task 6; the *failure-mode calibration* comes from the real UCI AI4I 2020 dataset in Task 2.

- [ ] **Step 1: Write `data/building_layout.json`**

Schema (abbreviated — fill all 6 rooms per the layout table above):

```json
{
  "building": {
    "name": "Engineering Building B",
    "outdoor": {"base_temp_c": 32.0, "diurnal_amplitude_c": 4.0},
    "power_budget_kw": 40.0
  },
  "floors": [
    {
      "floor_id": "f1",
      "name": "Ground Floor",
      "power_budget_kw": 22.0,
      "solar_gain": 0.6,
      "rooms": [
        {
          "room_id": "lab-a", "name": "Wet Lab A",
          "area_m2": 60, "height_m": 3.2, "max_occupancy": 30,
          "heat_capacity_j_per_c": 25000, "base_equipment_w": 400,
          "insulation_k": 0.05, "neighbours": ["f1/lab-b", "f1/corridor"],
          "occupancy_profile": "class_schedule",
          "hvac": {"max_power_w": 3500, "base_rpm": 1500}
        }
      ]
    }
  ]
}
```

Key constraint: `f1/lab-a` must keep Project-1's exact constants (`heat_capacity_j_per_c: 25000`, `max_power_w: 3500`, `insulation_k: 0.05`, `max_occupancy: 30`) so the migrated Project-1 physics tests still pass unchanged in Task 3.

- [ ] **Step 2: Write failing tests**

`simulator/tests/test_building.py` must assert:
- `load_building()` returns 2 floors and 6 rooms total.
- `room("f1/lab-a")` returns Project-1's constants exactly (this is the regression guard).
- Every `neighbours` entry resolves to a real twin_id or a corridor node — **no dangling adjacency**.
- Adjacency is symmetric: if A lists B, B lists A.
- `volume_m3 == area_m2 * height_m`.
- `sum(floor.power_budget_kw) <= building.power_budget_kw` is *false* by design (floors are over-subscribed → the building twin must arbitrate). Assert the over-subscription explicitly so the arbitration in Task 5 has a reason to exist.
- Unknown `twin_id` raises `KeyError`, not `None`.

- [ ] **Step 3: Implement `simulator/building.py`, run tests to green**

- [ ] **Step 4: Commit** — `feat: building layout dataset + config loader for 2 floors x 3 rooms`

---

## Task 2: HVAC equipment health model, calibrated to UCI AI4I 2020 — TDD

**Files:**
- Create: `data/ai4i2020.csv` (downloaded, 10,000 rows, committed — 510 KB, CC BY 4.0)
- Create: `data/README.md` (dataset provenance + licence + citation)
- Create: `simulator/hvac_health.py`
- Test: `simulator/tests/test_hvac_health.py`

**Interfaces:**
- Produces: `HVACHealth` (dataclass: `filter_clog, bearing_wear, motor_temp, fan_rpm, vibration_mm_s, runtime_hours, power_draw_w`), `step_health(health, ac_power_pct, occupancy, room_temp, dt) -> HVACHealth`, `failure_flags(health) -> dict[str, bool]` returning `{"hdf","pwf","osf","bearing"}`, `apply_maintenance(health, action) -> HVACHealth`.
- Consumed by: Task 3 (room twin), Task 6 (dataset generator labels), Task 7 (feature spec).

**Calibration source (verified):** UCI AI4I 2020 Predictive Maintenance Dataset — 10,000 rows, 3.39 % failure rate, columns `Air temperature [K], Process temperature [K], Rotational speed [rpm], Torque [Nm], Tool wear [min], Machine failure, TWF, HDF, PWF, OSF, RNF`. Its documented failure rules map onto our fan motor one-to-one:

| AI4I rule | AI4I condition | Our HVAC analogue |
|---|---|---|
| **HDF** — heat dissipation failure | (process_temp − air_temp) < 8.6 K **and** rpm < 1380 | motor can't shed heat into room air: `(motor_temp − room_temp) < 8.6` while `fan_rpm < 1380` → **fan motor overheating** |
| **PWF** — power failure | torque × ω outside [3500, 9000] W | `power_draw_w` outside the unit's rated band (clogged filter drives it up; a seized fan drives it down) |
| **OSF** — overstrain failure | tool_wear × torque > 11 000 min·Nm | `runtime_hours × torque` past the bearing's rated duty |
| **TWF** — tool wear failure | wear ∈ [200, 240] min | `filter_clog > 0.85` → airflow failure |

Document this mapping in `data/README.md`. It converts "we made up some thresholds" into "our thresholds are the published failure physics of a real predictive-maintenance dataset, rescaled to HVAC units" — which is what the brief's *Predictive Intelligence* task is really asking for.

- [ ] **Step 1: Download AI4I and write provenance**

```powershell
docker compose run --rm sim python -c "import urllib.request,zipfile,io; z=zipfile.ZipFile(io.BytesIO(urllib.request.urlopen('https://archive.ics.uci.edu/static/public/601/ai4i+2020+predictive+maintenance+dataset.zip').read())); z.extract('ai4i2020.csv','data')"
```

(The repo is bind-mounted at `/app`, so the extracted file lands in your working tree.)
Verify: 10 001 lines (header + 10 000 rows), `Machine failure` sums to 339.

- [ ] **Step 2: Write failing tests** — `simulator/tests/test_hvac_health.py`

Lock these behaviours (they are the physical claims the report will make):
- A clean filter under normal duty holds `motor_temp` below 70 °C indefinitely (steady state exists — no runaway on healthy hardware).
- `filter_clog` accumulates monotonically with runtime and faster at high occupancy; it never exceeds 1.0.
- As `filter_clog` rises from 0 → 0.8, `fan_rpm` rises and `power_draw_w` rises (fan law) — the ROI hook.
- **Overheating reproduces:** starting from `filter_clog=0.9, bearing_wear=0.7` at full duty, `motor_temp` crosses 85 °C within simulated 30 min and `failure_flags()["hdf"]` becomes True.
- `failure_flags()` is False on a brand-new unit at every duty level (no false alarms on healthy hardware).
- `apply_maintenance(h, "replace_filter")` zeroes `filter_clog` but leaves `bearing_wear` untouched; `"service_motor"` zeroes `bearing_wear` and `runtime_hours` but not `filter_clog`.
- `vibration_mm_s` is monotone in `bearing_wear` and crosses the ISO 10816 7.1 mm/s alarm band before bearing failure trips (the alarm must lead the failure, otherwise there is nothing to predict).
- Health evolution is deterministic given the same inputs (no hidden RNG).

- [ ] **Step 3: Implement `simulator/hvac_health.py`, run tests to green**

Constants to expose at module level so the report can cite them: `CLOG_RATE_PER_HOUR`, `CLOG_RPM_GAIN`, `BASE_RPM`, `MOTOR_THERMAL_MASS`, `MOTOR_TEMP_ALARM = 85.0`, `VIBRATION_ALARM = 7.1`, `HDF_DELTA_K = 8.6`, `HDF_RPM_MIN = 1380`, `PWF_MIN_W`, `PWF_MAX_W`, `OSF_LIMIT`.

- [ ] **Step 4: Commit** — `feat: hvac degradation model calibrated to UCI AI4I 2020 failure rules`

---

## Task 3: Room twin refactor — 6 autonomous room twins — TDD

**Files:**
- Modify: `simulator/physics.py` (parameterise by `RoomConfig`, add inter-room coupling)
- Create: `simulator/room_twin.py`
- Modify: `simulator/publisher.py` (becomes the multi-twin orchestrator)
- Modify: `simulator/tests/test_physics.py`, `test_publisher.py` (migrate topics; keep physical assertions)
- Test: `simulator/tests/test_room_twin.py`

**Interfaces:**
- Consumes: `building.RoomConfig`, `physics.step_*`, `pid_controller.PIDController`, `hvac_health.step_health`.
- Produces: `RoomTwin` with `.state: RoomState`, `.health: HVACHealth`, `.config: RoomConfig`, `.tick(dt, neighbour_temps: dict[str, float]) -> None`, `.handle_command(topic, payload) -> None`, `.telemetry() -> dict`, and `.topic(suffix) -> str`.

**Migration rule for the 38 existing tests:** every physical assertion survives verbatim; only the room being asserted about changes (`RoomState()` → `RoomTwin(config=building.room("f1/lab-a"))`) and topic strings gain the `f1/lab-a` prefix. If a Project-1 assertion breaks, the physics regressed — fix the physics, do not weaken the test.

- [ ] **Step 1: Extend `physics.py` with inter-room thermal coupling**

Add `q_neighbours = Σ COUPLING_K * (T_neighbour − T_room)` to `step_temperature`, and move the per-room constants (`ROOM_HEAT_CAPACITY`, `AC_POWER_W`, `WALL_K`) from module globals onto `RoomConfig`. Keep module-level defaults equal to Project-1's values so a `RoomTwin` built from `f1/lab-a` behaves identically to Project 1.

New tests to add:
- With coupling, a hot neighbour warms a cool room, and the pair converges (energy flows the right way, no runaway).
- Coupling is antisymmetric: heat A gains from B equals heat B loses to A (conservation).
- `COUPLING_K = 0` reproduces Project-1 numbers exactly (**the regression guard for the whole refactor**).

- [ ] **Step 2: Write failing `test_room_twin.py`**

- Six twins built from the layout each run independently; a command to `f1/lab-a` does not alter `f2/office`'s state (**isolation** — the core federated claim).
- The server room's PID holds setpoint under its constant 4 kW IT load with zero occupancy (proves `base_equipment_w` is wired in, and that `auto_hvac_decision`'s "empty room → off" rule is correctly overridden for always-on rooms).
- A room twin keeps running its PID when no floor/building twin exists (**graceful degradation**).
- `telemetry()` contains every field the ML feature spec requires (assert against an explicit field list, so Task 7's feature contract cannot silently drift).
- `cmd/maintenance` with `replace_filter` resets clog and is idempotent.

- [ ] **Step 3: Implement `room_twin.py`; migrate `test_physics.py` and `test_publisher.py`**

- [ ] **Step 4: Rewrite `publisher.py` as the orchestrator**

Single process, single MQTT client, one loop. Per tick: gather all room temps → for each twin call `tick(dt, neighbour_temps)` → publish due sensors on each twin's own topics. Subscribe `twin/+/+/cmd/#` and dispatch by parsing `{floor}/{room}` out of the topic. LWT on `twin/building/status`.

- [ ] **Step 5: Manual verification**

```powershell
docker compose up -d mosquitto sim
docker compose logs -f sim
# in another shell:
docker exec mosquitto mosquitto_sub -t 'twin/#' -v -C 30
docker exec mosquitto mosquitto_pub -t twin/f1/lab-a/cmd/occupancy -m '{\"value\": 28}'
```
Expected: 6 rooms publishing on distinct topics; forcing lab-a hot visibly warms `f1/lab-b` (its neighbour) but not `f2/office`.

- [ ] **Step 6: Commit** — `feat: six autonomous room twins with inter-room thermal coupling`

---

## Task 4: Occupancy twin — people flow between rooms — TDD

**Files:**
- Create: `simulator/occupancy_twin.py`
- Test: `simulator/tests/test_occupancy_twin.py`

**Interfaces:**
- Produces: `OccupancyTwin(building, rng)` with `.step(sim_time, dt) -> dict[twin_id, int]` and `.total_in_building`.
- Consumed by: Task 3's orchestrator (replaces each room's independent `step_occupancy` random walk).

**Why this exists:** the brief names "an energy twin interacting with an occupancy twin" as the example of ecosystem integration. Project 1's per-room random walk is not a twin — it's noise. A real occupancy twin conserves people: they *move between* rooms through the corridor, so lab-a emptying causes meeting-room to fill. That coupling is what makes the ecosystem diagram truthful.

- [ ] **Step 1: Write failing tests**

- **Conservation:** total people in the building only changes at entrances/exits; interior movement conserves headcount exactly.
- No room ever exceeds its `max_occupancy`.
- Occupancy is never negative.
- Schedule-driven: `class_schedule` rooms fill at class start and empty at class end; `steady_daytime` rooms hold a plateau; the server room stays ≈ 0.
- Deterministic under a seeded `random.Random` (same seed → same trace) — **required for the reproducible dataset in Task 6**.
- Movement respects adjacency: nobody teleports between floors without transiting a corridor/stair node.

- [ ] **Step 2: Implement, run tests to green**

- [ ] **Step 3: Wire into the orchestrator** — room twins now receive occupancy from the occupancy twin, and publish it as before. Update `test_room_twin.py` for the new source.

- [ ] **Step 4: Commit** — `feat: occupancy twin with headcount-conserving inter-room people flow`

---

## Task 5: Floor twins + building twin — federated coordination — TDD

**Files:**
- Create: `simulator/floor_twin.py`, `simulator/building_twin.py`
- Test: `simulator/tests/test_floor_twin.py`, `simulator/tests/test_building_twin.py`
- Modify: `simulator/publisher.py`

**Interfaces:**
- `FloorTwin(floor_config)`: `.aggregate(room_twins) -> dict` (total kW, mean temp, peak risk, occupancy), `.arbitrate(room_twins, budget_kw) -> dict[twin_id, float]` returning **setpoint nudges**, never direct power commands.
- `BuildingTwin(building_config)`: `.allocate_budgets(floor_summaries) -> dict[floor_id, float]`, `.advisories(risk_scores) -> list[dict]`.

- [ ] **Step 1: Write failing tests**

`test_floor_twin.py`:
- Under budget, `arbitrate` returns **no** nudges (supervisors stay silent when unneeded — this is what makes them federated rather than centralized).
- Over budget, total predicted draw after nudges is within the cap.
- Nudges are bounded (`|Δsetpoint| ≤ 1.5 °C`) — a supervisor can never make a room unsafe.
- The server room is **exempt** from load shedding (critical load priority).
- Arbitration is fair: under sustained scarcity, no single room absorbs every nudge (assert nudge variance across rooms stays bounded). This is the *distributional fairness* claim the ethics doc will make — the same fairness concern the ML bias audit covers, on the control side.

`test_building_twin.py`:
- Floor budgets sum to ≤ building budget even though the floors' declared budgets over-subscribe it (Task 1 Step 2 asserted the over-subscription; here it gets resolved).
- A high ML risk score produces exactly one work-order advisory, and repeated identical scores do not spam duplicates (dedupe by twin + fault type).
- With all room twins removed, the building twin degrades to publishing an empty summary rather than crashing.

- [ ] **Step 2: Implement both twins, run tests to green**

- [ ] **Step 3: Wire into orchestrator** at their own cadences (floor 10 s, building 30 s), publish `twin/{floor}/summary`, `twin/building/summary`, `twin/building/advisory`.

- [ ] **Step 4: Commit** — `feat: federated floor + building twins with bounded setpoint arbitration`

---

## Task 6: Telemetry dataset generator

**Files:**
- Create: `simulator/dataset_generator.py`
- Create: `data/README.md` (extend with the generated-dataset schema)
- Test: `simulator/tests/test_dataset_generator.py`

**Interfaces:**
- Produces: `data/building_telemetry.csv` — one row per room per simulated minute.
- CLI: `docker compose run --rm sim python simulator/dataset_generator.py --days 90 --seed 42 --out data/building_telemetry.csv`

**Design:** runs the full twin ecosystem headless with no MQTT and no sleeping, at high `dt`, seeded. Degradation is accelerated so 90 simulated days contain enough failure events to train on. Each room gets a different maintenance discipline (lab-a serviced on schedule, meeting-room neglected) so the dataset contains both healthy and run-to-failure trajectories — **and so the bias audit in Task 7 has real per-room distribution shift to detect.**

Columns:
```
timestamp, twin_id, floor, room_type, occupancy, room_temp, humidity, setpoint,
hvac_on, ac_power_pct, motor_temp, fan_rpm, vibration_mm_s, filter_clog,
power_draw_w, runtime_hours, outdoor_temp,
label_failure_within_30min, label_failure_type, label_rul_hours
```

- [ ] **Step 1: Write failing tests**

- Same seed → byte-identical CSV (**reproducibility**).
- Failure rate lands in 2–8 % of rows (comparable to AI4I's 3.39 %; if it's 0 % or 40 %, the degradation constants are wrong and the ML task is meaningless).
- Every `label_failure_within_30min == 1` row has a failure event within the next 30 min for that same `twin_id` (**label correctness — verify by construction, not by trust**).
- `label_rul_hours` is monotonically decreasing within a run-to-failure segment and resets at maintenance.
- All 6 twin_ids present; no NaNs; no negative RUL.
- A short `--days 1` run completes in under 60 s (keeps the test suite fast; the full 90-day run is a manual step).

- [ ] **Step 2: Implement generator, run tests to green**

- [ ] **Step 3: Generate the full dataset and record its statistics in `data/README.md`**

```powershell
docker compose run --rm sim python simulator/dataset_generator.py --days 90 --seed 42 --out data/building_telemetry.csv
```
Record: row count, failure rate, per-room failure counts, date span. (CSV is gitignored; the README statistics are committed so results are auditable.)

- [ ] **Step 4: Commit** — `feat: reproducible labeled telemetry dataset generator`

---

## Task 7: Predictive model notebooks

**Files:**
- Create: `ml/notebooks/01_data_exploration.ipynb`
- Create: `ml/notebooks/02_failure_prediction.ipynb`
- Create: `ml/features.py` (shared feature engineering — imported by the notebook **and** by Task 8's live inference)
- Create: `ml/models/failure_classifier.joblib`, `ml/models/rul_regressor.joblib`, `ml/models/feature_spec.json`, `ml/models/model_card.md`
- Test: `simulator/tests/test_features.py`

**Interfaces:**
- `ml/features.py` produces `FEATURE_COLUMNS: list[str]`, `build_features(df) -> DataFrame`, `build_features_live(history: deque) -> np.ndarray`.
- **Critical:** both notebooks and the live scorer call the *same* `build_features`. Training/serving skew is the classic failure here — a test asserts the two paths agree on identical input.

- [ ] **Step 1: `01_data_exploration.ipynb` — the real dataset first**

Load `data/ai4i2020.csv`. Show: 10 000 rows, 3.39 % failure rate, class imbalance, per-failure-mode counts (TWF 46, HDF 115, PWF 95, OSF 98), and reproduce the documented HDF rule from the raw columns to prove the rule is real. Then load `data/building_telemetry.csv` and put the two side by side, showing the mapping table from Task 2. This notebook's job is to justify the thresholds, not to train anything.

- [ ] **Step 2: `ml/features.py` + its test**

Rolling-window features per twin: `motor_temp` mean/max/slope over 5/15/30 min, `vibration` slope, `filter_clog` rate, `duty_cycle` fraction, `motor_room_delta` (= motor_temp − room_temp, the HDF driver), `power_per_rpm`. Plus statics: `room_type`, `floor`.

Test: `build_features` and `build_features_live` return identical vectors for the same 30-minute window (**guards training/serving skew**); rolling windows never look ahead (**no future leakage** — assert that a row's features are unchanged when all later rows are deleted).

- [ ] **Step 3: `02_failure_prediction.ipynb` — split, train, compare**

- **Split by time and room**: train on days 0–60, test on days 61–90; additionally hold out `f2/meeting-room` entirely as an unseen-room generalisation check. Never `train_test_split(shuffle=True)`.
- Models: (a) Logistic Regression baseline — interpretable, satisfies the brief's "linear regression"; (b) Random Forest; (c) Gradient Boosting. Plus a **trivial baseline** (`motor_temp > 80`) — if the ML model can't beat a single threshold, say so in the model card rather than hiding it.
- Metrics for imbalance: PR-AUC (primary), ROC-AUC, recall at 90 % precision, confusion matrix. **Accuracy is not reported as a headline** — 96 % accuracy is what you get by predicting "no failure" always, and the report must say this explicitly.
- Cost analysis: false negative = unplanned outage; false positive = unnecessary truck roll. Pick the decision threshold from the cost curve, not from 0.5. This threshold is the input to the ROI numbers in Task 11.

- [ ] **Step 4: RUL regressor**

Linear regression on `label_rul_hours` for rows in a degradation segment. Report MAE in hours and a predicted-vs-actual plot. This drives the dashboard's "filter change due in ~42 h".

- [ ] **Step 5: Explainability (→ Governance deliverable)**

Permutation importance + logistic-regression coefficients with signs. Produce a plain-language sentence per top feature ("rising motor-to-room temperature gap is the strongest predictor, consistent with the AI4I heat-dissipation rule"). Save the plot to `report/assets/`.

- [ ] **Step 6: Bias / fairness audit (→ Ethics deliverable)**

Report PR-AUC, recall, and false-negative rate **per room and per floor**. The generator deliberately gave rooms different maintenance discipline and duty cycles, so expect real disparity — likely worse recall on the server room (rare failures, constant duty) and on the held-out meeting room. Write up: what disparity was found, why it arises (training distribution skew, not malice), what it would cost the under-served room, and the mitigation (per-room threshold calibration, or reweighting). **A finding of "no disparity" must be justified, not assumed.**

- [ ] **Step 7: Export models + `model_card.md`**

Model card sections: intended use, training data + its synthetic provenance and AI4I calibration, metrics with the split described, **known limitations (trained on simulated data — real deployment requires recalibration on ≥ 3 months of real telemetry before any autonomous action)**, the fairness audit results, decision threshold and its cost rationale, and the human-in-the-loop requirement (model raises work orders; it never shuts down equipment).

- [ ] **Step 8: Commit** — `feat: failure-prediction and RUL models with fairness audit and model card`

---

## Task 8: Live inference wired into the ecosystem

**Files:**
- Create: `simulator/ml_inference.py`
- Test: `simulator/tests/test_ml_inference.py`
- Modify: `simulator/publisher.py`

**Interfaces:**
- `RiskScorer(model_dir)`: `.score(twin_id, history) -> {"failure_prob", "rul_hours", "top_factor", "recommended_action", "model_version"}`.
- Publishes `twin/{floor}/{room}/health/risk` (retained) every 30 s; the building twin consumes these into work-order advisories (Task 5 already handles this).

- [ ] **Step 1: Write failing tests**

- Scorer loads the joblib and returns a probability in [0, 1].
- Insufficient history (< 30 min) returns `None` rather than a garbage score (**cold-start honesty**).
- Feeding a known run-to-failure window from the test dataset yields `failure_prob` above the chosen threshold; a healthy window yields below it.
- **Missing model file degrades gracefully:** the simulator keeps running with risk reporting disabled and logs a warning — a broken model must never stop the cooling.
- Output payload contains `model_version`, so a dashboard reading a stale retained message can tell.

- [ ] **Step 2: Implement, run tests to green**

- [ ] **Step 3: Manual verification** — accelerate degradation on one room (`x10` timescale), watch `twin/f2/meeting-room/health/risk` climb, then `twin/building/advisory` emit a work order, then publish `cmd/maintenance` and watch risk fall.

- [ ] **Step 4: Commit** — `feat: live ML risk scoring published per room and consumed by building twin`

---

## Task 9: Multipage dashboard rebuild

> **Read the `developing-with-streamlit` skill first** (Task 0 Step 3 gives the resolution command), specifically `references/multipage-apps.md`, `references/dashboards.md`, and `references/layouts.md`.

**Files:**
- Create: `dashboard/streamlit_app.py` (entry point, `st.navigation`)
- Create: `dashboard/lib/mqtt_client.py` (single cached client + store, shared by all pages)
- Create: `dashboard/app_pages/building_overview.py`, `room_detail.py`, `predictive_maintenance.py`, `ecosystem.py`
- Delete: `dashboard/app.py` (superseded)

**Skill-mandated conventions** (Project 1's `app.py` violates several; do not carry them forward):
- `st.navigation` + `st.Page` + `app_pages/`, not a `pages/` directory.
- Drop the CSS injection block — use `st.container(border=True)`, `st.container(horizontal=True)`, and `.streamlit/config.toml` for theming.
- `width="stretch"`, never `use_container_width`.
- `st.segmented_control` instead of `st.radio(horizontal=True)`.
- Material Symbols icons (`:material/hvac:`) over emoji.
- One `@st.cache_resource` MQTT client for the whole app; one `@st.cache_resource` model load.
- Vega charts (`st.line_chart` / `st.altair_chart`) preferred over Plotly. *(Deviation permitted for the temperature chart if the existing Plotly setpoint/limit `add_hline` annotations prove hard to reproduce in Altair — if kept, note it as a conscious deviation in the commit message.)*

- [ ] **Step 1: `dashboard/lib/mqtt_client.py`** — cached client subscribing `twin/#`, store keyed by twin_id with per-room deques, one lock. Verify with `docker logs mosquitto` that navigating between pages does **not** create new connections.

- [ ] **Step 2: `building_overview.py`** — the money shot. Floor-by-floor grid of 6 room cards (temp, occupancy, AC power, risk badge), building KPI row (total kW vs budget, people in building, rooms at risk), and the 3D building view.

- [ ] **Step 3: `room_detail.py`** — room selector, then Project 1's full single-room experience (metrics, controls, trend chart, predictive alert) plus the health panel (motor temp, vibration, filter clog gauges) and a maintenance button.

- [ ] **Step 4: `predictive_maintenance.py`** — ranked risk table across all 6 rooms, RUL countdown per unit, top contributing factor per room, open work orders from `twin/building/advisory`, and a link to the model card. Include the model's stated limitations **in the UI**, not just in the docs — a dashboard that shows a probability without its provenance is exactly the transparency failure the ethics section is about.

- [ ] **Step 5: `ecosystem.py`** — live view of the federated hierarchy: which floor is over budget, what nudges are active, the coordination diagram, and message-flow counters.

- [ ] **Step 6: Manual verification, then commit** — `feat: multipage dashboard for 6-room building with predictive maintenance`

---

## Task 10: Multi-floor 3D building view

**Files:**
- Create: `room3d/building3d.html`
- Keep: `room3d/room3d.html` (single-room view, still linked from room detail)
- Reuse: `room3d/vendor/three.module.js`, `mqtt.min.js`

- [ ] **Step 1: Build the scene from `data/building_layout.json`** — fetch the same JSON the simulator uses, so geometry can never drift from physics. Two floor slabs (floor 2 raised and slightly offset for visibility), 3 rooms per slab, shared corridor, stairwell.

- [ ] **Step 2: Live bindings over WebSocket MQTT (port 9001)** — subscribe `twin/#`; floor colour per room lerps by temperature as in Project 1; people capsules per room from the occupancy twin; AC fan spins at a rate proportional to `ac_power_pct`; **a room with `failure_prob` over threshold pulses an amber warning halo** — this is the visual payoff of the ML work.

- [ ] **Step 3: Camera + interaction** — orbit, plus a floor-isolate toggle so floor 1 can be inspected without floor 2 occluding it.

- [ ] **Step 4: Serve, verify against a live sim, embed in `building_overview.py` via `st.iframe`, commit** — `feat: multi-floor 3d building view with live risk highlighting`

---

## Task 11: Ecosystem, governance, and roadmap documentation

**Files:**
- Modify: `docs/architecture.md`
- Create: `docs/ecosystem.md`, `docs/governance.md`, `docs/roi_roadmap.md`

- [ ] **Step 1: `docs/ecosystem.md` — Integrated Ecosystem Diagram deliverable**

Contents:
1. Twin inventory: 6 room twins, 2 floor twins, 1 building twin, 1 occupancy twin, 1 energy twin, 1 maintenance twin — with each one's state, inputs, outputs, and loop rate.
2. **Mermaid data-flow diagram** showing the actual topics between them (the occupancy twin → room twins → energy twin path the brief asks for by name).
3. **Centralized vs. federated comparison table**: single point of failure, latency, scalability to N rooms, data minimisation, and failure blast radius. State the decision (federated + hierarchical supervision) and the evidence from our own tests: Task 3's isolation test and Task 5's degradation test are the proof that the architecture behaves as claimed.
4. Sequence diagram of one full closed loop: occupancy spike → room PID → floor budget breach → building reallocation → setpoint nudge → resolution.
5. Mermaid line-break note: use `<br/>`, never a literal `\n` (this bit us in Project 1).

- [ ] **Step 2: `docs/governance.md` — Governance & Ethics deliverable**

- **Cybersecurity:** the honest starting position is that the current broker is `allow_anonymous true` with no TLS — state that plainly as the *pilot* posture, then specify the production hardening: per-twin client certificates (mTLS), per-topic ACLs so a room twin can publish only its own subtree, TLS on 8883/WSS, signed command payloads to stop a spoofed `cmd/hvac`, rate limiting, and an audit log of every command with its origin. Include a small threat model: spoofed sensor readings, command injection, occupancy data exfiltration, model poisoning via tampered telemetry, and denial of service on the broker.
- **Algorithmic transparency:** the model card, the per-feature explanations from Task 7 Step 5, the model version stamped on every risk message, and the rule that the dashboard always shows *why* a room is flagged.
- **Bias mitigation:** the Task 7 Step 6 audit results, with the per-room disparity quantified and the mitigation stated.
- **Human-in-the-loop:** the model opens work orders; a human approves anything that shuts equipment down. Autonomy is bounded — supervisors nudge setpoints by at most 1.5 °C (Task 5's test enforces this), so no software decision can make a room unsafe.
- **Privacy:** occupancy counts are personal-adjacent data. Rooms publish counts, never identities; floor/building twins receive aggregates only; retention limits stated.

- [ ] **Step 3: `docs/roi_roadmap.md` — Strategic Roadmap deliverable**

- **ROI model with stated assumptions** (every figure carries its source or its assumption — an unsourced number is worse than no number):
  - Energy: measured kW saved from the clogged-filter power penalty our own physics produces × tariff × hours.
  - Avoided downtime: failures caught early × cost per unplanned HVAC outage (lab equipment at risk in a wet lab).
  - Maintenance shift: calendar-based → condition-based servicing; fewer unnecessary filter changes.
  - Costs: hardware, integration, and the recurring cost of running and *recalibrating* the model.
  - Output: payback period and 3-year NPV, plus a sensitivity table — and an explicit statement that these are modelled on simulated data and need real-building validation.
- **Roadmap:** Phase 0 pilot (this build, 1 floor) → Phase 1 (full building, real sensors, model recalibration) → Phase 2 (campus multi-building, federated learning across buildings) → Phase 3 (autonomous optimisation), each with entry criteria, exit criteria, and a named risk.

- [ ] **Step 4: Update `docs/architecture.md`** — expand the 6-layer diagram to show the twin hierarchy and the ML layer; keep the Project-1 MQTT and PID rationale (still valid); add a "what changed in Project 2" section.

- [ ] **Step 5: Commit** — `docs: ecosystem, governance, and roi roadmap for intelligent ecosystem`

---

## Task 12: Executive pitch

**Files:**
- Create: `report/pitch/pitch_outline.md` (content, speaker notes, and the numbers)
- Create: `report/pitch/build_pitch.py` (generates `.pptx` via `python-pptx`) **or** an HTML artifact — decide at Step 2
- Create: `report/assets/` figures exported from Task 7

**Audience:** executives. Business value, security, ethical safety — not architecture.

- [ ] **Step 1: Write `pitch_outline.md`** — roughly 12 slides: problem/cost of the status quo → what we built (one ecosystem diagram) → the intelligence (failure prediction, with honest metrics) → live demo screenshots → ROI and payback → security posture → ethics and human-in-the-loop → roadmap and the ask. Every number traces to Task 11.

- [ ] **Step 2: Choose the output format** — `python-pptx` matches Project 1's `.pptx` deliverable and is editable by the user; an HTML artifact looks better but may not match submission requirements. **Ask the user before building.**

- [ ] **Step 3: Capture fresh demo screenshots** of the 6-room dashboard, the risk page, and the 3D building into `report/demo/` (Project 1's screenshots stay — they document Project 1).

- [ ] **Step 4: Build the deck, review it end to end, commit** — `docs: executive pitch deck for intelligent ecosystem`

---

## Task 13: Final integration + README

**Files:**
- Modify: `README.md`
- Create: `docs/demo_script_project2.md`

- [ ] **Step 1: Full-system run from a clean clone** — `git clone` into a fresh directory and run `docker compose up` following the README literally, with no host Python and no pre-built images. Anything that doesn't work as written is a README bug, not a user error.

- [ ] **Step 2: Update `README.md`** — new architecture summary, the full topic table for 6 rooms, ML pipeline instructions (generate dataset → run notebooks in the `jupyter` service → models land in `ml/models/`), and a link to each Project-2 doc. The run sequence collapses from Project 1's four terminals to:

```powershell
docker compose up -d          # mosquitto + sim + dashboard + room3d
# dashboard  http://localhost:8501
# 3D view    http://localhost:8000/building3d.html
docker compose --profile ml up -d jupyter   # notebooks at http://localhost:8888
```

Keep Project 1's host-Python instructions in a collapsed "running without Docker" section — the `MQTT_BROKER_HOST` default keeps that path working, and it costs nothing to document.

- [ ] **Step 3: Write the Project-2 demo script** — the narrative for the video: occupancy surge → federated arbitration → degradation acceleration → ML predicts overheating → work order → maintenance → risk clears.

- [ ] **Step 4: Full test suite + final commit**

```powershell
docker compose run --rm sim pytest -v      # every test from Projects 1 and 2
```

Then open a PR from `project-2-ecosystem` into `main`.

---

## Risks and how this plan handles them

| Risk | Mitigation |
|---|---|
| **The ML model is trained on data we generated ourselves — circular reasoning.** | Failure thresholds come from the real AI4I 2020 dataset's published rules (Task 2), not from us. The model card states the limitation outright (Task 7 Step 7) and the roadmap makes real-telemetry recalibration a Phase-1 entry criterion. This is the single most likely thing an examiner probes — meeting it head-on is stronger than hiding it. |
| Random train/test split inflates scores to a meaningless 0.99 | Split by time *and* by held-out room; leakage test in Task 7 Step 2. |
| Training/serving skew between notebook and live scorer | Both import the same `ml/features.py`; a test asserts the two paths agree (Task 7 Step 2). |
| Refactoring 6 rooms breaks Project-1 physics | `COUPLING_K = 0` regression test reproduces Project-1 numbers exactly (Task 3 Step 1); all 38 tests migrate rather than being rewritten. |
| Six twins + ML + 3D overload the 1 s loop | Tiered loop rates (room 1 s, floor 10 s, building 30 s, ML 30 s); measure before optimising. |
| Scope is large for the deadline | Tasks 1–9 are the graded core. Task 10 (3D) and Task 12 (deck) are the last-in items; if time runs short, the 3D view can stay single-room and the pitch can ship as markdown. |
| No Python on this machine | Task 0 dockerizes the whole stack; no host toolchain is ever needed. It is a hard blocker and runs first. |
| Containerization silently breaks MQTT connectivity (`localhost` ≠ broker inside a container) | Task 0 Step 4 moves the broker host to `MQTT_BROKER_HOST` **before** any service is containerized, and Step 7 gates the plan on 38 green tests plus a live dashboard. Browser-side URLs are explicitly excluded from the change. |
| Bind-mounting the repo over `/app` shadows the venv | `UV_PROJECT_ENVIRONMENT=/opt/venv` puts it outside the mount (Task 0 Step 2). |
| Project-1 work is lost or entangled with Project-2 changes | `main` stays pinned to `origin/main`; all work is on `project-2-ecosystem`. Project 1 remains reproducible from `main` alone. |

## Open questions for the user

- **Task 12 Step 2:** `.pptx` (matches Project 1, editable) or HTML artifact (better looking)? Defaults to `.pptx` if unanswered.
- Should the Project-1 demo video be re-recorded for the 6-room system, or does Project 2 get its own new recording? (Plan assumes: new recording, Project 1's is preserved.)
