"""
Gold Price Consumer / Processor
---------------------------------
Consumes raw ticks from Kafka topic 'gold_prices',
calculates derived metrics, persists to SQLite, and
triggers AI insight generation every N ticks.

Tables:
  raw_ticks    — every event as received from Kafka
  metrics      — computed metrics per tick (moving avg, volatility, trend)
  ai_insights  — latest AI-generated summaries
"""

import os
import json
import sqlite3
import logging
import statistics
from datetime import datetime, timezone
from collections import deque
from dotenv import load_dotenv
from kafka import KafkaConsumer
from ai_insights import generate_insight   # local module

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
KAFKA_SERVERS   = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC     = os.getenv("KAFKA_TOPIC", "gold_prices")
DB_PATH         = os.getenv("DB_PATH", "gold_monitor.db")
INSIGHT_EVERY   = 10  # generate AI insight every N ticks
MA_WINDOW       = 5   # moving average window

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CONSUMER] %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── In-memory sliding window for metrics ────────────────────────────────────
price_window: deque = deque(maxlen=MA_WINDOW)


# ── Database setup ────────────────────────────────────────────────────────────
def init_db(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS raw_ticks (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ts        TEXT NOT NULL,
            price     REAL NOT NULL,
            open      REAL,
            high      REAL,
            low       REAL,
            currency  TEXT DEFAULT 'USD',
            source    TEXT,
            created   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS metrics (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            tick_id       INTEGER REFERENCES raw_ticks(id),
            ts            TEXT NOT NULL,
            price         REAL NOT NULL,
            change_pct    REAL,
            ma10          REAL,
            volatility    REAL,
            trend         TEXT,
            alert         TEXT,
            created       TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS ai_insights (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            ts       TEXT NOT NULL,
            insight  TEXT NOT NULL,
            price    REAL,
            created  TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    log.info("SQLite DB initialised at: %s", DB_PATH)


# ── Metrics calculation ────────────────────────────────────────────────────────
def compute_metrics(tick: dict, conn: sqlite3.Connection) -> dict:
    price = tick["price"]
    price_window.append(price)

    # Moving average
    ma10 = round(statistics.mean(price_window), 2) if len(price_window) >= 2 else price

    # Volatility (std dev of window)
    volatility = round(statistics.stdev(price_window), 4) if len(price_window) >= 2 else 0.0

    # % change vs previous tick
    prev_row = conn.execute(
        "SELECT price FROM raw_ticks ORDER BY id DESC LIMIT 1"
    ).fetchone()
    prev_price = prev_row[0] if prev_row else price
    change_pct = round(((price - prev_price) / prev_price) * 100, 4) if prev_price else 0.0

    # Trend (last 3 data points)
    last3 = list(price_window)[-3:]
    if len(last3) == 3:
        if last3[2] > last3[1] > last3[0]:
            trend = "bullish"
        elif last3[2] < last3[1] < last3[0]:
            trend = "bearish"
        else:
            trend = "sideways"
    else:
        trend = "insufficient_data"

    # Alert
    alert = None
    if abs(change_pct) >= 0.5:
        direction = "📈 surge" if change_pct > 0 else "📉 drop"
        alert = f"High volatility {direction}: {change_pct:+.2f}% in one tick"

    return {
        "change_pct": change_pct,
        "ma10":       ma10,
        "volatility": volatility,
        "trend":      trend,
        "alert":      alert,
    }


# ── Persist tick + metrics ────────────────────────────────────────────────────
def persist(tick: dict, metrics: dict, conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "INSERT INTO raw_ticks (ts, price, open, high, low, currency, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (tick["timestamp"], tick["price"], tick.get("open"),
         tick.get("high"), tick.get("low"), tick.get("currency", "USD"), tick.get("source")),
    )
    tick_id = cur.lastrowid

    conn.execute(
        "INSERT INTO metrics (tick_id, ts, price, change_pct, ma10, volatility, trend, alert) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (tick_id, tick["timestamp"], tick["price"],
         metrics["change_pct"], metrics["ma10"], metrics["volatility"],
         metrics["trend"], metrics["alert"]),
    )
    conn.commit()
    return tick_id


# ── Main consumer loop ────────────────────────────────────────────────────────
def run():
    log.info("Starting Gold Price Consumer")
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    init_db(conn)

    consumer = KafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_SERVERS,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        group_id="gold_monitor_group",
    )
    log.info("Listening on topic: %s", KAFKA_TOPIC)

    tick_count = 0
    try:
        for message in consumer:
            tick = message.value
            metrics = compute_metrics(tick, conn)
            tick_id = persist(tick, metrics, conn)
            tick_count += 1

            log.info(
                "Tick #%d | price=%.2f | chg=%+.3f%% | trend=%s | alert=%s",
                tick_count, tick["price"], metrics["change_pct"],
                metrics["trend"], metrics["alert"] or "—",
            )

            # Generate AI insight every N ticks
            if tick_count % INSIGHT_EVERY == 0:
                recent = conn.execute(
                    "SELECT price, change_pct, ma10, volatility, trend FROM metrics "
                    "ORDER BY id DESC LIMIT 10"
                ).fetchall()
                insight_text = generate_insight(tick, metrics, recent)
                conn.execute(
                    "INSERT INTO ai_insights (ts, insight, price) VALUES (?, ?, ?)",
                    (tick["timestamp"], insight_text, tick["price"]),
                )
                conn.commit()
                log.info("AI insight saved.")

    except KeyboardInterrupt:
        log.info("Consumer stopped after %d ticks.", tick_count)
    finally:
        consumer.close()
        conn.close()
        log.info("Consumer shut down cleanly.")


if __name__ == "__main__":
    run()
