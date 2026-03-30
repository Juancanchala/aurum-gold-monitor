"""
Gold Monitor — REST API
-----------------------
FastAPI server that reads from SQLite and exposes endpoints
consumed by the HTML dashboard via fetch/polling.

Endpoints:
  GET /status           — health check
  GET /current          — latest tick + metrics + insight
  GET /history?n=50     — last N price points for chart
  GET /insights?n=5     — last N AI insights
  GET /stats            — 24h high/low/change/count
"""

import os
import sqlite3
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

log = logging.getLogger(__name__)

load_dotenv()

DB_PATH        = os.getenv("DB_PATH", "gold_monitor.db")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE    = "https://api.openai.com/v1"

app = FastAPI(title="Gold Monitor API", version="1.0.0")

# Allow dashboard (file://, localhost) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ── /status ──────────────────────────────────────────────────────────────────
@app.get("/status")
def status():
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM raw_ticks").fetchone()[0]
    conn.close()
    return {
        "status": "ok",
        "db_path": DB_PATH,
        "total_ticks": count,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


# ── /current ──────────────────────────────────────────────────────────────────
@app.get("/current")
def current():
    conn = get_db()

    tick_row = conn.execute(
        "SELECT t.ts, t.price, t.open, t.high, t.low, t.source, "
        "       m.change_pct, m.ma10, m.volatility, m.trend, m.alert "
        "FROM raw_ticks t "
        "JOIN metrics m ON m.tick_id = t.id "
        "ORDER BY t.id DESC LIMIT 1"
    ).fetchone()

    if not tick_row:
        raise HTTPException(status_code=404, detail="No data yet. Is the producer running?")

    insight_row = conn.execute(
        "SELECT insight, ts FROM ai_insights ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()

    return {
        "timestamp":  tick_row["ts"],
        "price":      tick_row["price"],
        "open":       tick_row["open"],
        "high":       tick_row["high"],
        "low":        tick_row["low"],
        "source":     tick_row["source"],
        "change_pct": tick_row["change_pct"],
        "ma10":       tick_row["ma10"],
        "volatility": tick_row["volatility"],
        "trend":      tick_row["trend"],
        "alert":      tick_row["alert"],
        "ai_insight": insight_row["insight"] if insight_row else None,
        "insight_ts": insight_row["ts"] if insight_row else None,
    }


# ── /history ──────────────────────────────────────────────────────────────────
@app.get("/history")
def history(n: int = 50):
    n = min(max(n, 5), 200)
    conn = get_db()
    rows = conn.execute(
        "SELECT t.ts, t.price, m.ma10, m.change_pct, m.trend "
        "FROM raw_ticks t JOIN metrics m ON m.tick_id = t.id "
        "ORDER BY t.id DESC LIMIT ?",
        (n,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]   # chronological order


# ── /insights ────────────────────────────────────────────────────────────────
@app.get("/insights")
def insights(n: int = 5):
    n = min(max(n, 1), 20)
    conn = get_db()
    rows = conn.execute(
        "SELECT ts, insight, price FROM ai_insights ORDER BY id DESC LIMIT ?", (n,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── /stats ────────────────────────────────────────────────────────────────────
@app.get("/stats")
def stats():
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as cnt, MAX(price) as high, MIN(price) as low, "
        "       MAX(price) - MIN(price) as range_ "
        "FROM raw_ticks WHERE ts >= datetime('now', '-24 hours')"
    ).fetchone()

    first = conn.execute(
        "SELECT price FROM raw_ticks WHERE ts >= datetime('now', '-24 hours') "
        "ORDER BY id ASC LIMIT 1"
    ).fetchone()
    last = conn.execute(
        "SELECT price FROM raw_ticks ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()

    open_p  = first["price"] if first else None
    close_p = last["price"] if last else None
    chg_24h = round(((close_p - open_p) / open_p) * 100, 3) if open_p and close_p else None

    return {
        "ticks_24h":   row["cnt"],
        "high_24h":    row["high"],
        "low_24h":     row["low"],
        "range_24h":   row["range_"],
        "change_24h":  chg_24h,
    }


# ── /prediction ──────────────────────────────────────────────────────────────
@app.get("/prediction")
def prediction():
    try:
        import ml_predictor
        return ml_predictor.predict(DB_PATH)
    except Exception as exc:
        log.error("ML prediction error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── /api/agent ───────────────────────────────────────────────────────────────
class AgentRequest(BaseModel):
    message: str

@app.post("/api/agent")
async def agent(req: AgentRequest):
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured on server.")

    conn = get_db()
    tick_row = conn.execute(
        "SELECT t.price, m.change_pct, m.ma10, m.volatility, m.trend "
        "FROM raw_ticks t JOIN metrics m ON m.tick_id = t.id "
        "ORDER BY t.id DESC LIMIT 1"
    ).fetchone()
    conn.close()

    if tick_row:
        context = (
            f"You are AURUM, a concise gold market analyst embedded in a real-time trading dashboard.\n"
            f"Current data:\n"
            f"- Gold spot price: ${tick_row['price']:.2f} USD/oz\n"
            f"- Change: {tick_row['change_pct']:+.3f}%\n"
            f"- MA(10): {tick_row['ma10']:.2f}\n"
            f"- Volatility (σ): {tick_row['volatility']:.4f}\n"
            f"- Trend: {tick_row['trend']}\n"
            f"Answer in the same language the user uses. Be concise (2-3 sentences). Focus on actionable insights."
        )
    else:
        context = (
            "You are AURUM, a concise gold market analyst. "
            "No live data is available right now. Answer the user's question as best you can."
        )

    payload = {
        "model": "gpt-4o-mini",
        "max_tokens": 150,
        "temperature": 0.5,
        "messages": [
            {"role": "system", "content": context},
            {"role": "user",   "content": req.message},
        ],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{OPENAI_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json=payload,
        )
    if resp.status_code != 200:
        log.error("OpenAI /agent error %s: %s", resp.status_code, resp.text)
        raise HTTPException(status_code=502, detail="OpenAI request failed.")
    return {"reply": resp.json()["choices"][0]["message"]["content"].strip()}


# ── /api/transcribe ──────────────────────────────────────────────────────────
@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured on server.")

    audio_bytes = await audio.read()
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{OPENAI_BASE}/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            files={"file": (audio.filename or "audio.webm", audio_bytes, audio.content_type or "audio/webm")},
            data={"model": "whisper-1"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Whisper transcription failed.")
    return {"text": resp.json().get("text", "").strip()}


# ── Run ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("API_PORT", "8000")))
    uvicorn.run("api_server:app", host=host, port=port, reload=False)
