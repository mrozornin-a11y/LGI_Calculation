"""Этап 2б, часть 4: режимы 1–3 модели H₂O–CO₂–NaCl."""
import csv
import unittest
from pathlib import Path

from fluid_core import clathrate as C
from fluid_core import h2o_co2_nacl as M

ROOT = Path(__file__).resolve().parent.parent


class TestMode1(unittest.TestCase):
    def test_matches_author_program(self):
        """Выборка эталонных случаев (полная сверка 36 случаев — в validation/)."""
        with open(ROOT / 'validation' / 'data' / 'sm2018_oracle.csv', encoding='utf-8') as fh:
            rows = {r['case']: r for r in csv.DictReader(fh)}
        for case in ('SM01', 'SM16', 'SM26', 'SM31', 'SM36'):     # φ выше и ниже Th CO₂, обе ветви
            r = rows[case]
            with self.subTest(case):
                o = M.mode1(float(r['Tm_clath']), float(r['Th_CO2']), 'liquid' if r['homog_to'] == 'L' else 'vapor',
                            float(r['PhiVap_pct']) / 100, M.ROOM_TEMPERATURE_C, numerics='author')
                for got, key in ((o.x_nacl, 'X_NaCl'), (o.x_co2, 'X_CO2'), (o.x_h2o, 'X_H2O'),
                                 (o.salinity_wt_pct, 'wt_pct_NaCl'), (o.co2_mol_pct_salt_free, 'mol_pct_CO2'),
                                 (o.molar_volume_cm3_mol, 'V_cm3_mol'), (o.density_g_cm3, 'rho_g_cm3')):
                    self.assertAlmostEqual(got / float(r[key]), 1, delta=1e-4, msg=key)

    def test_internal_consistency(self):
        o = M.mode1(5.0, 20.0, 'liquid', 0.3)                      # φ задана при Th CO₂
        self.assertEqual(o.carbonic_fraction_at_th_co2, 0.3)
        self.assertAlmostEqual(o.x_nacl + o.x_co2 + o.x_h2o, 1, delta=1e-12)
        self.assertAlmostEqual(o.salinity_at_tm_clath_wt_pct, C.q2_salinity(5.0), delta=1e-12)
        self.assertAlmostEqual(o.pressure_at_tm_clath_bar, C.q2_pressure_bar(5.0), delta=1e-12)
        self.assertLess(o.salinity_wt_pct, o.salinity_at_tm_clath_wt_pct)   # вода в углекислотной фазе разбавляет
        self.assertAlmostEqual(o.salinity_wt_pct, o.salinity_at_tm_clath_wt_pct, delta=0.05)
        mass = o.x_nacl * 58.44277 + o.x_co2 * 44.01 + o.x_h2o * 18.0152
        self.assertAlmostEqual(o.density_g_cm3, mass / o.molar_volume_cm3_mol, delta=1e-12)

    def test_physical_trends(self):
        base = M.mode1(5.0, 20.0, 'liquid', 0.3)
        self.assertGreater(M.mode1(5.0, 20.0, 'liquid', 0.5).x_co2, base.x_co2)          # больше CO₂-фазы
        self.assertLess(M.mode1(5.0, 20.0, 'vapor', 0.3).density_g_cm3, base.density_g_cm3)   # пар легче жидкости
        self.assertGreater(M.mode1(0.0, 20.0, 'liquid', 0.3).salinity_wt_pct, base.salinity_wt_pct)

    def test_fraction_temperature_round_trip(self):
        """φ при комнатной температуре и соответствующая ей φ при Th CO₂ дают одно и то же включение."""
        room = M.mode1(5.0, 15.0, 'liquid', 0.3, M.ROOM_TEMPERATURE_C, numerics='exact')
        at_th = M.mode1(5.0, 15.0, 'liquid', room.carbonic_fraction_at_th_co2, numerics='exact')
        self.assertAlmostEqual(room.density_g_cm3, at_th.density_g_cm3, delta=1e-9)
        self.assertAlmostEqual(room.x_co2, at_th.x_co2, delta=1e-9)
        # для жидкой CO₂ доля между 15 и 23,5 °C меняется мало (0,30005), но меняется
        self.assertNotAlmostEqual(room.carbonic_fraction_at_th_co2, 0.3, delta=1e-6)

    def test_author_numerics_effect_is_small(self):
        a = M.mode1(9.0, 12.0, 'liquid', 0.5, M.ROOM_TEMPERATURE_C, numerics='author')
        e = M.mode1(9.0, 12.0, 'liquid', 0.5, M.ROOM_TEMPERATURE_C, numerics='exact')
        self.assertAlmostEqual(a.density_g_cm3 / e.density_g_cm3, 1, delta=1e-4)
        self.assertNotEqual(a.x_co2, e.x_co2)

    def test_salt_free(self):
        o = M.mode1(10.0, 20.0, 'liquid', 0.3)
        self.assertEqual(o.x_nacl, 0.0)
        self.assertEqual(o.salinity_wt_pct, 0.0)
        with self.assertRaises(ValueError):
            M.mode1(10.0, 28.0, 'liquid', 0.3, M.ROOM_TEMPERATURE_C)     # φ ниже Th CO₂ без соли не определена

    def test_nothing_is_guessed(self):
        for args, kw in (((5.0, 20.0, None, 0.3), {}), ((5.0, 20.0, 'L', 0.3), {}),
                         ((5.0, 20.0, 'liquid', 0.3), {'numerics': 'fast'}),
                         ((12.0, 20.0, 'liquid', 0.3), {}), ((-11.0, 20.0, 'liquid', 0.3), {}),
                         ((5.0, 31.2, 'liquid', 0.3), {}), ((5.0, 3.0, 'liquid', 0.3), {}),     # это режим 2
                         ((5.0, 20.0, 'liquid', 0.0), {}), ((5.0, 20.0, 'liquid', 1.0), {}),
                         ((5.0, 20.0, 'liquid', 0.3, 2.0), {}), ((float('nan'), 20.0, 'liquid', 0.3), {})):
            with self.subTest(args), self.assertRaises(ValueError):
                M.mode1(*args, **kw)
        with self.assertRaises(TypeError):
            M.mode1(5.0, 20.0, 'liquid', True)


def _oracle():
    with open(ROOT / 'validation' / 'data' / 'sm2018_oracle.csv', encoding='utf-8') as fh:
        return {r['case']: r for r in csv.DictReader(fh)}


class TestMode2(unittest.TestCase):
    def test_matches_author_program(self):
        rows = _oracle()
        for case in ('SM39', 'SM40'):
            r = rows[case]
            with self.subTest(case):
                o = M.mode2(float(r['Tm_clath']), float(r['Th_CO2']), 'liquid' if r['homog_to'] == 'L' else 'vapor',
                            float(r['PhiVap_pct']) / 100, M.ROOM_TEMPERATURE_C, numerics='author')
                for got, key in ((o.x_nacl, 'X_NaCl'), (o.x_co2, 'X_CO2'), (o.salinity_wt_pct, 'wt_pct_NaCl'),
                                 (o.molar_volume_cm3_mol, 'V_cm3_mol'), (o.density_g_cm3, 'rho_g_cm3')):
                    self.assertAlmostEqual(got / float(r[key]), 1, delta=1e-4, msg=key)

    def test_converged_solution(self):
        liq = M.mode2(8.0, 5.0, 'liquid', 0.3, numerics='exact')
        vap = M.mode2(8.0, 5.0, 'vapor', 0.3, numerics='exact')
        self.assertEqual(liq.mode, 2)
        self.assertEqual(liq.carbonic_fraction_at_tm_clath, 0.3)
        # давление плавления клатрата: выше давления насыщения CO₂ для жидкости, ниже — для пара
        psat = C.q2_pressure_bar(8.0)
        self.assertGreater(liq.pressure_at_tm_clath_bar, psat)
        self.assertLess(vap.pressure_at_tm_clath_bar, psat)
        # солёность: при той же Tm клатрата с жидкой CO₂ — выше, с паром — ниже, чем по уравнению Darling (Q2)
        darling = C.q2_salinity(8.0)
        self.assertGreater(liq.salinity_at_tm_clath_wt_pct, darling)
        self.assertLess(vap.salinity_at_tm_clath_wt_pct, darling)
        self.assertGreater(liq.density_g_cm3, vap.density_g_cm3)
        self.assertAlmostEqual(liq.x_nacl + liq.x_co2 + liq.x_h2o, 1, delta=1e-12)
        # условия на границе клатрата выполнены
        self.assertAlmostEqual(C.laq_lcarb_c_pressure_bar(8.0, liq.salinity_at_tm_clath_wt_pct),
                               liq.pressure_at_tm_clath_bar, delta=1e-6)
        self.assertAlmostEqual(C.laq_v_c_pressure_bar(8.0, vap.salinity_at_tm_clath_wt_pct),
                               vap.pressure_at_tm_clath_bar, delta=1e-6)

    def test_author_iteration_is_close_to_converged(self):
        a = M.mode2(8.0, 5.0, 'liquid', 0.3, numerics='author')
        e = M.mode2(8.0, 5.0, 'liquid', 0.3, numerics='exact')
        self.assertAlmostEqual(a.density_g_cm3 / e.density_g_cm3, 1, delta=2e-4)
        self.assertAlmostEqual(a.salinity_wt_pct / e.salinity_wt_pct, 1, delta=5e-3)

    def test_domain(self):
        for args in ((3.0, 5.0, 'liquid', 0.3), (8.0, 5.0, 'gas', 0.3), (11.0, 5.0, 'vapor', 0.3),
                     (-10.0, -12.0, 'liquid', 0.3), (8.0, 5.0, 'liquid', 1.2), (8.0, 5.0, 'liquid', 0.3, 6.0)):
            with self.subTest(args), self.assertRaises(ValueError):
                M.mode2(*args)


class TestMode3(unittest.TestCase):
    def test_matches_author_program(self):
        r = _oracle()['SM41']
        o = M.mode3(float(r['Tm_ice']), float(r['Tm_clath']), float(r['PhiVap_pct']) / 100, numerics='author')
        for got, key in ((o.x_nacl, 'X_NaCl'), (o.x_co2, 'X_CO2'), (o.salinity_wt_pct, 'wt_pct_NaCl'),
                         (o.molar_volume_cm3_mol, 'V_cm3_mol'), (o.density_g_cm3, 'rho_g_cm3')):
            self.assertAlmostEqual(got / float(r[key]), 1, delta=1e-10, msg=key)

    def test_converged_solution(self):
        o = M.mode3(-5.0, 5.0, 0.2, numerics='exact')
        self.assertEqual(o.mode, 3)
        self.assertAlmostEqual(o.salinity_at_tm_ice_wt_pct, C.q1_salinity(-5.0), delta=1e-12)
        self.assertAlmostEqual(o.pressure_at_tm_ice_bar, C.q1_pressure_bar(-5.0), delta=1e-12)
        self.assertAlmostEqual(C.laq_v_c_pressure_bar(5.0, o.salinity_at_tm_clath_wt_pct), o.pressure_at_tm_clath_bar,
                               delta=1e-9)
        # при Tm льда часть воды связана в клатрате, поэтому раствор там солонее, чем после плавления клатрата
        self.assertLess(o.salinity_at_tm_clath_wt_pct, o.salinity_at_tm_ice_wt_pct)
        self.assertLess(o.pressure_at_tm_clath_bar, C.q2_pressure_bar(5.0))
        a = M.mode3(-5.0, 5.0, 0.2, numerics='author')
        self.assertAlmostEqual(a.salinity_wt_pct / o.salinity_wt_pct, 1, delta=5e-3)      # критерий 0,02 см³/моль
        self.assertNotEqual(a.salinity_wt_pct, o.salinity_wt_pct)

    def test_fraction_at_room_temperature(self):
        o = M.mode3(-5.0, 5.0, 0.2, M.ROOM_TEMPERATURE_C, numerics='exact')
        self.assertNotEqual(o.carbonic_fraction_at_tm_clath, 0.2)
        self.assertAlmostEqual(o.carbonic_fraction_at_tm_clath, 0.2, delta=0.02)

    def test_domain(self):
        for args in ((-1.0, 5.0, 0.2), (-5.0, 11.0, 0.2), (-5.0, -6.0, 0.2), (-25.0, 5.0, 0.2), (-5.0, 5.0, 0.0),
                     (-5.0, 5.0, 0.2, 2.0)):
            with self.subTest(args), self.assertRaises(ValueError):
                M.mode3(*args)


class TestTotalHomogenization(unittest.TestCase):
    """Доля углекислотной фазы по Th общ. (гомогенизация в водную жидкость)."""
    def test_matches_author_program(self):
        rows = _oracle()
        for case in ('SM37', 'SM38'):
            r = rows[case]
            with self.subTest(case):
                o = M.mode1(float(r['Tm_clath']), float(r['Th_CO2']), 'liquid',
                            total_homogenization_c=float(r['Th_tot']), total_homogenization_to='liquid',
                            numerics='author')
                self.assertFalse(o.converged)
                for got, key in ((o.x_nacl, 'X_NaCl'), (o.x_co2, 'X_CO2'), (o.salinity_wt_pct, 'wt_pct_NaCl'),
                                 (o.molar_volume_cm3_mol, 'V_cm3_mol'), (o.density_g_cm3, 'rho_g_cm3')):
                    self.assertAlmostEqual(got / float(r[key]), 1, delta=1e-8, msg=key)

    def test_converged_solution(self):
        o = M.mode1(8.0, 25.0, 'liquid', total_homogenization_c=250.0, total_homogenization_to='liquid')
        self.assertTrue(o.converged)
        self.assertEqual(o.total_homogenization_c, 250.0)
        self.assertLessEqual(abs(o.residuals['volume_cm3_mol:th_total']), M.RESIDUAL_LIMITS['volume_cm3_mol'])
        self.assertLessEqual(abs(o.residuals['fraction:solvus']), M.RESIDUAL_LIMITS['fraction'])
        self.assertTrue(0 < o.carbonic_fraction_at_th_co2 < 1)
        # та же доля, заданная напрямую, даёт то же включение
        same = M.mode1(8.0, 25.0, 'liquid', o.carbonic_fraction_at_th_co2)
        self.assertAlmostEqual(same.density_g_cm3, o.density_g_cm3, delta=1e-10)
        # более высокая Th общ. — больше CO₂ растворяется, включение менее плотное
        hot = M.mode1(8.0, 25.0, 'liquid', total_homogenization_c=300.0, total_homogenization_to='liquid')
        self.assertGreater(hot.x_co2, o.x_co2)
        self.assertLess(hot.density_g_cm3, o.density_g_cm3)
        # вариант автора останавливается при расхождении объёмов 0,05 см³/моль
        a = M.mode1(8.0, 25.0, 'liquid', total_homogenization_c=250.0, total_homogenization_to='liquid',
                    numerics='author')
        self.assertAlmostEqual(abs(a.residuals['volume_cm3_mol:th_total']), 0.05, delta=0.005)
        self.assertAlmostEqual(a.density_g_cm3 / o.density_g_cm3, 1, delta=1e-3)

    def test_other_modes(self):
        o2 = M.mode2(8.0, 5.0, 'liquid', total_homogenization_c=280.0, total_homogenization_to='liquid')
        o3 = M.mode3(-5.0, 5.0, total_homogenization_c=200.0, total_homogenization_to='liquid')
        for o in (o2, o3):
            self.assertTrue(o.converged)
            self.assertIsNotNone(o.pressure_at_th_total_bar)
            self.assertTrue(0 < o.carbonic_fraction_at_tm_clath < 1)

    def test_nothing_is_guessed(self):
        kw = dict(total_homogenization_c=250.0, total_homogenization_to='liquid')
        for args, k in (((8.0, 25.0, 'liquid'), {}),                                   # ни φ, ни Th общ.
                        ((8.0, 25.0, 'liquid', 0.3), kw),                              # и то и другое
                        ((8.0, 25.0, 'liquid'), dict(total_homogenization_c=250.0)),   # направление не указано
                        ((8.0, 25.0, 'liquid'), dict(kw, total_homogenization_to='vapor')),
                        ((8.0, 25.0, 'liquid'), dict(kw, total_homogenization_c=20.0)),    # ниже Th CO₂
                        ((8.0, 25.0, 'liquid'), dict(kw, total_homogenization_c=460.0)),   # выше области модели
                        ((8.0, 25.0, 'liquid', None, 23.5), kw),                       # T оценки φ вместе с Th общ.
                        ((8.0, 25.0, 'liquid', 0.3), dict(total_homogenization_to='liquid'))):
            with self.subTest((args, k)), self.assertRaises(ValueError):
                M.mode1(*args, **k)


class TestConvergedDefault(unittest.TestCase):
    """По умолчанию выдаётся сошедшееся решение с проверкой невязок и физической допустимости."""
    def test_default_is_converged(self):
        for o in (M.mode1(5.0, 20.0, 'liquid', 0.3), M.mode2(8.0, 5.0, 'liquid', 0.3), M.mode3(-5.0, 5.0, 0.2)):
            with self.subTest(o.mode):
                self.assertEqual(o.numerics, 'exact')
                self.assertTrue(o.converged)
                self.assertEqual(o.diagnostics['violations'], [])
                self.assertTrue(o.residuals)
                for key, r in o.residuals.items():
                    self.assertLessEqual(abs(r), M.RESIDUAL_LIMITS[key.split(':')[0]], msg=key)
                for fractions in o.phase_fractions.values():
                    self.assertAlmostEqual(sum(fractions.values()), 1, delta=1e-12)
                    self.assertTrue(all(0 <= x <= 1 for x in fractions.values()))

    def test_author_variant_is_marked_not_converged(self):
        a2 = M.mode2(8.0, 5.0, 'liquid', 0.3, numerics='author')
        a3 = M.mode3(-5.0, 5.0, 0.2, numerics='author')
        self.assertFalse(a2.converged)
        self.assertFalse(a3.converged)
        self.assertGreater(abs(a3.residuals['volume_cm3_mol']), 1e-4)        # остановка по критерию 0,02 см³/моль
        self.assertLessEqual(abs(a3.residuals['volume_cm3_mol']), 0.02)
        self.assertGreater(abs(a2.residuals['fraction:volume']), 1e-9)
        self.assertLessEqual(abs(a2.residuals['fraction:volume']), 0.001)

    def test_stable_under_tolerance_change(self):
        """Ослабление критериев остановки в 100 и 10⁴ раз меняет результат не более чем на 1·10⁻⁸ и 1·10⁻⁵."""
        cases = ((M.mode1, (5.0, 15.0, 'liquid', 0.3, M.ROOM_TEMPERATURE_C)), (M.mode2, (8.0, 5.0, 'vapor', 0.3)),
                 (M.mode3, (-5.0, 5.0, 0.2, M.ROOM_TEMPERATURE_C)))
        for f, args in cases:
            base = f(*args)
            for scale, limit in ((1e2, 1e-8), (1e4, 1e-5)):
                with self.subTest((f.__name__, scale)), M.solver_tolerance_scale(scale):
                    o = f(*args)
                    for a in ('density_g_cm3', 'salinity_wt_pct', 'x_co2'):
                        self.assertAlmostEqual(getattr(o, a) / getattr(base, a), 1, delta=limit)
        with self.assertRaises(ValueError):
            with M.solver_tolerance_scale(0.1):
                pass

    def test_non_convergence_is_reported(self):
        with self.assertRaises(M.ConvergenceError):
            M._secant(lambda x: 1.0 + x * x, 0.0, 1.0, 1e-13, 'проверка')     # корня нет
        import fluid_core.h2o_co2_nacl as mod
        limits = dict(mod.RESIDUAL_LIMITS)
        try:
            mod.RESIDUAL_LIMITS['volume_cm3_mol'] = 0.0                      # любая невязка считается превышением
            with self.assertRaises(M.ConvergenceError):
                M.mode1(5.0, 20.0, 'liquid', 0.3)
        finally:
            mod.RESIDUAL_LIMITS.update(limits)
        self.assertTrue(issubclass(M.ConvergenceError, ArithmeticError))

    def test_non_physical_solution_is_rejected(self):
        # режим 1: при такой малой доле пара жидкой CO₂ при Tm клатрата быть не может
        with self.assertRaises(M.NonPhysicalSolutionError) as ctx:
            M.mode1(5.0, 30.5, 'vapor', 0.02)
        self.assertIn('жидкая CO₂', str(ctx.exception))
        # то же в варианте автора не отвергается, но нарушение записывается
        a = M.mode1(5.0, 30.5, 'vapor', 0.02, numerics='author')
        self.assertTrue(a.diagnostics['violations'])
        with self.assertRaises(M.NonPhysicalSolutionError):
            M.mode3(-5.0, 9.5, 0.2)                     # объёмы при Tm льда и Tm клатрата несовместимы
        with self.assertRaises(M.NonPhysicalSolutionError):
            M.mode2(12.0, 5.0, 'liquid', 0.3)           # такое давление не достигается на изохоре CO₂
        self.assertTrue(issubclass(M.NonPhysicalSolutionError, ValueError))


if __name__ == '__main__':
    unittest.main()
