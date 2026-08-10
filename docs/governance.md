# Governance, Security and Ethics

What this system is allowed to do, what it must not do, and what is currently
unsafe about it.

---

## 1. Security posture — the honest starting point

**The pilot as built is not secure, and this section does not pretend otherwise.**

| Weakness | Where | Risk today |
|---|---|---|
| `allow_anonymous true` | `mosquitto/config/mosquitto.conf` | Anyone reaching port 1883 can publish any command to any room |
| No TLS | Ports 1883 / 9001 | Telemetry and commands are plaintext on the wire |
| No per-topic ACLs | Broker | A compromised room twin can publish as any other twin |
| Tokenless Jupyter | `jupyter` compose service | Remote code execution for anyone who reaches the port |
| Working tree over HTTP | `room3d` service serves `/app` | Source and data readable by anyone who reaches port 8000 |

Two are already mitigated by binding: Jupyter and the static server publish only
to `127.0.0.1`, and Jupyter sits behind an opt-in compose profile so it does not
start by default. The broker is **deliberately left open** because this is a
single-machine simulation — and that decision is exactly what must not survive
contact with a real building.

### Threat model

| Threat | Vector | Consequence | Mitigation for production |
|---|---|---|---|
| **Command injection** | Publish to `twin/+/+/cmd/hvac` | Attacker disables cooling in a wet lab; samples spoil | mTLS client certificates; per-topic ACLs so only the UI identity may publish `cmd/*`; signed payloads with a nonce |
| **Sensor spoofing** | Publish fake `temperature` | Twins act on false readings; the model scores garbage | Publisher identity bound to topic subtree by ACL; reject readings whose rate of change is physically impossible |
| **Occupancy exfiltration** | Subscribe to `twin/#` | Attendance patterns per room, per hour — personal-adjacent data | ACL-restrict occupancy topics; publish only aggregates off-floor (already the design, see §4) |
| **Model poisoning** | Feed tampered telemetry over months | Model learns attacker-chosen thresholds | Retraining gated on human review of the fairness audit and drift report; never auto-deploy |
| **Denial of service** | Flood the broker | Twins run blind | Rate limits per client; twins already keep local physics and survive broker loss |
| **Malformed payload** | Junk on any `cmd/` topic | Crash the simulator | **Already handled** — malformed commands are ignored, never raised, and tests enforce it |

### Production hardening checklist

1. TLS on 8883 (MQTT) and WSS (WebSocket); retire 1883/9001.
2. Per-twin client certificates; identity bound to topic subtree.
3. ACLs: a room twin may publish only `twin/{its floor}/{its room}/#`, and only
   the dashboard identity may publish `cmd/*`.
4. Signed command payloads with nonce and expiry, to stop replay.
5. Broker-side rate limiting per client.
6. Append-only audit log of every command: topic, payload, publisher identity,
   timestamp. **A maintenance action that changes physical equipment must be
   attributable to a person.**
7. Network segmentation: the OT segment is not routable from the office LAN.

Item 6 is the one that matters most for this system specifically, because a work
order dispatches a human to physically service equipment.

---

## 2. Algorithmic transparency

Every risk message carries the evidence for its own claim:

```json
{"failure_prob": 0.4954, "likely_fault": "osf", "top_factor": "runtime_hours",
 "explanation": "running hours past the rated service interval",
 "thermal_guard": 0.0, "alert_source": "model", "rul_hours": 0.0,
 "threshold": 0.00528, "model_version": "1.0.0",
 "history_samples": 72, "history_full": true}
```

- **`model_version`** on every message, so a stale retained message is
  identifiable.
- **`top_factor` and `explanation`** — the dashboard never shows a bare
  probability. A number with no provenance is the transparency failure this
  section exists to prevent.
- **`alert_source`** distinguishes the ML model from the thermal guard, so a
  technician knows which system spoke.
- **`threshold` travels with the score**, because it is derived from a cost
  curve rather than being a convention. An earlier build hardcoded a guess in the
  consumer and silently dropped every work order.
- **`history_samples`** says how much context backed the score — a
  freshly-serviced unit is scored from a short window, and a consumer can tell.

The dashboard's maintenance page states the model's limitations **in the UI**,
not only in the model card: that it is blind to heat-dissipation failure alone,
that Wet Lab A is inadequately covered, that it is trained on simulated data, and
that it never switches anything off.

Full detail, including the decision-threshold rationale:
[`ml/models/model_card.md`](../ml/models/model_card.md).

---

## 3. Bias and fairness

A full audit is in the model card §5.

| Room | Dominant fault | Positive rate | PR-AUC | Recall | Precision |
|---|---|---|---|---|---|
| `f1/lab-a` | airflow | 3.34 % | 0.980 | 0.992 | 0.700 |
| `f1/lab-b` | bearing | 1.79 % | 0.995 | 0.998 | 0.836 |
| `f1/server-room` | overstrain | 4.25 % | 0.978 | 1.000 | 0.849 |
| `f2/lab-c` | heat dissipation | 2.73 % | **0.679** | 0.953 | **0.462** |
| `f2/meeting-room` | power | 4.39 % | 0.995 | 0.999 | 0.812 |

### A correction we are documenting rather than quietly deleting

An earlier version of this system had a **100 % false-negative rate on Wet Lab A**
— it missed every failure in the room where an outage costs most. That is
recorded here because how it was found and fixed matters more than the number
that replaced it.

The cause was never room identity. Identity (`twin_id`, `floor`, `room_profile`,
`segment_id`) is excluded from the feature set by construction, enforced by
`test_no_identity_column_is_a_feature`, and a second test feeds two *different*
rooms identical condition data and asserts identical scores.

The real cause was **mode starvation**: all six units had been modelled with
identical wear characteristics, so one failure mode accounted for ~90 % of
positives and the rarest had about two training examples. Giving each unit a
distinct wear character — as real buildings have — supplied hundreds of examples
of every mode, and recall on the affected room went from 0.000 to 0.992.

**The generalisable point: a model blind to a subgroup is usually being starved
of it, not badly tuned.** Reaching for a fairness-specific fix before checking
the data distribution would have papered over it.

### What disparity remains

Detection is now even (recall 0.95–1.00 everywhere). The remaining gap is in
**precision and ranking quality**: `f2/lab-c` scores PR-AUC 0.679 and precision
0.462, so roughly half its work orders are unnecessary.

That room is a teaching lab, where a missed or spurious alert is disruptive
rather than dangerous. **That is fortunate, not designed** — nothing in the
system arranges for its weakest coverage to land on its least critical room, and
a future retraining could move the weakness somewhere worse. This is a reason to
repeat the audit after every retraining, not a reason to relax.

### Still outstanding

- At `f2/lab-c`'s precision, alert fatigue is a real risk. The decision threshold
  should be re-derived against real dispatch costs before that room's alerts are
  acted on automatically.
- Generalisation to unseen equipment is weak (PR-AUC 0.26). A newly commissioned
  unit is not adequately covered until it has contributed its own history.

We do not claim to have solved fairness. We claim to have measured it, found a
severe failure, fixed its actual cause, published both states, and named what is
still wrong.

---

## 4. Privacy

Occupancy counts are **personal-adjacent data**. "Six people were in the meeting
room at 14:00 on Tuesday" is, in a small organisation, close to identifying.

| Principle | How it is implemented |
|---|---|
| No identities | Twins carry counts only. There is no person entity, no badge id, no device id anywhere in the system |
| Data minimisation off-floor | Floor summaries publish totals; the building twin never receives per-room occupancy |
| Locality | The federated design keeps occupancy in the room twin that produced it. A centralised controller would pull every record to one place — this is a privacy argument for the architecture, not only a resilience one |
| Retention | Dashboard buffers are bounded deques (~12 min). Nothing persists occupancy to disk in the live system |
| Training data | `building_telemetry.csv` contains occupancy counts. It is git-ignored and synthetic; a real deployment must treat the equivalent file as personal data under retention policy |

The last row is the one a real deployment gets wrong most easily: the *model
training set* is where occupancy history quietly accumulates.

---

## 5. Human oversight and bounded autonomy

The system has exactly two autonomous powers, and both are bounded.

**1. Room twins actuate their own HVAC.** Bounded by physical limits and by the
setpoint range (18–30 °C). This is ordinary thermostat autonomy.

**2. Supervisory twins may nudge a setpoint.** Bounded at **1.5 °C**, and the
bound is enforced by the *room*, not by the supervisor that sent the advice
(`test_room_clamps_an_oversized_advisory`). Nudges may only make a room warmer,
never colder, so load shedding cannot be inverted into a demand spike. Critical
loads are exempt from shedding entirely.

**3. Autonomous preventive maintenance — opt-in, OFF by default.**

The system can be configured to dispatch servicing without waiting for approval.
This is a deliberate, bounded delegation, not an erosion of the rule above:

| Bound | Value |
|---|---|
| Default state | **Disabled**. Autonomy must be switched on, never inherited |
| Permitted actions | `replace_filter`, `service_motor` — **preventive only** |
| Forbidden | Anything that stops cooling, changes a setpoint, or takes a room out of service |
| Rate limit | At most one automatic service per unit per 24 h |
| Auditability | Every automatic dispatch is still published to `twin/building/advisory`, flagged `auto_dispatched: true` |
| Switch | `twin/building/cmd/autofix`, and a labelled dashboard toggle that warns while it is on |

The distinction that makes this acceptable: **replacing a filter is additive to
safety; shutting a unit down is not.** The worst outcome of a false positive here
is an unnecessary service visit — the same failure mode as an over-eager
calendar, and one the cooldown bounds. An action that could *remove* cooling from
a lab would carry an entirely different risk profile and is not eligible at any
setting.

`inspect` is never auto-dispatched, because the twin cannot inspect anything.

**Without that toggle, the model has no autonomous power at all.** It opens
tickets, every advisory carries `requires_human_approval: true`, and the
dashboard's approve button is the only path from a prediction to a physical
action.

### What the system must never be allowed to do

- Shut down a unit on a model score — **at any autonomy setting**.
- Change a setpoint on a model score.
- Retrain and self-deploy without human review of the fairness audit.
- Raise a setpoint beyond the room's own limit, whatever a supervisor requests.
- Act on a score whose `model_version` it cannot resolve.
- Auto-dispatch more often than the cooldown permits, however high the score.

---

## 6. Known governance debt

Carried openly rather than buried:

1. Broker is anonymous and unencrypted (§1) — pilot-only.
2. No audit log of commands yet.
3. No drift monitoring; a maintenance-policy change would invalidate the model
   silently.
4. Cost assumptions behind the decision threshold (€2,000 / €150) are estimates,
   not measurements, and the ROI case inherits that.
5. Models are trained on simulated telemetry and must be recalibrated on ≥3
   months of real data before any output is trusted.
