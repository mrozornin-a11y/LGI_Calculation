"""Эталонные прогоны программ авторов и предел чистой воды (этапы 1–2a)."""
import unittest

from validation import models as V


class TestHokieFlincsTranscription(unittest.TestCase):
    def test_all_ice_cases_match(self):
        rows = V.evaluate_hokieflincs()
        self.assertEqual([r.status for r in rows].count('PASS'), 20)
        self.assertEqual([r.status for r in rows].count('SKIPPED'), 2)     # галит не реализован
        self.assertNotIn('FAIL', [r.status for r in rows])


class TestPureWater(unittest.TestCase):
    def test_characterisation(self):
        rows = V.evaluate_pure_water()
        self.assertTrue(all(abs(r.dp_pct) < 1.0 for r in rows))           # Ph: < 1 % от IAPWS-95
        far = [r for r in rows if not r.near_critical]
        self.assertTrue(all(abs(r.drho_pct) < 2.0 for r in far))          # ρ: < 2 % вдали от Tc
        near = [r for r in rows if r.near_critical]
        self.assertTrue(any(r.drho_pct > 5.0 for r in near))              # у Tc — заметно хуже (зафиксировано)


class TestStage1VsSM2018(unittest.TestCase):
    def test_systematic_underestimate(self):
        rows = V.evaluate_stage1_vs_sm2018()
        st = V.stage1_statistics(rows)
        self.assertEqual(st['n'], 36)
        self.assertTrue(all(r.dev_pct < 0 for r in rows))                 # растворённая CO₂ не учтена
        self.assertGreater(st['min'], -2.0)
        self.assertLess(st['max_abs_dS'], 0.01)                           # Darling ≈ солёность модели SM2018


class TestCo2Duan1992(unittest.TestCase):
    """Этап 2б, часть 1: независимая характеристика уравнения Duan et al. (1992a) по Span & Wagner (1996)."""
    def test_against_span_wagner(self):
        st = V.co2_statistics(V.evaluate_co2_duan1992())
        self.assertEqual(st['n'], 126)
        self.assertLess(st['core_dv'], 1.1)            # 0–500 °C, до 3 кбар: объём в пределах 1,1 %
        self.assertLess(st['core_dphi'], 4.0)          # там же φ: до 4 % (жидкая CO₂ при 0 °C)
        self.assertLess(st['all_dv'], 3.5)             # вся заявленная область
        self.assertLess(st['all_dphi'], 6.0)
        self.assertGreater(st['cold_dphi'], 5.0)       # ниже 0 °C — экстраполяция, заметно хуже (зафиксировано)

    def test_author_scheme_features(self):
        st = V.co2_statistics(V.evaluate_co2_duan1992())
        self.assertGreater(st['author_liquid_dphi'], 1.0)                 # сдвиг φ в схеме автора
        self.assertEqual(st['author_other_root'], [(700.0, 8000.0)])      # нефизичный корень при 8 кбар

    def test_saturation_inconsistency_is_recorded(self):
        rows = V.evaluate_co2_saturation()
        self.assertTrue(all(abs(r.p_eq / r.p_sw - 1) < 5e-4 for r in rows))
        self.assertTrue(any(abs(r.p_duan_liquid / r.p_eq - 1) > 0.05 for r in rows))


class TestDuanTable5(unittest.TestCase):
    def test_published_fugacity_coefficients(self):
        """Перенос уравнения Duan et al. (1992a) против табл. 5 самой статьи."""
        rows = V.evaluate_duan_table5()
        self.assertEqual(len(rows), 117)
        self.assertTrue(all(abs(m / x - 1) <= V.PUBLISHED_TABLE_REL_TOL for _, _, x, m in rows))


class TestClathrateBoundaries(unittest.TestCase):
    """Этап 2б, часть 2: корреляции Steele-MacInnis (2018) против таблиц Bakker et al. (1996)."""
    def test_against_bakker(self):
        rows = V.evaluate_clathrate_boundaries()
        self.assertEqual(len(rows), 57)
        st = V.clathrate_boundary_statistics(rows)
        self.assertLess(st['q1_dt'], 0.03)
        self.assertLess(st['q1_dp_pct'], 0.25)
        self.assertLess(st['q2_dt_chen'], 0.02)
        self.assertLess(st['q2_dt_bakker'], 0.6)
        self.assertLess(st['q2_dp_pct'], 1.5)
        self.assertLess(st['gc_dp_pct'], 4.0)
        self.assertLess(st['lc_dt_to_1kbar'], 1.5)
        self.assertGreater(st['lc_dt_above_1kbar'], 3.0)      # выше 1 кбар прямая ур. 23 расходится с Bakker (Q25)

    def test_clathrate_properties(self):
        for _, _, comp, _, rho in V.evaluate_clathrate_properties():
            self.assertTrue(5.75 < comp.hydration_number < 7.0)
            self.assertTrue(1.05 < rho < 1.15)


class TestStage2bPart3(unittest.TestCase):
    """Растворимость CO₂ и объёмы: перенос против таблиц статей и независимые характеристики."""
    def test_duan_sun_tables(self):
        rows = V.evaluate_duan_sun_tables()
        self.assertEqual(len(rows), 141)
        self.assertTrue(all(r.ok for r in rows))
        self.assertEqual({r.m_nacl for r in rows}, {0.0, 4.0})              # проверены и солевые слагаемые

    def test_water_volume(self):
        wv = V.evaluate_water_volume()
        self.assertTrue(all(wv[t] < 0.03 for t in wv if t <= 200))
        self.assertGreater(wv[300.0], 1.0)                                  # вне области уравнения (зафиксировано)

    def test_brine_density_consistency(self):
        rows = V.evaluate_brine_density()
        self.assertTrue(all(abs(a / b - 1) < 3e-3 for _, t, a, b in rows if t <= 200))
        self.assertTrue(any(abs(a / b - 1) > 0.05 for _, t, a, b in rows if t == 300))

    def test_examples(self):
        for *_, m, rho, y in V.evaluate_phase_examples():
            self.assertTrue(0.5 < m < 2.0 and 1.0 < rho < 1.15 and 0 < y < 0.01)


class TestMode1VsSM2018(unittest.TestCase):
    """Этап 2б, часть 4: режим 1 против эталонного прогона программы автора."""
    def test_all_cases_match(self):
        rows = V.evaluate_mode1_vs_sm2018()
        self.assertEqual(len(rows), 36)
        self.assertEqual([r.status for r in rows].count('PASS'), 36)
        self.assertLess(max(abs(r.deviations['rho']) for r in rows), 1e-5)
        # точное решение уравнения CO₂ вместо схемы автора меняет плотность меньше чем на 0,01 % (Q22)
        self.assertLess(max(abs(r.exact_deviations['rho']) for r in rows), 1e-4)
        self.assertLess(max(abs(r.exact_deviations['X_CO2']) for r in rows), 1e-3)


if __name__ == '__main__':
    unittest.main()
