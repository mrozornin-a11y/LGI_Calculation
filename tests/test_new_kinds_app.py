"""Новые типы наблюдений, интерпретации и условия захвата в расчётном слое приложения и в базе данных."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fluid_app import calc, exporter, importer
from fluid_app.db import Database, DatabaseError, MIGRATIONS, SCHEMA_VERSION
from fluid_app.methods import KINDS, METHODS, method_category, methods_html, status_label
from fluid_core import halite, trapping


def obs(kind, t, inc=1, **kw):
    d = dict(kind=kind, temperature_c=t, uncertainty_c=None, homogenization_to=None, liquid_co2_present=None,
             vapor_co2_present=None, aqueous_brine_present=None, co2_purity_confirmed=None, inclusion_id=inc,
             inclusion_name=str(inc), sample_name='S', project_name='P', carbonic_fraction=None,
             carbonic_fraction_unc=None, carbonic_fraction_method=None, carbonic_fraction_temp_c=None)
    d.update(kw)
    return d


def one(rows, kind):
    return next(o for _, o in calc.calculate_all(rows) if o.kind == kind)


class TestHaliteAndHydrohalite(unittest.TestCase):
    def test_halite_needs_vapor(self):
        ok = one([obs('T_diss_halite', 300.0, vapor_present_at_transition=True, uncertainty_c=2.0)], 'T_diss_halite')
        self.assertEqual(ok.status, 'ok')
        self.assertEqual(ok.value, halite.halite_liquidus_wt_pct(300.0))             # без округления
        self.assertEqual(ok.unit, 'мас. % NaCl')
        self.assertEqual(method_category(ok.method_key), 'calculation')
        self.assertLess(ok.extras['sensitivity_t_minus_u'], ok.value)
        for flag in (False, None):
            o = one([obs('T_diss_halite', 300.0, vapor_present_at_transition=flag)], 'T_diss_halite')
            self.assertEqual(o.status, 'error')
            self.assertIsNone(o.value)
            self.assertIn('Количественный результат не выдаётся', o.message)
            self.assertIn('зависит от давления', o.message)
        out = one([obs('T_diss_halite', 900.0, vapor_present_at_transition=True)], 'T_diss_halite')
        self.assertEqual(out.status, 'error')

    def test_hydrohalite_prerequisites(self):
        ok = one([obs('Tm_hydrohalite', -10.0, phase_identified=True)], 'Tm_hydrohalite')
        self.assertEqual(ok.status, 'ok')
        self.assertAlmostEqual(ok.value, 25.125138134358654, delta=1e-12)
        self.assertTrue(any('Сведений о других солях нет' in w for w in ok.warnings))
        for flag in (False, None):
            o = one([obs('Tm_hydrohalite', -10.0, phase_identified=flag)], 'Tm_hydrohalite')
            self.assertEqual(o.status, 'error')
            self.assertIsNone(o.value)
        self.assertEqual(one([obs('Tm_hydrohalite', -25.0, phase_identified=True)], 'Tm_hydrohalite').status, 'error')

    def test_hydrohalite_blocked_by_te_or_confirmed_salts(self):
        rows = [obs('Tm_hydrohalite', -10.0, phase_identified=True), obs('Te', -51.0, uncertainty_c=0.5)]
        o = one(rows, 'Tm_hydrohalite')
        self.assertEqual(o.status, 'error')
        self.assertIn('недостаточно для определения состава многокомпонентной системы', o.message)
        self.assertIn('Te', o.message)
        # Te около эвтектики H₂O–NaCl расчёту не мешает
        rows = [obs('Tm_hydrohalite', -10.0, phase_identified=True), obs('Te', -21.3, uncertainty_c=0.3)]
        self.assertEqual(one(rows, 'Tm_hydrohalite').status, 'ok')
        # внешнее подтверждение других солей
        o = one([obs('Tm_hydrohalite', -10.0, phase_identified=True, other_salts_confirmed=True)], 'Tm_hydrohalite')
        self.assertEqual(o.status, 'error')
        self.assertIn('подтверждение', o.message)
        # Te другого включения не учитывается
        rows = [obs('Tm_hydrohalite', -10.0, phase_identified=True), obs('Te', -51.0, inc=2)]
        self.assertEqual(one(rows, 'Tm_hydrohalite').status, 'ok')


class TestInterpretationsInApp(unittest.TestCase):
    def test_te(self):
        o = one([obs('Te', -35.0, uncertainty_c=0.5), obs('Tm_ice', -8.0)], 'Te')
        self.assertEqual(o.status, 'ok')
        self.assertIsNone(o.value)
        self.assertEqual(method_category(o.method_key), 'interpretation')
        self.assertEqual(status_label(o.status, o.method_key), 'интерпретация (не расчёт)')
        self.assertEqual([c['key'] for c in o.extras['candidates']], ['mgcl2_bearing', 'fecl2_bearing'])
        self.assertFalse(o.extras['quantitative_composition_available'])
        self.assertIn('Одна Te не определяет количественный солевой состав.', o.warnings)
        self.assertNotIn('Tm льда', o.extras['recommended_data'])           # Tm льда у включения уже есть
        lines = dict(calc.passport_lines(obs('Te', -35.0, uncertainty_c=0.5), o.__dict__))
        self.assertIn('ИНТЕРПРЕТАЦИЯ', lines['Вид сведений'])
        self.assertEqual(lines['Количественный результат'], 'не выдаётся')
        self.assertNotIn('Результат', lines)

    def test_tm_co2_uses_sibling_th_co2_and_raman(self):
        rows = [obs('Tm_CO2', -58.0, uncertainty_c=0.2, raman_species='CO2+CH4'),
                obs('Th_CO2', 10.0, homogenization_to='liquid', co2_purity_confirmed=None)]
        o = one(rows, 'Tm_CO2')
        self.assertEqual(o.extras['interpretation_status'], 'data_sufficient_for_future_Thiery_binary_VX_model')
        self.assertFalse(o.extras['quantitative_result_available'])
        self.assertIsNone(o.value)
        o = one([obs('Tm_CO2', -58.0, uncertainty_c=0.2, raman_species='CO2+CH4+N2')], 'Tm_CO2')
        self.assertEqual(o.extras['interpretation_status'], 'ternary_requires_quantitative_Raman_and_mixture_EOS')
        o = one([obs('Tm_CO2', -58.0, uncertainty_c=0.2)], 'Tm_CO2')
        self.assertEqual(o.extras['interpretation_status'], 'volatile_impurity_suspected')
        o = one([obs('Tm_CO2', -56.6, uncertainty_c=0.1)], 'Tm_CO2')
        self.assertEqual(o.extras['interpretation_status'], 'consistent_with_pure_CO2_within_measurement')

    def test_existing_calculations_untouched(self):
        from fluid_core.salinity import bodnar_1993
        o = one([obs('Tm_ice', -5.0), obs('Te', -21.3)], 'Tm_ice')
        self.assertEqual(o.value, bodnar_1993(-5.0).salinity_wt_pct_nacl_eq)
        self.assertEqual(method_category(o.method_key), 'calculation')
        self.assertEqual(status_label('ok', o.method_key), 'рассчитано')
        self.assertEqual(one([obs('Th_total', 250.0)], 'Th_total').status, 'skipped')
        self.assertEqual(method_category(None), 'observation')

    def test_methods_reference(self):
        for key in ('te_interpretation', 'tm_co2_interpretation'):
            self.assertEqual(METHODS[key]['category'], 'interpretation')
        for key in ('halite_sterner1988', 'hydrohalite_sm2011', 'trapping_constraint'):
            self.assertEqual(METHODS[key]['category'], 'calculation')
        html = methods_html()
        for text in ('НАБЛЮДЕНИЕ', 'РАСЧЁТ', 'ИНТЕРПРЕТАЦИЯ', '10.1016/0016-7037(90)90355-O',
                     '10.1016/0016-7037(90)90356-P', '10.1016/j.earscirev.2016.04.011', '10.1016/j.gca.2014.08.015',
                     'Baldassaro', '−196', '10.1127/ejm/6/6/0753', '10.1016/0016-7037(94)90573-8',
                     '10.1016/0016-7037(88)90254-2', '10.1016/j.gca.2010.10.002', 'LA-ICP-MS',
                     'условия захвата включения при независимом ограничении'):
            self.assertIn(text, html)
        self.assertIn('Tm_hydrohalite', KINDS)
        self.assertIn('T_diss_halite', KINDS)


AQ = dict(trap_temperature_c=None, trap_temperature_max_c=None, trap_pressure_bar=None, trap_pressure_max_bar=None,
          trap_constraint_source='хлоритовый геотермометр', coeval_documented=None, coeval_note=None)


def aq_rows(**trap):
    props = dict(AQ, **trap)
    return [obs('Tm_ice', -5.0, **props), obs('Th_total', 250.0, homogenization_to='liquid', **props)]


class TestTrappingInApp(unittest.TestCase):
    def test_no_constraint_no_row(self):
        self.assertFalse([o for _, o in calc.calculate_all(aq_rows()) if o.kind == 'trapping'])

    def test_h2o_nacl_temperature_and_pressure(self):
        aq = one(aq_rows(trap_temperature_c=400.0), 'aq_pvt')
        o = one(aq_rows(trap_temperature_c=400.0), 'trapping')
        self.assertEqual(o.status, 'ok', o.message)
        self.assertAlmostEqual(o.value, aq.extras['Ph_bar'] + aq.extras['dPdT_bar_per_C'] * 150.0, delta=1e-9)
        self.assertEqual(o.unit, 'бар')
        self.assertIn('Условия захвата включения при независимом ограничении', o.result_kind)
        self.assertNotIn('минералообразования', o.result_kind)
        self.assertTrue(any('а не давление или температура минералообразования' in w for w in o.warnings))
        p = one(aq_rows(trap_pressure_bar=1000.0), 'trapping')
        self.assertEqual(p.unit, '°C')
        self.assertAlmostEqual(p.value, 250.0 + (1000.0 - aq.extras['Ph_bar']) / aq.extras['dPdT_bar_per_C'], delta=1e-9)

    def test_range_and_failures(self):
        r = one(aq_rows(trap_temperature_c=300.0, trap_temperature_max_c=400.0), 'trapping')
        self.assertEqual(r.status, 'ok')
        self.assertIsNone(r.value)
        self.assertEqual(r.extras['temperature_range_c'], [300.0, 400.0])
        self.assertLess(r.extras['pressure_range_bar'][0], r.extras['pressure_range_bar'][1])
        self.assertTrue(any('не статистический доверительный интервал' in w for w in r.warnings))
        low = one(aq_rows(trap_pressure_bar=10.0), 'trapping')
        self.assertEqual(low.status, 'error')
        self.assertIn('Допустимого пересечения нет', low.message)
        self.assertEqual(one(aq_rows(trap_temperature_c=200.0), 'trapping').status, 'error')   # ниже Th
        both = one(aq_rows(trap_temperature_c=400.0, trap_pressure_bar=1000.0), 'trapping')
        self.assertIn('ровно одно', both.message)
        # изохора не рассчитана (нет направления гомогенизации) — условия захвата не выдаются
        rows = [obs('Tm_ice', -5.0, **dict(AQ, trap_temperature_c=400.0)),
                obs('Th_total', 250.0, **dict(AQ, trap_temperature_c=400.0))]
        self.assertIn('изохора включения не рассчитана', one(rows, 'trapping').message)

    def test_coeval_wording_only_when_documented(self):
        plain = one(aq_rows(trap_temperature_c=400.0), 'trapping')
        self.assertNotIn('может интерпретироваться', plain.extras['wording'])
        doc = one(aq_rows(trap_temperature_c=400.0, coeval_documented=True, coeval_note='включения в зоне роста'),
                  'trapping')
        self.assertIn('может интерпретироваться как условие соответствующего этапа минералообразования',
                      doc.extras['wording'])
        self.assertTrue(any('включения в зоне роста' in w for w in doc.warnings))
        nosrc = one(aq_rows(trap_temperature_c=400.0, trap_constraint_source=None), 'trapping')
        self.assertTrue(any('Источник независимой оценки не указан' in w for w in nosrc.warnings))

    def test_h2o_co2_nacl(self):
        props = dict(AQ, carbonic_fraction=0.3, carbonic_fraction_temp_c=23.5, trap_temperature_c=420.0)
        rows = [obs('Th_CO2', 25.0, homogenization_to='liquid', co2_purity_confirmed=True, **props),
                obs('Tm_clath', 8.0, liquid_co2_present=True, vapor_co2_present=True, aqueous_brine_present=True,
                    **props)]
        pv = one(rows, 'co2_pvtx')
        o = one(rows, 'trapping')
        self.assertEqual(o.status, 'ok', o.message)
        iso = trapping.CompositionIsochore(pv.extras['molar_volume_cm3_mol'], pv.extras['x_h2o'], pv.extras['x_nacl'],
                                           pv.extras['x_co2'])
        self.assertEqual(o.value, iso.pressure_at(420.0))
        back = one([dict(r, trap_temperature_c=None, trap_pressure_bar=o.value) for r in rows], 'trapping')
        self.assertAlmostEqual(back.value, 420.0, delta=1e-8)
        cold = one([dict(r, trap_temperature_c=250.0) for r in rows], 'trapping')
        self.assertEqual(cold.status, 'error')
        self.assertIn('Вне области применимости', cold.message)


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_migration_from_v2_keeps_observations_results_and_ids(self):
        path = self.dir / 'old.sqlite'
        c = sqlite3.connect(path)
        c.executescript(MIGRATIONS[0] + MIGRATIONS[1] + '; PRAGMA user_version = 2;')
        c.executescript("""
            INSERT INTO projects(id, name, created_at) VALUES (1, 'Старый', '2026-01-01');
            INSERT INTO samples(id, project_id, name, created_at) VALUES (1, 1, 'Бр-2', '2026-01-01');
            INSERT INTO inclusions(id, sample_id, name, carbonic_fraction) VALUES (7, 1, '1-1', 0.3);
            INSERT INTO observations(id, inclusion_id, kind, temperature_c, uncertainty_c, liquid_co2_present,
                                     created_at, updated_at)
                VALUES (41, 7, 'Te', -21.5, 0.5, NULL, 'a', 'b'), (42, 7, 'Tm_CO2', -56.9, NULL, NULL, 'a', 'b'),
                       (43, 7, 'Tm_clath', 8.0, NULL, 1, 'a', 'b');
            INSERT INTO calc_runs(id, created_at) VALUES (1, '2026-01-02');
            INSERT INTO results(id, run_id, observation_id, kind, inputs_json, status) VALUES (5, 1, 43, 'Tm_clath', '{}', 'ok');
        """)
        c.commit()
        # в старой схеме новые типы наблюдений были запрещены
        with self.assertRaises(sqlite3.IntegrityError):
            c.execute("INSERT INTO observations(inclusion_id, kind, temperature_c, created_at, updated_at) "
                      "VALUES (7, 'T_diss_halite', 300, 'a', 'b')")
        c.close()
        db = Database(path)
        self.assertEqual(db.schema_version(), SCHEMA_VERSION)
        self.assertTrue(list(self.dir.glob('old.bak-v2-*.sqlite')))
        rows = {o['id']: o for o in db.observations()}
        self.assertEqual(sorted(rows), [41, 42, 43])
        self.assertEqual((rows[41]['kind'], rows[41]['temperature_c'], rows[41]['uncertainty_c']), ('Te', -21.5, 0.5))
        self.assertIs(rows[43]['liquid_co2_present'], True)
        self.assertIsNone(rows[41]['vapor_present_at_transition'])
        self.assertEqual(rows[43]['carbonic_fraction'], 0.3)
        # ссылка результата на наблюдение не потеряна при пересоздании таблицы
        self.assertEqual(db._one('SELECT observation_id FROM results WHERE id=5')['observation_id'], 43)
        self.assertEqual(db.conn.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        self.assertEqual(db.conn.execute('PRAGMA foreign_key_check').fetchall(), [])
        # старые наблюдения Te и Tm CO₂ теперь интерпретируются, новые типы принимаются
        kinds = {o.kind: o for _, o in calc.calculate_all(db.observations())}
        self.assertEqual(kinds['Te'].status, 'ok')
        self.assertEqual(kinds['Tm_CO2'].extras['interpretation_status'], 'uncertainty_not_specified')
        oid = db.add_observation(7, {'kind': 'T_diss_halite', 'temperature_c': 300.0,
                                     'vapor_present_at_transition': True})
        self.assertIs(db.observation(oid)['vapor_present_at_transition'], True)
        db.close()

    def test_new_fields_round_trip_and_validation(self):
        db = Database(self.dir / 'x.sqlite')
        pid = db.add_project('P')
        sid = db.add_sample(pid, 'S')
        iid = db.add_inclusion(sid, '1')
        a = db.add_observation(iid, {'kind': 'Tm_hydrohalite', 'temperature_c': -10.0, 'phase_identified': True})
        b = db.add_observation(iid, {'kind': 'Tm_CO2', 'temperature_c': -57.5, 'raman_species': 'CO2+N2'})
        self.assertIs(db.observation(a)['phase_identified'], True)
        self.assertEqual(db.observation(b)['raman_species'], 'CO2+N2')
        with self.assertRaises(DatabaseError):
            db.add_observation(iid, {'kind': 'Tm_CO2', 'temperature_c': -57.5, 'raman_species': 'H2S'})
        with self.assertRaises(DatabaseError):
            db.add_observation(iid, {'kind': 'Tm_sylvite', 'temperature_c': 100.0})
        db.set_inclusion_context(iid, trap_temperature_c=350.0, trap_temperature_max_c=400.0,
                                 trap_constraint_source='изотопный термометр', coeval_documented=True,
                                 coeval_note='зона роста', other_salts_confirmed=False)
        o = db.observation(a)
        self.assertEqual((o['trap_temperature_c'], o['trap_temperature_max_c']), (350.0, 400.0))
        self.assertIs(o['coeval_documented'], True)
        self.assertIs(o['other_salts_confirmed'], False)
        with self.assertRaises(DatabaseError):
            db.set_inclusion_context(iid, trap_pressure_bar=1000.0)             # температура уже задана
        with self.assertRaises(DatabaseError):
            db.set_inclusion_context(iid, trap_temperature_c=None, trap_temperature_max_c=400.0)
        with self.assertRaises(DatabaseError):
            db.set_inclusion_context(iid, nonsense=1)
        db.set_inclusion_context(iid, trap_temperature_c=None, trap_temperature_max_c=None, trap_pressure_bar=1500.0)
        self.assertEqual(db.observation(a)['trap_pressure_bar'], 1500.0)
        db.close()

    def test_save_export_and_import_round_trip(self):
        from openpyxl import load_workbook
        db = Database(self.dir / 'x.sqlite')
        pid = db.add_project('P')
        sid = db.add_sample(pid, 'S')
        iid = db.add_inclusion(sid, '1')
        db.add_observation(iid, {'kind': 'Te', 'temperature_c': -21.4, 'uncertainty_c': 0.3})
        db.add_observation(iid, {'kind': 'Tm_hydrohalite', 'temperature_c': -10.0, 'phase_identified': True})
        db.add_observation(iid, {'kind': 'T_diss_halite', 'temperature_c': 300.0, 'vapor_present_at_transition': True})
        i2 = db.add_inclusion(sid, '2')
        db.add_observation(i2, {'kind': 'T_diss_halite', 'temperature_c': 300.0})
        db.add_observation(i2, {'kind': 'Tm_ice', 'temperature_c': -5.0})
        db.add_observation(i2, {'kind': 'Th_total', 'temperature_c': 250.0, 'homogenization_to': 'liquid'})
        db.set_inclusion_context(i2, trap_temperature_c=400.0, trap_constraint_source='термометр')
        rid = db.save_run(pid, 'все', calc.backend_versions(), calc.calculate_all(db.observations()))
        res = db.results(rid)
        te = next(r for r in res if r['kind'] == 'Te')
        self.assertEqual(te['extras']['category'], 'interpretation')
        self.assertTrue(te['warnings'])
        xlsx = exporter.export_results_xlsx(self.dir / 'r.xlsx', db.run(rid), res)
        ws = load_workbook(xlsx)['Результаты']
        head = [c.value for c in ws[1]]
        lines = list(ws.iter_rows(min_row=2, values_only=True))
        by_kind = {}
        for line in lines:
            by_kind.setdefault(line[head.index('Тип наблюдения')], []).append(line)
        self.assertEqual(by_kind['Te'][0][head.index('Статус')], 'интерпретация (не расчёт)')
        self.assertEqual(by_kind['Te'][0][head.index('Вид сведений')], 'интерпретация')
        self.assertIsNone(by_kind['Te'][0][head.index('Значение')])
        self.assertIn('Кандидаты', by_kind['Te'][0][head.index('Заключение интерпретации')])
        self.assertEqual(by_kind['Th общ.'][0][head.index('Вид сведений')], 'наблюдение')
        hal = by_kind['T раств. галита']
        self.assertEqual(sorted(x[head.index('Статус')] for x in hal), ['отказ', 'рассчитано'])
        trap = by_kind['Условия захвата'][0]
        self.assertEqual(trap[head.index('Условия захвата: T, °C')], 400.0)
        self.assertGreater(trap[head.index('Условия захвата: P, бар')], 1000)
        self.assertEqual(trap[head.index('Условия захвата: формулировка')],
                         'условия захвата включения при независимом ограничении')
        self.assertIn('не давление или температура минералообразования', trap[head.index('Предупреждения')])
        lab = exporter.export_lab_format_xlsx(self.dir / 'lab.xlsx', db.run(rid), res, db)
        rows = [[c.value for c in r] for r in load_workbook(lab).active.iter_rows()]
        header = next(r for r in rows if r[0] == '№ п/п')
        d1 = next(r for r in rows if isinstance(r[0], int) and r[1] == '1')
        self.assertEqual(d1[header.index('Солёность по галиту, мас. % NaCl')], 38.16)
        self.assertEqual(d1[header.index('Солёность по гидрогалиту, мас. % NaCl')], 25.13)
        self.assertIn('Кандидаты', d1[header.index('Te: интерпретация (не состав)')])
        d2 = next(r for r in rows if isinstance(r[0], int) and r[1] == '2')
        self.assertIn('условия захвата включения при независимом ограничении',
                      d2[header.index('Условия захвата при независимом ограничении')])
        self.assertIsNone(d2[header.index('Солёность по галиту, мас. % NaCl')])       # пар не указан
        # экспорт наблюдений читается импортом обратно вместе с новыми типами и признаками
        csv_path = exporter.export_observations_csv(self.dir / 'obs.csv', db.observations())
        t = importer.read_table(csv_path)
        parsed = importer.parse_rows(t, importer.auto_mapping(t.headers))
        got = {(p.observations[0]['kind'], p.observations[0]['temperature_c']): p.observations[0]
               for p in parsed if p.observations}
        self.assertIs(got[('Tm_hydrohalite', -10.0)]['phase_identified'], True)
        halite_flags = [p.observations[0]['vapor_present_at_transition'] for p in parsed
                        if p.observations and p.observations[0]['kind'] == 'T_diss_halite']
        self.assertEqual(sorted(halite_flags, key=str), [None, True])
        kinds = sorted(k for k, _ in got)
        self.assertIn('Tm_hydrohalite', kinds)
        self.assertIn('T_diss_halite', kinds)
        self.assertIsNone(got[('Te', -21.4)]['phase_identified'])
        db.close()


if __name__ == '__main__':
    unittest.main()
