"""Validated offline inputs and transparent, session-based analytics."""
import csv
import json
import math
from datetime import date
from pathlib import Path
from statistics import mean


def number(value, label, minimum=None, integer=False):
    if isinstance(value, bool):
        raise ValueError(f"{label}: expected a number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: expected a number") from exc
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError(f"{label}: invalid numeric range")
    if integer and not result.is_integer():
        raise ValueError(f"{label}: expected an integer")
    return result


def load_prices(path):
    """ISO Gregorian dates; close in IRR/share; volume in shares."""
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"date", "close_irr", "adjusted_close_irr", "volume"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Price CSV must contain {sorted(required)}")
        rows = []
        seen = set()
        for row in reader:
            day = date.fromisoformat(row["date"])
            if day.isoformat() != row["date"] or day > date.today():
                raise ValueError("Price dates must be ISO dates in the past or today")
            if day in seen:
                raise ValueError(f"Duplicate price date: {day}")
            seen.add(day)
            rows.append({
                "date": day.isoformat(),
                "close_irr": number(row["close_irr"], "close_irr", minimum=0.000001),
                "adjusted_close_irr": number(row["adjusted_close_irr"], "adjusted_close_irr", minimum=0.000001),
                "volume": number(row["volume"], "volume", minimum=0, integer=True),
            })
    if len(rows) < 2:
        raise ValueError("At least two price observations are required")
    return sorted(rows, key=lambda row: row["date"])


def load_fundamentals(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Fundamentals must be a JSON object")
    for field in ("symbol", "company", "source", "price_source", "adjustment_method", "period_end", "available_on", "basis", "currency", "data_kind"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"Missing or invalid field: {field}")
    if data["currency"] != "IRR" or data["basis"] != "TTM":
        raise ValueError("Use IRR monetary amounts and TTM financial statements")
    if data["data_kind"] not in ("synthetic", "user_provided"):
        raise ValueError("data_kind must be synthetic or user_provided")
    end, available = date.fromisoformat(data["period_end"]), date.fromisoformat(data["available_on"])
    if end.isoformat() != data["period_end"] or available.isoformat() != data["available_on"]:
        raise ValueError("Financial dates must use YYYY-MM-DD")
    if end > available:
        raise ValueError("available_on cannot precede period_end")
    for field in ("revenue_irr", "assets_irr", "liabilities_irr"):
        data[field] = number(data.get(field), field, minimum=0)
    data["equity_irr"] = number(data.get("equity_irr"), "equity_irr")
    data["net_income_irr"] = number(data.get("net_income_irr"), "net_income_irr")
    data["shares_outstanding"] = number(data.get("shares_outstanding"), "shares_outstanding", minimum=1, integer=True)
    if not math.isclose(data["assets_irr"], data["equity_irr"] + data["liabilities_irr"], rel_tol=1e-6, abs_tol=1):
        raise ValueError("Assets must equal equity plus liabilities")
    return data


def divide(a, b):
    return a / b if b else None


def analyze(prices, fundamentals):
    latest = prices[-1]
    if fundamentals["available_on"] > latest["date"]:
        raise ValueError("Financial statements were unavailable on the price valuation date")
    adjusted = [p["adjusted_close_irr"] for p in prices]
    returns = {str(n): adjusted[-1] / adjusted[-n - 1] - 1 if len(prices) > n else None for n in (1, 5, 20, 60)}
    # Exactly 20 preceding sessions; current volume is deliberately excluded.
    baseline = mean(p["volume"] for p in prices[-21:-1]) if len(prices) >= 21 else None
    volume_ratio = divide(latest["volume"], baseline) if baseline is not None else None
    peak = adjusted[0]
    max_drawdown = 0.0
    for close in adjusted:
        peak = max(peak, close)
        max_drawdown = min(max_drawdown, close / peak - 1)
    f = fundamentals
    market_cap = latest["close_irr"] * f["shares_outstanding"]
    eps = f["net_income_irr"] / f["shares_outstanding"]
    return {
        "metadata": {k: f[k] for k in ("symbol", "company", "source", "price_source", "adjustment_method", "period_end", "available_on", "basis", "currency", "data_kind")},
        "as_of": latest["date"], "observations": len(prices),
        "close_irr": latest["close_irr"], "market_cap_irr": market_cap,
        "returns": returns, "max_drawdown": max_drawdown,
        "volume": latest["volume"], "previous_20_session_volume_mean": baseline,
        "volume_ratio": volume_ratio,
        "volume_alert": volume_ratio >= 2 if volume_ratio is not None else None,
        "eps_ttm_irr": eps,
        "pe_ttm": latest["close_irr"] / eps if eps > 0 else None,
        "pb": market_cap / f["equity_irr"] if f["equity_irr"] > 0 else None,
        "net_margin": divide(f["net_income_irr"], f["revenue_irr"]),
        "liabilities_to_assets": divide(f["liabilities_irr"], f["assets_irr"]),
        "prices": prices,
    }
