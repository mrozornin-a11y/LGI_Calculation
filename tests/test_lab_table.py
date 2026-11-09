"""Импорт и сверка лабораторной сводной таблицы («Таблица 1/2/3»).

Используется синтетическая таблица того же формата (не данные лаборатории).
"""
import os
import tempfile
import unittest
from pathlib import Path

from fluid_app import lab_compare
from fluid_app.importer import import_rows
from fluid_app.lab_table import read_lab_table, to_parsed_rows
from fluid_app.db import Database

HEAD1 = ['№', '№', 'Тгом.', 'тип', 'Т тр.', 'Тэвт', 'Тпл..', 'Тпл.', 'С% ', 'Газ', 'Тгом.', 'd фл', 'Рфл', 'форма',
         'местонах']
HEAD2 = ['п/п', 'обр.', 'Тº С', 'включения', 'газа', 'Тº С', 'г-гил.', 'льда', 'экв.NaCl', None, 'част.', 'г/см3',
         'бар', 'вкл.', ' вкл.']


def make_table(path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append([None, None, 'Таблица1'])
    ws.append([])
    ws.append([None, 'Обр,', 'S-1', '2 пласт'])
    ws.append([])
    ws.append(HEAD1)
    ws.append(HEAD2)
    ws.append([None, None, 'группа1'])
    # водно-солевое: Tm лёд −5 → 7,86 (в таблице 7,9 — согласуется)
    ws.append([1, '1-1', 250, 'Ж+Г', None, -38.0, None, -5.0, 7.9, 'Н2О', None, None, None, 'овал', 'трещина'])
    # CO₂: Tm клатрат 8,5 → 3,02 (в таблице 6,7 — существенное расхождение); плотность 1,46 — невозможна
    ws.append([2, '1-2', 210, 'Ж+(Ж+Г)СО2', -59.6, -38.7, 8.5, None, 6.7, 'СО2', 30.1, 1.46, 296, 'овал', 'трещина'])
    # CO₂: тот же Tm клатрат 8,5, другое значение в таблице → внутренняя несогласованность; d '1,0,6'
    ws.append([3, '1-3', 220, 'Ж+(Ж+Г)СО2', -56.7, None, 8.5, None, 3.0, 'СО2', 9.6, '1,0,6', 1870, 'овал',
               'трещина'])
    ws.append([None, 'сред.'])
    ws.append([])
    ws.append(['Обр.', 'S-2', '1 пласт'])
    ws.append(HEAD1)
    ws.append(HEAD2)
    ws.append([1, '2-1', 320, 'Ж+Г', None, None, None, -24.0, 25.0, 'Н2О', None, None, None, 'овал', 'у границы'])
    wb.save(path)


class TestLabTable(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'lab.xlsx'
        make_table(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_blocks_and_columns(self):
        t = read_lab_table(self.path)
        self.assertEqual([(r.sample, r.inclusion) for r in t.rows], [('S-1', '1-1'), ('S-1', '1-2'), ('S-1', '1-3'),
                                                                        ('S-2', '2-1')])
        r = t.rows[1]
        self.assertEqual(r.layer, '2 пласт')
        self.assertEqual(r.group, 'группа 1')
        self.assertTrue(r.co2_bearing)
        self.assertEqual(r.measurements, {'Th_total': 210, 'Tm_CO2': -59.6, 'Te': -38.7, 'Tm_clath': 8.5,
                                          'Th_CO2': 30.1})
        self.assertEqual(r.lab_results, {'lab_salinity': 6.7, 'lab_density': 1.46, 'lab_pressure': 296})
        self.assertEqual(t.rows[2].lab_results['lab_density'], ('bad', '1,0,6'))
        self.assertEqual(t.rows[3].sample, 'S-2')

    def test_parsed_rows_do_not_guess(self):
        t = read_lab_table(self.path)
        rows = to_parsed_rows(t)
        clath = next(o for o in rows[1].observations if o['kind'] == 'Tm_clath')
        self.assertIsNone(clath['liquid_co2_present'])         # не подтверждено — не угадывается
        thco2 = next(o for o in rows[1].observations if o['kind'] == 'Th_CO2')
        self.assertIsNone(thco2['homogenization_to'])
        self.assertIsNone(thco2['co2_purity_confirmed'])
        self.assertIn('группировка исследователя, не FIA', clath['phase_notes'])
        self.assertIn('lab_salinity=6.7', clath['comment'])
        self.assertFalse(rows[2].errors)                       # плохая плотность лаборатории — не ошибка измерения
        rows_c = to_parsed_rows(t, confirm_clathrate_phases=True)
        clath = next(o for o in rows_c[1].observations if o['kind'] == 'Tm_clath')
        self.assertIs(clath['liquid_co2_present'], True)
        self.assertIn('подтверждено оператором', clath['comment'])

    def test_import_into_database(self):
        db = Database(Path(self.tmp.name) / 'db.sqlite')
        pid = db.add_project('Лаборатория')
        rep = import_rows(db, pid, to_parsed_rows(read_lab_table(self.path)), source='lab.xlsx')
        self.assertEqual(rep.n_errors, 0)
        self.assertEqual(rep.n_observations, 3 + 5 + 4 + 2)
        self.assertEqual(len(db.samples(pid)), 2)
        db.close()

    def test_comparison(self):
        checks, incons = lab_compare.compare(read_lab_table(self.path))
        by = {c.row.inclusion: c for c in checks}
        self.assertEqual(by['1-1'].salinity_status, 'согласуется')
        self.assertEqual(by['1-2'].salinity_status, 'существенное расхождение')
        self.assertAlmostEqual(by['1-2'].calc_salinity, 3.0158, places=3)
        self.assertTrue(by['1-2'].density_status.startswith('физически невозможно'))
        self.assertTrue(by['1-3'].density_status.startswith('нечисловое'))
        self.assertTrue(any('вероятны примеси' in n for n in by['1-2'].notes))
        self.assertTrue(any('от критической точки' in n for n in by['1-2'].notes))
        self.assertTrue(any('Давление лаборатории не проверяется' in n for n in by['1-2'].notes))
        self.assertEqual(by['2-1'].salinity_status, 'нет данных')     # −24 °C вне области Bodnar
        self.assertTrue(any('Пересчёт невозможен' in n for n in by['2-1'].notes))
        self.assertEqual(len(incons), 1)
        self.assertIn('8.5', incons[0])

    def test_comparison_xlsx(self):
        from openpyxl import load_workbook
        out = Path(self.tmp.name) / 'cmp.xlsx'
        lab_compare.write_comparison_xlsx(read_lab_table(self.path), out)
        wb = load_workbook(out)
        self.assertEqual(wb.sheetnames, ['Сверка', 'Итоги'])
        self.assertEqual(wb['Сверка'].max_row, 5)

    def test_source_not_modified(self):
        from fluid_app.importer import file_sha256
        before = file_sha256(self.path)
        lab_compare.write_comparison_xlsx(read_lab_table(self.path), Path(self.tmp.name) / 'c.xlsx')
        self.assertEqual(file_sha256(self.path), before)


@unittest.skipUnless(os.environ.get('QT_QPA_PLATFORM') == 'offscreen' or os.environ.get('DISPLAY'), 'нет дисплея')
class TestLabTableGui(unittest.TestCase):
    def test_gui_import(self):
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError:
            self.skipTest('PySide6 недоступен')
        with tempfile.TemporaryDirectory() as d:
            os.environ['XDG_DATA_HOME'] = d
            QApplication.instance() or QApplication([])
            from fluid_app.gui.main_window import MainWindow
            path = Path(d) / 'lab.xlsx'
            make_table(path)
            w = MainWindow(str(Path(d) / 'g.sqlite'))
            rep = w.import_lab_table(str(path), ask=False)
            self.assertEqual(rep.n_observations, 14)
            self.assertEqual(w.obs_table.rowCount(), 14)
            w.close()


if __name__ == '__main__':
    unittest.main()
