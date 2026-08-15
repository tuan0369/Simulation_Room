# Smart Lab Intelligent Ecosystem

A real-time **two-room Digital Twin ecosystem** for a smart-laboratory classroom simulation. Each room has an independent local PID comfort controller, while both share one finite-capacity AHU. The ecosystem models filter and fan degradation, allocates scarce airflow transparently, estimates thermal and electrical energy, and publishes an interpretable simulated fan-risk assessment.

> **Evidence boundary:** all physics, energy, equipment condition, ROI, and predictive-risk values are simulated or illustrative. The synthetic model has not been validated on a real facility and must not be treated as a production failure probability or control authority.

## Implemented capabilities

| Capability | Current implementation |
|---|---|
| Multi-twin ecosystem | `room1` and `room2` have independent temperature, humidity, occupancy, setpoint, mode, HVAC state, and PID controller state. |
| Shared AHU | A finite supply-air capacity is allocated across both rooms; filter clog and fan wear derate available flow. |
| Temporal fairness | `occupied-comfort-debt-v2` ranks occupancy first, then current positive temperature error, bounded accumulated comfort debt, occupancy count, and stable room ID. Decisions expose request, grant, debt, limited-service time, and reason codes. |
| Closed-loop actuation | Each PID requests airflow. The controller receives the granted actuator output after coordination so its integral state can bleed down when shared capacity prevents delivery. |
| Energy coherence | Room values are delivered **thermal cooling**. AHU cooling electricity is thermal cooling divided by the simulated COP of `3.2`; fan electricity is added separately, and total electrical power is integrated to kWh. |
| Predictive intelligence | A versioned JSON logistic model estimates simulated fan-failure risk and reports top log-odds contributors. It emits an explicit non-prediction for missing/non-finite, out-of-domain, or unavailable model inputs. |
| Acknowledged commands | Strict JSON-object commands are validated and applied on the simulation thread. Retained commands are rejected; a bounded in-memory result cache replays identical command IDs and rejects conflicting reuse. The simulator publishes a non-retained correlated application result. |
| Guided scenarios | Atomic `baseline` and `shared_capacity_stress` presets support a repeatable classroom demonstration. |
| Coherent presentation telemetry | A retained snapshot carries a run ID, monotonic snapshot ID, both rooms, AHU, risk, scenario, and coordination state from one simulation tick. |

Detailed references: [ecosystem design](docs/intelligent-ecosystem.md), [architecture](docs/architecture.md), and [executive-pitch outline](docs/executive-pitch.md).

---

## Architecture at a glance

```text
Room 1 + PID ─┐                           ┌─> Fan condition → risk model
               ├─> fairness coordinator ─> shared AHU
Room 2 + PID ─┘             │             └─> thermal/electrical energy
                             └─> granted airflow + PID actuator feedback

Simulator ──retained telemetry──> MQTT ──> dashboard + unified two-room 3D view
Clients ──non-retained commands─> MQTT ──> simulator ──application result──> clients
```

The PID loops generate requests; they are not an independently validated safety layer. The coordinator controls only simulated shared-airflow allocation. This prototype has no authority over a physical HVAC system.

---

## Run the application

### 1. Start the classroom broker

```bash
docker compose up -d
```

The checked-in Mosquitto configuration serves anonymous, plaintext MQTT on `1883` and WebSockets on `9001`. It is a convenient local default, not a hardened deployment configuration.

### 2. Install dependencies

```bash
uv sync
```

Or use a traditional environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r simulator/requirements.txt -r dashboard/requirements.txt
```

### 3. Launch the components

Use three terminals from the project root:

```bash
# Terminal 1 — simulator
uv run python simulator/publisher.py

# Terminal 2 — dashboard
uv run streamlit run dashboard/app.py

# Terminal 3 — static 3D client
uv run python -m http.server 8000 --directory room3d
```

Open:

- dashboard: [http://localhost:8501](http://localhost:8501)
- unified two-room 3D operations scene: [http://localhost:8000/room3d.html](http://localhost:8000/room3d.html)

The 3D client defaults to `ws(s)://<page-host>:9001`. Override the endpoint with a validated `ws:` or `wss:` URL in the `mqtt` query parameter, for example:

```text
http://localhost:8000/room3d.html?mqtt=ws%3A%2F%2Fbroker-host%3A9001
```

The simulator and dashboard read `ECOHVAC_BROKER_HOST` and `ECOHVAC_BROKER_PORT`; the dashboard also reads `ECOHVAC_3D_URL`. These settings select a host/port only: the Python clients currently use plain MQTT and do not implement TLS or credential hooks for the hardened example. The browser 3D client accepts a `wss:` endpoint override, but authentication is not wired into the page.

---

## Guided scenarios and simulation lifecycle

The dashboard provides buttons for the two atomic scenario presets:

- `baseline` restores the canonical initial state, including rooms, controllers, AHU/fan condition, cumulative energy, and deterministic random-generator state.
- `shared_capacity_stress` sets competing cooling demand, Room 1 occupancy `24`, Room 2 occupancy `5`, filter clog `0.85`, and fan wear `0.75`. Both rooms request `0.16 m³/s`, while degraded available capacity is about `0.0953 m³/s` on the first tick.

The same scenarios can be invoked through MQTT. Include a `command_id` to correlate the simulator's application result:

```bash
docker exec mosquitto mosquitto_pub \
  -t twin/ecosystem/cmd/scenario \
  -m '{"scenario":"shared_capacity_stress","command_id":"scenario-1","source":"cli"}'

docker exec mosquitto mosquitto_sub -v -t twin/ecosystem/command/result
```

The simulator also implements `pause`, `resume`, and `emergency_stop` on `twin/ecosystem/cmd/simulation`:

```bash
docker exec mosquitto mosquitto_pub \
  -t twin/ecosystem/cmd/simulation \
  -m '{"command":"pause","command_id":"sim-1","source":"cli"}'
```

`pause` and `emergency_stop` freeze this software simulation and zero instantaneous requests, airflow, thermal cooling, and electrical power while preserving cumulative energy and comfort debt. `resume` returns to ticking. **`emergency_stop` is only a simulation lifecycle state; it is not a physical emergency-stop circuit, safety function, broker kill switch, or production control guarantee.** These lifecycle actions are implemented in the MQTT contract but are not currently dashboard buttons.

### Command contract

Commands must be UTF-8 JSON objects no larger than 16,384 bytes. The parser rejects malformed JSON, JSON `NaN`/`Infinity`, non-object payloads, invalid metadata, booleans where numbers are required, non-finite values, and out-of-range/unsupported choices. `command_id` is optional but, when supplied, must be a non-empty string of at most 128 characters; `source` has the same string constraints.

For every dequeued command, `twin/ecosystem/command/result` reports:

```json
{
  "command_id": "scenario-1",
  "source": "cli",
  "topic": "twin/ecosystem/cmd/scenario",
  "target": "ecosystem",
  "command": "scenario",
  "accepted": true,
  "changed": true,
  "reason": "applied",
  "applied_values": {},
  "timestamp": "<UTC>"
}
```

This is an application-level acknowledgement, distinct from an MQTT transport PUBACK. Retained command messages are rejected before queuing. For the latest 1,024 non-empty IDs in the current process, an identical repeated topic/payload receives the cached prior result marked `duplicate: true, replayed: true` without repeating mutation; reuse of an ID with a different request is rejected as `command_id_conflict`. This cache is in-memory and resets on restart. The dashboard generates IDs, tracks pending commands, and reconciles matching results. Results themselves are non-retained; durable local recording is opt-in as described below.

---

## MQTT topic contract

Telemetry/state topics are retained unless noted; commands and command results are non-retained.

| Topic | Direction | Key data |
|---|---|---|
| `twin/{room}/temperature`, `/humidity`, `/occupancy` | Simulator → clients | `{sensor, value, unit, timestamp}` for `room1` and `room2`. |
| `twin/{room}/hvac/state` | Simulator → clients | HVAC state, PID request, setpoint, requested/delivered airflow, time scale. |
| `twin/{room}/hvac/allocation` | Simulator → clients | Request/grant, allocation %, comfort debt, limited-service time, priority score, reasons. |
| `twin/{room}/energy` | Simulator → clients | Delivered room thermal cooling power in watts. |
| `twin/{room}/cmd/{hvac,occupancy,setpoint,mode,timescale}` | Clients → simulator | Strict per-room commands; time scale applies ecosystem-wide. |
| `twin/ahu/state` | Simulator → clients | Capacity, delivered flow, supply-air temperature, filter clog, fan speed. |
| `twin/ahu/energy` | Simulator → clients | Thermal cooling; fan, cooling, and total electrical power; electrical kWh; illustrative tariff cost. |
| `twin/ahu/fan/health` | Simulator → clients | Condition telemetry plus scored or explicit abstained/OOD/unavailable risk status. |
| `twin/ahu/coordinator/decision` | Simulator → clients | `occupied-comfort-debt-v2` allocation for both rooms. |
| `twin/ahu/cmd/{filter_clog,fan_wear}` | Clients → simulator | Degradation values in `[0.0, 1.0]`. |
| `twin/ecosystem/cmd/scenario` | Clients → simulator | `baseline` or `shared_capacity_stress`. |
| `twin/ecosystem/cmd/simulation` | Clients → simulator | `pause`, `resume`, or simulation-only `emergency_stop`. |
| `twin/ecosystem/command/result` | Simulator → clients | Non-retained application acknowledgement/result. |
| `twin/ecosystem/scenario/state` | Simulator → clients | Active scenario, revision, operating mode, paused state, correlation ID. |
| `twin/ecosystem/presentation/state` | Simulator → clients | Coherent retained snapshot for presentation clients. |
| `twin/ecosystem/status` | Simulator → clients | Authoritative retained online/offline state with Last Will. |

---

## Predictive-model evidence

The model is inspectable and estimates **simulated fan-failure risk**, not real-world failure probability.

```bash
# Regenerate deterministic data, model JSON, and holdout metrics
uv run python simulator/train_fan_model.py --seed 20260805 --rows 2400

# Or regenerate only the labelled synthetic scenarios
uv run python simulator/generate_fan_data.py --seed 20260805 --rows 2400
```

Evidence artifacts:

- `simulator/data/fan_failure_synthetic.csv` — generated training rows.
- `simulator/models/fan_risk_logistic.json` — coefficients, feature standardisation, feature domain, thresholds, and model version.
- `simulator/models/fan_risk_logistic.metrics.json` — deterministic synthetic holdout metrics.
- `notebooks/fan_failure_prediction.ipynb` — an executed 11-code-cell walkthrough with no stored error outputs; it reconstructs the split and asserts exact equality with both checked-in JSON artifacts, and demonstrates OOD/abstention behavior.

If required telemetry is missing/non-numeric/non-finite, the runtime abstains. If a feature is outside the artifact's stored training domain, it returns `failure_risk: null` with `prediction_status: "out_of_distribution"`. If the bundled artifact cannot be loaded, the default loader returns an unavailable, non-predicting model state rather than inventing a score. The predictor does not participate in HVAC control.

---

## Audit and presentation evidence status

The publisher integrates the tested local SQLite, SHA-256 hash-chained `AuditJournal` when `ECOHVAC_AUDIT_PATH` is set:

```bash
ECOHVAC_AUDIT_PATH=runtime/ecohvac-audit.db uv run python simulator/publisher.py
```

Each handled command result records the topic, correlation/source metadata, retained flag, payload byte length and SHA-256 digest, plus the application result; the raw request values are deliberately not copied into the audit entry. Journal startup errors are printed and exposed in `Simulator.audit_error`; a write failure is also added to the published result as `audit_write_failed` and `audit_error` rather than silently claiming success. When the variable is unset, no runtime audit journal is created. Dashboard-only recommendation responses remain Streamlit session state and are not journaled.

The local chain detects row/link changes within its threat model, but it is neither immutable nor externally anchored: an attacker able to rewrite the complete database and recompute hashes can replace the history.

`docs/executive-pitch.md` is the Project 2 pitch outline. The current editable generator, eight-slide PPTX, eight-page PDF, evidence index, and rendered verification are under `report/pitch/`. The repository also contains a legacy `report/Digital_Twin_Project1_Report.pptx`; that legacy deck must not be presented as current Project 2 evidence.

---

## Test suite

```bash
uv run pytest -q simulator/tests dashboard/tests
```

**Verified 2026-08-15:** `145 passed` in the full simulator and dashboard suite. This count describes that checkout at verification time, not a permanent project invariant.

---

## Security, governance, and deployment boundary

The default broker allows anonymous plaintext access. An opt-in **target example** is provided in `docker-compose.hardened.yml`, `mosquitto/config/mosquitto-hardened.conf`, `mosquitto/config/acl.hardened`, and `mosquitto/README.md`: it disables anonymous access, requires a password file, defines placeholder least-privilege identities, enables TLS MQTT on `8883` and WSS on `9002`, and persists broker data. It ships no certificates, private keys, passwords, secret manager, firewall, reverse proxy, certificate renewal, or deployed security. Replace and review all identities/grants and provide external operations controls before use; browser credentials need a gateway or short-lived mechanism rather than a durable password in public source. The current Python clients do not yet configure TLS or authentication, so the hardened broker files are not an end-to-end runnable secure application profile without additional client integration.

The simulation uses aggregate occupancy counts only and does not process identity, video, or biometric data. No production validation, facilities approval, safety certification, measured savings, or deployment authorization is claimed. The dashboard ROI inputs and tariff-derived costs are illustrative assumptions that require measured facility baselines and uncertainty ranges before any decision.