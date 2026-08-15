# EcoHVAC Guardian — Video Demo Script (Project 2 / HW2)

**Target length:** ~5–6 minutes
**Course Deliverable:** SUTD Digital Twin — Project 2 (Intelligent Ecosystem & Strategic Optimization)
**Format:** Screen recording with voice-over. Each scene lists on-screen visuals, user interactions, and narration.

---

## Pre-recording Checklist

1. **Start the Multi-Twin Stack:**
   ```bash
   # 1. Start Mosquitto broker (MQTT 1883, WS 9001)
   docker compose up -d

   # 2. Start Simulator Engine (Terminal 1)
   uv run python simulator/publisher.py

   # 3. Start 3D Operations Server (Terminal 2)
   uv run python -m http.server 8080 --directory room3d

   # 4. Start Streamlit Operations Dashboard (Terminal 3)
   ECOHVAC_3D_URL=http://localhost:8080 uv run streamlit run dashboard/app.py
   ```
2. **Open Browser Tabs:**
   - Operations Dashboard: `http://localhost:8501`
   - Unified 3D Two-Room View: `http://localhost:8080/room3d.html`
3. **Reset Baseline:** Ensure the dashboard loads in `baseline` state (`Safe`, `Online`, Low fan risk).
4. **Prepare Terminal for CLI Command Demo (Scene 6).**

---

## Scene 1 — Introduction & Ecosystem Architecture (0:00 – 0:50)

**On screen:** Integrated Architecture Diagram (`report/hw2-evidence/00-integrated-architecture.png`) or `docs/architecture.md`.

**Narration:**
> "Hello! Welcome to the demonstration of **EcoHVAC Guardian** — our Project 2 Digital Twin ecosystem for intelligent smart-laboratory HVAC operations.
>
> In Project 1, we simulated an isolated single room. For Project 2, we have expanded this into a complete **multi-twin ecosystem**: two independent laboratory classrooms (`Room 1` and `Room 2`) competing for cooling from a single, finite-capacity Air Handling Unit (AHU).
>
> Our architecture combines local PID comfort control, centralized deterministic fairness coordination under physical degradation, real-time energy accounting with simulated COP 3.2, explainable predictive maintenance via an inspectable logistic regression model, and synchronized 3D digital twin visualization."

**Action:** Hover cursor over the 6-layer architecture flow: Room Twins + Local PIDs $\rightarrow$ Fairness Coordinator $\rightarrow$ Shared AHU Physics $\rightarrow$ Predictive Model $\rightarrow$ MQTT Broker $\rightarrow$ Dashboard & 3D Viewer.

---

## Scene 2 — Operations Dashboard & Baseline State (0:50 – 1:40)

**On screen:** Streamlit Operations Dashboard at `http://localhost:8501` (`Operations centre` tab).

**Narration:**
> "This is the **Operations Centre**. At the top, live status strips confirm the simulator is `ONLINE`, shared capacity is `SAFE`, and fan risk is `LOW (15%)`.
>
> Below, we see both room twins running independently:
> - `Room 1` is occupied with 8 people, currently at 22.8 °C.
> - `Room 2` is occupied with 2 people, at 22.8 °C.
> - The shared AHU has clean filters (5% clog) and healthy fan condition (3% wear), comfortably supplying 80% airflow with zero capacity deficit.
>
> Notice that every telemetry update is backed by a monotonic snapshot ID and correlated timestamp over retained MQTT topics."

**Action:** Scroll through the top status cards, the Room 1 and Room 2 telemetry metrics, and the AHU supply airflow status.

---

## Scene 3 — Shared Capacity Stress Scenario (1:40 – 2:45)

**On screen:** Dashboard Guided Scenarios section.

**Narration:**
> "Now let's simulate a severe operational challenge: equipment degradation combined with high cooling demand.
>
> I will trigger the **'Run shared-capacity stress test'** preset."

**Action:** Click the **`Run shared-capacity stress test`** button.

**Narration:**
> "Instantly, the simulator applies the stress scenario:
> 1. Filter clog jumps to 85% and fan wear to 75%, derating AHU available supply airflow down to approximately 40%.
> 2. Simultaneously, Room 1 occupancy jumps to 24 students, creating a heavy 10.0 kW cooling request. Room 2 requests 3.5 kW.
>
> Notice how the system reacts: Total requested airflow now far exceeds available AHU supply air. The status immediately flips to **`CONSTRAINED`**."

**Action:** Show the status indicator change to `CONSTRAINED`, point to the gap between requested and granted airflow in the telemetry cards, and watch Room 1 temperature rise as cooling is constrained.

---

## Scene 4 — Deterministic Fairness Coordination & Comfort Debt (2:45 – 3:45)

**On screen:** Coordination & Allocation section of the dashboard.

**Narration:**
> "How does the system resolve this conflict?
>
> EcoHVAC Guardian employs our deterministic **`occupied-comfort-debt-v2`** coordination policy. Rather than naive static splitting, it dynamically arbitrates scarce air:
> 1. Occupied rooms receive absolute priority over unoccupied rooms.
> 2. Higher positive temperature error is prioritized.
> 3. Over time, under-served rooms accumulate **Comfort Debt** (in °C·seconds), ensuring long-term fairness and preventing starvation.
>
> Crucially, granted airflow is fed directly back into each room's PID controller. This **actuator feedback mechanism** bleeds down integral error and prevents controller windup while the physical asset is saturated."

**Action:** Point out the reason codes (`occupied`, `above_setpoint`, `capacity_limited`, `higher_comfort_priority_applied`) and the comfort debt tracking chart.

---

## Scene 5 — Predictive Intelligence & Explainable AI (3:45 – 4:35)

**On screen:** Switch to the **`Predictive intelligence`** tab.

**Narration:**
> "Next, let's look at predictive equipment health.
>
> In the Predictive Intelligence tab, our runtime **Logistic Regression Model** evaluates simulated 7-day fan failure probability. Under our stress scenario, risk has escalated to **63.0% (Medium Risk)**.
>
> Unlike a black-box AI, our model is fully explainable:
> - It exposes the exact signed **log-odds feature drivers**: high vibration (4.27 mm/s) and severe filter clogging (+85%) are the primary risk contributors.
> - It includes built-in domain validation: if sensor inputs are missing, corrupted, or out-of-domain, the model explicitly **abstains** rather than outputting a false sense of security.
> - As an ethical AI guardrail, this prediction serves as **human-in-the-loop advisory decision support**—it suggests inspection without making dangerous autonomous control overrides."

**Action:** Highlight the risk gauge (63%), the top log-odds drivers list, and the risk trajectory timeline.

---

## Scene 6 — Unified 3D Digital Twin & MQTT Control (4:35 – 5:15)

**On screen:** Tab over to `http://localhost:8080/room3d.html` (Unified 3D Room Scene).

**Narration:**
> "Here is our **Unified 3D Digital Twin Viewer**, built in Three.js and connected live over MQTT WebSockets.
>
> Both Room 1 and Room 2 are rendered simultaneously alongside the central AHU ducting. The visual environment reflects real-time physics:
> - Dynamic room heat maps on the floor change color based on temperature.
> - Animated occupants dynamically enter and exit as occupancy updates.
> - AHU duct airflow particles visually represent granted supply volume.
>
> Furthermore, all commands support idempotency and replay protection via correlated `command_id` envelopes."

**Action:** Orbit camera around the two rooms, show the connecting AHU ducts, and highlight the responsive WebSocket status.

---

## Scene 7 — Strategic Roadmap, ROI & Conclusion (5:15 – 5:45)

**On screen:** Return to Dashboard $\rightarrow$ **`Strategy & governance`** tab.

**Narration:**
> "Finally, the **Strategy & Governance** tab presents our deployment framework:
> - An interactive **ROI Sandbox** showing a realistic 33-month capital payback period.
> - A 5-stage deployment roadmap transitioning from this simulated prototype to a digital shadow, human-in-the-loop pilot, and eventual federated facility automation.
>
> In summary, EcoHVAC Guardian successfully integrates multi-twin simulation, fair closed-loop control, explainable machine learning, and interactive 3D visualization. Thank you for watching!"

**Action:** Briefly scroll the ROI calculator and the 5-stage roadmap, concluding on the title header.

---

## B-Roll / Defense Tips for Live Q&A

- **If asked about PID vs ML:** "The local PID and central coordinator handle real-time physical airflow allocation deterministically; the ML model provides explainable predictive maintenance advisory to facility operators."
- **If asked about test verification:** Run `uv run pytest` in terminal showing all 144 unit tests passing in ~0.4s.
- **If asked about security:** "Our classroom stack uses standard MQTT for development, but we have architected and documented the production target with TLS, topic ACLs, and hash-chained SQLite audit logging."
