"""Этап 1: доля углекислотной фазы, плотность включения по объёмному балансу, экспорт в формате лаборатории."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fluid_core.brine import TABLE_20C, nacl_solution_density_20c
from fluid_core.salinity import darling_1991
from fluid_app import calc, exporter, importer
from fluid_app.db import MIGRATIONS, SCHEMA_VERSION, Database, DatabaseError

try:
    import CoolProp  # noqa: F401
    HAVE_COOLPROP = True
except ImportError:
    HAVE_COOLPROP = False

PHASES = dict(liquid_co2_present=True, vapor_co2_present=True, aqueous_brine_present=True)


def obs(kind, t, inc=1, **kw):
    d = dict(kind=kind, temperature_c=t, uncertainty_c=None, homogenization_to=None, liquid_co2_present=None,
             vapor_co2_present=None, aqueous_brine_present=None, co2_purity_confirmed=None, inclusion_id=inc,
             inclusion_name=f'I{inc}', sample_name='S', project_name='P', carbonic_fraction=None,
             carbonic_fraction_unc=None, carbonic_fraction_method=None, carbonic_fraction_temp_c=None)
    d.update(kw)
    return d


def co2_inclusion(phi=0.3, unc=None, th=20.0, branch='liquid', tm_clath=8.0, tm_co2=None):
    props = dict(carbonic_fraction=phi, carbonic_fraction_unc=unc)
    rows = [obs('Th_CO2', th, homogenization_to=branch, co2_purity_confirmed=True, **props),
            obs('Tm_clath', tm_clath, **PHASES, **props), obs('Th_total', 250.0, **props)]
    if tm_co2 is not None:
        rows.append(obs('Tm_CO2', tm_co2, **props))
    return rows


class TestBrineDensity(unittest.TestCase):
    def test_nodes_and_water(self):
        self.assertEqual(nacl_solution_density_20c(0), 0.99821)
        self.assertEqual(nacl_solution_density_20c(10), 1.0707)
        self.assertEqual(nacl_solution_density_20c(26), 1.1972)

    def test_matches_lab_table_9_9(self):
        """Интерполяция совпадает с независимо полученными значениями табл. 9.9 лабораторной методики."""
        table_9_9 = {3: 1.01965, 5: 1.03405, 15: 1.10855, 17: 1.12405, 23: 1.1722, 25: 1.1888}
        for s, rho in table_9_9.items():
            self.assertAlmostEqual(nacl_solution_density_20c(s), rho, delta=1e-4, msg=s)

    def test_monotonic_and_range(self):
        vals = [d for _, d in TABLE_20C]
        self.assertEqual(vals, sorted(vals))
        for bad in (-0.1, 26.5, float('nan')):
            with self.assertRaises(ValueError):
                nacl_solution_density_20c(bad)
        with self.assertRaises(TypeError):
            nacl_solution_density_20c(True)


@unittest.skipUnless(HAVE_COOLPROP, 'CoolProp не установлен')
class TestBulkDensity(unittest.TestCase):
    def derived(self, rows):
        items = calc.calculate_all(rows)
        return [o for ob, o in items if o.kind == 'bulk_density']

    def test_hand_calculation(self):
        (o,) = self.derived(co2_inclusion(phi=0.3))
        self.assertEqual(o.status, 'ok', o.message)
        from fluid_core.co2 import pure_co2_saturation
        rho_c = pure_co2_saturation(20.0, 'liquid', co2_purity_confirmed=True).density_g_cm3
        s = darling_1991(8.0, **PHASES).salinity_wt_pct_nacl_eq
        rho_aq = 1.0196 + (1.0268 - 1.0196) * (s - 3.0)          # узлы CRC 3 и 4 мас. %
        self.assertAlmostEqual(o.value, 0.3 * rho_c + 0.7 * rho_aq, places=12)
        self.assertLess(o.value, rho_aq)                           # не больше плотности раствора
        self.assertGreater(o.value, rho_c)

    def test_phi_uncertainty_range(self):
        (o,) = self.derived(co2_inclusion(phi=0.3, unc=0.1))
        lo, hi = o.extras['rho_at_phi_plus_u'], o.extras['rho_at_phi_minus_u']
        self.assertLess(lo, o.value)
        self.assertGreater(hi, o.value)
        (o2,) = self.derived(co2_inclusion(phi=0.3))
        self.assertTrue(any('Погрешность φ не указана' in w for w in o2.warnings))

    def test_blocked_without_inputs(self):
        (o,) = self.derived(co2_inclusion(phi=None))
        self.assertEqual(o.status, 'error')
        self.assertIn('доля углекислотной фазы', o.message)
        rows = co2_inclusion()
        rows[0]['homogenization_to'] = None                        # ветвь не указана → нет ρ CO₂
        (o,) = self.derived(rows)
        self.assertIn('плотности CO₂', o.message)
        rows = co2_inclusion()
        rows[1]['vapor_co2_present'] = None                        # фазы клатрата не подтверждены
        (o,) = self.derived(rows)
        self.assertIn('солёности', o.message)
        rows = co2_inclusion() + [obs('Th_CO2', 21.0, homogenization_to='liquid', co2_purity_confirmed=True,
                                      carbonic_fraction=0.3)]
        (o,) = self.derived(rows)
        self.assertIn('несколько', o.message)

    def test_no_derived_result_for_aqueous_inclusion(self):
        self.assertEqual(self.derived([obs('Tm_ice', -3.0), obs('Th_total', 200.0)]), [])

    def test_impurity_warning(self):
        (o,) = self.derived(co2_inclusion(tm_co2=-59.6))
        self.assertTrue(any('примеси' in w for w in o.warnings))

    def test_passport(self):
        rows = co2_inclusion(phi=0.3, unc=0.05)
        items = calc.calculate_all(rows)
        ob, o = next((ob, o) for ob, o in items if o.kind == 'bulk_density')
        inputs = dict(kind='bulk_density', **ob['extra_inputs'])
        lines = dict(calc.passport_lines(inputs, o.__dict__))
        self.assertIn('φ углекислотной фазы, %', lines)
        self.assertIn('30,0 ± 5,0', lines['φ углекислотной фазы, %'])
        self.assertIn('Плотность при φ + u / φ − u', lines)
        self.assertIn('Источник', lines)

    def test_against_steele_macinnis_2018_cached_example(self):
        """Сравнение упрощённого объёмного баланса со строгой моделью Steele-MacInnis (2018).

        Эталон — результат, сохранённый автором в его программе (лист HeatingPath): режим 1, Tm клатрата 8 °C,
        Th CO₂ 20 °C в газ, φ = 20 % при 20 °C → 3,964 мас. % NaCl, ρ = 0,87166 г/см³. Это одна точка и
        сравнение моделей, а не валидация: упрощённый баланс не учитывает растворённую CO₂.
        """
        (o,) = self.derived(co2_inclusion(phi=0.20, th=20.0, branch='vapor', tm_clath=8.0))
        self.assertAlmostEqual(o.extras['salinity_wt_pct'], 3.964021035424017, delta=0.01)
        rel = (o.value - 0.8716597568267156) / 0.8716597568267156
        self.assertLess(rel, 0)                    # растворённая CO₂ не учтена → плотность занижена
        self.assertLess(abs(rel), 0.02)            # фактически ≈1,3 %


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_migration_from_v1_keeps_data_and_backs_up(self):
        path = self.dir / 'old.sqlite'
        c = sqlite3.connect(path)
        c.executescript(MIGRATIONS[0] + '; PRAGMA user_version = 1;')
        c.execute("INSERT INTO projects(name, created_at) VALUES ('Старый', '2026-01-01')")
        c.commit()
        c.close()
        db = Database(path)
        self.assertEqual(db.schema_version(), SCHEMA_VERSION)
        self.assertEqual([p['name'] for p in db.projects()], ['Старый'])
        self.assertTrue(list(self.dir.glob('old.bak-v1-*.sqlite')))
        db.close()

    def test_set_fraction(self):
        db = Database(self.dir / 'x.sqlite')
        sid = db.add_sample(db.add_project('P'), 'S')
        iid = db.add_inclusion(sid, '1')
        db.set_carbonic_fraction(iid, 0.35, 0.1, 'визуальная оценка', 22.0)
        inc = db.inclusion(iid)
        self.assertEqual((inc['carbonic_fraction'], inc['carbonic_fraction_unc']), (0.35, 0.1))
        with self.assertRaises(DatabaseError):
            db.set_carbonic_fraction(iid, 1.5)
        db.set_carbonic_fraction(iid, None, 0.1, 'x', 20.0)        # сброс очищает и сопутствующие поля
        inc = db.inclusion(iid)
        self.assertIsNone(inc['carbonic_fraction_method'])
        db.close()

    def test_import_and_export_fraction(self):
        db = Database(self.dir / 'x.sqlite')
        pid = db.add_project('P')
        src = self.dir / 'in.csv'
        src.write_text('sample;inclusion;Tm клатрат;Th CO2;Th CO2: направление;φ;погрешность φ;способ оценки φ\n'
                       'S;1;8,0;20;ж;30;10;визуальная оценка\n'
                       'S;2;7,5;25;г;150;;\n', encoding='utf-8')
        t = importer.read_table(src)
        rows = importer.parse_rows(t, importer.auto_mapping(t.headers))
        self.assertTrue(rows[0].ok)
        self.assertTrue(rows[1].errors)                           # 150 % — ошибка
        importer.import_rows(db, pid, rows, source='in.csv')
        inc = db.find_inclusion(db.samples(pid)[0]['id'], '1')
        self.assertAlmostEqual(inc['carbonic_fraction'], 0.30)
        self.assertEqual(inc['carbonic_fraction_method'], 'визуальная оценка')
        out = exporter.export_observations_csv(self.dir / 'obs.csv', db.observations())
        t2 = importer.read_table(out)
        rows2 = importer.parse_rows(t2, importer.auto_mapping(t2.headers))
        self.assertAlmostEqual(rows2[0].inclusion_props['carbonic_fraction'], 0.30)
        # повторный импорт с другой φ не перезаписывает существующую
        src.write_text('sample;inclusion;Tm клатрат;φ\nS;1;8,1;40\n', encoding='utf-8')
        t3 = importer.read_table(src)
        rep = importer.import_rows(db, pid, importer.parse_rows(t3, importer.auto_mapping(t3.headers)), source='x')
        self.assertTrue(any('уже задана' in m for m in rep.messages))
        self.assertAlmostEqual(db.inclusion(inc['id'])['carbonic_fraction'], 0.30)
        db.close()

    @unittest.skipUnless(HAVE_COOLPROP, 'CoolProp не установлен')
    def test_lab_format_export(self):
        from openpyxl import load_workbook
        db = Database(self.dir / 'x.sqlite')
        pid = db.add_project('P')
        sid = db.add_sample(pid, 'S-1')
        iid = db.add_inclusion(sid, '1-2', inclusion_type='Ж+(Ж+Г)СО2')
        db.set_carbonic_fraction(iid, 0.3, 0.1, 'визуальная оценка', 22.0)
        db.add_observation(iid, {'kind': 'Th_CO2', 'temperature_c': 20.0, 'homogenization_to': 'liquid',
                                 'co2_purity_confirmed': True})
        db.add_observation(iid, {'kind': 'Tm_clath', 'temperature_c': 8.0, **PHASES})
        db.add_observation(iid, {'kind': 'Th_total', 'temperature_c': 250.0})
        iid2 = db.add_inclusion(sid, '1-10', inclusion_type='Ж+Г')
        db.add_observation(iid2, {'kind': 'Tm_ice', 'temperature_c': -3.0})
        items = calc.calculate_all(db.observations())
        rid = db.save_run(pid, 'все', calc.backend_versions(), items)
        out = exporter.export_lab_format_xlsx(self.dir / 'lab.xlsx', db.run(rid), db.results(rid), db)
        ws = load_workbook(out).active
        rows = [[c.value for c in r] for r in ws.iter_rows()]
        header = next(r for r in rows if r[0] == '№ п/п')
        self.assertNotIn('Рфл', ' '.join(str(x) for x in header))
        data = [r for r in rows if isinstance(r[0], int)]
        self.assertEqual([r[1] for r in data], ['1-2', '1-10'])  # естественная сортировка
        r12 = data[0]
        self.assertEqual(r12[3], 'Ж+(Ж+Г)СО2')
        self.assertEqual(r12[9], 'Darling (1991)')
        self.assertEqual(r12[11], 'Ж')
        self.assertEqual(r12[13], 30.0)
        self.assertIsNotNone(r12[14])
        self.assertEqual(data[1][9], 'Bodnar (1993)')
        # включения с CO₂: строгая модель; давления показаны раздельно и не выдаются за давление захвата
        self.assertTrue(any('НЕ являются давлением захвата' in str(r[0]) for r in rows))
        col = {h: i for i, h in enumerate(header)}
        self.assertAlmostEqual(r12[col['ρ включения, строгая модель, г/см³']], 0.9601, delta=5e-4)
        self.assertGreater(r12[col['ρ включения, строгая модель, г/см³']], r12[14])     # объёмный баланс занижает
        self.assertIsNone(r12[col['P расслоения при Th общ., бар']])                    # направление Th общ. не указано
        self.assertIn('не давление захвата', r12[col['Предупреждения модели']])
        self.assertIsNone(data[1][col['ρ включения, строгая модель, г/см³']])           # водно-солевое включение
        self.assertTrue(any('МИНИМАЛЬНОЕ давление' in str(r[0]) for r in rows))       # Ph водно-солевых
        db.close()


if __name__ == '__main__':
    unittest.main()
