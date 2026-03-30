"""
Gold Price Producer
-------------------
Fetches gold price from GoldAPI.io every POLL_INTERVAL seconds
and publishes each tick as a JSON event to the Kafka topic 'gold_prices'.

API: https://www.goldapi.io  (free tier: ~30 req/day)
Fallback: simulated price stream for local dev/demo
"""

import os
import json
import time
import logging
import random
from datetime import datetime, timezone
from dotenv import load_dotenv
from kafka import KafkaProducer
import requests

load_dotenv()

# ── Config ──────────────────────────────────────────────────────────────────
GOLD_API_KEY        = os.getenv("GOLD_API_KEY", "")
KAFKA_SERVERS       = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC         = os.getenv("KAFKA_TOPIC", "gold_prices")
POLL_INTERVAL       = int(os.getenv("POLL_INTERVAL", "300"))
GOLDAPI_URL         = "https://www.goldapi.io/api/XAU/USD"

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PRODUCER] %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Simulated price generator (demo/dev fallback) ───────────────────────────
_sim_price = 2320.0  # starting price ~USD

def _simulated_tick() -> dict:
    """Generate a realistic-looking gold price tick for demo purposes."""
    global _sim_price
    change = random.gauss(0, 3.5)           # ~$3.5 std dev per tick
    _sim_price = max(1800, _sim_price + change)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "price":     round(_sim_price, 2),
        "open":      round(_sim_price - random.uniform(-5, 5), 2),
        "high":      round(_sim_price + random.uniform(0, 8), 2),
        "low":       round(_sim_price - random.uniform(0, 8), 2),
        "currency":  "USD",
        "metal":     "XAU",
        "source":    "simulated",
    }


# ── Real API fetch ───────────────────────────────────────────────────────────
def _fetch_real_price() -> dict | None:
    """Fetch live price from GoldAPI.io. Returns None on any error."""
    if not GOLD_API_KEY or GOLD_API_KEY == "your_goldapi_key_here":
        return None
    try:
        headers = {"x-access-token": GOLD_API_KEY, "Content-Type": "application/json"}
        resp = requests.get(GOLDAPI_URL, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "price":     data.get("price"),
            "open":      data.get("open_price"),
            "high":      data.get("high_price"),
            "low":       data.get("low_price"),
            "currency":  "USD",
            "metal":     "XAU",
            "source":    "goldapi.io",
        }
    except Exception as exc:
        log.warning("GoldAPI fetch failed: %s — falling back to simulation", exc)
        return None


# ── Kafka producer setup ──────────────────────────────────────────────────────
def build_producer() -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=KAFKA_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        acks="all",
        retries=3,
        linger_ms=100,
    )


# ── Main loop ────────────────────────────────────────────────────────────────
def run():
    log.info("Starting Gold Price Producer")
    log.info("Kafka broker  : %s", KAFKA_SERVERS)
    log.info("Topic         : %s", KAFKA_TOPIC)
    log.info("Poll interval : %ds", POLL_INTERVAL)
    log.info("API key set   : %s", bool(GOLD_API_KEY and GOLD_API_KEY != "your_goldapi_key_here"))

    producer = build_producer()
    tick_count = 0

    try:
        while True:
            tick = _fetch_real_price() or _simulated_tick()
            producer.send(KAFKA_TOPIC, value=tick)
            producer.flush()
            tick_count += 1
            log.info(
                "✓ Tick #%d published | price=%.2f | source=%s",
                tick_count, tick["price"], tick["source"],
            )
            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        log.info("Producer stopped by user after %d ticks.", tick_count)
    finally:
        producer.close()
        log.info("Kafka producer closed.")


if __name__ == "__main__":
    run()
