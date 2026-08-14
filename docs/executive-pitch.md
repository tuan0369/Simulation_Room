# Executive Pitch Outline — EcoHVAC Guardian

Use this as a concise Project 2 presentation structure.

## Slide 1 — The problem

A smart lab can keep rooms cool today, but it cannot see the interaction between occupancy surges, shared HVAC capacity, energy use, filter degradation, and fan-health risk. Reactive maintenance creates avoidable disruption and cost.

## Slide 2 — The solution

**EcoHVAC Guardian** is a coordinated two-room Digital Twin ecosystem. It combines local PID comfort control with a shared-AHU coordinator and an explainable fan-risk model.

## Slide 3 — Ecosystem architecture

Show the diagram in [architecture.md](architecture.md): two room twins → shared AHU → energy and fan-health twins → risk model / coordinator → dashboard and operator.

Emphasise the hybrid design: local loops retain safe responsiveness; central coordination handles shared capacity.

## Slide 4 — Live scenario

1. Increase Room 1 occupancy.
2. Create competing Room 2 demand.
3. Inject filter clog and fan wear.
4. Show reduced airflow capacity, increasing power, and fan-risk drivers.
5. Show Room 1 receiving a higher grant because it is occupied and above target.
6. Show the decision reason codes and maintenance recommendation.

## Slide 5 — Predictive evidence

Show the reproducible synthetic-data workflow:

- feature schema;
- JSON logistic coefficients;
- holdout metrics;
- probability / low-medium-high threshold;
- top contributing drivers.

State clearly: the model is a simulation-pilot result, not a real-world maintenance claim.

## Slide 6 — Business value

Use a conservative ROI table with explicit assumptions for:

- annual HVAC energy baseline and tariff;
- expected energy reduction;
- avoided maintenance incidents;
- downtime cost per incident;
- sensors/gateway/implementation cost;
- recurring support cost;
- ROI and payback formulas.

## Slide 7 — Trust, security, and ethics

Commit to aggregate occupancy data, explainable actions, manual override, TLS / ACLs / audit logging, model monitoring, and human approval for high-impact changes.

## Slide 8 — Scalable roadmap

Simulation → digital shadow → human-in-the-loop recommendation → constrained automation → federated multi-building deployment.

End with the message: **the goal is not autonomous cooling alone; it is safe, explainable, measurable coordination across a facility ecosystem.**
