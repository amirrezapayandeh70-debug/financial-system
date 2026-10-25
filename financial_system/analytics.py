"""Validated offline inputs and transparent, session-based analytics."""
import csv
import json
import io
import math
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean


def number(value, label, minimum=None, integer=False):
    if isinstance(value, bool):
        raise ValueError(f"{label}: expected a number")
    try:
        precise = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{label}: expected a number") from exc
    if not precise.is_finite() or (minimum is not None and precise < Decimal(str(minimum))):
        raise ValueError(f"{label}: invalid numeric range")
    if abs(precise) > Decimal(str(sys.float_info.max)):
        raise ValueError(f"{label}: numeric range exceeds supported precision")
    if integer:
        if precise != precise.to_integral_value():
            raise ValueError(f"{label}: expected an integer")
        return int(precise)
    result = float(precise)
    if not math.isfinite(result):
        raise ValueError(f"{label}: numeric range exceeds supported precision")
    return result


def iso_day(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label}: expected YYYY-MM-DD")
    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label}: expected YYYY-MM-DD") from exc
    if day.isoformat() != value or day > date.today():
        raise ValueError(f"{label}: expected a past or current YYYY-MM-DD date")
    return day


def validate_prices(rows):
    if not isinstance(rows, list) or len(rows) < 2:
        raise ValueError("At least two price observations are required")
    normalized, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not {"date", "close_irr", "adjusted_close_irr", "volume"}.issubset(row):
            raise ValueError("Each price observation must contain date, close_irr, adjusted_close_irr, volume")
        day = iso_day(row["date"], "price date").isoformat()
        if day in seen:
            raise ValueError(f"Duplicate price date: {day}")
        seen.add(day)
        normalized.append({
            "date": day,
            "close_irr": number(row["close_irr"], "close_irr", minimum=0.000001),
            "adjusted_close_irr": number(row["adjusted_close_irr"], "adjusted_close_irr", minimum=0.000001),
            "volume": number(row["volume"], "volume", minimum=0, integer=True),
        })
    return sorted(normalized, key=lambda row: row["date"])


def load_prices(path):
    """ISO Gregorian dates; close in IRR/share; volume in shares."""
    return parse_prices(Path(path).read_bytes().decode("utf-8-sig"))


def parse_prices(text):
    with io.StringIO(text, newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"date", "close_irr", "adjusted_close_irr", "volume"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Price CSV must contain {sorted(required)}")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("Duplicate CSV column names")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"Malformed CSV row at line {reader.line_num}")
            rows.append(row)
    return validate_prices(rows)


def load_fundamentals(path):
    return validate_fundamentals(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def validate_fundamentals(data):
    if not isinstance(data, dict):
        raise ValueError("Fundamentals must be a JSON object")
    data = data.copy()
    for field in ("symbol", "company", "source", "price_source", "adjustment_method", "period_end", "available_on", "basis", "currency", "data_kind"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"Missing or invalid field: {field}")
    if data["currency"] != "IRR" or data["basis"] != "TTM":
        raise ValueError("Use IRR monetary amounts and TTM financial statements")
    if data["data_kind"] not in ("synthetic", "user_provided"):
        raise ValueError("data_kind must be synthetic or user_provided")
    end, available = iso_day(data["period_end"], "period_end"), iso_day(data["available_on"], "available_on")
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


def analyze(prices, fundamentals, as_of=None):
    prices = validate_prices(prices)
    fundamentals = validate_fundamentals(fundamentals)
    if as_of is not None:
        cutoff = iso_day(as_of, "as_of").isoformat()
        prices = [p for p in prices if p["date"] <= cutoff]
        if len(prices) < 2:
            raise ValueError("At least two price observations required on or before as_of")
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
    result = {
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

    # Reject overflow at the engine boundary, before reporting or writing output.
    try:
        json.dumps(result, allow_nan=False)
    except (ValueError, OverflowError) as exc:
        raise ValueError("Calculated values exceed supported numeric range") from exc
    return result


def compare_benchmark(prices, benchmark):
    """Compare endpoints only when every selected equity session is present."""
    prices = validate_prices(prices)
    benchmark = validate_prices(benchmark)
    by_date = {p["date"]: p["adjusted_close_irr"] for p in benchmark}
    if any(p["date"] not in by_date for p in prices):
        raise ValueError("Benchmark must cover every selected equity session exactly by date")
    comparison = {}
    for n in (1, 5, 20, 60):
        if len(prices) <= n:
            comparison[str(n)] = None
            continue
        start, end = prices[-n - 1], prices[-1]
        equity_return = end["adjusted_close_irr"] / start["adjusted_close_irr"] - 1
        benchmark_return = by_date[end["date"]] / by_date[start["date"]] - 1
        comparison[str(n)] = {"start": start["date"], "end": end["date"],
                              "benchmark_return": benchmark_return,
                              "excess_return": equity_return - benchmark_return}
    json.dumps(comparison, allow_nan=False)
    return comparison
