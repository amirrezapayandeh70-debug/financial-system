import argparse
import json
from pathlib import Path

from .analytics import analyze, load_fundamentals, load_prices
from .report import render


def main():
    parser = argparse.ArgumentParser(description="Offline equity analytics and Persian RTL reporting")
    parser.add_argument("--demo", action="store_true", help="Use clearly labeled synthetic FMLI inputs")
    parser.add_argument("--prices", type=Path, help="CSV price history")
    parser.add_argument("--fundamentals", type=Path, help="JSON TTM financial statements")
    parser.add_argument("--output", type=Path, default=Path("output"))
    args = parser.parse_args()
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
        result = analyze(load_prices(prices), load_fundamentals(fundamentals))
        html = render(result)
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        (args.output / "report.html").write_text(html, encoding="utf-8")
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f"Input/output error: {exc}\n")
    print(f"Report: {(args.output / 'report.html').resolve()}")
    print(f"Data: {(args.output / 'analysis.json').resolve()}")


if __name__ == "__main__":
    main()
