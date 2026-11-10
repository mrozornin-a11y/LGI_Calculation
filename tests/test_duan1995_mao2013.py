"""Этап 2б, часть 5: уравнение состояния Duan et al. (1995), изохора и линия расслоения Mao et al. (2013)."""
import csv
import unittest
from pathlib import Path

from fluid_core import duan1995 as E
from fluid_core import mao2013 as S

ROOT = Path(__file__).resolve().parent.parent


class TestDuan1995(unittest.TestCase):
    def test_matches_author_program(self):
        """Давления, наклон и свободный член изохоры для состава и объёма из эталонного прогона (выборка)."""
        with open(ROOT / 'validation' / 'data' / 'sm2018_oracle.csv', encoding='utf-8') as fh:
            rows = {r['case']: r for r in csv.DictReader(fh)}
        for case in ('SM01', 'SM20', 'SM32', 'SM38', 'SM40', 'SM41'):
            r = rows[case]
            with self.subTest(case):
                iso = E.author_isochore(float(r['V_cm3_mol']), float(r['X_H2O']), float(r['X_NaCl']), float(r['X_CO2']))
                for got, key in zip(iso.pressures_bar, ('P350_bar', 'P400_bar', 'P450_bar', 'P500_bar')):
                    self.assertAlmostEqual(got / float(r[key]), 1, delta=1e-7)
                self.assertAlmostEqual(iso.slope_bar_per_c / float(r['dPdT_bar_C']), 1, delta=1e-7)
                self.assertAlmostEqual(iso.intercept_bar / float(r['intercept_bar']), 1, delta=1e-6)
                if r['P_Thtot_bar']:
                    self.assertAlmostEqual(iso.pressure_at(float(r['Th_tot'])) / float(r['P_Thtot_bar']), 1, delta=1e-7)

    def test_limits_and_trends(self):
        x = (0.89, 0.006, 0.104)
        self.assertAlmostEqual(E.pressure_bar(400.0, 1e7, *x) * 1e7 / (83.14472 * 673.15), 1, delta=1e-4)   # идеальный газ
        self.assertGreater(E.pressure_bar(450.0, 25.0, *x), E.pressure_bar(400.0, 25.0, *x))                 # изохора растёт
        self.assertGreater(E.pressure_bar(400.0, 22.0, *x), E.pressure_bar(400.0, 25.0, *x))                 # сжатие
        self.assertAlmostEqual(E.pressure_bar(349.85, 25.0, *x), E.pressure_at_kelvin_bar(623.0, 25.0, *x), delta=1e-9)
        # чистая вода при 400 °C и 500 бар: объём по IAPWS-95 → давление в пределах 5 %
        from CoolProp.CoolProp import PropsSI
        v = PropsSI('M', 'Water') * 1e3 / PropsSI('Dmass', 'T', 673.15, 'P', 500e5, 'Water') * 1e3
        self.assertAlmostEqual(E.pressure_bar(400.0, v, 1.0, 0.0, 0.0) / 500, 1, delta=0.05)

    def test_linear_isochore_is_least_squares_line(self):
        iso = E.author_isochore(22.0, 0.89, 0.006, 0.104)
        resid = [p - iso.pressure_at(t) for p, t in zip(iso.pressures_bar, E.AUTHOR_ISOCHORE_LABELS_C)]
        self.assertAlmostEqual(sum(resid), 0, delta=1e-8)
        self.assertAlmostEqual(sum(r * t for r, t in zip(resid, E.AUTHOR_ISOCHORE_LABELS_C)), 0, delta=1e-5)

    def test_domain(self):
        for args in ((299.0, 25.0, 0.9, 0.0, 0.1), (1001.0, 25.0, 0.9, 0.0, 0.1), (400.0, 0.0, 0.9, 0.0, 0.1),
                     (400.0, 25.0, 0.9, 0.0, 0.2), (400.0, 25.0, 1.1, 0.0, -0.1), (float('nan'), 25.0, 0.9, 0.0, 0.1)):
            with self.subTest(args), self.assertRaises(ValueError):
                E.pressure_bar(*args)
        with self.assertRaises(TypeError):
            E.pressure_bar(True, 25.0, 0.9, 0.0, 0.1)


class TestMao2013(unittest.TestCase):
    def test_published_values(self):
        """Mao et al. (2013), табл. 9 (2 моль/кг NaCl): 373,15 K и 623,15 K при 1000 бар; табл. 7: 298,15 K, 100 бар."""
        s2 = 100 * 2 * 58.44277 / (1000 + 2 * 58.44277)
        self.assertAlmostEqual(S.co2_solubility(100.0, 1000.0, s2)[0], 1.3916, delta=0.004)
        self.assertAlmostEqual(S.co2_solubility(350.0, 1000.0, s2)[0], 6.3055, delta=0.02)
        self.assertAlmostEqual(S.co2_solubility(25.0, 100.0, 0.0)[0], 1.4330, delta=0.004)

    def test_interpolation_between_parameter_sets(self):
        lo, mid, hi = (S.co2_solubility(t, 800.0, 8.0)[0] for t in (229.85, 239.85, 249.85))
        self.assertTrue(min(lo, hi) < mid < max(lo, hi))
        m, x = S.co2_solubility(250.0, 800.0, 8.0)
        self.assertAlmostEqual(x, m / (m + 8 / 58.44277 / 0.092 + 1000 / 18.0152), delta=1e-12)

    def test_domain(self):
        for args in ((-1.0, 500.0, 5.0), (451.0, 500.0, 5.0), (250.0, 0.0, 5.0), (250.0, 30.0, 5.0),
                     (250.0, 500.0, -1.0)):
            with self.subTest(args), self.assertRaises(ValueError):
                S.co2_solubility(*args)
        with self.assertRaises(ValueError):
            S.co2_solubility(250.0, 500.0, 5.0, numerics='fast')


if __name__ == '__main__':
    unittest.main()
