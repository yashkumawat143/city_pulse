# 🌆 CityPulse — Live Civic Intelligence Dashboard

> **A real-time civic intelligence platform for monitoring city conditions, detecting anomalies, identifying possible multi-signal events, and supporting faster civic decision-making.**

🔗 **Live Demo:** (https://married-graduate-guam-rpg.trycloudflare.com/login)

---

## 📌 Overview

**CityPulse** is a smart civic intelligence dashboard designed to bring different city-level signals together in one place.

Modern cities generate large amounts of data from different sources such as traffic, weather, public complaints, incidents, environmental conditions, and other civic indicators. Monitoring these signals separately can make it difficult to identify unusual situations or relationships between events.

CityPulse provides a centralized dashboard where users can:

* 📊 Monitor live civic indicators
* 🚨 Detect unusual or anomalous conditions
* 🔍 Analyze multiple signals together
* 📈 Visualize city trends
* 🗺️ Monitor location-based information
* ⚡ Identify potential multi-signal events
* 🧠 Support faster data-driven civic decisions

---

## 🎯 Problem Statement

Cities continuously generate large volumes of information, but this information is often distributed across different systems.

For example:

```text
Traffic Data
     ↓
Weather Data
     ↓
Public Complaints
     ↓
Incidents
     ↓
Environmental Data
     ↓
      CityPulse
         ↓
 ┌──────────────────────┐
 │ Unified Dashboard    │
 │ Anomaly Detection    │
 │ Event Detection      │
 │ Data Visualization   │
 └──────────────────────┘
```

CityPulse aims to provide a unified view of these signals and help identify patterns that may require attention.

---

## ✨ Key Features

### 📊 Live Dashboard

Provides a centralized dashboard for viewing important civic indicators and current city conditions.

### 🚨 Anomaly Detection

Identifies unusual changes or abnormal patterns in incoming data.

Examples:

* Unexpected traffic increase
* Sudden increase in complaints
* Unusual environmental readings
* Abnormal activity in a particular area

### 🔗 Multi-Signal Event Detection

CityPulse can combine multiple signals to identify situations that may not be obvious when each signal is viewed independently.

For example:

```text
Heavy Rain
    +
Traffic Increase
    +
Multiple Road Complaints
    ↓
Possible Flooding / Traffic Disruption Event
```

### 📈 Data Visualization

Interactive charts and visual components make it easier to understand:

* Trends
* Changes over time
* Geographic patterns
* Anomalies
* Civic indicators

### 🗺️ Location-Based Intelligence

CityPulse can organize civic information according to geographical locations and help identify areas experiencing unusual activity.

### ⚡ Real-Time Monitoring

The dashboard is designed around continuously changing civic information, allowing users to monitor city conditions instead of relying only on static reports.

---

## 🏗️ System Architecture

```text
                 ┌──────────────────┐
                 │   Civic Sources  │
                 └────────┬─────────┘
                          │
                          ▼
                ┌────────────────────┐
                │ Data Collection /  │
                │       APIs         │
                └─────────┬──────────┘
                          │
                          ▼
                ┌────────────────────┐
                │ Data Processing &  │
                │   Preprocessing    │
                └─────────┬──────────┘
                          │
             ┌────────────┴────────────┐
             ▼                         ▼
    ┌─────────────────┐       ┌─────────────────┐
    │ Anomaly         │       │ Multi-Signal    │
    │ Detection       │       │ Event Detection │
    └────────┬────────┘       └────────┬────────┘
             │                         │
             └────────────┬────────────┘
                          ▼
                ┌────────────────────┐
                │   CityPulse API   │
                └─────────┬──────────┘
                          │
                          ▼
                ┌────────────────────┐
                │   Web Dashboard    │
                │                    │
                │ Charts • Maps      │
                │ Alerts • Analytics │
                └────────────────────┘
```

---

## 🛠️ Technology Stack

### Frontend

* **React.js**
* **TypeScript**
* **Tailwind CSS**
* **Lucide React**
* **React Router**
* Interactive charts and dashboard components

### Backend

* **Python**
* **FastAPI**
* REST APIs
* Data processing services

### Data & Machine Learning

* **Python**
* **Pandas**
* **NumPy**
* **Scikit-learn**
* Anomaly detection
* Data preprocessing
* Statistical analysis

### Database

Depending on the deployed configuration, the application can use a structured database for storing civic events, signals, users, and historical information.

### Deployment / Development

* Git
* GitHub
* Cloudflare Tunnel
* Local development environment

---

## 🧠 Intelligence Layer

One of the important components of CityPulse is its intelligence layer.

### Anomaly Detection

Historical or incoming data can be analyzed to determine whether a new observation is significantly different from normal behavior.

Conceptually:

```text
Normal Pattern
      │
      ▼
Incoming Data
      │
      ▼
Compare With Expected Pattern
      │
 ┌────┴─────┐
 │          │
Normal    Anomaly
 │          │
 ▼          ▼
Monitor    Alert
```

### Multi-Signal Analysis

Instead of analyzing individual signals independently, CityPulse can combine multiple signals.

```text
Signal A ──┐
Signal B ──┤
Signal C ──┼──► Correlation / Rule Analysis
Signal D ──┘
                    │
                    ▼
             Possible Event
```

This approach can help identify complex civic situations.

---

## 📊 Example Use Cases

### 🚦 Traffic Monitoring

Detect unusual increases in traffic and identify areas that may require attention.

### 🌧️ Weather + Traffic Analysis

Combine weather conditions with traffic information to identify possible disruptions.

### 🚨 Incident Detection

Identify areas where multiple unusual signals occur at the same time.

### 🏙️ Smart City Monitoring

Provide a centralized intelligence layer for monitoring different city conditions.

### 📍 Area-Level Analysis

Compare different regions of a city and identify locations experiencing abnormal activity.

---

## 📁 Project Structure

A possible project structure is:

```text
CityPulse/
│
├── frontend/
│   ├── src/
│   ├── components/
│   ├── pages/
│   ├── services/
│   └── ...
│
├── backend/
│   ├── main.py
│   ├── api/
│   ├── models/
│   ├── services/
│   └── ...
│
├── data/
│   ├── raw/
│   └── processed/
│
├── ml/
│   ├── preprocessing/
│   ├── models/
│   └── anomaly_detection/
│
├── requirements.txt
├── README.md
└── .gitignore
```

---

## 🚀 Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/yashkumawat143/city_pulse.git
cd city_pulse
```

### 2. Install Backend Dependencies

```bash
pip install -r requirements.txt
```

### 3. Start the Backend

```bash
uvicorn main:app --reload
```

### 4. Start the Frontend

Navigate to the frontend directory:

```bash
cd frontend
```

Install dependencies:

```bash
npm install
```

Run the development server:

```bash
npm run dev
```

---

## 🔐 Environment Variables

Create a `.env` file for sensitive configuration:

```env
API_KEY=your_api_key
DATABASE_URL=your_database_url
```

> **Never upload API keys, passwords, database credentials, or other secrets to GitHub.**

Add `.env` to `.gitignore`:

```gitignore
.env
__pycache__/
node_modules/
*.pkl
*.pyc
```

---

## 🌐 Live Demo

The current development/demo deployment is available here:

🔗 **https://lanes-terminals-campbell-ace.trycloudflare.com/**

> Note: This URL is a Cloudflare Tunnel address and may change when the tunnel is restarted.

---

## 🔮 Future Improvements

* 🤖 Advanced ML-based anomaly detection
* 📡 More real-time data sources
* 🗺️ Advanced GIS/map integration
* 🔔 Real-time alert notifications
* 📱 Mobile-friendly civic monitoring interface
* 🧠 Predictive civic event detection
* 📊 Historical trend analysis
* 👥 Role-based access control
* ☁️ Cloud deployment
* 🔄 Automated data pipelines
* 📈 Advanced forecasting models

---

## 🎓 Skills Demonstrated

This project demonstrates practical experience in:

* Full-stack development
* Python
* React
* TypeScript
* REST APIs
* FastAPI
* Data processing
* Pandas & NumPy
* Machine Learning
* Anomaly Detection
* Data Visualization
* Real-time monitoring
* Git & GitHub
* API integration
* Dashboard development

---

## 👨‍💻 Author

**Yash Kumawat**

GitHub: [yashkumawat143](https://github.com/yashkumawat143)

---

## ⭐ Support

If you find this project useful, consider giving the repository a ⭐ on GitHub.

---

## 📜 License

This project is intended for educational, experimental, and demonstration purposes.
