"""
Gold Price Producer
-------------------
Fetches gold price from Yahoo Finance (yfinance) every POLL_INTERVAL seconds
and publishes each tick as a JSON event to the Kafka topic 'gold_prices'.

Source: yfinance GC=F (Gold Futures) — free, no API key required.
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
import yfinance as yf

load_dotenv()

# ── Config ──────────────────────────────────────────────────────────────────
KAFKA_SERVERS       = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC         = os.getenv("KAFKA_TOPIC", "gold_prices")
POLL_INTERVAL       = int(os.getenv("POLL_INTERVAL", "300"))
YFINANCE_TICKER     = "GC=F"
KAFKA_SASL_USERNAME      = os.getenv("KAFKA_SASL_USERNAME", "")
KAFKA_SASL_PASSWORD      = os.getenv("KAFKA_SASL_PASSWORD", "")
KAFKA_SECURITY_PROTOCOL  = os.getenv("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT")
KAFKA_SASL_MECHANISM     = os.getenv("KAFKA_SASL_MECHANISM", "PLAIN")

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


# ── Real price fetch via yfinance ────────────────────────────────────────────
def _fetch_real_price() -> dict | None:
    """Fetch live gold price from Yahoo Finance. Returns None on any error."""
    try:
        ticker = yf.Ticker(YFINANCE_TICKER)
        info = ticker.fast_info
        price = info.last_price
        if not price:
            return None
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "price":     round(float(price), 2),
            "open":      round(float(info.open), 2) if info.open else None,
            "high":      round(float(info.day_high), 2) if info.day_high else None,
            "low":       round(float(info.day_low), 2) if info.day_low else None,
            "currency":  "USD",
            "metal":     "XAU",
            "source":    "yahoo_finance",
        }
    except Exception as exc:
        log.warning("yfinance fetch failed: %s — falling back to simulation", exc)
        return None


# ── Kafka producer setup ──────────────────────────────────────────────────────
def build_producer() -> KafkaProducer:
    kwargs = dict(
        bootstrap_servers=KAFKA_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        acks="all",
        retries=3,
        linger_ms=100,
    )
    if KAFKA_SECURITY_PROTOCOL != "PLAINTEXT":
        kwargs.update(
            security_protocol=KAFKA_SECURITY_PROTOCOL,
            sasl_mechanism=KAFKA_SASL_MECHANISM,
            sasl_plain_username=KAFKA_SASL_USERNAME,
            sasl_plain_password=KAFKA_SASL_PASSWORD,
            ssl_check_hostname=True,
        )
    return KafkaProducer(**kwargs)


# ── Main loop ────────────────────────────────────────────────────────────────
def run():
    log.info("Starting Gold Price Producer")
    log.info("Kafka broker  : %s", KAFKA_SERVERS)
    log.info("Topic         : %s", KAFKA_TOPIC)
    log.info("Poll interval : %ds", POLL_INTERVAL)
    log.info("Price source  : Yahoo Finance (%s)", YFINANCE_TICKER)

    producer = build_producer()
    tick_count = 0

    try:
        price_history: list = []
        while True:
            tick = _fetch_real_price()
            if tick is None:
                if len(price_history) >= 2:
                    # Linear extrapolation from recent trend
                    n = len(price_history)
                    avg_change = (price_history[-1] - price_history[0]) / (n - 1)
                    estimated_price = round(price_history[-1] + avg_change, 2)
                    last = {k: v for k, v in zip(
                        ["open", "high", "low", "currency", "metal"],
                        [estimated_price, estimated_price, estimated_price, "USD", "XAU"]
                    )}
                    tick = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "price":     estimated_price,
                        "open":      estimated_price,
                        "high":      estimated_price,
                        "low":       estimated_price,
                        "currency":  "USD",
                        "metal":     "XAU",
                        "source":    "estimated",
                    }
                    log.warning("yfinance unavailable — estimated price %.2f from trend", estimated_price)
                else:
                    log.warning("yfinance unavailable and insufficient history — skipping tick")
                    time.sleep(POLL_INTERVAL)
                    continue
            else:
                price_history.append(tick["price"])
                if len(price_history) > 10:
                    price_history.pop(0)
            log.info("Attempting to publish tick to topic: %s", KAFKA_TOPIC)
            try:
                producer.send(KAFKA_TOPIC, value=tick)
                producer.flush(timeout=30)
                tick_count += 1
                log.info(
                    "✓ Tick #%d published | price=%.2f | source=%s",
                    tick_count, tick["price"], tick["source"],
                )
            except Exception as e:
                log.error("Send failed: %s: %s", type(e).__name__, e)
            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        log.info("Producer stopped by user after %d ticks.", tick_count)
    finally:
        producer.close()
        log.info("Kafka producer closed.")


if __name__ == "__main__":
    run()
