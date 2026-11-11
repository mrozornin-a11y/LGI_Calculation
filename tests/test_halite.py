"""Солёность по растворению галита (Sterner et al., 1988) и плавлению гидрогалита (Steele-MacInnis et al., 2011)."""
import unittest

from fluid_core import halite as H


class TestHalite(unittest.TestCase):
    def test_control_values(self):
        for t, wt in ((100.0, 27.9775292), (200.0, 31.8740256), (300.0, 38.1628264), (400.0, 47.4425888),
                      (500.0, 59.76225)):
            r = H.halite_dissolution_salinity(t, True)
            self.assertEqual(r.status, 'ok')
            self.assertAlmostEqual(r.salinity_wt_pct_nacl, wt, delta=1e-12)

    def test_coefficients_are_the_published_ones(self):
        self.assertEqual(H._HALITE, (26.242, 0.4928, 1.42, -0.223, 0.04129, 0.006295, -0.001967, 0.0001112))
        # при T = 100 °C (ψ = 1) значение равно сумме коэффициентов
        self.assertAlmostEqual(H.halite_liquidus_wt_pct(100.0), sum(H._HALITE), delta=1e-12)

    def test_no_rounding_and_mole_fraction(self):
        r = H.halite_dissolution_salinity(123.456, True)
        self.assertNotEqual(r.salinity_wt_pct_nacl, round(r.salinity_wt_pct_nacl, 4))
        wt = r.salinity_wt_pct_nacl
        self.assertAlmostEqual(r.mole_fraction_nacl,
                               (wt / H.M_NACL) / (wt / H.M_NACL + (100 - wt) / H.M_H2O), delta=1e-15)

    def test_requires_vapor(self):
        for vapor in (False, None):
            r = H.halite_dissolution_salinity(300.0, vapor)
            self.assertEqual(r.status, 'no_quantitative_result')
            self.assertIsNone(r.salinity_wt_pct_nacl)
            self.assertIn('в присутствии пара', r.reason)
            self.assertIn('зависит от давления', r.reason)
        self.assertIn('Не указано', H.halite_dissolution_salinity(300.0, None).reason)
        self.assertIn('отсутствует', H.halite_dissolution_salinity(300.0, False).reason)

    def test_domain(self):
        self.assertEqual(H.halite_dissolution_salinity(0.1, True).status, 'ok')
        self.assertEqual(H.halite_dissolution_salinity(801.0, True).status, 'ok')
        for t in (0.0, -5.0, 801.5, float('nan')):
            with self.subTest(t), self.assertRaises(ValueError):
                H.halite_dissolution_salinity(t, True)
        with self.assertRaises(TypeError):
            H.halite_dissolution_salinity(300.0, 'yes')
        with self.assertRaises(TypeError):
            H.halite_dissolution_salinity(True, True)


class TestHydrohalite(unittest.TestCase):
    A = (0.06039097042, -2.967800E-5, 7.0463278E-6, 1.237133E-3, -1.290978E-3, -5.219129E-3, -3.178747E-6,
         -1.408898E-7, 1.0353807E-3)

    def general(self, t, psi):
        """Общая запись ур. 2 для поля гидрогалита (для проверки предела Ψ = 1)."""
        a, x = self.A, t + 52
        return (a[0] + a[1] * x + a[2] * x ** 2 + a[3] * psi + a[4] * psi ** 2 + a[5] * psi ** 3
                + a[6] * psi * x ** 2 + a[7] * psi * x ** 3 + a[8] * psi ** 2 * x)

    def test_coefficients(self):
        self.assertEqual(H._HH, self.A)

    def test_binary_limit_equals_general_equation_at_psi_1(self):
        for t in (-21.2, -21.18, -15.0, -10.0, -5.0, 0.0, 0.1):
            self.assertAlmostEqual(H.hydrohalite_liquidus_mole_fraction(t), self.general(t, 1.0), delta=1e-16)

    def test_control_values(self):
        for t, wt in ((-21.18, 23.308955260398985), (-10.0, 25.125138134358654), (0.0, 26.074288596126248)):
            r = H.hydrohalite_melting_salinity(t, True)
            self.assertEqual(r.status, 'ok')
            self.assertAlmostEqual(r.salinity_wt_pct_nacl, wt, delta=1e-12)
            s = r.mole_fraction_nacl
            self.assertAlmostEqual(r.salinity_wt_pct_nacl,
                                   100 * s * H.M_NACL / (s * H.M_NACL + (1 - s) * H.M_H2O), delta=1e-13)
        # значения задачи: ~23,31; ~25,13; ~26,07 мас. %
        self.assertEqual([round(H.hydrohalite_melting_salinity(t, True).salinity_wt_pct_nacl, 2)
                          for t in (-21.18, -10.0, 0.0)], [23.31, 25.13, 26.07])

    def test_molar_masses_are_the_project_constants(self):
        from fluid_core import co2_brine
        self.assertEqual((H.M_NACL, H.M_H2O), (co2_brine.M_NACL, co2_brine.M_H2O))

    def test_requires_identified_phase(self):
        for flag in (False, None):
            r = H.hydrohalite_melting_salinity(-10.0, flag)
            self.assertEqual(r.status, 'no_quantitative_result')
            self.assertIsNone(r.salinity_wt_pct_nacl)
            self.assertIn('гидрогалит', r.reason)

    def test_multicomponent_blocks_binary_result(self):
        r = H.hydrohalite_melting_salinity(-10.0, True, multicomponent_salts_indicated=True)
        self.assertEqual(r.status, 'no_quantitative_result')
        self.assertEqual(r.reason, H.MULTICOMPONENT_MESSAGE)
        self.assertIn('недостаточно', r.reason)

    def test_no_extrapolation(self):
        for t in (-21.3, -30.0, 0.15, 5.0):
            with self.subTest(t), self.assertRaises(ValueError):
                H.hydrohalite_melting_salinity(t, True)
        with self.assertRaises(TypeError):
            H.hydrohalite_melting_salinity(-10.0, True, multicomponent_salts_indicated=None)


if __name__ == '__main__':
    unittest.main()
