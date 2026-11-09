"""Этап 2a: включения H₂O–NaCl — плотность, давление при Th, изохора (HokieFlincs)."""
import csv
import unittest
from pathlib import Path

from fluid_core import h2o_nacl as M
from fluid_core.salinity import bodnar_1993
from fluid_app import calc

ROOT = Path(__file__).resolve().parent.parent


def obs(kind, t, **kw):
    d = dict(kind=kind, temperature_c=t, uncertainty_c=None, homogenization_to=None, liquid_co2_present=None,
             vapor_co2_present=None, aqueous_brine_present=None, co2_purity_confirmed=None, inclusion_id=7,
             inclusion_name='7', sample_name='S', project_name='P', carbonic_fraction=None)
    d.update(kw)
    return d


def aq(rows):
    return [(ob, o) for ob, o in calc.calculate_all(rows) if o.kind == 'aq_pvt']


class TestCore(unittest.TestCase):
    def test_matches_hokieflincs_reference_run(self):
        """Перенос формул: совпадение с программой авторов (прогон в Excel), машинная точность."""
        with open(ROOT / 'validation' / 'data' / 'hokieflincs_oracle.csv', encoding='utf-8') as fh:
            rows = [r for r in csv.DictReader(fh) if r['phase'] == 'ice']
        self.assertEqual(len(rows), 20)
        for r in rows:
            with self.subTest(r['case']):
                s = bodnar_1993(float(r['Tm'])).salinity_wt_pct_nacl_eq
                res = M.homogenization_to_liquid(float(r['Th']), s, homogenization_to='liquid')
                self.assertAlmostEqual(res.pressure_bar / float(r['Ph_bar']), 1, delta=1e-12)
                self.assertAlmostEqual(res.density_g_cm3 / float(r['rho_g_cm3']), 1, delta=1e-12)
                self.assertAlmostEqual(res.slope_bar_per_c / float(r['dPdT_bar_C']), 1, delta=1e-12)

    def test_isochore_and_trapping(self):
        res = M.homogenization_to_liquid(250.0, 7.864625, homogenization_to='liquid')
        self.assertAlmostEqual(res.pressure_at(400.0), 2081.5160887827833, places=6)
        self.assertAlmostEqual(res.temperature_at(1000.0), 320.6306302357562, places=9)
        with self.assertRaises(ValueError):
            res.pressure_at(200.0)                          # ниже Th — двухфазная область
        with self.assertRaises(ValueError):
            res.temperature_at(10.0)                        # ниже Ph
        with self.assertRaises(ValueError):
            res.pressure_at(1000.0)                         # > 6 кбар
        self.assertTrue(all(p <= M.P_MAX_BAR for _, p in res.isochore))

    def test_domain(self):
        for th, s, h in ((40.0, 5.0, 'liquid'), (710.0, 5.0, 'liquid'), (400.0, 0.0, 'liquid'), (250.0, 45.0, 'liquid'),
                         (250.0, 5.0, 'vapor')):
            with self.subTest((th, s, h)), self.assertRaises(ValueError):
                M.homogenization_to_liquid(th, s, homogenization_to=h)

    def test_pure_water_limit_vs_iapws95(self):
        """Независимая проверка: при S = 0 давление Atkinson — в пределах 1 % от IAPWS-95 (50–370 °C)."""
        from CoolProp.CoolProp import PropsSI
        for th in (50.0, 100.0, 200.0, 300.0, 350.0, 370.0):
            p = PropsSI('P', 'T', th + 273.15, 'Q', 0, 'Water') / 1e5
            self.assertLess(abs(M.homogenization_pressure_bar(th, 0.0) / p - 1), 0.01, th)

    def test_critical_temperature(self):
        self.assertAlmostEqual(M.critical_temperature_c(0.0), 374.1)
        self.assertGreater(M.critical_temperature_c(10.0), 450)


class TestDerived(unittest.TestCase):
    def test_ok(self):
        ((ob, o),) = aq([obs('Tm_ice', -5.0), obs('Th_total', 250.0, homogenization_to='liquid')])
        self.assertEqual(o.status, 'ok', o.message)
        self.assertAlmostEqual(o.value, 0.8663170125549483, places=12)
        self.assertAlmostEqual(o.extras['Ph_bar'], 37.56117520223502, places=9)
        lines = dict(calc.passport_lines(dict(kind='aq_pvt', **ob['extra_inputs']), o.__dict__))
        self.assertIn('минимальное давление захвата', lines['Давление при Th (Ph), бар'])
        self.assertIn('Изохора (T, °C → P, бар)', lines)

    def test_direction_not_assumed(self):
        ((_, o),) = aq([obs('Tm_ice', -5.0), obs('Th_total', 250.0)])
        self.assertEqual(o.status, 'error')
        self.assertIn('направление', o.message)
        ((_, o),) = aq([obs('Tm_ice', -5.0), obs('Th_total', 250.0, homogenization_to='vapor')])
        self.assertEqual(o.status, 'error')

    def test_not_for_co2_inclusions(self):
        rows = [obs('Tm_ice', -5.0), obs('Th_total', 250.0, homogenization_to='liquid'),
                obs('Th_CO2', 20.0, homogenization_to='liquid', co2_purity_confirmed=True)]
        self.assertEqual(aq(rows), [])

    def test_missing_salinity_and_duplicates(self):
        ((_, o),) = aq([obs('Th_total', 250.0, homogenization_to='liquid')])
        self.assertIn('Нет Tm льда', o.message)
        ((_, o),) = aq([obs('Tm_ice', -25.0), obs('Th_total', 250.0, homogenization_to='liquid')])
        self.assertIn('не рассчитана', o.message)
        ((_, o),) = aq([obs('Tm_ice', -5.0), obs('Th_total', 250.0, homogenization_to='liquid'),
                        obs('Th_total', 251.0, homogenization_to='liquid')])
        self.assertIn('несколько Th', o.message)

    def test_warnings(self):
        ((_, o),) = aq([obs('Tm_ice', -1.0), obs('Th_total', 370.0, homogenization_to='liquid'), obs('Te', -40.0)])
        self.assertEqual(o.status, 'ok')
        self.assertTrue(any('критической' in w for w in o.warnings))
        self.assertTrue(any('другие соли' in w for w in o.warnings))

    def test_out_of_range_translated(self):
        ((_, o),) = aq([obs('Tm_ice', -5.0), obs('Th_total', 30.0, homogenization_to='liquid')])
        self.assertIn('от 50 до 700', o.message)


class TestLabImportOption(unittest.TestCase):
    def test_confirm_liquid_homogenization(self):
        import tempfile
        from test_lab_table import make_table
        from fluid_app.lab_table import read_lab_table, to_parsed_rows
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'lab.xlsx'
            make_table(p)
            t = read_lab_table(p)
            rows = to_parsed_rows(t)
            th = next(o for o in rows[0].observations if o['kind'] == 'Th_total')
            self.assertIsNone(th['homogenization_to'])
            rows = to_parsed_rows(t, confirm_aqueous_liquid_homogenization=True)
            th = next(o for o in rows[0].observations if o['kind'] == 'Th_total')
            self.assertEqual(th['homogenization_to'], 'liquid')
            th_co2_incl = next(o for o in rows[1].observations if o['kind'] == 'Th_total')
            self.assertIsNone(th_co2_incl['homogenization_to'])     # включение с CO₂ — не трогаем


if __name__ == '__main__':
    unittest.main()
