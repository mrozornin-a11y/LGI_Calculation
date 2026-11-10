"""Этап 2б, часть 4: режим 1 модели H₂O–CO₂–NaCl (Tm клатрата ≤ Th CO₂)."""
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
                            float(r['PhiVap_pct']) / 100, M.ROOM_TEMPERATURE_C)
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


if __name__ == '__main__':
    unittest.main()
