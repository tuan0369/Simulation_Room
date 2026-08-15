# Intelligent Ecosystem Design

## Project proposition

**EcoHVAC Guardian** is a two-zone smart-lab Digital Twin classroom simulation. It connects room comfort, shared AHU capacity, equipment degradation, electrical energy, and simulated predictive status instead of presenting them as unrelated dashboards.

The repeatable stress story is:

1. Both rooms request cooling from one AHU.
2. The `shared_capacity_stress` preset applies high demand plus filter clog and fan wear atomically.
3. Available airflow falls below total requested airflow.
4. `occupied-comfort-debt-v2` allocates the available supply and publishes reasons and temporal-fairness state.
5. PID actuator feedback reflects the difference between requested and granted output.
6. Thermal cooling, fan/cooling electrical power, cumulative simulated kWh, fan condition, and the risk-model status remain causally aligned.
7. The dashboard and unified 3D scene display the outcome; dashboard commands receive correlated application results.

The companion `baseline` preset restores the canonical deterministic initial state. Neither preset controls a real building.

## Sub-twins and interactions

| Twin or service | State | Implemented interaction |
|---|---|---|
| Room 1 | Temperature, humidity, aggregate occupancy, setpoint, mode, PID request, comfort debt | Requests cooling and receives a coordinator-limited supply. |
| Room 2 | Equivalent independent state | Competes for the same finite capacity and accumulates/reduces its own temporal debt. |
| Shared AHU | Maximum/available/delivered airflow, supply temperature, filter clog, fan wear/speed | Constrains both rooms and estimates fan plus cooling electrical load. |
| Fan health | Wear, vibration, bearing temperature, run hours, health | Supplies the stable feature contract for the risk model. |
| Energy | Room thermal cooling; AHU fan/cooling/total electricity; cumulative kWh | Keeps thermal delivery distinct from electrical input using simulated COP `3.2`. |
| Coordinator | Requests, grants, debt, limited-service time, priority components, reasons | Applies deterministic `occupied-comfort-debt-v2` capacity allocation. |
| Command contract | Strict input parsing and `CommandOutcome` | Separates MQTT transport receipt from application acceptance/change. |
| Presentation clients | Lock-protected dashboard store and read-only 3D scene | Display live/retained state and command correlation without direct state mutation. |

## Physics and energy simplification

This is a teaching model, not a certified building simulation or digital commissioning model:

```text
Room heat = occupant sensible heat + outdoor wall gain − supplied-air cooling
Supplied-air thermal cooling = air density × heat capacity × airflow × temperature difference
Cooling electrical power = supplied-air thermal cooling / 3.2
Total electrical power = cooling electrical power + fan electrical power
```

Filter clog and wear derate airflow. Fan electricity follows a cubic speed relationship with resistance and wear penalties. Fan wear, vibration, bearing temperature, and health evolve from simulated load and degradation. The causal structure is useful for demonstration, but parameters are not identified from a particular room, AHU, tariff, or meter.

## Coordination and temporal fairness

The policy ranks enabled demands as follows:

1. occupied before unoccupied;
2. larger bounded comfort debt before smaller debt;
3. larger positive temperature error;
4. larger occupancy count;
5. stable room ID.

For an occupied enabled room receiving less than its request, debt accumulates from temperature error × unmet fraction × simulated time, capped at `3600 °C·s`; consecutive limited-service time also rises. Full service reduces debt at `2 °C·s` per simulated second and resets limited-service time. Disabled, unoccupied, or non-requesting rooms recover debt and reset limited-service time.

This improves temporal behavior over a purely instantaneous priority rule but is not proof of social, accessibility, or operational fairness. A real deployment would need governed definitions for room criticality, ventilation, schedules, comfort bands, and protected occupant needs, plus outcome monitoring.

## PID actuator feedback

Each local PID first calculates requested output. After the shared coordinator grants airflow, the room converts that grant back to applied output and calls `apply_actuator_feedback`. When applied output is lower than requested, the PID integral is reduced and bounded. This mitigates windup caused by shared scarcity; it does not make the controller production-certified or safety-rated.

## Predictive model card

| Item | Implemented definition |
|---|---|
| Purpose | Estimate simulated AHU fan-failure risk within the synthetic maintenance horizon. |
| Model | Standardized logistic regression serialized as reviewed JSON, model version `fan-risk-logistic-v1`. |
| Inputs | Filter clog fraction, fan speed fraction, vibration (mm/s), bearing temperature (°C), and run hours. |
| Scored output | Probability, low/medium/high band, and three largest positive log-odds contributors. |
| Non-prediction output | `failure_risk: null` plus explicit abstained, out-of-distribution, or unavailable status and reason. |
| Training evidence | Deterministic synthetic generator; checked-in JSON artifact and holdout metrics. |
| Notebook | Executed walkthrough with 11 executed code cells, no stored errors, exact artifact/metrics assertions, and OOD examples. |
| Runtime role | Advisory telemetry only; never an input to airflow allocation or PID control. |
| Limitation | Synthetic holdout performance does not establish real-world discrimination, calibration, maintenance utility, or safety. |

The default loader catches invalid/missing-artifact failures and returns an unavailable model that does not invent a score. In-domain scoring requires every feature to be numeric, finite, and within the stored synthetic feature domain.

## Commands, scenarios, and lifecycle

Non-retained subscribed commands are enqueued from the MQTT callback and applied on the simulation thread; retained commands are rejected before queuing. The parser requires a bounded UTF-8 JSON object, rejects non-standard numeric constants and invalid metadata, and validates implemented ranges/choices. Dashboard commands carry generated IDs; the simulator emits a non-retained result and the dashboard reconciles matching IDs. A bounded in-memory cache replays the result for an identical repeated ID/topic/payload without mutation and rejects conflicting reuse as `command_id_conflict`; this state is limited to 1,024 IDs and resets when the process restarts.

Implemented atomic scenarios:

- `baseline` — canonical two-room, controller, AHU, fan, energy, risk, coordination, and deterministic RNG reset;
- `shared_capacity_stress` — fixed competing loads with severe filter clog and fan wear for a reproducible constrained first tick.

Implemented simulation lifecycle commands:

- `pause` — freezes progression and zeroes instantaneous request/flow/power;
- `resume` — resumes simulation ticks;
- `emergency_stop` — enters the same non-running simulation boundary under the explicit state `simulation_emergency_stop`.

The emergency-stop name applies only to software simulation state. It is not a hardwired physical E-stop, life-safety control, broker shutdown, or certified fail-safe. Lifecycle commands are available over MQTT but currently are not exposed as dashboard buttons.

## Audit status

A tested `AuditJournal` appends JSON events to local SQLite with SHA-256 links and verifies continuity. The publisher integrates it when `ECOHVAC_AUDIT_PATH` is set. Each handled command records sanitized request metadata (topic, source/correlation, retained flag, byte length, payload digest) and its result, without storing raw request values. Startup failure is visible through stderr and `audit_error`; a write failure is marked in the published result.

When the environment variable is unset, no runtime journal is created. Dashboard recommendation acknowledgements remain only in Streamlit session state. No immutable or externally anchored audit trail is claimed: an attacker able to replace the database and recompute its hashes can replace the chain. Production use still requires threat modeling, protected access, durable backup/export, external anchoring or signing, retention rules, and operational review.

## Energy and ROI framing

The dashboard's annual business case is an **illustrative assumption sandbox**:

```text
Annual energy savings = baseline kWh × assumed reduction × tariff
Annual net benefit = energy savings + illustrative avoided-incident value − annual support cost
First-year ROI = (annual net benefit − implementation cost) / implementation cost
Payback months = implementation cost / (annual net benefit / 12), when net benefit is positive
```

Current-run simulated tariff cost is displayed separately from annual assumptions. Do not infer or claim measured energy savings, avoided failures, downtime reduction, maintenance savings, or approved ROI from this simulation. A real business case needs measured baselines, scoped costs, causal evaluation, uncertainty ranges, and owner review.

## Roadmap

| Stage | Scope | Gate to advance |
|---|---|---|
| 1. Simulated pilot | Two rooms, shared AHU, strict acknowledged commands, synthetic fan-risk evidence | Tests and scenarios pass; limits and decision reasons are inspectable. |
| 2. Digital shadow | Read-only governed facility telemetry alongside simulation | Sensor quality, cybersecurity, data governance, and model calibration are accepted by named owners. |
| 3. Human-in-the-loop | Recommendations and work-order drafts | Operators evaluate alert utility, abstention, workload, and false-negative handling. |
| 4. Constrained automation | Bounded recommendations with independent safety controls | Physical safety, cybersecurity, override, rollback, commissioning, and approvals are demonstrated. |
| 5. Federated scale | Multiple AHUs/buildings with local gateways | Site resilience, identity/ACL management, monitoring, and cross-site governance are validated. |

## Ethics, security, and safety principles

1. **Maintain the simulation boundary:** no claim of physical authority, emergency-stop behavior, or production validation.
2. **Abstain visibly:** unavailable, malformed, non-finite, or OOD predictive inputs produce no numeric score.
3. **Explain allocation:** publish requests, grants, debt, limited-service time, and reason codes.
4. **Minimize personal data:** aggregate occupancy only; no identity, video, facial recognition, or biometrics.
5. **Separate evidence from assumptions:** synthetic model metrics and illustrative ROI are not measured facility outcomes.
6. **Harden before deployment:** the current anonymous plaintext broker is classroom-only. The opt-in TLS/WSS, password, and placeholder-ACL files are a target example, not deployed security or an end-to-end client profile; Python TLS/authentication and browser credential integration are not implemented. Identities/grants, secrets, certificates, segmentation, rate limiting, monitoring, and independently reviewed fallback/override behavior still require deployment work.
7. **Require accountable review:** high-impact maintenance and control decisions remain human-approved until governed real-world validation is complete.