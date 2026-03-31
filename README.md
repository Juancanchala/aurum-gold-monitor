# AURUM — Gold Market Monitor

> Real-time gold price streaming, ML price prediction, and AI-powered market analysis — built as a portfolio-grade data engineering project.

Built by **D'LOGIA** · [dlogia.tech](https://dlogia.tech)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        DATA INGESTION                        │
│                                                             │
│   GoldAPI.io (live)  ──┐                                    │
│                        ├──▶  producer.py  ──▶  Kafka topic  │
│   Simulation (fallback)┘       (polls every 300s)           │
└─────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                       STREAM PROCESSING                      │
│                                                             │
│   consumer.py                                               │
│   ├── Computes: change_pct, MA(5), volatility, trend        │
│   ├── Triggers AI insight every 10 ticks (GPT-4o-mini)      │
│   └── Persists to SQLite: raw_ticks / metrics / ai_insights │
└─────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                         REST API                             │
│                                                             │
│   api_server.py  (FastAPI · uvicorn)                        │
│   ├── GET  /current · /history · /stats · /insights         │
│   ├── GET  /prediction  (ML: Linear Regression + RF)        │
│   ├── POST /api/agent   (GPT-4o-mini chat proxy)            │
│   └── POST /api/transcribe  (Whisper voice proxy)           │
└─────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                        DASHBOARD                             │
│                                                             │
│   dashboard.html  (vanilla JS · Chart.js · glassmorphism)   │
│   ├── Live price hero + 24h stats                           │
│   ├── Interactive price chart with MA(5)                    │
│   ├── AI insight feed                                       │
│   ├── ML prediction card (LR vs RF · buy score)             │
│   ├── Gold calculator (profitability + fair price)          │
│   ├── Currency converter (USD / COP / EUR / GBP)            │
│   └── Voice + text AI agent (Whisper + GPT-4o-mini)         │
└─────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Message broker | Apache Kafka + Zookeeper (Docker) |
| Ingestion | Python · requests · GoldAPI.io |
| Stream processing | Python · kafka-python-ng |
| Persistence | SQLite |
| AI insights | OpenAI GPT-4o-mini |
| Voice transcription | OpenAI Whisper |
| ML prediction | scikit-learn (Linear Regression + Random Forest) |
| REST API | FastAPI · uvicorn · httpx |
| Frontend | Vanilla JS · Chart.js · Cormorant Garamond |
| Deployment | Railway (API) · Docker Compose (local Kafka) |

---

## Local Installation

### Prerequisites

- Python 3.10+
- Docker and Docker Compose
- A free [GoldAPI.io](https://www.goldapi.io) key (optional — falls back to simulation)
- An OpenAI API key (optional — falls back to rule-based insights)

### Step 1 — Clone and start Kafka

```bash
git clone https://github.com/YOUR_USER/aurum-gold-monitor.git
cd aurum-gold-monitor

docker compose up -d
```

Verify brokers are up:

```bash
docker ps   # should show gold_zookeeper + gold_kafka
```

### Step 2 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 3 — Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

```env
GOLD_API_KEY=your_goldapi_key_here
OPENAI_API_KEY=your_openai_key_here
KAFKA_BOOTSTRAP_SERVERS=localhost:9092
POLL_INTERVAL=300
DB_PATH=gold_monitor.db
```

> **No API keys?** The producer auto-detects missing keys and falls back to a realistic simulated price stream. The AI insight module falls back to rule-based summaries. The dashboard is fully functional in demo mode.

### Step 4 — Run the three services (3 terminals)

**Terminal 1 — Consumer** (start first, creates the DB schema)

```bash
python consumer.py
```

**Terminal 2 — Producer**

```bash
python producer.py
```

**Terminal 3 — API Server**

```bash
python api_server.py
```

API available at: `http://localhost:8000`
Interactive docs: `http://localhost:8000/docs`

### Step 5 — Open the dashboard

Open `dashboard.html` directly in your browser (no build step required).

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOLD_API_KEY` | No | `""` | GoldAPI.io key. Falls back to simulation if empty. |
| `OPENAI_API_KEY` | No | `""` | OpenAI key for GPT-4o-mini insights and Whisper. |
| `KAFKA_BOOTSTRAP_SERVERS` | No | `localhost:9092` | Kafka broker address. |
| `POLL_INTERVAL` | No | `300` | Seconds between price fetches. |
| `DB_PATH` | No | `gold_monitor.db` | SQLite database file path. |
| `PORT` | No | `8000` | API server port (set automatically by Railway). |

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/status` | Health check + total tick count |
| GET | `/current` | Latest price, metrics, and most recent AI insight |
| GET | `/history?n=50` | Last N ticks for the price chart (max 200) |
| GET | `/insights?n=5` | Last N AI-generated market insights (max 20) |
| GET | `/stats` | 24h high, low, range, and change percentage |
| GET | `/prediction` | ML next-tick price prediction (Linear Regression + Random Forest) |
| POST | `/api/agent` | GPT-4o-mini chat proxy — body: `{"message": "..."}` |
| POST | `/api/transcribe` | Whisper voice transcription proxy — body: audio file (multipart) |

---

## Project Structure

```
aurum-gold-monitor/
├── producer.py          ← Fetches gold price, publishes to Kafka
├── consumer.py          ← Processes stream, computes metrics, persists to SQLite
├── ai_insights.py       ← GPT-4o-mini market commentary module
├── ml_predictor.py      ← scikit-learn Linear Regression + Random Forest
├── api_server.py        ← FastAPI REST server with AI proxy endpoints
├── dashboard.html       ← Glassmorphism real-time dashboard (no build needed)
├── docker-compose.yml   ← Kafka + Zookeeper local dev environment
├── requirements.txt     ← Python dependencies
├── Procfile             ← Railway deployment entry point
├── runtime.txt          ← Python version for Railway
└── .env.example         ← Environment variable template
```

---

## ML Prediction

The `/prediction` endpoint trains two models on-the-fly using the last 200 ticks stored in SQLite:

- **Linear Regression** — fast baseline with StandardScaler normalization
- **Random Forest** — 100 estimators; confidence derived from per-tree prediction standard deviation

Features: `price`, `change_pct`, `MA(5)`, `volatility`
Target: price of the next tick
Minimum data required: 20 ticks

The **Buy Score** (0–100) maps predicted price direction to a signal, dampened by current volatility. The combined **recommendation** (BUY / HOLD / WAIT) averages both model scores.

---

## Deployment on Railway

AURUM deploys as **three separate Railway services** from the same GitHub repository, each using a different Procfile.

### Prerequisites

- Redpanda Cloud cluster (or any Kafka-compatible broker) with SASL_SSL credentials
- GitHub repository with this code pushed

### Step 1 — Push to GitHub

```bash
git add .
git commit -m "feat: Railway deploy config"
git push origin main
```

### Step 2 — Create the three services on Railway

On [railway.app](https://railway.app), create a **new project** and add three services, all pointing to the same GitHub repo:

| Service name | Procfile to use | Process type |
|---|---|---|
| `aurum-api` | `Procfile` | `web` — exposes public URL |
| `aurum-producer` | `Procfile.producer` | `worker` — no public URL |
| `aurum-consumer` | `Procfile.consumer` | `worker` — no public URL |

For each service, set the **Custom Start Command** in Railway's settings to the content of its Procfile:

- **aurum-api:** `uvicorn api_server:app --host 0.0.0.0 --port $PORT`
- **aurum-producer:** `python producer.py`
- **aurum-consumer:** `python consumer.py`

### Step 3 — Set environment variables

Add these variables to **each of the three services** in Railway's Variables tab:

```env
OPENAI_API_KEY=your_openai_key_here
KAFKA_BOOTSTRAP_SERVERS=your-cluster.redpanda.com:9092
KAFKA_TOPIC=gold_prices
KAFKA_SECURITY_PROTOCOL=SASL_SSL
KAFKA_SASL_MECHANISM=SCRAM-SHA-256
KAFKA_SASL_USERNAME=your-username
KAFKA_SASL_PASSWORD=your-password
POLL_INTERVAL=300
DB_PATH=/data/gold_monitor.db
```

> `PORT` is injected automatically by Railway for the `web` service — do not set it manually.

### Step 4 — Add a persistent volume (consumer + api)

The consumer writes to SQLite and the API reads from it. Attach a Railway **Volume** to both `aurum-consumer` and `aurum-api`, mounted at `/data`, so they share the same database file.

### Step 5 — Update the dashboard API URL

After `aurum-api` is deployed, copy its public Railway URL and update `dashboard.html`:

```js
// dashboard.html — line ~630
const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://localhost:8000'
  : 'https://YOUR-APP.up.railway.app';   // ← replace with your Railway URL
```

### Architecture on Railway

```
Redpanda Cloud (SASL_SSL)
        │
        ├──▶  aurum-producer  (worker) — fetches Yahoo Finance, publishes ticks
        │
        └──▶  aurum-consumer  (worker) — processes stream, writes SQLite on /data volume
                                                │
                                    aurum-api  (web)  ← reads same /data volume
                                        │
                                    dashboard.html (browser)
```

---

## Portfolio Narrative

AURUM demonstrates a complete event-driven data engineering pipeline from ingestion to visualization:

- **Kafka** decouples the price ingestion layer from downstream processing, enabling independent scaling and replay capability.
- **FastAPI** serves as a low-latency data gateway with an async OpenAI proxy that keeps API secrets server-side — the frontend never handles credentials.
- **scikit-learn** models are trained on-demand from live SQLite data, returning next-tick price predictions and a composite buy signal derived from both models.
- **The dashboard** is a dependency-free single HTML file using glassmorphism design, Chart.js for live charting, and a voice-enabled AI analyst (Whisper + GPT-4o-mini) — fully responsive for mobile.

**Skills demonstrated:** Kafka · Event-driven architecture · Python · FastAPI · SQLite · REST API design · OpenAI API integration · scikit-learn · Real-time dashboards · Responsive CSS · Railway deployment

---

## Estimated Costs (production · 300s polling)

| Service | Usage | Cost |
|---|---|---|
| GoldAPI.io | Free tier (30 req/day) | $0 |
| OpenAI GPT-4o-mini | ~144 insights/day | ~$0.002/day |
| OpenAI Whisper | On demand | ~$0.006/min |
| Railway | Hobby plan | ~$5/month |
