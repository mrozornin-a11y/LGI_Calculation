"""Автоматическая проверка контрольных точек (научная валидация).

Отдельно от регрессионных тестов в tests/: запускается командой
    python -m unittest discover -s validation -t .
"""
import unittest

from validation import checkpoints as V

try:
    import CoolProp  # noqa: F401
    HAVE_COOLPROP = True
except ImportError:
    HAVE_COOLPROP = False


class TestCheckpointFile(unittest.TestCase):
    def test_file_is_well_formed(self):
        cps = V.load_checkpoints()
        self.assertGreater(len(cps), 0)
        for cp in cps:
            self.assertGreater(cp.tolerance(), 0, cp.id)
            if cp.reference_uncertainty is not None:
                # допуск не может быть строже собственной точности опорного значения
                self.assertGreaterEqual(cp.tolerance() + 1e-12, cp.reference_uncertainty, cp.id)

    def test_equation_reproduction_never_marked_independent(self):
        for cp in V.load_checkpoints():
            if cp.evidence_type == 'equation_reproduction':
                self.assertFalse(cp.independent, cp.id)
            else:
                self.assertTrue(cp.independent, cp.id)

    def test_matches_audit_source_file(self):
        """Каждая строка из приложенного аудиторского CSV перенесена без изменения значения."""
        cps = V.load_checkpoints()
        index = {(c.method, c.temperature_c, c.quantity): c for c in cps}
        src = V.source_rows()
        self.assertEqual(len(src), len(cps))
        for row in src:
            cp = index[(row['method'], float(row['temperature_c']), row['quantity'])]
            self.assertEqual(cp.expected, float(row['value']))
            self.assertEqual(cp.unit, row['unit'])
            self.assertEqual(cp.evidence_type, row['evidence_type'])


class TestEquationReproduction(unittest.TestCase):
    """Пересчёт по тем же уравнениям: проверка переноса формул, НЕ независимая проверка."""

    def test_reproduction_points(self):
        for cp in V.load_checkpoints():
            if cp.evidence_type != 'equation_reproduction':
                continue
            with self.subTest(cp.id):
                r = V.evaluate(cp)
                self.assertEqual(r.status, 'PASS', f'{cp.id}: {r.computed} vs {cp.expected}')
                self.assertTrue(r.app_consistent)


class TestIndependentReferences(unittest.TestCase):
    def test_bodnar_educational_example(self):
        cp = next(c for c in V.load_checkpoints() if c.id == 'BOD-LILLE-01')
        r = V.evaluate(cp)
        self.assertEqual(r.status, 'PASS')
        self.assertTrue(r.within_rounding)
        self.assertTrue(r.required_controls_detected, r.controls)
        self.assertEqual(r.undetected_informative, [])       # сдвиг Tm на 0,1 °C тоже обнаруживается

    @unittest.skipUnless(HAVE_COOLPROP, 'CoolProp не установлен: проверка CO₂ не выполнена')
    def test_co2_ashrae_rounded_reference(self):
        cps = [c for c in V.load_checkpoints() if c.method == 'CO2_sat']
        self.assertEqual(len(cps), 9)
        for cp in cps:
            with self.subTest(cp.id):
                r = V.evaluate(cp)
                self.assertEqual(r.status, 'PASS', f'{cp.id}: {r.computed} vs {cp.expected}')
                self.assertTrue(r.app_consistent)
                # допуск обязан обнаруживать ошибочную ветвь и путаницу °C/K
                self.assertTrue(r.controls)
                self.assertTrue(r.required_controls_detected, (cp.id, r.controls))

    @unittest.skipUnless(HAVE_COOLPROP, 'CoolProp не установлен')
    def test_ashrae_tolerance_is_coarse(self):
        """Честность отчёта: часть отклонений от ASHRAE больше интервала округления таблицы."""
        rs = [V.evaluate(c) for c in V.load_checkpoints() if c.method == 'CO2_sat']
        self.assertTrue(any(r.within_rounding is False for r in rs))
        # и 1 % не разрешает сдвиг на 1 °C для ρ жидкости при 0 и 10 °C — это должно быть видно в отчёте
        coarse = {r.checkpoint.id for r in rs if r.undetected_informative}
        self.assertEqual(coarse, {'CO2-ASH-RL00', 'CO2-ASH-RL10'})


class TestRunner(unittest.TestCase):
    def test_report_generation(self):
        import tempfile
        from pathlib import Path
        from validation import report
        rs = V.evaluate_all()
        with tempfile.TemporaryDirectory() as d:
            md = report.write_report(rs, Path(d) / 'r.md')
            text = md.read_text(encoding='utf-8')
            self.assertIn('НЕ независимая проверка', text)
            self.assertIn('Открытые вопросы', text)
            self.assertIn('Ограничение разрешающей способности', text)
            csvp = report.write_results_csv(rs, Path(d) / 'r.csv')
            self.assertEqual(len(csvp.read_text(encoding='utf-8').splitlines()), len(rs) + 1)


if __name__ == '__main__':
    unittest.main()
