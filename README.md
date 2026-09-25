# 🌆 CityPulse — Live Civic Intelligence Dashboard

> **A real-time civic intelligence platform for monitoring city conditions, detecting anomalies, identifying possible multi-signal events, and supporting faster civic decision-making.**

CityPulse brings scattered civic signals such as **traffic, weather, road incidents, and complaints** into a unified dashboard.

Instead of simply displaying raw data, CityPulse processes changing city conditions through a pipeline of:

**Data → Baselines → Anomalies → Temporal Relationships → Civic Events → Risk → Alerts → Explanation → Prediction**

The project uses a **fictional city with synthetic data** for demonstration and hackathon purposes.

**🔗 Live demo:** https://lanes-terminals-campbell-ace.trycloudflare.com

One public URL serves the built React dashboard **and** its FastAPI REST/WebSocket API
(single-origin), so this link opens the whole running application — map, KPIs, anomalies,
events, alerts and the simulation controls. Quick-tunnel URLs are **temporary**: they stop
working when the tunnel process or the host machine stops, so treat the link as a snapshot
of the running app rather than a permanent address.

---

## 🚀 Why CityPulse?

Modern cities generate large amounts of data from different systems:

* 🚗 Traffic and congestion
* 🌧️ Weather and rainfall
* 🚧 Road incidents
* 📢 Civic complaints
* ⚠️ Alerts and abnormal conditions

These signals are often separated across different systems.

CityPulse provides a unified view so an operator can quickly understand:

* **What is happening?**
* **Where is it happening?**
* **What changed from the normal baseline?**
* **Are multiple signals changing together?**
* **Is there a possible civic event?**
* **What should be investigated?**
* **What might happen next?**

---

# ✨ Key Features

## 📊 Live Civic Dashboard

The main dashboard provides a quick overview of city health and current conditions.

It includes:

* City Health Score
* Active anomalies
* Civic events
* Active alerts
* Data source status
* Live city map
* Zone-level metrics
* Health trends
* Baseline comparison
* Possible signal relationships
* Live event stream

---

## 🔍 Anomaly Detection

CityPulse compares current observations against historical or simulated baselines.

Example:

```text
Traffic
Current: 39%
Baseline: 31.7%

Change: +22.9%
```

The system can identify unusual changes in individual civic signals.

---

## 🔗 Multi-Signal Event Detection

A major goal of CityPulse is to move beyond individual anomalies.

For example:

```text
Heavy Rainfall
      ↓
Traffic Increase
      ↓
Road Incidents
      ↓
Complaint Increase
      ↓
Possible Civic Event
```

The system looks for signals that change within a relevant time window.

These relationships are presented as **possible associations**, not confirmed causal relationships.

---

## 🧠 Why Now?

CityPulse provides an explanation layer that helps answer:

> **Why is this city or zone receiving attention right now?**

Instead of forcing an operator to inspect every metric, the dashboard summarizes the important changes and their temporal relationships.

---

## 🚨 Alert System

CityPulse supports alert levels such as:

* 🟢 LOW
* 🟡 MEDIUM
* 🟠 HIGH
* 🔴 CRITICAL

Alerts are generated from detected conditions rather than simply treating every anomaly as a critical event.

---

## 🗺️ Live City Map

The dashboard includes a simulated city map showing conditions across different zones.

Example zones:

```text
Zone A → Primary event impact
Zone B → Limited spillover
Zone C → Mostly stable
```

This makes it easier to understand **where** an event is developing.

---

## 🎮 Scenario-Based Simulation

CityPulse includes a simulation system designed to demonstrate how a civic event develops over time.

### Example Scenario

**Urban Rainfall Disruption**

```text
NORMAL
   ↓
EARLY WARNING
   ↓
WEATHER ONSET
   ↓
HEAVY RAIN
   ↓
TRAFFIC RESPONSE
   ↓
COMPLAINT RESPONSE
   ↓
CIVIC EVENT PEAK
   ↓
RECOVERY
   ↓
NORMALIZATION
```

The simulation creates changing raw conditions while the analytics layer independently detects anomalies and possible events.

---

## 📈 Trend & Prediction

CityPulse provides prototype trend-based prediction to help identify how conditions may develop in the near future.

Predictions are clearly treated as **prototype analytical estimates**, not guaranteed forecasts.

---

## 📡 Data Sources

The current prototype uses **synthetic data for a fictional city**.

The architecture is designed around multiple civic data streams so that additional public/open data sources can be integrated later.

Example signals:

| Data Type  | Example                  |
| ---------- | ------------------------ |
| Weather    | Rainfall, weather state  |
| Traffic    | Congestion percentage    |
| Road       | Incident frequency       |
| Complaints | Complaint volume         |
| Location   | Zone information         |
| Time       | Timestamped observations |

---

# 🏗️ System Architecture

```text
                 ┌─────────────────────┐
                 │   Civic Data Feeds  │
                 │                     │
                 │ Weather             │
                 │ Traffic             │
                 │ Road Incidents      │
                 │ Complaints          │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │ Data Normalization   │
                 │                     │
                 │ Timestamping        │
                 │ Zone Mapping        │
                 │ Common Schema       │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │     Baselines       │
                 │                     │
                 │ Normal Conditions   │
                 │ Historical Trends   │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │ Anomaly Detection   │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │ Temporal Analysis   │
                 │ & Correlations      │
                 └──────────┬──────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │ Civic Event         │
                 │ Detection           │
                 └──────────┬──────────┘
                            │
                 ┌──────────┴──────────┐
                 ▼                     ▼
        ┌─────────────────┐    ┌─────────────────┐
        │ Risk & Alerts   │    │ Prediction      │
        └────────┬────────┘    └────────┬────────┘
                 │                      │
                 └──────────┬───────────┘
                            ▼
                 ┌─────────────────────┐
                 │ CityPulse Dashboard │
                 │                     │
                 │ Map                 │
                 │ Health              │
                 │ Events              │
                 │ Alerts              │
                 │ Trends              │
                 │ Explanations        │
                 └─────────────────────┘
```

---

# 🧩 Main Modules

### 🏠 Dashboard

Central city overview containing:

* City health
* Active anomalies
* Civic events
* Alerts
* Live map
* Trends
* Baseline comparison
* Possible links
* Event stream

### 🔎 Anomalies

Displays unusual changes detected in individual civic signals.

### 🚨 Alerts

Displays generated alerts and their severity.

### 📡 Sources

Shows the status of connected/simulated civic data sources.

### 🎮 Simulation

Allows demonstration of changing city conditions through controlled scenarios.

---

# 🛠️ Tech Stack

## Frontend

* React
* Vite
* JavaScript / TypeScript
* HTML
* CSS

## Data & Analytics

* Python
* NumPy
* Pandas
* Statistical / rule-based analysis
* Trend analysis

## Visualization

* Interactive dashboard
* City map
* Charts
* Event timeline
* Civic health indicators

## Development

* Git
* GitHub
* npm

---

# 📁 Project Structure

```text
CityPulse/
│
├── public/
│
├── src/
│   ├── components/
│   ├── pages/
│   ├── data/
│   ├── simulation/
│   ├── analytics/
│   └── ...
│
├── package.json
├── vite.config.js
├── index.html
└── README.md
```

> The exact structure may vary depending on the current implementation.

---

# 🎯 Example Event Detection Flow

Suppose heavy rainfall begins in **Zone A**.

### Step 1 — Weather

Rainfall increases above its normal baseline.

```text
Rainfall ↑
```

### Step 2 — Traffic

Traffic begins increasing after a short time lag.

```text
Rainfall ↑
     ↓
Traffic ↑
```

### Step 3 — Road Incidents

Road incidents begin increasing.

```text
Rainfall ↑
     ↓
Traffic ↑
     ↓
Road Incidents ↑
```

### Step 4 — Complaints

Civic complaints increase after another delay.

```text
Rainfall ↑
     ↓
Traffic ↑
     ↓
Road Incidents ↑
     ↓
Complaints ↑
```

### Step 5 — Civic Event

The analytics layer detects multiple unusual signals occurring within a relevant time window.

```text
Possible Civic Event
```

### Step 6 — Recovery

As rainfall decreases:

```text
Rainfall ↓
   ↓
Traffic gradually ↓
   ↓
Incidents ↓
   ↓
Complaints ↓
   ↓
NORMALIZATION
```

This demonstrates how CityPulse tracks an evolving event rather than only displaying isolated metrics.

---

# 📊 Correlation & Temporal Relationships

CityPulse can analyze relationships between signals at different time lags.

Example:

```text
Lag 0 min
Lag 15 min
Lag 30 min
```

Correlation interpretation:

|   Correlation | Interpretation    |
| ------------: | ----------------- |
|        ≥ 0.70 | Strong positive   |
|   0.40 – 0.69 | Moderate positive |
|   0.20 – 0.39 | Weak positive     |
|  -0.19 – 0.19 | Very weak         |
| -0.39 – -0.20 | Weak inverse      |
| -0.69 – -0.40 | Moderate inverse  |
|       ≤ -0.70 | Strong inverse    |

These relationships indicate **possible temporal associations** and should not be interpreted as proof of causation.

---

# 🏙️ City Health

CityPulse calculates a prototype city-health indicator using multiple civic signals.

Example:

```text
City Health
     88.6 / 100
```

The dashboard also provides a breakdown such as:

```text
Traffic       88
Weather      100
Complaints    83
```

The health score is a **prototype analytical indicator** intended to provide a quick overview rather than an official measurement of real-world city health.

---

# 🔐 Privacy & Safety

CityPulse is designed around aggregated civic information.

The current prototype:

* Uses synthetic data
* Uses a fictional city
* Does not identify individual citizens
* Does not expose personal information
* Treats correlations as possible relationships rather than confirmed causes

---

# 🚀 Getting Started

## 1. Clone the repository

```bash
git clone YOUR_GITHUB_REPOSITORY_URL
```

## 2. Enter the project

```bash
cd CityPulse
```

## 3. Install dependencies

```bash
npm install
```

## 4. Start the development server

```bash
npm run dev
```

The terminal will provide a local URL, typically:

```text
http://localhost:5173
```

## 5. Build for production

```bash
npm run build
```

The production files will normally be generated inside:

```text
dist/
```

## 6. Preview the production build

```bash
npm run preview
```

---

# 🌐 Deployment

## 🔗 Live demo

**https://lanes-terminals-campbell-ace.trycloudflare.com**

The running deployment is a single FastAPI process that also serves the built frontend
(`frontend/dist`), published with a Cloudflare quick tunnel. That keeps REST + WebSocket on
one origin, so there is no CORS setup and no second host:

```bash
cd frontend && npm run build                                     # build the dashboard
cd ../backend && uvicorn main:app --host 127.0.0.1 --port 8000   # serve dist/ + API + WS
cloudflared tunnel --url http://127.0.0.1:8000 --no-autoupdate   # -> public https URL
```

Verify with `GET https://<tunnel-host>/api/health → {"status":"ok"}`, then start the
simulation from the UI (or `POST /api/simulation/start`) so the shared dashboard shows live
data. Quick-tunnel URLs are ephemeral — for a stable address deploy the frontend to Vercel
(`frontend/vercel.json` handles SPA routing) and the backend to Render
(`render.yaml` + `backend/Dockerfile`).

CityPulse can be deployed as a React/Vite web application using platforms such as:

* Vercel
* Netlify
* Render

For a production deployment, make sure the application is configured for **single-page application routing**, because CityPulse contains multiple routes such as:

```text
/
 /anomalies
 /alerts
 /sources
 /simulation
```

---

# 🧪 Current Prototype

CityPulse currently focuses on demonstrating the complete civic-intelligence workflow using synthetic data:

```text
Synthetic Civic Data
        ↓
Normalization
        ↓
Baseline Comparison
        ↓
Anomaly Detection
        ↓
Temporal Relationships
        ↓
Civic Event Detection
        ↓
Risk / Alerts
        ↓
Explanation
        ↓
Prediction
        ↓
Dashboard
```

---

# 🔮 Future Improvements

### V1 — Hackathon MVP

* Multi-source civic data
* Unified schema
* Anomaly detection
* Civic event detection
* Live dashboard
* Simulation

### V2 — Smart Analytics

* Improved anomaly detection
* More robust time-series analysis
* Better correlation analysis
* ML-based predictions
* Historical replay

### V3 — Public & Admin Platform

* Public citizen dashboard
* Admin dashboard
* Role-based access
* Real-world public datasets
* Notification system

### V4 — Production Intelligence

* Real-time data pipelines
* Scalable backend
* PostgreSQL
* FastAPI
* Production monitoring
* Authentication and authorization

### V5 — Advanced City Intelligence

* Advanced AI agents
* Automated investigation
* Predictive civic risk
* Cross-city analytics
* Automated decision-support workflows

---

# 🏆 Hackathon Context

**Project:** CityPulse
**Track:** Industry / Open Innovation
**Focus:** Live Civic Health & Intelligence

The project is designed around the idea of turning fragmented civic signals into an understandable, continuously updated picture of city conditions.

---

# ⚠️ Disclaimer

CityPulse is a **prototype / hackathon project**.

The current demonstration uses **synthetic data and a fictional city**. City health scores, event confidence, alerts, and predictions are prototype analytical outputs and should not be treated as official civic measurements or real-world emergency information.

---

# 👨‍💻 Author

**Yash Kumawat**

Built as a civic-tech / AI-focused hackathon project.

---

## ⭐ If you find this project interesting

Consider giving the repository a ⭐ on GitHub!
