"""Этап 2б, часть 3: растворимость CO₂, объёмы раствора H₂O–NaCl–CO₂, вода в углекислотной фазе."""
import unittest

from fluid_core import co2_brine as B
from fluid_core import co2_duan1992 as D


class TestSolubility(unittest.TestCase):
    def setUp(self):
        self.lnphi = D.state(5.0, 25.0).ln_fugacity_coefficient

    def test_regression_and_balance(self):
        c = B.co2_solubility(5.0, 25.0, 6.0, self.lnphi)
        self.assertAlmostEqual(c.m_co2, 0.9396255332336372, delta=1e-9)
        self.assertAlmostEqual(c.m_nacl, 1.0921759395395283, delta=1e-12)
        self.assertAlmostEqual(c.x_co2, 0.016329816569917464, delta=1e-12)
        self.assertAlmostEqual(c.x_nacl, 0.018981000541119925, delta=1e-12)
        self.assertAlmostEqual(c.x_co2 + c.x_nacl + c.x_h2o, 1, delta=1e-15)
        self.assertAlmostEqual(c.x_nacl / c.x_h2o, c.m_nacl / B.MOL_H2O_PER_KG, delta=1e-15)
        self.assertTrue(c.in_published_range)

    def test_published_value(self):
        """Duan & Sun (2003), табл. 3: 303,15 K, 100 бар, вода — 1,3611 моль/кг."""
        c = B.co2_solubility(30.0, 100.0, 0.0, D.state(30.0, 100.0).ln_fugacity_coefficient)
        self.assertAlmostEqual(c.m_co2, 1.3611, delta=0.003)
        self.assertEqual(c.x_nacl, 0.0)

    def test_salting_out_and_pressure(self):
        fresh = B.co2_solubility(5.0, 25.0, 0.0, self.lnphi).m_co2
        salty = B.co2_solubility(5.0, 25.0, 15.0, self.lnphi).m_co2
        self.assertGreater(fresh, salty)                       # высаливание
        lo = B.co2_solubility(20.0, 20.0, 0.0, D.state(20.0, 20.0).ln_fugacity_coefficient).m_co2
        hi = B.co2_solubility(20.0, 40.0, 0.0, D.state(20.0, 40.0).ln_fugacity_coefficient).m_co2
        self.assertGreater(hi, lo)

    def test_flags_and_domain(self):
        self.assertFalse(B.co2_solubility(-5.0, 20.0, 5.0, -0.2).in_published_range)      # ниже 0 °C
        self.assertFalse(B.co2_solubility(5.0, 25.0, 24.0, self.lnphi).in_published_range)  # > 4,3 моль/кг
        for args in ((5.0, 0.0, 0.0, 0.0), (5.0, 0.005, 0.0, 0.0), (5.0, 25.0, -1.0, 0.0), (5.0, 25.0, 100.0, 0.0),
                     (400.0, 25.0, 0.0, 0.0), (float('nan'), 25.0, 0.0, 0.0)):
            with self.subTest(args), self.assertRaises(ValueError):
                B.co2_solubility(*args)
        with self.assertRaises(TypeError):
            B.co2_solubility(5.0, 25.0, True, 0.0)

    def test_molality(self):
        self.assertEqual(B.nacl_molality(0.0), 0.0)
        self.assertAlmostEqual(B.nacl_molality(10.0), 100 / 58.44277 / 0.9, delta=1e-12)


class TestWater(unittest.TestCase):
    def test_vapor_pressure_vs_iapws95(self):
        from CoolProp.CoolProp import PropsSI
        self.assertAlmostEqual(B.water_vapor_pressure_bar(5.0), 0.00871663349807542, delta=1e-12)
        for t in (0.01, 25.0, 100.0, 200.0, 300.0):
            ref = PropsSI('P', 'T', t + 273.15, 'Q', 0, 'Water') / 1e5
            self.assertAlmostEqual(B.water_vapor_pressure_bar(t) / ref, 1, delta=0.015)   # корреляция: до 1,3 %
        with self.assertRaises(ValueError):
            B.water_vapor_pressure_bar(380.0)

    def test_molar_volume_vs_iapws95(self):
        """Hu et al. (2007) против IAPWS-95: в пределах 0,03 % при 0–200 °C, до 2 кбар."""
        from CoolProp.CoolProp import PropsSI
        self.assertAlmostEqual(B.water_molar_volume(5.0, 25.0), 17.9950151754325, delta=1e-9)
        m = PropsSI('M', 'Water') * 1e3
        for t in (0.01, 10.0, 25.0, 100.0, 200.0):
            for p in (50.0, 500.0, 2000.0):
                ref = m / PropsSI('Dmass', 'T', t + 273.15, 'P', p * 1e5, 'Water') * 1e3
                self.assertAlmostEqual(B.water_molar_volume(t, p) / ref, 1, delta=3e-4)


class TestVolumes(unittest.TestCase):
    def test_nacl_apparent_volume(self):
        self.assertAlmostEqual(B.nacl_apparent_molar_volume(5.0, 25.0, 1.0921759395395283), 16.590678050524126,
                               delta=1e-9)
        self.assertAlmostEqual(B.nacl_apparent_molar_volume(80.0, 300.0, 2.0), 21.275504124138372, delta=1e-9)
        self.assertEqual(B.nacl_apparent_molar_volume(25.0, 1.0, 0.0), 0.0)    # как в программе автора
        v = [B.nacl_apparent_molar_volume(25.0, 1.01325, m) for m in (0.5, 1.0, 3.0, 5.0)]
        self.assertEqual(v, sorted(v))
        with self.assertRaises(ValueError):
            B.nacl_apparent_molar_volume(25.0, 1.0, -1.0)

    def test_co2_apparent_volume(self):
        """Контрольное значение из Duan et al. (2008): 276,15 K, 34,75 МПа — 31 ± 0,9 см³/моль (Ohsumi et al.)."""
        self.assertAlmostEqual(B.co2_apparent_molar_volume(3.0, 347.5, 0.01), 31.0, delta=0.9)
        self.assertAlmostEqual(B.co2_apparent_molar_volume(3.0, 347.5, 0.01),
                               B.co2_apparent_molar_volume(3.0, 347.5, 0.03), delta=1e-9)   # не зависит от доли
        with self.assertRaises(ValueError):
            B.co2_apparent_molar_volume(3.0, 347.5, 0.0)

    def test_solution_volume_and_density(self):
        c = B.co2_solubility(5.0, 25.0, 6.0, D.state(5.0, 25.0).ln_fugacity_coefficient)
        v = B.aqueous_molar_volume(5.0, 25.0, c.x_co2, c.x_nacl)
        self.assertAlmostEqual(v, 18.19614060632893, delta=1e-9)
        self.assertAlmostEqual(B.aqueous_density_g_cm3(5.0, 25.0, c.x_co2, c.x_nacl), c.molar_mass_g_mol / v, delta=1e-12)
        self.assertAlmostEqual(B.aqueous_molar_volume(5.0, 25.0, 0.0, 0.0), B.water_molar_volume(5.0, 25.0), delta=1e-12)
        # растворённая CO₂ и соль утяжеляют раствор
        self.assertGreater(B.aqueous_density_g_cm3(5.0, 25.0, 0.016, 0.0), B.aqueous_density_g_cm3(5.0, 25.0, 0.0, 0.0))
        self.assertGreater(B.aqueous_density_g_cm3(5.0, 25.0, 0.0, 0.019), B.aqueous_density_g_cm3(5.0, 25.0, 0.0, 0.0))
        for args in ((5.0, 25.0, -0.1, 0.0), (5.0, 25.0, 0.6, 0.5)):
            with self.subTest(args), self.assertRaises(ValueError):
                B.aqueous_molar_volume(*args)

    def test_agrees_with_stage_2a_density(self):
        """Раствор NaCl без CO₂: согласие с плотностью Bodnar (1983) из этапа 2а в пределах 0,3 % при 50–200 °C."""
        from fluid_core import h2o_nacl as H
        for s in (5.0, 10.0, 20.0):
            m = B.nacl_molality(s)
            xn = m / (m + B.MOL_H2O_PER_KG)
            for t in (50.0, 100.0, 150.0, 200.0):
                p = max(H.homogenization_pressure_bar(t, s), 1.0)
                self.assertAlmostEqual(B.aqueous_density_g_cm3(t, p, 0.0, xn) / H.liquid_density_g_cm3(t, s), 1,
                                       delta=3e-3)


class TestWaterInCo2(unittest.TestCase):
    def test_regression_and_trends(self):
        st = D.state(5.0, 25.0)
        c = B.co2_solubility(5.0, 25.0, 6.0, st.ln_fugacity_coefficient)
        y = B.water_fraction_in_co2(5.0, 25.0, c.x_co2, c.x_nacl, st.molar_volume_cm3_mol)
        self.assertAlmostEqual(y, 0.0004487077034900117, delta=1e-12)
        self.assertGreater(B.water_fraction_in_co2(5.0, 25.0, 0.0, 0.0, st.molar_volume_cm3_mol), y)   # активность воды
        warm = D.state(50.0, 100.0)
        cold = D.state(25.0, 100.0)
        self.assertGreater(B.water_fraction_in_co2(50.0, 100.0, 0.02, 0.0, warm.molar_volume_cm3_mol),
                           B.water_fraction_in_co2(25.0, 100.0, 0.02, 0.0, cold.molar_volume_cm3_mol))

    def test_domain(self):
        for args in ((5.0, 25.0, 0.0, 0.0, 27.0), (5.0, 25.0, 0.6, 0.5, 600.0), (5.0, 0.0, 0.0, 0.0, 600.0),
                     (5.0, 25.0, -0.1, 0.0, 600.0)):
            with self.subTest(args), self.assertRaises(ValueError):
                B.water_fraction_in_co2(*args)


if __name__ == '__main__':
    unittest.main()
