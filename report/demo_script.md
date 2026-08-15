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
   - Unified 3D 4-Room View: `http://localhost:8080/room3d.html`
3. **Reset Baseline:** Ensure the dashboard loads in `baseline` state (`Safe`, `Online`, Low fan risk).
4. **Prepare Terminal for CLI Command Demo if needed.**

---

## Scene 1 — Introduction & 4-Zone Smart Wing Architecture (0:00 – 0:50)

**On screen:** Integrated Architecture Diagram (`report/hw2-evidence/00-integrated-architecture.png`) or `docs/architecture.md`.

**Narration:**
> "Hello! Welcome to the demonstration of **EcoHVAC Guardian** — our Project 2 Digital Twin ecosystem for intelligent smart-laboratory HVAC operations.
>
> In Project 1, we simulated an isolated single room. For Project 2, we have expanded this into a complete **4-Zone Smart Wing Ecosystem**:
> - `Room 1`: Large Lecture Hall (30 seats)
> - `Room 2`: Robotics Lab (20 seats, +400W equipment heat)
> - `Room 3`: Seminar Room (15 seats)
> - `Room 4`: Computing Hub (20 seats, +600W server heat)
> All four zones share cooling capacity from a single central VAV Air Handling Unit ($0.48\text{ m}^3\text{/s}$ nominal capacity).
>
> Our architecture combines local anti-windup PID control, centralized deterministic fairness coordination under physical degradation, explainable machine-learned fan risk prediction, a 5-stage predictive risk pipeline, and synchronized 3D WebGL spatial visualization."

**Action:** Hover cursor over the architecture flow: 4 Room Twins $\rightarrow$ Fairness Coordinator $\rightarrow$ Shared VAV AHU $\rightarrow$ ML Predictive Risk $\rightarrow$ MQTT Broker $\rightarrow$ Dashboard & 3D Spatial Twin.

---

## Scene 2 — Operations Centre, 5-Stage Pipeline & Resource Map (0:50 – 1:50)

**On screen:** Streamlit Operations Dashboard at `http://localhost:8501` (`Operations centre (with 3D Twin)` tab).

**Narration:**
> "This is the **Operations Centre**. Directly above the 3D map is our **5-Stage HVAC Predictive Risk, Coordination & Solution Pipeline**:
> 1. **Step 1: Sensing** — Real-time 4-zone headcount (42 people) and sensible heat (5.1 kW).
> 2. **Step 2: Prediction** — Predictive cooling demand ($0.241\text{ m}^3\text{/s}$) and ML fan risk ($2\%$).
> 3. **Step 3: Coordinator** — Deterministic comfort-debt priority dispatch to eliminate starvation.
> 4. **Step 4: Solution** — Target mitigation formulation (Preemptive Pre-Cooling).
> 5. **Step 5: Verify & Learn** — Automated 4-part verification testing and self-learning knowledge cataloging.
>
> Immediately below is the **AHU Airflow Resource Distribution Map** — a color-segmented bar showing blue for Room 1, cyan for Room 2, purple for Room 3, amber for Room 4, and gray for reserve margin."

**Action:** Scroll through the 5 pipeline boxes, the segmented distribution bar, and the embedded 3D spatial twin below.

---

## Scene 3 — Multi-Room Stress Scenario & Thermal Saturation (1:50 – 2:50)

**On screen:** Guided Scenarios & Interactive 4-Zone Occupancy Injector.

**Narration:**
> "Now let's simulate complex multi-room loading. I will trigger the **'📝 Campus Exam (75 ppl)'** preset, or set Room 3 to 14 occupants and Room 4 to 16 occupants."

**Action:** Click the **`📝 Campus Exam (75 ppl)`** button or adjust Room 3 / Room 4 sliders.

**Narration:**
> "Notice the instantaneous multi-room response:
> 1. Total 4-zone cooling demand surges past available AHU capacity.
> 2. The Resource Distribution Map immediately renders a yellow **Capacity Deficit Alert**.
> 3. The coordinator enforces comfort-debt shielding to balance airflow fairly across all 4 zones."

---

## Scene 4 — Autonomous Agent, Popup Banner & 4-Test Verification (2:50 – 4:00)

**On screen:** Active Mitigation Recommendations section.

**Narration:**
> "The dashboard displays tailored recommendations for every room: `Execute for ROOM1`, `Execute for ROOM2`, `Execute for ROOM3`, and `Execute for ROOM4`.
>
> When we toggle **'Autonomous Action Mode 🤖'**:
> 1. The agent automatically detects the thermal threat and applies a verified policy from the Knowledge Hub.
> 2. A prominent **Green Notification Pop-up Banner** and browser Toast appear: *'AUTONOMOUS AGENT ACTIVE · KNOWLEDGE BASE POLICY APPLIED — Preemptive Precool (ROOM3)'*.
> 3. The agent tracks the policy across a 15-tick live evaluation window.
> 4. Once complete, the policy passes all 4 automated unit tests: Comfort preservation (0% error), Equipment safety (98%), Energy coherence (96%), and Coordination fairness (95%) — and is cataloged in the Knowledge Base."

**Action:** Toggle **`Autonomous Action Mode 🤖`**, point to the green Pop-up Banner, progress bar, and toast popup.

---

## Scene 5 — Thermodynamic Limit & CapEx Equipment Retrofit Advisory (4:00 – 4:50)

**On screen:** Equipment Retrofit & CapEx Sizing Advisory card.

**Narration:**
> "When software optimization reaches the **physical thermodynamic limit** ($>8.5\text{ kW}$ peak sensible heat, requiring $>0.55\text{ m}^3\text{/s}$ airflow beyond AHU capacity):
> The system automatically generates a **CapEx Equipment Retrofit Advisory**:
> - **Option A:** Upgrade central VAV AHU to $0.75\text{ m}^3\text{/s}$ (~S$12.5k, 1.8-year payback).
> - **Option B:** Add a dedicated $3.5\text{ kW}$ Inverter Split-Unit for Room 4 Computing Hub (~S$2.8k, 11-month payback).
> This empowers facility managers with automated engineering evidence for capital investments."

**Action:** Highlight the Option A / Option B ROI comparison on the dashboard.

---

## Scene 6 — Governance, SHA-256 Audit Trail & Conclusion (4:50 – 5:30)

**On screen:** `Strategy & Governance` tab and `Self-Learning Knowledge Hub`.

**Narration:**
> "All autonomous actions and telemetry records are sealed in an append-only **SHA-256 Cryptographic Audit Ledger** and strictly comply with Zero-PII privacy standards.
>
> With **161 / 161 automated unit and integration tests passing** (100% pass rate in 1.78s), EcoHVAC Guardian delivers a production-grade, self-learning Cyber-Physical Twin ecosystem.
>
> Thank you for watching!"

**Action:** Show the Knowledge Hub table, the cryptographic audit trail, and terminal test summary.
