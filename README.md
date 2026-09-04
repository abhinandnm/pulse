# PULSE — Autonomous AI Payment Reliability & Revenue Recovery Platform

[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.137.0-009688.svg)](https://fastapi.tiangolo.com/)
[![Tests Passing](https://img.shields.io/badge/tests-96%20passed-success.svg)](tests/)
[![Buildathon](https://img.shields.io/badge/Razorpay%20Buildathon-Track%2003%20Revenue%20Recovery-blueviolet.svg)](#)

> **PULSE** is an autonomous, mission-critical payment reliability platform designed for **Razorpay Buildathon — Track 03: AI Revenue Recovery**.
> It monitors live payment streams, detects sub-second success rate anomalies, quantifies real-time revenue at risk, performs grounded AI root-cause diagnosis, and autonomously orchestrates progressive canary rerouting ($20\% \rightarrow 50\% \rightarrow 100\%$) backed by 5 deterministic safety gates, route quarantine cooldowns, and anti-flapping circuit breakers.

---

## 🏛 System Architecture

```mermaid
flowchart TD
    subgraph INGESTION["1. Ingestion & Observer"]
        TX[Live Razorpay Stream / Webhooks] --> WIN[Thread-Safe Sliding Window]
        WIN --> METRICS[Metrics Calculator + Wilson CI]
        METRICS --> BASE[Adaptive EWMA Baselines]
    end

    subgraph DETECTION["2. Statistical Anomaly & Accountant"]
        METRICS --> DETECT[Statistical Anomaly Detector]
        DETECT -->|Breach Detected| ACC[Revenue Accountant]
        ACC -->|Quantified Loss| EXP[Financial Exposure Report]
    end

    subgraph DIAGNOSIS["3. Grounded AI Doctor"]
        DETECT --> DOC[Grounded AI Doctor]
        DOC --> TOOLS[Diagnostic Evidence Tools]
        DOC --> MEM[Incident Memory & Precedent]
        DOC --> DIAG[Structured AIDoctorDiagnosis]
    end

    subgraph DECISION["4. Counterfactual & Safety Policy"]
        DIAG --> CF[Counterfactual Engine]
        EXP --> CF
        CF --> FSM[Deterministic FSM (9 States)]
        FSM --> CANARY[Canary Safety Controller (5 Gates)]
    end

    subgraph ACTUATION["5. Autonomous Recovery & Protection"]
        CANARY -->|Pass 5 Gates| PROMOTE[Full 100% Traffic Promotion]
        CANARY -->|Gate Breach| ROLLBACK[Immediate Rollback & Quarantine]
        ROLLBACK --> ANTI[Anti-Flapping Backoff]
        PROMOTE --> RECOV[Prevented Revenue Quantified]
    end
```

---

## 🌟 Key Features & Track 03 Alignment

| Buildathon Requirement | PULSE Architectural Implementation |
| :--- | :--- |
| **Statistical Anomaly Detection** | Evaluates Wilson 95% confidence intervals, latency percentiles ($p_{50}, p_{90}, p_{95}, p_{99}$), timeout rate spikes, and bank issuer degradation vs. EWMA baselines. |
| **Revenue Exposure Quantification** | Implements $\text{Revenue At Risk} = \max(0, \text{Baseline\_SR} - \text{Current\_SR}) \times \text{Volume} \times \text{AOV}$. Generates 1-hour and 24-hour projected exposure flags. |
| **Grounded AI Doctor** | Diagnostic tool-use querying route health, error distributions, and historical memory. Outputs strictly verified `AIDoctorDiagnosis` schemas without raw chain-of-thought hallucinations. |
| **Progressive Canary Deployment** | Automated multi-stage rollout ($20\% \rightarrow 50\% \rightarrow 100\%$) evaluated against 5 deterministic safety gates (Sample Size, SR Delta, Wilson Bound, Latency SLO, Error Cap). |
| **Blast Radius & Anti-Flapping** | Route quarantine with exponential backoff ($60\text{s} \times 2^{\text{flap\_count}}$) and hysteresis deadbands ($85\%$ degrade / $95\%$ recover) to halt route ping-pong. |
| **Razorpay Test Mode Integration** | Isolated adapter handling Orders, Payments, and strict cryptographic HMAC SHA256 webhook signature verification (`X-Razorpay-Signature`). |
| **Real-Time Dashboard** | 100ms high-frequency WebSocket stream driving an interactive dark-mode glassmorphic UI with one-click sandbox failure injection. |

---

## 🚦 The 5 Deterministic Canary Safety Gates

During progressive canary rollout, PULSE validates candidate route health across 5 deterministic criteria before advancing:

1. **`MIN_SAMPLE_SIZE`**: Holds canary in `PENDING` until statistically significant transaction volume ($N \ge 25$) is recorded.
2. **`SUCCESS_RATE_DELTA`**: Enforces strict candidate success rate ($\ge 90\%$).
3. **`WILSON_LOWER_BOUND`**: Ensures the statistical lower bound of the 95% Wilson confidence interval exceeds the safety floor.
4. **`LATENCY_SLO`**: Enforces $p_{95} \le 1000\text{ms}$ to prevent downstream latency degradation.
5. **`ERROR_RATE_CAP`**: Restricts allowable error rate to $\le 8\%$.

> **Autonomous Rollback**: If **any** gate is breached at any stage, traffic is immediately reverted to $0\%$, the candidate route is quarantined, and the system restores the fallback route.

---

## ⚡ Quickstart & Running PULSE

### 1. Run the Automated Demo Pitch Walkthrough
Demonstrates the full autonomous recovery loop in the CLI:
```powershell
python run_demo.py
```

### 2. Start the Live Server & Real-Time Dashboard
Launches the FastAPI server and serves the real-time glassmorphic dashboard:
```powershell
python run_demo.py --server
```
Then navigate to: **[http://localhost:8000](http://localhost:8000)** (or `http://localhost:8000/dashboard/`)

### 3. Run the Full Test Suite
Runs all 96 unit, integration, and adversarial tests:
```powershell
python -m pytest tests/ -v
```

---

## 📊 Test Suite & Verification Matrix

PULSE is thoroughly tested across 17 modular bricks:

```text
============================= test session starts =============================
tests/test_accountant/test_revenue_at_risk.py .............. [4 passed]
tests/test_adversarial/test_stress_and_adversarial.py ...... [5 passed]
tests/test_api/test_fastapi_endpoints.py ................... [9 passed]
tests/test_canary/test_safety_gates.py ..................... [4 passed]
tests/test_counterfactual/test_decision.py ................. [2 passed]
tests/test_demo/test_pitch_demo.py ......................... [1 passed]
tests/test_doctor/test_ai_doctor.py ........................ [3 passed]
tests/test_doctor/test_evidence_tools.py ................... [6 passed]
tests/test_domain/test_contracts.py ........................ [17 passed]
tests/test_engine/test_control_loop.py ..................... [5 passed]
tests/test_fsm/test_state_machine.py ....................... [3 passed]
tests/test_memory/test_incident_memory.py .................. [4 passed]
tests/test_observer/test_anomaly.py ........................ [7 passed]
tests/test_observer/test_telemetry.py ...................... [10 passed]
tests/test_safety/test_quarantine_flapping.py .............. [4 passed]
tests/test_simulator/test_simulation.py .................... [12 passed]
============================= 96 passed in 0.85s ==============================
```

---

## 📁 Repository Structure

```text
├── pulse/
│   ├── accountant/        # Track 03 Revenue-At-Risk & Prevented Loss Engine
│   ├── api/               # FastAPI REST endpoints, WebSockets, & Razorpay Adapter
│   ├── canary/            # Multi-stage Canary Controller & 5 Safety Gates
│   ├── counterfactual/    # Counterfactual Utility Evaluator
│   ├── dashboard/         # Real-time Glassmorphic Dashboard (HTML/CSS/JS)
│   ├── doctor/            # Grounded AI Doctor & Diagnostic Evidence Tools
│   ├── domain/            # Core Pydantic Contracts, Enums, & Events
│   ├── engine/            # Autonomous Control Loop Engine
│   ├── fsm/               # Deterministic 9-State Finite State Machine
│   ├── memory/            # Operational Incident Memory & Similarity Retriever
│   ├── observer/          # Sliding Window, Metrics, & Anomaly Detector
│   ├── safety/            # Route Quarantine & Anti-Flapping Controller
│   └── simulator/         # Seeded Deterministic Payment Simulator & 8 Failures
├── tests/                 # 96 automated tests covering all 17 bricks
├── notes/
│   └── BRICKS.txt         # Master 17-brick buildathon specification
├── run_demo.py            # CLI Demo Pitch Runner & Web Server launcher
└── README.md              # Project documentation & submission report
```
