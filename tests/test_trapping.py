"""Пересечение готовой изохоры с независимым ограничением (новых уравнений состояния нет)."""
import unittest

from fluid_core import duan1995, h2o_co2_nacl, h2o_nacl
from fluid_core import trapping as T


class TestLinearIsochore(unittest.TestCase):
    def setUp(self):
        self.res = h2o_nacl.homogenization_to_liquid(250.0, 7.864625, homogenization_to='liquid')
        self.iso = T.LinearIsochore.from_h2o_nacl(self.res)

    def test_forward_equals_existing_isochore(self):
        r = T.solve_trapping_constraint(self.iso, independent_temperature=400.0)
        self.assertEqual(r.status, 'ok')
        self.assertEqual(r.pressure_bar, self.res.pressure_at(400.0))
        self.assertAlmostEqual(r.pressure_bar, self.res.pressure_bar + self.res.slope_bar_per_c * 150.0, delta=1e-9)

    def test_inverse_algebra(self):
        r = T.solve_trapping_constraint(self.iso, independent_pressure=1000.0)
        self.assertEqual(r.temperature_c, self.res.temperature_at(1000.0))
        self.assertAlmostEqual(r.temperature_c, 250.0 + (1000.0 - self.res.pressure_bar) / self.res.slope_bar_per_c,
                               delta=1e-9)
        back = T.solve_trapping_constraint(self.iso, independent_temperature=r.temperature_c)
        self.assertAlmostEqual(back.pressure_bar, 1000.0, delta=1e-9)

    def test_ranges_are_endpoint_values_sorted(self):
        r = T.solve_trapping_constraint(self.iso, temperature_range=(400.0, 300.0))       # порядок не важен
        self.assertEqual(r.temperature_range_c, (300.0, 400.0))
        self.assertEqual(r.pressure_range_bar, (self.res.pressure_at(300.0), self.res.pressure_at(400.0)))
        p = T.solve_trapping_constraint(self.iso, pressure_range=(2000.0, 1000.0))
        self.assertEqual(p.temperature_range_c, (self.res.temperature_at(1000.0), self.res.temperature_at(2000.0)))
        self.assertTrue(any('не статистический доверительный интервал' in n for n in r.notes + p.notes))
        self.assertIsNone(r.pressure_bar)

    def test_limits_no_extrapolation(self):
        self.assertEqual(T.solve_trapping_constraint(self.iso, independent_temperature=200.0).status, 'out_of_range')
        self.assertEqual(T.solve_trapping_constraint(self.iso, independent_temperature=900.0).status, 'out_of_range')
        self.assertEqual(T.solve_trapping_constraint(self.iso, independent_pressure=6500.0).status, 'out_of_range')
        low = T.solve_trapping_constraint(self.iso, independent_pressure=10.0)             # ниже Ph
        self.assertEqual(low.status, 'no_valid_intersection')
        self.assertIsNone(low.temperature_c)
        self.assertEqual(T.solve_trapping_constraint(self.iso, pressure_range=(10.0, 1000.0)).status,
                         'no_valid_intersection')
        self.assertEqual(T.solve_trapping_constraint(self.iso, temperature_range=(300.0, 900.0)).status,
                         'out_of_range')


class TestCompositionIsochore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # уже проверенный случай ядра: режим 1, Tm клатрата 8 °C, Th CO₂ 25 °C в жидкость, φ 30 % при 23,5 °C
        o = h2o_co2_nacl.mode1(8.0, 25.0, 'liquid', 0.3, 23.5)
        cls.o = o
        cls.iso = T.CompositionIsochore(o.molar_volume_cm3_mol, o.x_h2o, o.x_nacl, o.x_co2)

    def test_forward_calls_existing_core(self):
        o = self.o
        r = T.solve_trapping_constraint(self.iso, independent_temperature=420.0)
        self.assertEqual(r.status, 'ok')
        self.assertEqual(r.pressure_bar, duan1995.pressure_bar(420.0, o.molar_volume_cm3_mol, o.x_h2o, o.x_nacl, o.x_co2))

    def test_forward_then_inverse_round_trip(self):
        for t in (300.0, 365.5, 420.0, 500.0):
            p = T.solve_trapping_constraint(self.iso, independent_temperature=t).pressure_bar
            back = T.solve_trapping_constraint(self.iso, independent_pressure=p)
            self.assertEqual(back.status, 'ok', t)
            self.assertAlmostEqual(back.temperature_c, t, delta=1e-8)

    def test_range_and_limits(self):
        r = T.solve_trapping_constraint(self.iso, temperature_range=(450.0, 350.0))
        self.assertEqual(r.status, 'ok')
        self.assertLess(r.pressure_range_bar[0], r.pressure_range_bar[1])
        pr = T.solve_trapping_constraint(self.iso, pressure_range=r.pressure_range_bar)
        self.assertAlmostEqual(pr.temperature_range_c[0], 350.0, delta=1e-8)
        self.assertAlmostEqual(pr.temperature_range_c[1], 450.0, delta=1e-8)
        self.assertEqual(T.solve_trapping_constraint(self.iso, independent_temperature=250.0).status, 'out_of_range')
        self.assertEqual(T.solve_trapping_constraint(self.iso, independent_temperature=1100.0).status, 'out_of_range')
        self.assertEqual(T.solve_trapping_constraint(self.iso, independent_temperature=700.0).status,
                         'out_of_range')                    # давление на изохоре выше 6 кбар
        self.assertEqual(T.solve_trapping_constraint(self.iso, independent_pressure=6500.0).status, 'out_of_range')

    def test_no_intersection(self):
        r = T.solve_trapping_constraint(self.iso, independent_pressure=500.0)     # ниже давления изохоры при 300 °C
        self.assertEqual(r.status, 'no_valid_intersection')
        self.assertIsNone(r.temperature_c)
        self.assertIn('не достигается', r.message)

    def test_ambiguous_intersections_are_not_resolved(self):
        class Wavy(T.CompositionIsochore):
            def pressure_at(self, t_c):                     # искусственная немонотонная «изохора»
                return 3000.0 + 0.01 * (t_c - 500.0) ** 2
        r = T.solve_trapping_constraint(Wavy(1.0, 1.0, 0.0, 0.0), independent_pressure=3100.0)
        self.assertEqual(r.status, 'ambiguous_intersections')
        self.assertIsNone(r.temperature_c)
        self.assertIn('выбор не делается', r.message)


class TestContract(unittest.TestCase):
    def setUp(self):
        self.iso = T.LinearIsochore(250.0, 40.0, 14.0)

    def test_exactly_one_constraint(self):
        for kw in ({}, dict(independent_temperature=400.0, independent_pressure=1000.0),
                   dict(independent_temperature=400.0, temperature_range=(300.0, 400.0)),
                   dict(temperature_range=(300.0, 400.0), pressure_range=(500.0, 900.0))):
            with self.subTest(kw), self.assertRaises(ValueError):
                T.solve_trapping_constraint(self.iso, **kw)
        with self.assertRaises(ValueError):
            T.solve_trapping_constraint(self.iso, temperature_range=400.0)
        with self.assertRaises(TypeError):
            T.solve_trapping_constraint(self.iso, independent_temperature=True)

    def test_wording(self):
        r = T.solve_trapping_constraint(self.iso, independent_temperature=400.0)
        self.assertEqual(r.wording, 'условия захвата включения при независимом ограничении')
        self.assertEqual(r.interpretation, r.wording)
        self.assertNotIn('минералообразования', r.interpretation)
        c = T.solve_trapping_constraint(self.iso, independent_temperature=400.0,
                                        coeval_with_mineral_growth_documented=True)
        self.assertIn('может интерпретироваться как условие соответствующего этапа минералообразования',
                      c.interpretation)
        with self.assertRaises(TypeError):
            T.solve_trapping_constraint(self.iso, independent_temperature=400.0,
                                        coeval_with_mineral_growth_documented='yes')


if __name__ == '__main__':
    unittest.main()
