# Executive Pitch Outline — EcoHVAC Guardian

Use this as the concise structure behind the generated Project 2 deck in `report/pitch/`. The editable generator, eight-slide PPTX, eight-page PDF, evidence index, and rendered verification are current Project 2 deliverables, but they are not evidence of production deployment, approval, or measured savings. The repository's `Digital_Twin_Project1_Report.pptx` remains a legacy Project 1 deck and is explicitly excluded.

## Slide 1 — The operational problem

A shared HVAC asset creates interactions that isolated room dashboards miss: simultaneous comfort demand, finite airflow, filter resistance, fan condition, electrical load, and maintenance uncertainty. The classroom question is whether a Digital Twin can make those interactions visible and explain its choices.

Avoid claiming that the prototype has observed real failures, downtime, or waste.

## Slide 2 — The simulated solution

**EcoHVAC Guardian** combines:

- two independently controlled room twins;
- one finite-capacity shared AHU;
- `occupied-comfort-debt-v2` temporal allocation;
- PID actuator feedback from granted airflow;
- thermal/electrical energy accounting with simulated COP `3.2`;
- an interpretable fan-risk model that can abstain; and
- strict correlated command results plus an optional local audit journal.

State the boundary: this is classroom simulation software with no physical control authority.

## Slide 3 — Six-layer architecture

Show the diagram in [architecture.md](architecture.md): simulated assets → local request controllers → ecosystem intelligence → MQTT/contracts → dashboard and 3D client → human oversight.

Key points:

- PID loops create room requests; they are not certified safety layers.
- The coordinator allocates only simulated shared airflow.
- Retained presentation telemetry packages one coherent simulator snapshot.
- The 3D WebSocket endpoint accepts a validated `ws:`/`wss:` query override rather than being fixed to localhost.

## Slide 4 — Repeatable live scenario

1. Use the dashboard button for `shared_capacity_stress`.
2. Show both rooms requesting `0.16 m³/s` and first-tick available flow of about `0.0953 m³/s` under the preset.
3. Show request versus grant, capacity constraint, reason codes, comfort debt, and limited-service time.
4. Show PID request/grant feedback, thermal cooling, fan/cooling electrical power, and cumulative simulated kWh.
5. Show fan condition plus either an in-domain risk score and drivers or an explicit non-prediction status.
6. Restore `baseline` and show the canonical state reset.

The simulator also implements MQTT `pause`, `resume`, and simulation-only `emergency_stop`; these are not dashboard buttons and must not be presented as a physical E-stop.

## Slide 5 — Trustworthy command path

Demonstrate a dashboard or CLI command carrying `command_id` and `source`, then show `twin/ecosystem/command/result`:

- strict JSON/range validation;
- application acceptance versus actual state change;
- rejection of retained command messages;
- identical-ID request replay without repeated mutation;
- rejection of conflicting ID reuse; and
- dashboard pending/result correlation.

Clarify that the 1,024-ID deduplication cache is in-memory and resets on restart. An MQTT PUBACK alone is not the application result.

## Slide 6 — Predictive evidence and abstention

Show the reproducible synthetic workflow and executed notebook:

- 11 executed code cells with no stored errors;
- checked-in feature schema and JSON logistic coefficients;
- exact reconstruction assertions for the model and metrics artifacts;
- synthetic holdout metrics and baseline comparison;
- threshold and false-negative discussion;
- feature-domain checking; and
- missing/non-finite, OOD, or unavailable-model abstention with no invented numeric score.

State clearly: synthetic holdout results do not establish real-facility discrimination, calibration, maintenance utility, or safety. The predictor is advisory and outside the HVAC control path.

## Slide 7 — Energy and business value

Keep the units explicit:

- room/AHU thermal cooling is delivered sensible heat removal;
- cooling electricity is thermal cooling divided by simulated COP `3.2`;
- fan electricity is estimated separately;
- cumulative kWh integrates total simulated electrical power.

Use the dashboard ROI area only as an illustrative assumption sandbox. Label every input and show the formula. Do not claim measured energy savings, avoided incidents, maintenance savings, payback, or approved funding. A credible business case needs measured facility baselines, scoped costs, causal evaluation, and uncertainty ranges.

## Slide 8 — Governance, audit, and security

Current implemented facts:

- aggregate occupancy only—no identity, video, or biometrics;
- optional `ECOHVAC_AUDIT_PATH` integration records sanitized command/result metadata in local SQLite;
- audit startup/write failures are visible;
- the local SHA-256 chain is tamper-evident within a limited threat model, not immutable or externally anchored;
- dashboard-only recommendation responses are not in the journal;
- the default broker is anonymous plaintext classroom infrastructure.

Target example, not deployed security:

- opt-in Mosquitto TLS/WSS configuration on `8883`/`9002`;
- password authentication and placeholder ACL identities;
- no supplied certificates, keys, passwords, secret management, firewall, gateway, monitoring, or approvals; and
- no current Python TLS/authentication hooks or browser credential integration, so the target broker files are not yet an end-to-end secure application profile.

## Slide 9 — Evidence and roadmap

Evidence to show:

- a live baseline/stress round trip;
- correlated accepted and rejected command results;
- current full test result, labelled with its verification date;
- the executed notebook and checked-in model artifacts; and
- optional audit-journal verification when deliberately enabled for the demo.

Roadmap:

simulation → governed read-only digital shadow → human-in-the-loop evaluation → independently safeguarded constrained automation → federated scale.

Each stage requires named owners and explicit gates for sensor quality, cybersecurity, model calibration, physical safety, override/rollback, and operational approval.

## Closing message

**The demonstrated value is explainable coordination and inspectable evidence inside a simulation—not autonomous building control or proven savings.** The next credible step is governed real-world validation, not broader claims.