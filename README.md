# Smart Lab Intelligent Ecosystem

A real-time **two-room Digital Twin ecosystem** for a smart laboratory. Each room has its own local PID comfort controller, while both share one finite-capacity AHU. The ecosystem predicts fan-health risk, models filter clogging, allocates scarce airflow transparently, and estimates energy impact.

> **Demo boundary:** all physics, energy, and predictive-risk data are simulated. The model is trained on reproducible synthetic scenarios and must be recalibrated before use with a real facility.

## What changed for Project 2

| Capability | Implementation |
|---|---|
| Multi-twin ecosystem | `room1` and `room2` have independent temperature, humidity, occupancy, PID, setpoint, and control mode. |
| Shared AHU | A finite supply-air capacity is allocated between both rooms rather than giving each room an independent AC plant. |
| Predictive intelligence | A versioned, interpretable logistic model estimates simulated fan-failure risk from filter clog, fan speed, vibration, bearing temperature, and runtime. |
| Coordinated autonomy | `occupied-comfort-v1` prioritises occupied rooms, then larger positive comfort error, then occupancy count. Each decision includes reason codes. |
| Equipment degradation | Filter clogging reduces available airflow and increases fan energy; fan wear changes vibration, bearing temperature, health, and risk. |
| Strategic metrics | The dashboard publishes estimated fan/cooling power, cumulative simulated kWh, tariff-based cost, health, risk drivers, and allocation outcomes. |

Read the detailed [ecosystem design](docs/intelligent-ecosystem.md), [architecture](docs/architecture.md), and [executive-pitch outline](docs/executive-pitch.md).

---

## Architecture at a glance

```text
Room 1 Twin ─┐                          ┌─> Fan Health + Risk Twin
             ├─> Shared AHU ─> Energy ──┤
Room 2 Twin ─┘        │                 └─> Coordinator Decision Log
                       └─> finite airflow allocation back to both rooms
```

- **Local safety / responsiveness:** each room’s existing PID remains responsible for generating its cooling request.
- **Central coordination:** the shared-AHU coordinator decides how much of each request can be granted when capacity is limited.
- **Transparent action:** MQTT publishes both the requested and delivered airflow, plus the policy reason codes.
- **Graceful demo degradation:** an empty or lower-priority room may receive less airflow; the system never silently hides that decision.

---

## Run the application

### 1. Start the MQTT broker

```bash
docker compose up -d
```

Mosquitto serves MQTT on `1883` and WebSockets on `9001`.

### 2. Install dependencies

```bash
uv sync
```

Or, with a traditional environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r simulator/requirements.txt -r dashboard/requirements.txt
```

### 3. Launch the components

Use three terminals from the project root.

```bash
# Terminal 1 — two rooms + shared AHU simulator
uv run python simulator/publisher.py

# Terminal 2 — ecosystem dashboard
uv run streamlit run dashboard/app.py

# Terminal 3 — selectable 3D room view
uv run python -m http.server 8000 --directory room3d
```

Open the dashboard at [http://localhost:8501](http://localhost:8501). A direct 3D drill-down is available at:

- [Room 1](http://localhost:8000/room3d.html?room=room1)
- [Room 2](http://localhost:8000/room3d.html?room=room2)

---

## Demo scenarios

All commands are non-retained. The simulator validates and applies them on its simulation thread.

```bash
# Make Room 1 the high-priority occupied room
docker exec mosquitto mosquitto_pub -t twin/room1/cmd/occupancy -m '{"value": 24}'
docker exec mosquitto mosquitto_pub -t twin/room1/cmd/setpoint -m '{"value": 20}'
docker exec mosquitto mosquitto_pub -t twin/room1/cmd/hvac -m '{"command": "on"}'

# Create competing demand in Room 2
docker exec mosquitto mosquitto_pub -t twin/room2/cmd/occupancy -m '{"value": 5}'
docker exec mosquitto mosquitto_pub -t twin/room2/cmd/setpoint -m '{"value": 20}'
docker exec mosquitto mosquitto_pub -t twin/room2/cmd/hvac -m '{"command": "on"}'

# Inject an adverse degradation scenario
docker exec mosquitto mosquitto_pub -t twin/ahu/cmd/filter_clog -m '{"value": 0.85}'
docker exec mosquitto mosquitto_pub -t twin/ahu/cmd/fan_wear -m '{"value": 0.75}'

# Accelerate simulated time for the demo
docker exec mosquitto mosquitto_pub -t twin/room1/cmd/timescale -m '{"value": 10}'
```

Watch `twin/ahu/coordinator/decision` for the allocation explanation and `twin/ahu/fan/health` for the risk and contributing features.

---

## MQTT topic contract

All telemetry/state topics below are retained so new UI clients receive the latest simulation state. Commands are non-retained.

| Topic | Direction | Key data |
|---|---|---|
| `twin/{room}/temperature`, `/humidity`, `/occupancy` | Simulator → clients | Existing `{sensor, value, unit, timestamp}` sensor format for `room1` and `room2`. |
| `twin/{room}/hvac/state` | Simulator → clients | HVAC request, target temperature, requested and delivered airflow. |
| `twin/{room}/hvac/allocation` | Simulator → clients | Requested/granted airflow, allocation %, priority score, reason codes. |
| `twin/{room}/energy` | Simulator → clients | Estimated room cooling demand. |
| `twin/{room}/cmd/{hvac,occupancy,setpoint,mode,timescale}` | Clients → simulator | Per-room controls; `timescale` applies ecosystem-wide. |
| `twin/ahu/state` | Simulator → clients | AHU capacity, delivered airflow, supply air, filter clog, fan speed. |
| `twin/ahu/energy` | Simulator → clients | Estimated fan/cooling/total W, cumulative kWh, tariff estimate. |
| `twin/ahu/fan/health` | Simulator → clients | Health, wear, risk, risk band, model version, driver contributions. |
| `twin/ahu/coordinator/decision` | Simulator → clients | `occupied-comfort-v1` allocation result for both rooms. |
| `twin/ahu/cmd/filter_clog`, `/fan_wear` | Clients → simulator | Explicit scenario injection values in `[0.0, 1.0]`. |
| `twin/ecosystem/status` | Simulator → clients | Authoritative process online/offline state (LWT). |

---

## Reproducible predictive model

The predictive model is intentionally simple and inspectable. It estimates **simulated fan-failure risk**, not real-world failure probability.

```bash
# Regenerate the deterministic synthetic dataset, model JSON, and holdout metrics
uv run python simulator/train_fan_model.py --seed 20260805 --rows 2400

# Or regenerate only the labelled synthetic scenarios
uv run python simulator/generate_fan_data.py --seed 20260805 --rows 2400
```

Artifacts:

- `simulator/data/fan_failure_synthetic.csv` — generated training rows.
- `simulator/models/fan_risk_logistic.json` — versioned coefficients, standardisation values, and thresholds.
- `simulator/models/fan_risk_logistic.metrics.json` — deterministic holdout metrics.
- `notebooks/fan_failure_prediction.ipynb` — presentation-friendly training walkthrough.

---

## Test suite

```bash
uv run pytest -q
```

The suite currently contains **54 tests** covering legacy room physics/PID/commands, shared-AHU physics, deterministic coordination, fan-risk explanation, synthetic-data reproducibility, and ecosystem command routing.

---

## Security and governance notes

The included Mosquitto configuration intentionally allows anonymous local access for a classroom demo. A production deployment must add TLS/WSS, device credentials or certificates, topic ACLs, network segmentation, input/schema validation, audit logs, alerting, and explicit human override rules.

The system uses aggregate occupancy counts only. It does not process identity, video, or facial-recognition data. Every autonomous allocation and ML risk alert is explainable, but high-impact maintenance or operational actions should remain human-approved until validated in a real environment.
