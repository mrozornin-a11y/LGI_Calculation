"""Пакетная обработка CSV ядра (fluid_core.batch)."""
import csv
import tempfile
import unittest
from pathlib import Path

from fluid_core.batch import HEADERS, run_csv

ROOT = Path(__file__).resolve().parent.parent

try:
    import CoolProp  # noqa: F401
    HAVE_COOLPROP = True
except ImportError:
    HAVE_COOLPROP = False


class TestBatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, text):
        src = self.dir / 'in.csv'
        src.write_text(text, encoding='utf-8')
        out = self.dir / 'out.csv'
        total, ok = run_csv(src, out)
        with out.open(encoding='utf-8-sig') as fh:
            return total, ok, list(csv.DictReader(fh))

    def test_short_row_does_not_crash_batch(self):
        text = ','.join(HEADERS) + '\nA,1,bodnar\nB,2,bodnar,-5\n'
        total, ok, rows = self._run(text)
        self.assertEqual((total, ok), (2, 1))
        self.assertEqual(rows[0]['status'], 'error')
        self.assertEqual(rows[1]['status'], 'ok')

    def test_missing_column_rejected(self):
        with self.assertRaises(ValueError):
            self._run('sample_id,method\nA,bodnar\n')

    def test_example_input(self):
        total, ok, rows = self._run((ROOT / 'examples' / 'example_input.csv').read_text(encoding='utf-8'))
        self.assertEqual(total, 5)
        status = [r['status'] for r in rows]
        self.assertEqual(status[:2], ['ok', 'ok'])
        self.assertEqual(status[4], 'error')     # направление гомогенизации не указано
        if HAVE_COOLPROP:
            self.assertEqual(status[2:4], ['ok', 'ok'])
        else:
            self.assertEqual(status[2:4], ['error', 'error'])

    def test_decimal_comma_quoted(self):
        text = ','.join(HEADERS) + '\nA,1,bodnar,"-5,0",,,,,\n'
        _, ok, rows = self._run(text)
        self.assertEqual(ok, 1)
        self.assertAlmostEqual(float(rows[0]['value']), 7.864625, places=6)


if __name__ == '__main__':
    unittest.main()
