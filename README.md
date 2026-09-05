# PULSE — Autonomous AI Payment Reliability & Revenue Recovery

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.137.0-009688.svg)](https://fastapi.tiangolo.com/)
[![Track 03](https://img.shields.io/badge/Razorpay%20Buildathon-Track%2003%20Revenue%20Recovery-blueviolet.svg)](#)

> **PULSE** is an autonomous, closed-loop AI system that protects payment revenue. When payment gateways degrade or bank CBS systems fail, PULSE **detects the outage, diagnoses the root cause using AI, and safely migrates checkout traffic to backup gateways in seconds—with zero human intervention.**

---

## 💡 The Core Problem in 30 Seconds

Think of a payment system like a **city during rush hour**:
* Every payment is a **car**.
* Every payment gateway (PSP) is a **highway**.
* When a customer clicks *"Pay Now"*, PULSE decides which highway that car should travel on.

Normally, when a payment gateway starts failing, existing monitoring tools only fire a dumb alert:  
*“Payment failures are high!”*  
Then, an on-call engineer has to wake up in the middle of the night, manually investigate logs, and decide whether to switch routes. That delay costs **tens of thousands of rupees in lost sales every minute**.

Even worse, if a system **blindly dumps 100% of traffic** onto a backup gateway all at once, the sudden surge can **crash the backup gateway too** (a cascading failure).

---

## ⚙️ How PULSE Works (The 3-Step Solution)

PULSE replaces the manual, slow human loop with an autonomous **Detect ➔ Diagnose ➔ Recover** cycle:

```
[ 1. OBSERVE ]               [ 2. DIAGNOSE ]                  [ 3. RECOVER ]
Live Transactions ──▶  AI Doctor Investigates ──▶  Safe Canary Swapping
(Wilson Confidence)     (Error Logs & Root Cause)   (20% ➔ 50% ➔ 100% Rollout)
```

### 1. 👁️ The Observer: Smart Detection (No False Alarms)
* Monitors payment streams in real time across all gateways.
* Instead of panicking over a single failed card or temporary network glitch, it uses **Wilson Score statistical intervals**.
* It only triggers when there is mathematically verified degradation, cutting out false-positive alerts.

### 2. 🩺 The AI Doctor: Root-Cause Diagnosis + Revenue Accountant
* When a gateway degrades, the **AI Doctor** investigates like an emergency room physician.
* It queries real-time diagnostic tools: inspecting HTTP status codes, bank latency percentiles, and transaction logs.
* It answers: *Is this merchant error, a bank CBS crash, or an upstream timeout?*
* It outputs a diagnosis with a **statistical confidence score (e.g. 95%)**.
* Simultaneously, the **Revenue Accountant** computes exactly how much revenue is at risk in real time (e.g., *₹38,000 at risk*).

### 3. 🛡️ Safe Canary Swapping: Progressive Traffic Migration
PULSE **never** blindly dumps 100% of traffic onto a backup gateway. Instead, it tests the waters with a **Canary Rollout**:
1. **Stage 1 (20% traffic):** Sends a small test slice to Gateway 2 and checks **5 strict safety rules**:
   - Minimum sample size
   - Success rate improvement
   - Statistical confidence (Wilson bound)
   - Latency within SLO (≤1000ms)
   - Error rate cap (≤8%)
2. **Stage 2 (50% traffic):** Verifies the safety gates again under higher load.
3. **Stage 3 (100% promotion):** Fully promotes Gateway 2 to handle all checkouts.
4. **Anti-Flapping Circuit Breaker:** If a broken gateway flickers on and off (flapping), PULSE locks it into a **60-second quarantine cooldown** so payments never get stuck ping-ponging between routes.

---

## 🚀 Live Interactive Dashboard

PULSE includes a real-time, glassmorphic operator dashboard (`http://localhost:8000/dashboard/`) driven by 100ms WebSockets:

* **Top Gateway Cards:** Live Status, Success Rates, Latency, and Wilson Confidence bounds.
* **Failure Simulator:** 1-click buttons to inject real-world outages:
  - `Simulate Gateway 1 Outage (Timeouts)`
  - `Simulate Bank CBS Crash (HTTP 500)`
  - `Simulate Route Flapping (Circuit Breaker Quarantine)`
  - `Simulate Cascading Failover (Gateway 3 Tertiary Fallback)`
  - `Reset to Healthy Normal`
* **AI Doctor Pane:** Live verdict, confidence percentage, and canary progress bar ($20\% \rightarrow 50\% \rightarrow 100\%$).
* **Platform KPIs:** Platform Success Rate, Real-Time Revenue at Risk, and Revenue Loss Prevented.

---

## ⚡ Quickstart (Run it Locally in 60 Seconds)

### 1. Launch the Server & Real-Time Dashboard
```powershell
python run_demo.py --server
```
Open your browser at: **[http://localhost:8000/dashboard/](http://localhost:8000/dashboard/)**

### 2. Run the CLI Walkthrough Demo
```powershell
python run_demo.py
```
Runs a complete simulated outage and autonomous canary recovery directly in your terminal.

### 3. Run the Automated Test Suite (All 96 Tests Passing)
```powershell
python -m pytest tests/ -v
```

---

## 🏆 Key Results & Impact

| Metric | Traditional Incident Response | PULSE Autonomous AI |
| :--- | :--- | :--- |
| **Recovery Time (MTTR)** | 20 to 45 minutes (manual triage) | **< 5 seconds (autonomous)** |
| **Human Engineering Required** | Yes (pages on-call engineers at 3 AM) | **Zero human intervention** |
| **Failover Safety** | Risky (dumping 100% traffic crashes backups) | **Progressive Canary (20% ➔ 50% ➔ 100%)** |
| **Route Ping-Ponging** | High risk during unstable network | **Guaranteed 60s Quarantine Circuit Breaker** |
| **Platform Success Rate** | Plunges to 44% during outage | **Restored back to 99%+** |
| **Revenue Saved** | Thousands lost every minute | **₹1,68,000+ saved per incident** |

---

## 📁 Clean Project Structure

```text
├── pulse/
│   ├── observer/          # Real-time Sliding Window, Metrics, & Wilson Confidence
│   ├── doctor/            # AI Doctor, Diagnostic Evidence Tools & Hypothesis Engine
│   ├── accountant/        # Real-time Revenue-At-Risk & Saved Loss Calculator
│   ├── canary/            # 5-Gate Progressive Canary Rollout Controller
│   ├── safety/            # Route Quarantine & Anti-Flapping Circuit Breaker
│   ├── counterfactual/    # What-if Route Evaluation Engine
│   ├── fsm/               # Deterministic Finite State Machine (9 States)
│   ├── api/               # FastAPI REST, WebSockets, & Razorpay Adapter
│   ├── dashboard/         # Real-time Dashboard UI (HTML, CSS, JS)
│   └── simulator/         # Deterministic Transaction & Outage Simulator
├── tests/                 # 96 comprehensive automated tests
├── run_demo.py            # CLI Demo & Web Server launcher
└── README.md              # Project documentation
```

---

## 👥 Built for Razorpay Buildathon
* **Track:** Track 03 — AI Revenue Recovery
* **Technology Stack:** Python, FastAPI, WebSockets, Statistics (Wilson Score Interval), Vanilla JS/CSS Dashboard
* **Verification:** 96/96 Automated Unit, Integration & Adversarial Tests Passing
