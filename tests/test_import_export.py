"""Импорт CSV/XLSX (разделители, кодировки, русская локаль, ошибки) и экспорт."""
import csv
import tempfile
import unittest
from pathlib import Path

from fluid_app import calc, exporter, importer
from fluid_app.db import Database

ROOT = Path(__file__).resolve().parent.parent


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.db = Database(self.dir / 'db.sqlite')
        self.pid = self.db.add_project('Импорт')

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def write(self, name, text, encoding='utf-8'):
        p = self.dir / name
        p.write_text(text, encoding=encoding, newline='')
        return p

    def parse(self, path, **kw):
        t = importer.read_table(path, **kw)
        m = importer.auto_mapping(t.headers)
        self.assertEqual(importer.validate_mapping(m), [])
        return t, importer.parse_rows(t, m)


class TestRead(Case):
    def test_example_input(self):
        t, rows = self.parse(ROOT / 'examples' / 'example_input.csv')
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(r.ok for r in rows))
        self.assertEqual([r.observations[0]['kind'] for r in rows],
                         ['Tm_ice', 'Tm_clath', 'Th_CO2', 'Th_CO2', 'Th_CO2'])
        self.assertIsNone(rows[4].observations[0]['homogenization_to'])   # не угадывается

    def test_semicolon_cp1251_decimal_comma(self):
        p = self.write('ru.csv', 'Образец;Включение;Tm лёд;Th общ.\nБР-1;1;-5,2;185,4\nБР-1;2;-3,1;\n',
                       encoding='cp1251')
        t, rows = self.parse(p)
        self.assertEqual((t.encoding, t.delimiter), ('cp1251', ';'))
        self.assertEqual(rows[0].observations[0]['temperature_c'], -5.2)
        self.assertEqual(rows[0].observations[1]['temperature_c'], 185.4)
        self.assertEqual(len(rows[1].observations), 1)       # пустая ячейка — нет наблюдения

    def test_unicode_minus_utf8(self):
        p = self.write('u.csv', 'Образец;Включение;Tm лёд\nБР-1;1;−5,2\n')
        t, rows = self.parse(p)
        self.assertEqual(rows[0].observations[0]['temperature_c'], -5.2)

    def test_tab_delimiter(self):
        p = self.write('t.tsv', 'sample\tinclusion\ttm_ice\nA\t1\t-2.5\n')
        t, rows = self.parse(p)
        self.assertEqual(t.delimiter, '\t')
        self.assertTrue(rows[0].ok)

    def test_xlsx_and_sheets(self):
        p = ROOT / 'examples' / 'example_wide.xlsx'
        self.assertEqual(importer.xlsx_sheets(p)[0], 'Измерения')
        t, rows = self.parse(p)
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(r.ok for r in rows))
        r5 = rows[3]
        kinds = {o['kind']: o for o in r5.observations}
        self.assertEqual(kinds['Th_CO2']['homogenization_to'], 'liquid')
        self.assertIs(kinds['Th_CO2']['co2_purity_confirmed'], True)
        self.assertIs(kinds['Tm_clath']['liquid_co2_present'], True)
        # признаки не переносятся на наблюдения, к которым они не относятся
        self.assertIsNone(kinds['Tm_clath']['co2_purity_confirmed'])
        self.assertIsNone(kinds['Th_total']['liquid_co2_present'])
        self.assertIsNone(kinds['Th_CO2']['vapor_co2_present'])

    def test_empty_file(self):
        with self.assertRaises(ValueError):
            importer.read_table(self.write('e.csv', ''))
        with self.assertRaises(ValueError):
            importer.read_table(self.write('e2.csv', '\n\n;;\n'))

    def test_header_only(self):
        t, rows = self.parse(self.write('h.csv', 'sample,inclusion,tm_ice\n'))
        self.assertEqual(rows, [])

    def test_xls_rejected(self):
        with self.assertRaises(ValueError):
            importer.read_table(self.write('old.xls', 'x'))

    def test_row_errors(self):
        p = self.write('bad.csv', 'sample,inclusion,kind,temperature,homogenization_to,liquid_co2_present\n'
                                  'A,1,Tm_ice,abc,,\n'
                                  'A,2,unknown,1,,\n'
                                  ',3,Tm_ice,-1,,\n'
                                  'A,4,Th_CO2,20,сверху,\n'
                                  'A,5,Tm_clath,5,,может быть\n'
                                  'A,6,Tm_ice,,,\n'
                                  'A,7,,,,\n'
                                  'A,8,Tm_ice,-1,,\n')
        t, rows = self.parse(p)
        status = [(r.row_number, bool(r.errors), r.ok) for r in rows]
        self.assertEqual(status, [(2, True, False), (3, True, False), (4, True, False), (5, True, False),
                                  (6, True, False), (7, True, False), (8, False, False), (9, False, True)])
        self.assertTrue(rows[6].warnings)

    def test_mapping_validation(self):
        self.assertTrue(importer.validate_mapping({'sample': 'a'}))
        self.assertTrue(importer.validate_mapping({'sample': 'a', 'inclusion': 'b', 'kind': 'k'}))
        self.assertEqual(importer.validate_mapping({'sample': 'a', 'inclusion': 'b', 'Te': 'c'}), [])

    def test_flags_and_homog_parsers(self):
        self.assertIs(importer.parse_flag('Да'), True)
        self.assertIs(importer.parse_flag('нет'), False)
        self.assertIsNone(importer.parse_flag(' '))
        self.assertEqual(importer.parse_homogenization('Ж'), 'liquid')
        self.assertEqual(importer.parse_homogenization('газ'), 'vapor')
        self.assertEqual(importer.parse_number(' 1 234,5 '), 1234.5)
        with self.assertRaises(ValueError):
            importer.parse_number('nan')


class TestImportAndExport(Case):
    def _import(self, path, **kw):
        t, rows = self.parse(path)
        return importer.import_rows(self.db, self.pid, rows, source=Path(path).name, **kw)

    def test_original_not_modified_and_duplicates_skipped(self):
        src = ROOT / 'examples' / 'example_wide.xlsx'
        before = importer.file_sha256(src)
        rep1 = self._import(src)
        rep2 = self._import(src)
        self.assertEqual(importer.file_sha256(src), before)
        self.assertEqual(rep1.n_observations, 27)
        self.assertEqual(rep2.n_observations, 0)
        self.assertEqual(rep2.n_duplicates, 27)
        rep3 = self._import(src, skip_duplicates=False)
        self.assertEqual(rep3.n_observations, 27)

    def test_hierarchy_conflict_reported(self):
        self.write('a.csv', 'sample,mineral,inclusion,tm_ice\nS,кварц,1,-1\n')
        self._import(self.dir / 'a.csv')
        self.write('b.csv', 'sample,mineral,inclusion,tm_ice\nS,кальцит,1,-2\n')
        rep = self._import(self.dir / 'b.csv')
        self.assertEqual(rep.n_errors, 1)
        self.assertIn('другим минералом', rep.messages[0])

    def _run(self):
        obs = self.db.observations()
        items = [(o, calc.calculate_observation(o)) for o in obs]
        rid = self.db.save_run(self.pid, 'все', calc.backend_versions(), items)
        return self.db.run(rid), self.db.results(rid)

    def test_export_csv_and_xlsx(self):
        self._import(ROOT / 'examples' / 'example_input.csv')
        run, results = self._run()
        p = exporter.export_results_csv(self.dir / 'r.csv', run, results)
        with p.open(encoding='utf-8-sig') as fh:
            rows = list(csv.reader(fh, delimiter=';'))
        self.assertEqual(len(rows), 6)
        self.assertIn('DOI', rows[0])
        i = rows[0].index('Значение')
        self.assertEqual(rows[1][i], '7,864625')
        p2 = exporter.export_results_csv(self.dir / 'r2.csv', run, results, delimiter=',', decimal_comma=False)
        with p2.open(encoding='utf-8-sig') as fh:
            rows2 = list(csv.reader(fh))
        self.assertEqual(rows2[1][i], '7.864625')
        x = exporter.export_results_xlsx(self.dir / 'r.xlsx', run, results)
        from openpyxl import load_workbook
        wb = load_workbook(x)
        self.assertEqual(wb.sheetnames, ['Результаты', 'Паспорта', 'Расчёт', 'Методики и источники', 'Ограничения'])
        ws = wb['Результаты']
        self.assertEqual(ws.max_row, 6)
        hdr = [c.value for c in ws[1]]
        self.assertAlmostEqual(ws.cell(2, hdr.index('Значение') + 1).value, 7.864625)
        statuses = [ws.cell(r, hdr.index('Статус') + 1).value for r in range(2, 7)]
        self.assertIn('отказ', statuses)

    def test_observation_export_roundtrip(self):
        self._import(ROOT / 'examples' / 'example_wide.xlsx')
        obs = self.db.observations()
        p = exporter.export_observations_csv(self.dir / 'obs.csv', obs)
        pid2 = self.db.add_project('Копия')
        t, rows = self.parse(p)
        rep = importer.import_rows(self.db, pid2, rows, source='obs.csv')
        self.assertEqual(rep.n_observations, len(obs))
        a = [(o['sample_name'], o['inclusion_name'], o['kind'], o['temperature_c'], o['homogenization_to'],
              o['co2_purity_confirmed'], o['mineral_name'], o['fia_name']) for o in obs]
        b = [(o['sample_name'], o['inclusion_name'], o['kind'], o['temperature_c'], o['homogenization_to'],
              o['co2_purity_confirmed'], o['mineral_name'], o['fia_name'])
             for o in self.db.observations('project_id=?', (pid2,))]
        self.assertEqual(sorted(a, key=str), sorted(b, key=str))

    def test_database_dump(self):
        self._import(ROOT / 'examples' / 'example_input.csv')
        self._run()
        p = exporter.export_database_xlsx(self.db, self.dir / 'dump.xlsx')
        from openpyxl import load_workbook
        wb = load_workbook(p)
        self.assertIn('results', wb.sheetnames)
        self.assertEqual(wb['observations'].max_row, 6)


if __name__ == '__main__':
    unittest.main()
