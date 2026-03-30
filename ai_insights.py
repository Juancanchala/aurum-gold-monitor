"""
AI Insights Module
------------------
Generates natural-language market commentary using OpenAI GPT-4o-mini
based on recent gold price metrics from the consumer pipeline.
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
log = logging.getLogger(__name__)

# Lazy import — only load openai if key is present
_openai_client = None


def _get_client():
    global _openai_client
    if _openai_client is None:
        if not OPENAI_API_KEY or OPENAI_API_KEY == "your_openai_key_here":
            return None
        from openai import OpenAI
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client


def generate_insight(tick: dict, metrics: dict, recent_rows: list) -> str:
    """
    Generate a 2-3 sentence market insight from recent metrics.

    Falls back to a rule-based summary if OpenAI is not configured.
    """
    client = _get_client()
    if client is None:
        return _rule_based_insight(tick, metrics)

    # Build context for the prompt
    history_lines = "\n".join(
        f"  price={r[0]:.2f}, chg={r[1]:+.3f}%, ma10={r[2]:.2f}, vol={r[3]:.4f}, trend={r[4]}"
        for r in recent_rows
    )

    prompt = f"""You are a concise gold market analyst. Based on the following recent data, 
write a 2-3 sentence insight for a trading dashboard. Be direct, factual, and professional.
Mention trend direction, volatility level, and any notable pattern. Do not use markdown.

Current tick:
  Price: ${tick['price']:.2f} USD/oz
  Change: {metrics['change_pct']:+.3f}%
  MA(10): {metrics['ma10']:.2f}
  Volatility (σ): {metrics['volatility']:.4f}
  Trend: {metrics['trend']}
  Alert: {metrics['alert'] or 'None'}

Last 10 ticks:
{history_lines}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120,
            temperature=0.4,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        log.warning("OpenAI call failed: %s — using rule-based fallback", exc)
        return _rule_based_insight(tick, metrics)


def _rule_based_insight(tick: dict, metrics: dict) -> str:
    """Simple deterministic insight when OpenAI is unavailable."""
    price    = tick["price"]
    chg      = metrics["change_pct"]
    trend    = metrics["trend"]
    vol      = metrics["volatility"]
    ma10     = metrics["ma10"]

    trend_desc = {
        "bullish":            "showing a short-term upward trend",
        "bearish":            "showing a short-term downward trend",
        "sideways":           "trading sideways with no clear direction",
        "insufficient_data":  "with limited data points available",
    }.get(trend, "in an indeterminate trend")

    vol_desc = "high" if vol > 5 else "moderate" if vol > 2 else "low"
    vs_ma = "above" if price > ma10 else "below"

    return (
        f"Gold is currently trading at ${price:.2f}/oz, {trend_desc}. "
        f"Volatility is {vol_desc} (σ={vol:.2f}) and price is {vs_ma} its 10-tick moving average "
        f"of ${ma10:.2f}. Recent change: {chg:+.3f}%."
    )
