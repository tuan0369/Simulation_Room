# Project 2 release evidence

## Provenance

- Source branch: `feat/intelligent-ecosystem`
- Source HEAD: `3187e93981d41ec2b84263559ab8c170069feef4`
- Working tree at validation: **dirty**
- Release status: pre-final-commit evidence; refresh hashes and source state after the intended commits.

This directory contains only newly generated evidence for the current Project 2 working tree. It does not claim that the current HEAD alone contains the validated code because implementation and artifact changes were uncommitted.

## Evidence inventory

| Evidence | Path | Result |
|---|---|---|
| Full pytest console | `tests/pytest-console.txt` | 145 passed |
| JUnit XML | `tests/pytest-junit.xml` | 145 tests, 0 failures/errors/skips |
| Tool and runtime versions | `environment/tool-versions.txt` | Captured, sanitized |
| Source branch/HEAD/dirty status | `environment/source-state.txt` | Dirty working tree disclosed |
| Artifact hashes | `artifacts/sha256-manifest.json`, `artifacts/SHA256SUMS` | SHA-256 generated |
| Notebook execution console | `notebook/execution-console.txt` | Completed |
| Notebook validation summary | `notebook/validation-summary.json` | PASS, 11/11 code cells, 0 errors |
| Compose validation | `broker/compose-validation.txt` | PASS |
| Raw MQTT transcript | `broker/scenario/mqtt-transcript.txt` | Captured |
| Machine-readable MQTT capture | `broker/scenario/mqtt-capture.jsonl` | Captured |
| Scenario validation manifest | `broker/scenario/scenario-manifest.json` | PASS |
| Fresh-subscriber retained recovery | `broker/scenario/retained-recovery.txt` | PASS |
| Simulator console | `broker/scenario/publisher-console.txt` | Runtime transcript (may be empty because stdout was buffered before controlled stop) |

## Live broker scenario result

A real local MQTT integration was executed against the default classroom Compose broker and the current simulator publisher.

1. Correlated `shared_capacity_stress` command was accepted and applied.
2. The coordinator reported `constrained=true`: requested airflow `0.32 m3/s` exceeded available airflow `0.0953 m3/s`; Room 1 received a constrained `0.0953 m3/s` grant and Room 2 received `0.0 m3/s` in the captured stress snapshot.
3. Correlated `pause` command was accepted and applied. Two successive paused snapshots showed zero instantaneous airflow, fan speed, room thermal cooling, and electrical power; cumulative energy remained `0.0006 kWh` in both snapshots.
4. Correlated `baseline` command was accepted and applied, restoring the baseline scenario and running mode.
5. A fresh subscriber received retained baseline scenario and presentation state, proving retained-state recovery.
6. The simulator and capture subscriber started for this run were stopped. The Mosquitto container was already running before validation and was therefore left running rather than disrupting a pre-existing service.

## Project 1 media explicitly excluded

The following repository media are legacy Project 1 material and are **not** Project 2 release evidence and are not hashed or copied here:

- `report/Digital_Twin_Project1_Report.pptx`
- `report/digital-twin demo.mov`
- `report/smart-lab-digital-twin.mp4`
- `report/demo/`
- `report/video-demo/`
- `report/assets/`

No browser/playwright captures, runtime audit databases, caches, credentials, broker data, or broker logs are included.

## Limitations

- This evidence validates a dirty working tree, not a final commit. Refresh the source-state file and SHA-256 manifests after commits.
- The default classroom broker permits anonymous plaintext MQTT and is suitable only for local teaching/demo use.
- Notebook execution used the available Jupyter kernel environment rather than the project virtual environment because notebook execution dependencies were not installed in the latter.
- The raw simulator console file is empty due to buffered stdout at controlled termination; application behavior is independently recorded in the broker transcript and JSONL capture.
