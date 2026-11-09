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


if __name__ == '__main__':
    unittest.main()
