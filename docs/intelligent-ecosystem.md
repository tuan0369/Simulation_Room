# Intelligent Ecosystem Design

## Project proposition

**EcoHVAC Guardian** is a two-zone smart-lab Digital Twin ecosystem. It protects occupant comfort and AHU health together instead of treating room temperature, equipment condition, and energy as separate dashboards.

The key scenario is deliberately easy to demonstrate:

1. Room 1 becomes crowded and needs cooling.
2. Room 2 also requests conditioning from the same finite-capacity AHU.
3. A filter-clogging scenario reduces airflow and raises fan resistance.
4. Fan vibration, bearing temperature, and simulated failure risk rise.
5. The coordinator prioritises the occupied room and publishes a transparent allocation decision.
6. The dashboard quantifies estimated energy/cost and recommends inspection when risk is elevated.

## Sub-twins

| Twin | State | Interaction |
|---|---|---|
| Occupancy / Room 1 | Temperature, humidity, people, setpoint, local PID request | Produces a priority-weighted cooling demand. |
| Occupancy / Room 2 | Equivalent independent zone state | Competes for the shared AHU in a visible, fair policy. |
| Shared AHU | Available airflow, supply temperature, filter clog, fan speed | Constrains every room’s delivered cooling and energy. |
| Fan health | Wear, vibration, bearing temperature, runtime | Feeds the failure-risk model. |
| Energy | Fan/cooling power, kWh, tariff estimate | Provides a transparent business-value signal. |
| Coordinator | Requests, available capacity, decisions/reasons | Prevents opaque cross-twin control. |

## Physics simplification

This is a teaching/pilot model, not a certified building simulation. It deliberately models sensible airflow cooling:

```text
Room heat = occupants + outdoor wall gain − supplied-air cooling
Supplied-air cooling = air density × air heat capacity × airflow × (room temp − supply temp)
```

Filter clog reduces available airflow and increases fan power. Fan wear gradually raises vibration and bearing temperature. This establishes a causal path from maintenance condition to comfort, energy, and risk without pretending to reproduce a particular vendor AHU.

## Predictive model card

| Item | Definition |
|---|---|
| Purpose | Estimate simulated fan-failure risk within a maintenance horizon. |
| Model | Standardised logistic regression serialized as JSON. |
| Inputs | Filter clog %, fan speed %, vibration (mm/s), bearing temperature (°C), run hours. |
| Output | Failure-risk probability, low/medium/high band, top log-odds contributors. |
| Training data | Deterministic synthetic scenarios, seed `20260805`. |
| Validation | Held-out synthetic episodes, stored in `fan_risk_logistic.metrics.json`. |
| Limitations | Does not establish real-world failure accuracy; requires calibration, drift monitoring, and safety review before production. |
| Owner / review | Facilities/data owner should review model version, thresholds, missing-data behavior, and retraining cadence. |

## Energy and ROI framing

The dashboard's energy values are explicitly simulated. For a deployment pitch, use transparent assumptions:

```text
Annual benefit = avoided failure cost
               + avoided downtime cost
               + HVAC energy savings
               + maintenance labour savings

Annual net benefit = annual benefit − recurring operating cost
ROI (%) = (annual net benefit − initial implementation cost) / initial implementation cost × 100
Payback period = initial implementation cost / monthly net benefit
```

Do not claim savings from the simulation alone. Present assumptions, baseline source, tariff, failure-cost estimate, and confidence range on the slide.

## Roadmap

| Stage | Scope | Gate to advance |
|---|---|---|
| 1. Simulated pilot | Two digital rooms, shared AHU, synthetic fan risk | Tests pass and policy decisions are explainable. |
| 2. Digital shadow | Read-only real telemetry alongside simulation | Sensor quality, data governance, and model calibration accepted. |
| 3. Human-in-the-loop | Recommendations and work-order drafts | Operators verify alerts and action utility. |
| 4. Constrained automation | Bounded setpoint / airflow recommendations | Safety, cybersecurity, override, and rollback controls audited. |
| 5. Federated scale | Multiple AHUs/buildings with local gateways | Local resilience and cross-site data governance established. |

## Ethics and safety principles

1. **Safety before optimisation:** no energy-saving action may violate comfort, air-quality, or equipment constraints.
2. **Explainability before autonomy:** operators see model drivers and coordinator reasons before relying on actions.
3. **Privacy minimisation:** use aggregate counts, not identities or visual surveillance.
4. **Human override:** any operator can override or pause automation; the action should be logged in a production system.
5. **Bias and drift monitoring:** occupancy and condition patterns may change by room, schedule, or operating season; evaluate error rates across these conditions.
6. **Secure-by-design controls:** production MQTT must use TLS, credentials/certificates, ACLs, command audit trails, and network segmentation.
