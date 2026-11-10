"""Этап 2б, часть 2: четверные точки Q1/Q2, поверхности плавления клатрата, состав и объём клатрата."""
import unittest

from fluid_core import clathrate as C
from fluid_core import co2_duan1992 as D
from fluid_core.salinity import darling_1991


class TestQuadruplePoints(unittest.TestCase):
    def test_anchor_points(self):
        """Опорные точки статьи: Q1 без соли −1,48 °C и 10,34 бар; Q2 без соли +10 °C."""
        self.assertAlmostEqual(C.q1_salinity(-1.48), 0, delta=1e-12)
        self.assertAlmostEqual(C.q1_pressure_bar(-1.48), 10.34, delta=1e-12)
        self.assertAlmostEqual(C.q2_salinity(10.0), 0, delta=1e-12)
        self.assertAlmostEqual(C.q2_pressure_bar(10.0), D.saturation_pressure_bar(10.0), delta=1e-12)
        self.assertAlmostEqual(C.q2_pressure_bar(10.0), 45.1, delta=0.1)        # Larson (1955): 45,1 бар

    def test_regression_values(self):
        self.assertAlmostEqual(C.q1_salinity(-5.0), 5.9068427832265025, delta=1e-12)
        self.assertAlmostEqual(C.q1_pressure_bar(-5.0), 9.128618475008924, delta=1e-12)
        self.assertAlmostEqual(C.q2_salinity(5.0), 9.041487633749998, delta=1e-12)

    def test_q2_salinity_is_darling(self):
        """Ур. 18 — то же уравнение Darling (1991), что и в неизменяемом fluid_core/salinity.py."""
        for t in (-9.5, -5.0, 0.0, 5.0, 9.9):
            ref = darling_1991(t, liquid_co2_present=True, vapor_co2_present=True, aqueous_brine_present=True)
            self.assertAlmostEqual(C.q2_salinity(t), ref.salinity_wt_pct_nacl_eq, delta=1e-12)

    def test_inverse(self):
        for s in (0.0, 0.5, 5.0, 12.3, 20.0, 24.2):
            with self.subTest(s):
                self.assertAlmostEqual(C.q1_salinity(C.q1_temperature_c(s)), s, delta=1e-9)
                self.assertAlmostEqual(C.q2_salinity(C.q2_temperature_c(s)), s, delta=1e-9)
        self.assertEqual(C.q1_temperature_c(0.0), -1.48)
        self.assertEqual(C.q2_temperature_c(0.0), 10.0)
        self.assertAlmostEqual(C.q1_temperature_c(10.0), -7.86356107244696, delta=1e-9)
        self.assertAlmostEqual(C.q2_temperature_c(10.0), 4.363165295799654, delta=1e-9)

    def test_domain(self):
        for f, t in ((C.q1_salinity, -1.0), (C.q1_salinity, -25.1), (C.q1_pressure_bar, 0.0), (C.q2_salinity, 10.1),
                     (C.q2_salinity, -10.1), (C.q2_pressure_bar, 11.0), (C.q1_temperature_c, -0.1),
                     (C.q1_temperature_c, 24.3), (C.q2_temperature_c, 25.0), (C.q2_temperature_c, float('nan'))):
            with self.subTest((f.__name__, t)), self.assertRaises(ValueError):
                f(t)
        with self.assertRaises(TypeError):
            C.q1_salinity(True)


class TestThreePhaseSurfaces(unittest.TestCase):
    def test_laq_v_c_meets_q1_and_q2(self):
        for s in (0.0, 5.0, 15.0, 24.2):
            with self.subTest(s):
                tq1, tq2 = C.q1_temperature_c(s), C.q2_temperature_c(s)
                self.assertAlmostEqual(C.laq_v_c_pressure_bar(tq1, s), C.q1_pressure_bar(tq1), delta=1e-9)
                # сумма коэффициентов ур. 21 равна 0,9933, а не 1: кривая приходит в Q2 с недолётом 0,67 % от
                # (P(Q2) − P(Q1)), то есть на 0,15–0,25 бар ниже давления Q2 (свойство корреляции автора)
                gap = C.laq_v_c_pressure_bar(tq2, s) - C.q2_pressure_bar(tq2)
                self.assertAlmostEqual(gap, -0.0067 * (C.q2_pressure_bar(tq2) - C.q1_pressure_bar(tq1)), delta=1e-9)
                self.assertTrue(-0.25 < gap < -0.1)

    def test_laq_v_c_monotonic_and_regression(self):
        p = [C.laq_v_c_pressure_bar(t, 3.0) for t in (-3.0, 0.0, 3.0, 6.0, 8.0)]
        self.assertEqual(p, sorted(p))
        self.assertAlmostEqual(C.laq_v_c_pressure_bar(5.0, 3.0), 25.514264242571016, delta=1e-9)
        self.assertGreater(C.laq_v_c_pressure_bar(2.0, 10.0), C.laq_v_c_pressure_bar(2.0, 5.0))   # соль повышает P

    def test_laq_lcarb_c(self):
        tq2 = C.q2_temperature_c(6.0)
        self.assertAlmostEqual(C.laq_lcarb_c_pressure_bar(tq2, 6.0), C.q2_pressure_bar(tq2), delta=1e-9)
        self.assertAlmostEqual(C.laq_lcarb_c_slope_bar_per_c(0.0), 116.2846, delta=1e-12)
        self.assertAlmostEqual(C.laq_lcarb_c_slope_bar_per_c(6.0), 117.15440050060286, delta=1e-9)
        self.assertAlmostEqual(C.laq_lcarb_c_pressure_bar(8.0, 6.0), 174.73904007226415, delta=1e-7)

    def test_outside_element_is_error(self):
        with self.assertRaises(ValueError):
            C.laq_v_c_pressure_bar(9.0, 5.0)            # выше Q2 для 5 мас. %
        with self.assertRaises(ValueError):
            C.laq_v_c_pressure_bar(-6.0, 5.0)           # ниже Q1
        with self.assertRaises(ValueError):
            C.laq_lcarb_c_pressure_bar(5.0, 5.0)        # ниже Q2: в программе автора здесь отрицательное давление
        with self.assertRaises(ValueError):
            C.laq_v_c_pressure_bar(0.0, 30.0)


class TestClathrate(unittest.TestCase):
    def test_composition_regression_and_limits(self):
        p = C.q1_pressure_bar(-1.48)
        c = C.clathrate_composition(-1.48, p, D.state(-1.48, p).ln_fugacity_coefficient)
        self.assertAlmostEqual(c.hydration_number, 6.474167015030843, delta=1e-9)
        self.assertAlmostEqual(c.x_h2o, c.hydration_number / (1 + c.hydration_number), delta=1e-15)
        self.assertGreater(c.occupancy_large, c.occupancy_small)
        full = C.clathrate_composition(0.0, 1e9, 0.0)                         # предел полного заполнения
        self.assertAlmostEqual(full.hydration_number, 5.75, delta=1e-3)
        low, high = C.clathrate_composition(5.0, 20.0, -0.2), C.clathrate_composition(5.0, 40.0, -0.2)
        self.assertGreater(low.hydration_number, high.hydration_number)       # рост фугитивности заполняет полости
        self.assertGreater(C.clathrate_composition(5.0, 20.0, -0.2, 0.9).hydration_number, low.hydration_number)

    def test_volume_and_density(self):
        self.assertAlmostEqual(C.clathrate_volume_per_mol_h2o(0.0), 22.668729225922142, delta=1e-9)
        self.assertAlmostEqual(C.clathrate_volume_per_mol_h2o(0.0), 22.6, delta=0.1)   # von Stackelberg & Müller
        c = C.clathrate_composition(5.0, 21.72, -0.17)
        v1, v2 = C.clathrate_molar_volume(5.0, 1.0, c.x_h2o), C.clathrate_molar_volume(5.0, 1001.0, c.x_h2o)
        self.assertAlmostEqual(v1, c.x_h2o * C.clathrate_volume_per_mol_h2o(5.0), delta=1e-12)
        self.assertAlmostEqual(v2 / v1, 0.9900498337491681, delta=1e-12)       # exp(−1·10⁻⁵·1000)
        rho = C.clathrate_density_g_cm3(5.0, 21.72, c)
        self.assertTrue(1.05 < rho < 1.15)

    def test_domain(self):
        for args in ((0.0, -1.0, 0.0), (0.0, 10.0, 0.0, 0.0), (0.0, 10.0, 0.0, 1.5), (-300.0, 10.0, 0.0)):
            with self.subTest(args), self.assertRaises(ValueError):
                C.clathrate_composition(*args)
        for args in ((0.0, 10.0, 1.0), (0.0, 10.0, 0.0), (0.0, 0.0, 0.8)):
            with self.subTest(args), self.assertRaises(ValueError):
                C.clathrate_molar_volume(*args)


if __name__ == '__main__':
    unittest.main()
