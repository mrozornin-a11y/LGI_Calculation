"""Этап 2б, часть 1: чистая CO₂ — уравнение состояния Duan et al. (1992a) и линия насыщения."""
import unittest
from math import exp, log

from fluid_core import co2_duan1992 as D


class TestEquationOfState(unittest.TestCase):
    def test_regression_values(self):
        """Закреплённые значения (защита от случайного изменения коэффициентов)."""
        for t, p, v, lnphi in ((0.0, 50.0, 47.0523274646246, -0.5628105040170661),
                               (25.0, 100.0, 53.926023810758835, -0.7406559224062071),
                               (20.0, 30.0, 661.608395817547, -0.1739267148582081),
                               (100.0, 500.0, 53.77803234182398, -0.7737554111806748),
                               (400.0, 2000.0, 54.035057153913485, 0.5862106992612588)):
            with self.subTest((t, p)):
                s = D.state(t, p)
                self.assertAlmostEqual(s.molar_volume_cm3_mol / v, 1, delta=1e-10)
                self.assertAlmostEqual(s.ln_fugacity_coefficient, lnphi, delta=1e-9)

    def test_self_consistency(self):
        for t, p in ((-10.0, 30.0), (10.0, 20.0), (10.0, 300.0), (31.05, 60.0), (150.0, 1000.0), (800.0, 6000.0)):
            with self.subTest((t, p)):
                s = D.state(t, p)
                self.assertAlmostEqual(D.pressure_bar(t, s.molar_volume_cm3_mol) / p, 1, delta=1e-9)
                self.assertAlmostEqual(D.ln_fugacity_coefficient(t, p, s.molar_volume_cm3_mol),
                                       s.ln_fugacity_coefficient, delta=1e-9)
                self.assertAlmostEqual(s.compressibility,
                                       p * s.molar_volume_cm3_mol / D.R_CM3_BAR / (t + 273.15), delta=1e-12)
                self.assertAlmostEqual(s.fugacity_bar, p * exp(s.ln_fugacity_coefficient), delta=1e-9)
                self.assertAlmostEqual(s.density_g_cm3, D.M_CO2 / s.molar_volume_cm3_mol, delta=1e-12)

    def test_fugacity_formula_is_thermodynamically_consistent(self):
        """Независимо от источника формулы: d ln f / dP = V / (R·T) на изотерме."""
        for t, p in ((5.0, 200.0), (20.0, 20.0), (50.0, 300.0), (300.0, 1500.0), (700.0, 4000.0)):
            with self.subTest((t, p)):
                h = p * 1e-4
                a, b, s = D.state(t, p - h), D.state(t, p + h), D.state(t, p)
                slope = (log(b.fugacity_bar) - log(a.fugacity_bar)) / (2 * h)
                self.assertAlmostEqual(slope / (s.molar_volume_cm3_mol / D.R_CM3_BAR / (t + 273.15)), 1, delta=1e-6)

    def test_ideal_gas_limit(self):
        s = D.state(500.0, 0.01)
        self.assertAlmostEqual(s.compressibility, 1, delta=1e-5)
        self.assertAlmostEqual(s.ln_fugacity_coefficient, 0, delta=1e-5)

    def test_branch_below_critical_temperature(self):
        ps = D.saturation_pressure_bar(10.0)
        self.assertEqual(D.state(10.0, ps + 0.5).phase, 'liquid')
        self.assertEqual(D.state(10.0, ps - 0.5).phase, 'vapor')
        self.assertLess(D.state(10.0, ps + 0.5).molar_volume_cm3_mol, 60)
        self.assertGreater(D.state(10.0, ps - 0.5).molar_volume_cm3_mol, 250)
        self.assertEqual(D.state(40.0, 100.0).phase, 'supercritical')

    def test_flags(self):
        self.assertFalse(D.state(-10.0, 100.0).in_published_range)       # ниже 0 °C — экстраполяция
        self.assertTrue(D.state(0.0, 100.0).in_published_range)
        self.assertFalse(D.state(100.0, 100.0).multiple_roots)
        near = D.state(31.5, 75.0)                                       # несколько корней у критической точки
        self.assertTrue(near.multiple_roots)
        self.assertLess(near.molar_volume_cm3_mol, 80)                   # выбран устойчивый (плотный) корень

    def test_domain(self):
        for t, p in ((-60.0, 10.0), (1000.1, 10.0), (100.0, 0.0), (100.0, -5.0), (100.0, 8000.1),
                     (float('nan'), 10.0), (100.0, float('inf'))):
            with self.subTest((t, p)), self.assertRaises(ValueError):
                D.state(t, p)
        with self.assertRaises(TypeError):
            D.state(True, 10.0)
        with self.assertRaises(ValueError):
            D.pressure_bar(100.0, 0.0)
        with self.assertRaises(ValueError):
            D.ln_fugacity_coefficient(100.0, 10.0, -1.0)


class TestSaturation(unittest.TestCase):
    def test_against_span_wagner(self):
        """Корреляции ур. 13–15 (запись программы автора) против полного уравнения Span & Wagner (CoolProp)."""
        from CoolProp.CoolProp import PropsSI
        m = PropsSI('M', 'CO2') * 1e3
        for t in (-50.0, -20.0, 0.0, 10.0, 20.0, 28.0):
            with self.subTest(t):
                k = t + 273.15
                self.assertAlmostEqual(D.saturation_pressure_bar(t) / (PropsSI('P', 'T', k, 'Q', 0, 'CO2') / 1e5), 1,
                                       delta=5e-4)
                self.assertAlmostEqual(D.saturated_liquid_volume(t) / (m / PropsSI('Dmass', 'T', k, 'Q', 0, 'CO2') * 1e3),
                                       1, delta=5e-3)
                self.assertAlmostEqual(D.saturated_vapor_volume(t) / (m / PropsSI('Dmass', 'T', k, 'Q', 1, 'CO2') * 1e3),
                                       1, delta=1e-2)

    def test_critical_end(self):
        self.assertAlmostEqual(D.saturation_pressure_bar(31.05), 73.9, delta=1e-6)
        self.assertAlmostEqual(D.saturated_liquid_volume(31.05), D.saturated_vapor_volume(31.05), delta=1e-4)

    def test_domain(self):
        for f in (D.saturation_pressure_bar, D.saturated_liquid_volume, D.saturated_vapor_volume):
            for t in (-57.0, 31.06):
                with self.subTest((f.__name__, t)), self.assertRaises(ValueError):
                    f(t)


class TestAuthorNumerics(unittest.TestCase):
    def test_same_volume_as_exact_solution(self):
        for t, p in ((-10.0, 30.0), (0.0, 50.0), (20.0, 30.0), (25.0, 100.0), (100.0, 500.0), (400.0, 2000.0)):
            with self.subTest((t, p)):
                v, _ = D.author_volume_and_lnphi(t, p)
                self.assertAlmostEqual(v / D.state(t, p).molar_volume_cm3_mol, 1, delta=1e-9)

    def test_documented_fugacity_shift(self):
        """Особенность программы автора: ln φ жидкой CO₂ сдвинут (Z взят в смещённой точке); для газа — нет."""
        _, liquid = D.author_volume_and_lnphi(0.0, 50.0)
        self.assertAlmostEqual(liquid, -0.5490224435869998, delta=1e-9)
        self.assertAlmostEqual(liquid - D.state(0.0, 50.0).ln_fugacity_coefficient, 0.013788, delta=1e-5)
        _, vapor = D.author_volume_and_lnphi(20.0, 30.0)
        self.assertAlmostEqual(vapor, D.state(20.0, 30.0).ln_fugacity_coefficient, delta=1e-5)

    def test_metastable_root_near_critical_point(self):
        """У критической точки схема автора сходится к газовому корню, а устойчив плотный."""
        v, _ = D.author_volume_and_lnphi(31.5, 75.0)
        self.assertAlmostEqual(v, 141.77, delta=0.01)
        self.assertAlmostEqual(D.state(31.5, 75.0).molar_volume_cm3_mol, 68.07, delta=0.01)


if __name__ == '__main__':
    unittest.main()
