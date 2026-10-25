import argparse
import csv
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from .analytics import analyze, parse_prices, validate_fundamentals, compare_benchmark
from .report import render


def main():
    parser = argparse.ArgumentParser(description="Offline equity analytics and Persian RTL reporting")
    parser.add_argument("--demo", action="store_true", help="Use clearly labeled synthetic FMLI inputs")
    parser.add_argument("--prices", type=Path, help="CSV price history")
    parser.add_argument("--fundamentals", type=Path, help="JSON TTM financial statements")
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--as-of", help="Historical cutoff, YYYY-MM-DD; requires a matching financial snapshot")
    parser.add_argument("--benchmark", type=Path, help="Benchmark CSV using the price schema")
    parser.add_argument("--benchmark-info", type=Path, help="JSON name/source/adjustment_method/data_kind")
    args = parser.parse_args()
    if bool(args.benchmark) != bool(args.benchmark_info):
        parser.error("Supply both --benchmark and --benchmark-info")
    if args.demo and (args.prices or args.fundamentals):
        parser.error("--demo cannot be combined with input files")
    if args.demo:
        root = Path(__file__).resolve().parent.parent / "data" / "demo"
        prices, fundamentals = root / "prices.csv", root / "fundamentals.json"
    elif args.prices and args.fundamentals:
        prices, fundamentals = args.prices, args.fundamentals
    else:
        parser.error("Use --demo or supply both --prices and --fundamentals")
    try:
        inputs = {}

        def snapshot(path, role):
            raw = path.read_bytes()
            inputs[role] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
            return raw.decode("utf-8-sig")

        result = analyze(parse_prices(snapshot(prices, "prices")),
                         validate_fundamentals(json.loads(snapshot(fundamentals, "fundamentals"))),
                         as_of=args.as_of)
        if args.benchmark:
            info = json.loads(snapshot(args.benchmark_info, "benchmark_info"))
            if not isinstance(info, dict) or any(not isinstance(info.get(k), str) or not info[k].strip()
                                                for k in ("name", "source", "adjustment_method", "data_kind")):
                raise ValueError("Benchmark info requires name/source/adjustment_method/data_kind")
            if info["data_kind"] not in ("synthetic", "user_provided"):
                raise ValueError("Invalid benchmark data_kind")
            result["benchmark"] = {"metadata": info, "returns": compare_benchmark(
                result["prices"], parse_prices(snapshot(args.benchmark, "benchmark")))}
        result["audit"] = {"schema_version": 1, "inputs": inputs,
                           "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                           "requested_as_of": args.as_of}
        html = render(result)
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        (args.output / "report.html").write_text(html, encoding="utf-8")
    except (OSError, ValueError, KeyError, OverflowError, csv.Error) as exc:
        parser.exit(2, f"Input/output error: {exc}\n")
    print(f"Report: {(args.output / 'report.html').resolve()}")
    print(f"Data: {(args.output / 'analysis.json').resolve()}")


if __name__ == "__main__":
    main()
