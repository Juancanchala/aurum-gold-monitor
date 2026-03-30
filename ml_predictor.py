"""
ML Price Predictor
------------------
Trains Linear Regression and Random Forest models on recent gold price
data from SQLite and predicts the next tick price.

Returns predicted price, buy_score (0–100), confidence, and a
combined recommendation for both models.
"""

import sqlite3
import logging
import numpy as np

log = logging.getLogger(__name__)

MIN_RECORDS = 20


def _load_data(db_path: str, n: int = 200):
    """Return feature matrix X and target vector y from SQLite."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT t.price, m.change_pct, m.ma10, m.volatility "
        "FROM raw_ticks t JOIN metrics m ON m.tick_id = t.id "
        "ORDER BY t.id ASC LIMIT ?",
        (n,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _build_xy(rows: list):
    """
    Features: [price, change_pct, ma10, volatility] at tick i
    Target:   price at tick i+1
    """
    X, y = [], []
    for i in range(len(rows) - 1):
        r = rows[i]
        X.append([r["price"], r["change_pct"], r["ma10"], r["volatility"]])
        y.append(rows[i + 1]["price"])
    return np.array(X, dtype=float), np.array(y, dtype=float)


def _buy_score(current_price: float, predicted_price: float, volatility: float) -> int:
    """
    Score 0–100:
    - Base is driven by predicted direction vs current price
    - High volatility compresses score toward neutral (50)
    """
    if current_price <= 0:
        return 50

    pct_change = (predicted_price - current_price) / current_price * 100

    # Map pct_change (-2% … +2%) to raw score (0 … 100)
    raw = 50 + pct_change * 12.5          # ±2% → ±25 pts around 50
    raw = max(0.0, min(100.0, raw))

    # Volatility dampening: high vol → pull toward 50
    vol_factor = min(volatility / 5.0, 1.0)   # saturates at vol=5
    dampened = raw + (50 - raw) * vol_factor * 0.4

    return int(round(dampened))


def _confidence(n_samples: int) -> str:
    if n_samples >= 100:
        return "high"
    if n_samples >= 40:
        return "medium"
    return "low"


def _recommendation(lr_score: int, rf_score: int) -> str:
    avg = (lr_score + rf_score) / 2
    if avg >= 65:
        return "BUY"
    if avg <= 38:
        return "WAIT"
    return "HOLD"


def predict(db_path: str):
    """
    Main entry point called by api_server.

    Returns a dict with predictions for both models or an
    insufficient_data response if not enough rows exist.
    """
    rows = _load_data(db_path)

    if len(rows) < MIN_RECORDS:
        return {
            "status": "insufficient_data",
            "message": f"Need at least {MIN_RECORDS} ticks. Currently have {len(rows)}.",
            "data_points_used": len(rows),
        }

    X, y = _build_xy(rows)
    n_samples = len(X)
    current_price = rows[-1]["price"]
    current_vol   = rows[-1]["volatility"]
    last_features = np.array([[
        rows[-1]["price"],
        rows[-1]["change_pct"],
        rows[-1]["ma10"],
        rows[-1]["volatility"],
    ]], dtype=float)

    results = {}

    # ── Linear Regression ────────────────────────────────────────────
    try:
        from sklearn.linear_model import LinearRegression
        from sklearn.preprocessing import StandardScaler

        scaler_lr = StandardScaler()
        X_scaled  = scaler_lr.fit_transform(X)
        lr_model  = LinearRegression()
        lr_model.fit(X_scaled, y)

        lr_pred  = float(lr_model.predict(scaler_lr.transform(last_features))[0])
        lr_score = _buy_score(current_price, lr_pred, current_vol)

        results["linear_regression"] = {
            "predicted_price": round(lr_pred, 2),
            "buy_score":       lr_score,
            "confidence":      _confidence(n_samples),
        }
    except Exception as exc:
        log.error("Linear Regression failed: %s", exc)
        results["linear_regression"] = {"error": str(exc)}

    # ── Random Forest ────────────────────────────────────────────────
    try:
        from sklearn.ensemble import RandomForestRegressor

        rf_model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
        rf_model.fit(X, y)

        rf_pred  = float(rf_model.predict(last_features)[0])
        rf_score = _buy_score(current_price, rf_pred, current_vol)

        # Approximate confidence via prediction std across trees
        tree_preds = np.array([t.predict(last_features)[0] for t in rf_model.estimators_])
        pred_std   = float(np.std(tree_preds))
        conf_label = "high" if pred_std < 2 else "medium" if pred_std < 8 else "low"

        results["random_forest"] = {
            "predicted_price": round(rf_pred, 2),
            "buy_score":       rf_score,
            "confidence":      conf_label,
        }
    except Exception as exc:
        log.error("Random Forest failed: %s", exc)
        results["random_forest"] = {"error": str(exc)}

    # ── Combined recommendation ───────────────────────────────────────
    lr_s = results["linear_regression"].get("buy_score", 50)
    rf_s = results["random_forest"].get("buy_score", 50)

    results["recommendation"]    = _recommendation(lr_s, rf_s)
    results["data_points_used"]  = n_samples
    results["status"]            = "ok"

    return results
