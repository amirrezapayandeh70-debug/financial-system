import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from financial_system.analytics import analyze, load_fundamentals, load_prices, number
from financial_system.report import render

ROOT = Path(__file__).resolve().parents[1]


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.prices = load_prices(ROOT / "data/demo/prices.csv")
        self.f = load_fundamentals(ROOT / "data/demo/fundamentals.json")

    def test_known_returns_and_volume_without_current_session(self):
        prices = [{"date": "2026-01-02", "close_irr": 100, "adjusted_close_irr": 100 + i, "volume": 10} for i in range(21)]
        prices[-1]["volume"] = 100
        r = analyze(prices, self.f)
        self.assertAlmostEqual(r["returns"]["20"], .2)
        self.assertEqual(r["volume_ratio"], 10)
        self.assertTrue(r["volume_alert"])
        self.assertIsNone(r["returns"]["60"])

    def test_drawdown_and_valuation_use_distinct_price_series(self):
        prices = [{"date": "2026-01-02", "close_irr": 200, "adjusted_close_irr": v, "volume": 0} for v in (100, 120, 90, 110)]
        r = analyze(prices, self.f)
        self.assertAlmostEqual(r["max_drawdown"], -.25)
        self.assertEqual(r["market_cap_irr"], 200 * self.f["shares_outstanding"])
        self.assertIsNone(r["volume_ratio"])

    def test_zero_baseline_and_loss_making_company(self):
        prices = copy.deepcopy(self.prices)
        for p in prices:
            p["volume"] = 0
        self.f.update(net_income_irr=-100, revenue_irr=0, equity_irr=0)
        r = analyze(prices, self.f)
        self.assertIsNone(r["volume_alert"])
        self.assertIsNone(r["pe_ttm"])
        self.assertIsNone(r["pb"])
        self.assertIsNone(r["net_margin"])

    def test_no_future_financial_information(self):
        self.f["available_on"] = "2099-01-01"
        with self.assertRaises(ValueError):
            analyze(self.prices, self.f)

    def test_reject_nonfinite_negative_and_boolean_numbers(self):
        for value in ("nan", "inf", -1, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                number(value, "test", minimum=0)

    def test_csv_duplicates_and_order(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "prices.csv"
            header = "date,close_irr,adjusted_close_irr,volume\n"
            path.write_text(header + "2026-01-02,100,100,5\n2026-01-01,90,90,0\n")
            self.assertEqual(load_prices(path)[0]["date"], "2026-01-01")
            path.write_text(header + "2026-01-02,100,100,5\n2026-01-02,90,90,0\n")
            with self.assertRaises(ValueError):
                load_prices(path)

    def test_invalid_financial_schema_and_balance_sheet(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "financials.json"
            for key, value in (("currency", "IRT"), ("basis", "quarterly"), ("assets_irr", 1), ("shares_outstanding", 1.5), ("available_on", "2025-01-01")):
                data = {**self.f, key: value}
                path.write_text(json.dumps(data))
                with self.subTest(key=key), self.assertRaises(ValueError):
                    load_fundamentals(path)

    def test_negative_equity_is_valid_but_pb_is_not_meaningful(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "financials.json"
            data = {**self.f, "equity_irr": -100, "assets_irr": 100, "liabilities_irr": 200}
            path.write_text(json.dumps(data))
            result = analyze(self.prices, load_fundamentals(path))
            self.assertIsNone(result["pb"])

    def test_report_escapes_user_strings(self):
        self.f["company"] = '<script>alert("x")</script>'
        report = render(analyze(self.prices, self.f))
        self.assertNotIn("<script>", report)
        self.assertIn("&lt;script&gt;", report)
        self.assertIn('dir="rtl"', report)
        self.assertIn("داده ساختگی", report)

    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as folder:
            proc = subprocess.run([sys.executable, "-m", "financial_system", "--demo", "--output", folder], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads((Path(folder) / "analysis.json").read_text())
            self.assertEqual(result["metadata"]["data_kind"], "synthetic")
            self.assertTrue((Path(folder) / "report.html").is_file())

    def test_cli_missing_input_exits_cleanly(self):
        proc = subprocess.run([sys.executable, "-m", "financial_system", "--prices", "missing.csv"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
