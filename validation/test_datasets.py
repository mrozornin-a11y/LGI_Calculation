"""Проверка ядра по калибровочным данным Hall (1988), Chen (1972) и выгрузке NIST WebBook.

Тесты фиксируют выявленные расхождения: они должны воспроизводиться и не должны исчезать из-за
изменения формул, границ применимости или допусков. Запуск:
    python -m unittest discover -s validation -t .
"""
import csv
import hashlib
import unittest
from pathlib import Path

from validation import datasets as D

ROOT = Path(__file__).resolve().parent.parent
AUDIT = D.AUDIT_DIR

try:
    import CoolProp  # noqa: F401
    HAVE_COOLPROP = True
except ImportError:
    HAVE_COOLPROP = False


def _archive(name):
    with open(AUDIT / name, encoding='utf-8', newline='') as fh:
        return {r['id']: r for r in csv.DictReader(fh)}


class TestProvenance(unittest.TestCase):
    def test_archive_hashes(self):
        """Файлы аудита хранятся без изменений (хеши ядра — из source_hashes.json аудитора)."""
        import json
        hashes = json.loads((AUDIT / 'source_hashes.json').read_text(encoding='utf-8'))
        for rel, h in hashes.items():
            if rel.startswith('audit_repo/'):
                self.assertEqual(hashlib.sha256((AUDIT / rel).read_bytes()).hexdigest(), h, rel)
        self.assertEqual((AUDIT / 'nist_co2_raw.tsv').read_bytes(), (AUDIT / 'nist_co2_mass.tsv').read_bytes())

    def test_audited_core_copy_equals_working_core(self):
        """Копии ядра в архиве отличаются от рабочих файлов только завершающими пустыми строками;
        рабочие файлы ими не заменялись."""
        for name in ('salinity.py', 'co2.py', '__init__.py'):
            audited = (AUDIT / 'audit_repo' / 'fluid_core' / name).read_text(encoding='utf-8')
            working = (ROOT / 'fluid_core' / name).read_text(encoding='utf-8')
            self.assertEqual(audited.rstrip('\n'), working.rstrip('\n'), name)

    def test_curated_inputs_match_archive(self):
        for curated, archive, cols in (
                (D.HALL_CSV, 'hall1988_experiments.csv',
                 ('temperature_c', 'expected_wt_pct', 'evidence_type', 'independence', 'source_temperature_error_c',
                  'source_composition_error_wt_pct')),
                (D.CHEN_CSV, 'chen1972_experiments.csv',
                 ('chen_printed_temperature_c', 'temperature_c', 'pressure_psia', 'expected_wt_pct', 'evidence_type',
                  'independence', 'source_temperature_error_c', 'source_composition_error_relative'))):
            arch = _archive(archive)
            with open(curated, encoding='utf-8', newline='') as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([r['id'] for r in rows], list(arch))
            for r in rows:
                for c in cols:
                    self.assertEqual(r[c], arch[r['id']][c], (r['id'], c))

    def test_evidence_classes_not_upgraded(self):
        for r in D.evaluate_hall() + D.evaluate_chen():
            self.assertEqual(r.meta['independence'], 'calibration_data', r.id)
        self.assertEqual(sum(r.role == 'anchor' for r in D.evaluate_hall()), 1)


class TestHall(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = D.evaluate_hall()
        cls.arch = _archive('hall1988_experiments.csv')

    def test_counts(self):
        reg = [r.regression for r in self.rows]
        self.assertEqual((reg.count('PASS'), reg.count('FAIL'), reg.count('OUTSIDE_DOMAIN')), (20, 1, 1))
        exp = [r.experimental for r in self.rows]
        self.assertEqual((exp.count('COMPATIBLE'), exp.count('INCOMPATIBLE')), (21, 0))

    def test_open_fail_preserved(self):
        r = next(x for x in self.rows if x.id == 'HSB88-02')
        self.assertEqual(r.regression, 'FAIL')
        self.assertEqual(r.experimental, 'COMPATIBLE')
        self.assertAlmostEqual(r.deviation, -0.06632701446400047, places=12)
        self.assertAlmostEqual(r.regression_tol, 0.063164477432, places=7)

    def test_endpoint_outside_domain_not_pass(self):
        r = next(x for x in self.rows if x.id == 'HSB88-22')
        self.assertEqual((r.regression, r.experimental), ('OUTSIDE_DOMAIN', 'OUTSIDE_DOMAIN'))
        self.assertIsNone(r.computed)
        self.assertIn('−21,1', r.reason)

    def test_reproduces_auditor_numbers(self):
        for r in self.rows:
            a = self.arch[r.id]
            status = {'OUTSIDE_DOMAIN': 'OUTSIDE_CORE_DOMAIN'}.get(r.regression, r.regression)
            self.assertEqual(status, a['status'], r.id)
            if r.computed is not None:
                self.assertEqual(r.computed, float(a['calculated_wt_pct']), r.id)
                self.assertAlmostEqual(r.regression_tol, float(a['regression_tolerance_abs']), delta=1e-7)
                self.assertAlmostEqual(r.experimental_tol, float(a['experimental_envelope_abs']), delta=1e-7)
                self.assertTrue(r.app_consistent, r.id)


class TestChen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = D.evaluate_chen()
        cls.arch = _archive('chen1972_experiments.csv')

    def test_counts(self):
        reg = [r.regression for r in self.rows]
        self.assertEqual((reg.count('PASS'), reg.count('FAIL'), reg.count('OUTSIDE_DOMAIN')), (55, 0, 2))
        exp = [r.experimental for r in self.rows]
        self.assertEqual((exp.count('COMPATIBLE'), exp.count('INCOMPATIBLE')), (38, 17))

    def test_statistics(self):
        st = D.chen_statistics(self.rows)
        self.assertAlmostEqual(st['max_abs'], 0.5575297772093748, places=12)
        self.assertAlmostEqual(st['max_rel_pct'], 5.586470713520789, places=10)
        self.assertEqual(st['max_rel_at_c'], 4.75)
        self.assertAlmostEqual(st['mean_abs_rel_pct'], 1.3196512776194336, places=10)
        self.assertLess(st['max_rel_pct'], 5.61)        # в пределах опубликованного максимума Darling

    def test_temperature_adoption_recorded(self):
        r = next(x for x in self.rows if x.id == 'CH72-29')
        self.assertEqual(r.meta['chen_printed_temperature_c'], '1.34')
        self.assertEqual(r.temperature_c, -1.34)
        self.assertIn('Darling', r.meta['temperature_basis'])

    def test_outside_domain_rows_kept(self):
        out = [r for r in self.rows if r.regression == 'OUTSIDE_DOMAIN']
        self.assertEqual([r.temperature_c for r in out], [-10.08, -10.4])
        self.assertTrue(all(r.computed is None for r in out))

    def test_reproduces_auditor_numbers(self):
        for r in self.rows:
            a = self.arch[r.id]
            status = {'OUTSIDE_DOMAIN': 'OUTSIDE_CORE_DOMAIN'}.get(r.regression, r.regression)
            self.assertEqual(status, a['status'], r.id)
            if r.computed is not None:
                self.assertEqual(r.computed, float(a['calculated_wt_pct']), r.id)
                self.assertAlmostEqual(r.regression_tol, float(a['regression_tolerance_abs']), delta=1e-7)
                self.assertAlmostEqual(r.experimental_tol, float(a['experimental_envelope_abs']), delta=1e-7)
                self.assertEqual(r.experimental == 'COMPATIBLE', a['within_experimental_envelope'] == 'True', r.id)
                self.assertTrue(r.app_consistent, r.id)


@unittest.skipUnless(HAVE_COOLPROP, 'CoolProp не установлен: проверка по NIST не выполнена (это не PASS)')
class TestNist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = D.evaluate_nist()

    def test_all_within_rounding_of_export(self):
        self.assertEqual(len(self.rows), 27)
        for r in self.rows:
            self.assertEqual(r.status, 'PASS', (r.id, r.deviation, r.tolerance))
            self.assertTrue(r.app_consistent, r.id)

    def test_tolerance_is_rounding_of_printed_digits(self):
        r = next(x for x in self.rows if x.id == 'NIST--50-pressure')
        self.assertEqual(r.expected_text, '6.8234161')
        self.assertEqual(r.rounding_half_unit, 5e-8)
        self.assertAlmostEqual(r.tolerance, 5e-8 + 6.8234161e-8, delta=1e-20)

    def test_matches_auditor(self):
        arch = _archive('nist_co2_checkpoints.csv')
        for r in self.rows:
            self.assertEqual(r.status, arch[r.id]['status'], r.id)
            self.assertEqual(r.expected, float(arch[r.id]['expected']), r.id)


class TestReconciliation(unittest.TestCase):
    def test_registry_matches_findings(self):
        rec = D.reconcile(D.evaluate_hall() + D.evaluate_chen(), D.evaluate_nist())
        self.assertEqual(rec.new_discrepancies, [])
        self.assertEqual(rec.known_not_reproduced, [])
        self.assertEqual(len(rec.known_reproduced), 18)
        self.assertTrue(rec.ok)

    def test_new_discrepancy_is_flagged(self):
        rows = D.evaluate_hall()
        rec = D.reconcile(rows, [], known=[])          # пустой реестр: все расхождения новые
        self.assertIn(('HSB88-02', 'regression', 'FAIL'), rec.new_discrepancies)
        self.assertFalse(rec.ok)

    def test_vanished_discrepancy_is_flagged(self):
        """Если известное расхождение исчезло (например, после правки формулы или допуска), нужен пересмотр."""
        rows = D.evaluate_hall()
        for r in rows:
            if r.id == 'HSB88-02':
                r.regression = 'PASS'
        rec = D.reconcile(rows, [], known=[k for k in D.load_known() if k.id == 'HSB88-02'])
        self.assertEqual([k.id for k in rec.known_not_reproduced], ['HSB88-02'])
        self.assertFalse(rec.ok)


if __name__ == '__main__':
    unittest.main()
