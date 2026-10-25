"""Acceptance and regression tests for PR #1 hardening."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from financial_system.analytics import analyze, compare_benchmark, load_fundamentals, load_prices, number, parse_prices
from financial_system.report import render

ROOT = Path(__file__).resolve().parents[1]


class ReviewAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.prices = load_prices(ROOT / 'data/demo/prices.csv')
        self.f = load_fundamentals(ROOT / 'data/demo/fundamentals.json')

    def cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'financial_system', *map(str, args)],
                              cwd=ROOT, capture_output=True, text=True)

    def test_direct_engine_rejects_invalid_inputs(self):
        for prices in ([], self.prices[:1], self.prices + self.prices[:1],
                       [{**self.prices[0], 'volume': None}, self.prices[1]],
                       [{**self.prices[0], 'date': None}, self.prices[1]]):
            with self.subTest(prices=prices[:1]), self.assertRaises(ValueError):
                analyze(prices, self.f)
        with self.assertRaises(ValueError):
            analyze(self.prices, {**self.f, 'assets_irr': 1})

    def test_direct_engine_sorts_and_does_not_mutate_inputs(self):
        prices = list(reversed(self.prices))
        before = copy.deepcopy((prices, self.f))
        result = analyze(prices, self.f)
        self.assertEqual(result['as_of'], self.prices[-1]['date'])
        self.assertEqual((prices, self.f), before)

    def test_integer_precision_is_preserved_and_fraction_is_rejected(self):
        self.assertEqual(number('9007199254740993', 'shares', integer=True), 9007199254740993)
        with self.assertRaises(ValueError):
            number('9007199254740992.1', 'shares', integer=True)

    def test_malformed_csv_and_duplicate_headers_are_rejected(self):
        header = 'date,close_irr,adjusted_close_irr,volume\n'
        for text in (header + '2026-01-02\n', header + '2026-01-02,1,1,2,extra\n',
                     'date,date,close_irr,adjusted_close_irr,volume\n',
                     header + ',1,1,2\n'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_prices(text)

    def test_cli_malformed_input_has_clean_error_and_no_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path, out = Path(folder) / 'bad.csv', Path(folder) / 'output'
            path.write_text('date,close_irr,adjusted_close_irr,volume\n2026-01-02\n')
            proc = self.cli('--prices', path, '--fundamentals', ROOT / 'data/demo/fundamentals.json', '--output', out)
            self.assertEqual(proc.returncode, 2)
            self.assertNotIn('Traceback', proc.stderr)
            self.assertFalse(out.exists())

    def test_cutoff_uses_only_available_prices(self):
        cutoff = self.prices[25]['date']
        result = analyze(self.prices, self.f, as_of=cutoff)
        expected = analyze(self.prices[:26], self.f)
        self.assertEqual(result, expected)
        future = copy.deepcopy(self.prices)
        future[-1]['adjusted_close_irr'] *= 100
        self.assertEqual(analyze(future, self.f, as_of=cutoff), expected)

    def test_cutoff_cannot_leak_financial_snapshot(self):
        with self.assertRaises(ValueError):
            analyze(self.prices, {**self.f, 'available_on': self.prices[30]['date']}, self.prices[25]['date'])

    def test_cutoff_before_history_or_invalid_is_rejected(self):
        for cutoff in ('2025-01-01', self.prices[0]['date'], '20260103', '2099-01-01'):
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                analyze(self.prices, self.f, cutoff)

    def test_cutoff_on_non_session_uses_previous_observation(self):
        result = analyze(self.prices, self.f, '2026-01-09')
        self.assertEqual(result['as_of'], '2026-01-07')

    def test_benchmark_same_dates_known_return_and_excess(self):
        prices = self.prices[:6]
        for i, row in enumerate(prices):
            row['adjusted_close_irr'] = 100 + 10 * i
        benchmark = copy.deepcopy(prices)
        for i, row in enumerate(benchmark):
            row['adjusted_close_irr'] = 100 + 5 * i
        result = compare_benchmark(prices, benchmark)
        self.assertAlmostEqual(result['5']['benchmark_return'], .25)
        self.assertAlmostEqual(result['5']['excess_return'], .25)
        self.assertEqual(result['5']['start'], prices[0]['date'])
        self.assertIsNone(result['20'])

    def test_benchmark_missing_session_rejected_extra_dates_allowed(self):
        with self.assertRaises(ValueError):
            compare_benchmark(self.prices[:6], self.prices[1:])
        self.assertAlmostEqual(compare_benchmark(self.prices[:6], self.prices)['5']['excess_return'], 0)

    def test_overflow_cannot_become_a_valid_result(self):
        prices = copy.deepcopy(self.prices)
        prices[-1]['close_irr'] = 1e308
        with self.assertRaises(ValueError):
            analyze(prices, self.f)

    def test_cli_audit_hashes_exact_input_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            proc = self.cli('--demo', '--as-of', '2026-03-01', '--output', folder)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads((Path(folder) / 'analysis.json').read_text())
            audit = result['audit']
            for role, filename in (('prices', 'prices.csv'), ('fundamentals', 'fundamentals.json')):
                raw = (ROOT / 'data/demo' / filename).read_bytes()
                self.assertEqual(audit['inputs'][role], {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
            self.assertEqual(audit['requested_as_of'], '2026-03-01')
            self.assertEqual(result['as_of'], '2026-03-01')

    def test_cli_benchmark_and_escaped_report(self):
        with tempfile.TemporaryDirectory() as folder:
            info_path = Path(folder) / 'info.json'
            info_path.write_text(json.dumps({'name': '<script>x</script>', 'source': 'fixture',
                                           'adjustment_method': 'synthetic', 'data_kind': 'synthetic'}))
            proc = self.cli('--demo', '--benchmark', ROOT / 'data/demo/prices.csv',
                            '--benchmark-info', info_path, '--output', folder)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads((Path(folder) / 'analysis.json').read_text())
            self.assertEqual(result['benchmark']['returns']['60']['excess_return'], 0)
            self.assertEqual(len(result['audit']['inputs']), 4)
            html = render(result)
            self.assertIn('&lt;script&gt;', html)
            self.assertNotIn('<script>', html)

    def test_cli_requires_benchmark_metadata_and_valid_kind(self):
        proc = self.cli('--demo', '--benchmark', ROOT / 'data/demo/prices.csv')
        self.assertEqual(proc.returncode, 2)
        with tempfile.TemporaryDirectory() as folder:
            info = Path(folder) / 'info.json'
            info.write_text('{"name":"x","source":"s","adjustment_method":"m","data_kind":"verified"}')
            proc = self.cli('--demo', '--benchmark', ROOT / 'data/demo/prices.csv', '--benchmark-info', info)
            self.assertEqual(proc.returncode, 2)
            self.assertNotIn('Traceback', proc.stderr)


if __name__ == '__main__':
    unittest.main()
