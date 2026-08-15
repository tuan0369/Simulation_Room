# Smart Lab 4-Zone Multi-Twin Ecosystem Architecture

This document specifies the complete 6-layer cyber-physical architecture for **EcoHVAC Guardian**, an intelligent multi-twin ecosystem operating across a **4-Zone Smart Wing** (`Room 1` Lecture Hall, `Room 2` Robotics Lab, `Room 3` Seminar Room, `Room 4` Computing Hub) served by a central Variable Air Volume (VAV) Air Handling Unit ($0.480\text{ m}^3\text{/s}$ nominal capacity).

---

## Six-Layer Multi-Twin Architecture

```mermaid
flowchart TB
    subgraph L6["6. Presentation & Spatial 3D Twin Layer"]
        DASH["Streamlit Operations Dashboard (Port 8501)\n5-Stage Pipeline · Segmented AHU Bar · 2x3 Scenario Presets · Financial ROI"]
        ROOM3D["Three.js 4-Zone 3D WebGL Twin (room3d.html:8000)\n4 Holographic Billboards · Neon Particle Streams · Diffusers · AHU Beacon · HUD Toggle (H)"]
    end

    subgraph L5["5. Governance, Security & Knowledge Management Layer"]
        AUDIT["SHA-256 Cryptographic Audit Ledger\nImmutable Hash-Chain SQLite Journal · Monotonic Sequence Verification"]
        KB["Self-Learning Knowledge Hub & HITL Sign-Off\nCandidate Queue ➔ Reviewer Notes & Approval ➔ SQLite Approved Catalog"]
        CAPEX["Strategic ROI & Equipment Retrofit Advisory\n5-Yr Cash Flow (Month 33 Breakeven ★) · Option A (0.75m³/s AHU) vs Option B (3.5kW Split)"]
    end

    subgraph L4["4. Real-Time Event & Messaging Fabric Layer"]
        MQTT["Mosquitto MQTT Message Broker (TCP 1883 / WS 9001)\nStrict Topic Hierarchy: twin/{room1..4, ahu, ecosystem}/*"]
        GUARD["Idempotency & Replay Attack Protection\n1,024-Command Deduplication Cache · Physical Clamp Guards (18–30°C, P ≤ 250W)"]
    end

    subgraph L3["3. Ecosystem Intelligence & Multi-Twin Models Layer"]
        COORD["Centralized Coordinator\noccupied-comfort-debt-v2 Dynamic Lexicographic Priority Queue"]
        ML["Predictive Logistic Failure Model\nN=2,400 Episodes, ROC-AUC 0.8449, Accuracy 80.42% + 30% OOD Envelope"]
        ODE["Forward Thermal Trajectory ODE Solver\n+5m & +15m Forecasting · Sensible Occupant (100W/person) & Equipment Heat"]
        TEST["15-Tick Automated Verification Test Suite\nComfort (≤1°C) · Fan Risk (<40%) · Power (≤250W) · Starvation Debt (≤20°C·s)"]
    end

    subgraph L2["2. Local Actuation & Anti-Windup Control Layer"]
        PID1["PID Room 1 (Lecture Hall, 30 cap)\nAirflow Request + Actuator Feedback Bleed"]
        PID2["PID Room 2 (Robotics Lab, 20 cap)\nAirflow Request + Actuator Feedback Bleed"]
        PID3["PID Room 3 (Seminar Room, 15 cap)\nAirflow Request + Actuator Feedback Bleed"]
        PID4["PID Room 4 (Computing Hub, 20 cap)\nAirflow Request + Actuator Feedback Bleed"]
    end

    subgraph L1["1. Physical & Simulated 4-Zone Facility Layer"]
        R1["Room 1: Lecture Hall\nV=200m³, Cth=600kJ/K, Cap: 30 students"]
        R2["Room 2: Robotics Lab\nV=140m³, Cth=420kJ/K, Cap: 20, +400W equip"]
        R3["Room 3: Seminar Room\nV=100m³, Cth=300kJ/K, Cap: 15 students"]
        R4["Room 4: Computing Hub\nV=140m³, Cth=420kJ/K, Cap: 20, +600W servers"]
        AHU["Central VAV AHU (0.480 m³/s)\nFilter Clog (0–100%) · Vibration (0.4–5.65mm/s) · Bearing Temp (28–86°C) · Run Hours · COP 3.20"]
    end

    R1 --> PID1
    R2 --> PID2
    R3 --> PID3
    R4 --> PID4

    PID1 --> COORD
    PID2 --> COORD
    PID3 --> COORD
    PID4 --> COORD

    COORD --> AHU
    AHU --> R1
    AHU --> R2
    AHU --> R3
    AHU --> R4

    COORD -. Granted Output Bleed .-> PID1
    COORD -. Granted Output Bleed .-> PID2
    COORD -. Granted Output Bleed .-> PID3
    COORD -. Granted Output Bleed .-> PID4

    AHU --> ML
    AHU --> TEST
    R1 & R2 & R3 & R4 --> ODE

    R1 & R2 & R3 & R4 & AHU & COORD & ML & TEST --> MQTT
    MQTT <--> GUARD
    GUARD <--> AUDIT & KB & CAPEX
    MQTT --> DASH & ROOM3D
    DASH & ROOM3D -. Operator Commands .-> MQTT
```

---

## 4-Zone Cyber-Physical Room Specifications

| Room / Asset | Physical Role | Volume ($V$) | Thermal Capacitance ($C_{\text{th}}$) | Max Occupancy | Internal Baseline Heat | PID Parameters ($K_p, K_i, K_d$) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **Room 1: Lecture Hall** | Tiered amphitheater lecture classroom | $200\text{ m}^3$ | $600\text{ kJ/K}$ | 30 students | $450\text{ W}$ | $K_p=0.45, K_i=0.008, K_d=0.12$ |
| **Room 2: Robotics Lab** | Experimental robotics testbed & assembly | $140\text{ m}^3$ | $420\text{ kJ/K}$ | 20 students | $850\text{ W}$ (+400W robotics) | $K_p=0.50, K_i=0.010, K_d=0.15$ |
| **Room 3: Seminar Room** | Collaborative breakout & presentation room | $100\text{ m}^3$ | $300\text{ kJ/K}$ | 15 students | $350\text{ W}$ | $K_p=0.40, K_i=0.007, K_d=0.10$ |
| **Room 4: Computing Hub** | High-density workstation cluster & servers | $140\text{ m}^3$ | $420\text{ kJ/K}$ | 20 students | $1,050\text{ W}$ (+600W servers) | $K_p=0.55, K_i=0.012, K_d=0.18$ |
| **Central VAV AHU** | Shared supply plenum cooling infrastructure | $0.480\text{ m}^3\text{/s}$ max flow | $T_{\text{supply}}=16.0^\circ\text{C}$ | Whole Wing | EC Plug Fan ($P=250\text{W}\cdot\text{speed}^3$) | $\text{COP}=3.20, 0.408\text{ kg CO}_2\text{e/kWh}$ |

---

## Dynamic Resource Allocation: `occupied-comfort-debt-v2`

For every running simulation tick ($dt = 1.0\text{ s}$):
1. **Zero-Demand Filtering:** Rooms with disabled HVAC request $0.0\text{ m}^3\text{/s}$.
2. **Occupancy Prioritization:** Occupied zones strictly outrank empty rooms ($\text{is\_occupied} = 1 > 0$).
3. **Thermal Error Ranking:** Zones with active overheating error ($e_T = \max(0, T_{\text{room}} - T_{\text{setpoint}})$) take priority.
4. **Comfort Debt Shield:** Unserved or starved rooms accumulate comfort debt ($D_{\text{comfort}}$ in $^\circ\text{C}\cdot\text{s}$), dynamically promoting constrained rooms to prevent persistent student starvation.
5. **Capacity Slicing:** Available AHU supply capacity ($q_{\text{available}} \le 0.480\text{ m}^3\text{/s}$) is granted in rank order until exhausted.
6. **Actuator Feedback Anti-Windup:** When granted airflow is less than requested airflow ($q_{\text{granted}} < q_{\text{demanded}}$), the local PID controller bleeds its accumulated integral error, eliminating temperature overshoot (+4.5°C) upon capacity recovery.