"""Проверка графического интерфейса без дисплея (QT_QPA_PLATFORM=offscreen)."""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
ROOT = Path(__file__).resolve().parent.parent

try:
    from PySide6.QtWidgets import QApplication
    HAVE_QT = True
except ImportError as exc:   # PySide6 нет или нет системных библиотек Qt
    HAVE_QT = False
    QT_ERROR = str(exc)


@unittest.skipUnless(HAVE_QT, 'PySide6 недоступен')
class TestMainWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ['XDG_DATA_HOME'] = cls.tmp.name
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        from PySide6.QtCore import QSettings
        QSettings('FluidCalc', 'FluidCalc').clear()
        from fluid_app.gui.main_window import MainWindow
        self.dbpath = Path(self.tmp.name) / f'{self.id()}.sqlite'
        self.w = MainWindow(str(self.dbpath))

    def tearDown(self):
        self.w.close()

    def test_import_dialog_and_threaded_calculation(self):
        from fluid_app.gui.dialogs import ImportDialog, NEW_PROJECT
        dlg = ImportDialog(self.w, self.w.db, str(ROOT / 'examples' / 'example_wide.xlsx'))
        self.assertEqual(dlg.map_combos['Th_total'].currentData(), 'Th общ.')
        dlg.project.setCurrentIndex(dlg.project.findData(NEW_PROJECT))
        dlg.new_project.setText('Демо')
        dlg._check()
        self.assertTrue(dlg.import_btn.isEnabled())
        from unittest import mock
        with mock.patch('fluid_app.gui.dialogs.QMessageBox.information'):
            dlg._import()
        self.assertEqual(dlg.report.n_observations, 27)
        self.w.refresh_all()
        self.assertEqual(self.w.obs_table.rowCount(), 27)
        self.w.calculate(selected_only=False)
        self.w.wait_for_calculation()
        self.assertIsNotNone(self.w._run)
        # 27 наблюдений + 4 «ρ включения» и 4 «Состав, ρ H₂O–CO₂–NaCl» (включения с Th CO₂) + 6 «ρ, Ph H₂O–NaCl»
        self.assertEqual(self.w._run['n_total'], 41)
        self.assertEqual(self.w.res_table.rowCount(), 41)
        pvtx = [r for r in self.w._results if r['kind'] == 'co2_pvtx']
        self.assertEqual(len(pvtx), 4)
        # φ в примере не задана: два включения с Th общ. в жидкость рассчитаны по Th общ. (с пометкой),
        # у двух расчёт заблокирован с объяснением, чего не хватает
        self.assertEqual(sorted(r['status'] for r in pvtx), ['error', 'error', 'ok', 'ok'])
        for r in pvtx:
            if r['status'] == 'ok':
                self.assertTrue(any('Доля углекислотных фаз не измерена' in w for w in r['warnings']))
            else:
                self.assertTrue('Не хватает данных' in r['message'] or 'Укажите φ' in r['message'])
        aq = [r for r in self.w._results if r['kind'] == 'aq_pvt']
        self.assertEqual(sorted(r['status'] for r in aq), ['error'] + ['ok'] * 5)   # Tm льда −24,5 °C вне области
        dens = [r for r in self.w._results if r['kind'] == 'bulk_density']
        self.assertEqual(len(dens), 4)
        self.assertTrue(all(r['status'] == 'error' for r in dens))   # φ не задана — расчёт заблокирован
        self.w.res_table.selectRow(0)
        self.assertIn('Паспорт', self.w.passport.toHtml())
        self.w.plot_type.setCurrentIndex(0)
        self.w.update_plot()
        self.assertTrue(self.w._figure.axes)

    def test_pvtx_input_calculation_save_reopen_export(self):
        """Строгая модель H₂O–CO₂–NaCl: ввод → расчёт → сохранение → повторное открытие → экспорт."""
        from unittest import mock
        from openpyxl import load_workbook
        from fluid_app import exporter
        from fluid_app.gui.dialogs import CarbonicFractionDialog, ObservationDialog
        from fluid_app.gui.main_window import MainWindow, ROLE
        w = self.w
        pid = w.db.add_project('Проект')
        sid = w.db.add_sample(pid, 'Бр-1')
        iid = w.db.add_inclusion(sid, '1-1')
        # ввод наблюдений через диалог (как делает пользователь)
        for kind, t, setup in (
                ('Th_CO2', '25,0', lambda d: (d.homog.set_value('liquid'), d.purity.setChecked(True))),
                ('Tm_clath', '8,0', lambda d: (d.liquid.set_value(True), d.vapor.set_value(True),
                                               d.brine.set_value(True))),
                ('Th_total', '250', lambda d: d.homog.set_value('liquid'))):
            dlg = ObservationDialog(w, '1-1')
            dlg.kind.setCurrentIndex(dlg.kind.findData(kind))
            dlg.temperature.setText(t)
            setup(dlg)
            dlg._accept()
            self.assertIsNotNone(dlg.result, kind)
            w.db.add_observation(iid, dlg.result)
        fr = CarbonicFractionDialog(w, '1-1', w.db.inclusion(iid))
        fr.value.setText('30')
        fr.unc.setText('5')
        fr.temp.setText('23,5')
        fr._accept()
        w.db.set_carbonic_fraction(iid, *fr.result)
        w.refresh_all()
        w.calculate(selected_only=False)
        w.wait_for_calculation()
        res = next(r for r in w._results if r['kind'] == 'co2_pvtx')
        self.assertEqual(res['status'], 'ok', res['message'])
        self.assertAlmostEqual(res['value'], 0.93991, delta=1e-4)
        self.assertTrue(res['extras']['converged'])
        # паспорт в окне: результат, единицы, модель, допущения, предупреждения, раздельные давления
        row = next(i for i in range(w.res_table.rowCount())
                   if w._results[w.res_table.item(i, 0).data(ROLE)]['kind'] == 'co2_pvtx')
        w.res_table.selectRow(row)
        html = w.passport.toPlainText()
        for text in ('г/см³', 'Steele-MacInnis', 'Допущения', 'Предупреждение', 'Давление на линии расслоения при Th общ.',
                     'Давление по изохоре при Th общ.', 'Расхождение двух давлений', 'ЭКСТРАПОЛЯЦИЯ',
                     'не давление захвата', 'сошедшееся'):
            self.assertIn(text, html)
        run_id = w._run['id']
        w.close()
        # повторное открытие той же базы: результат и предупреждения сохранены
        w2 = MainWindow(str(self.dbpath))
        try:
            again = next(r for r in w2.db.results(run_id) if r['kind'] == 'co2_pvtx')
            self.assertEqual(again['value'], res['value'])
            self.assertEqual(again['warnings'], res['warnings'])
            self.assertEqual(again['extras']['pressure_solvus_th_total_bar'], res['extras']['pressure_solvus_th_total_bar'])
            run = w2.db.run(run_id)
            out = Path(self.tmp.name)
            x = exporter.export_results_xlsx(out / 'r.xlsx', run, w2.db.results(run_id))
            c = exporter.export_results_csv(out / 'r.csv', run, w2.db.results(run_id))
            lab = exporter.export_lab_format_xlsx(out / 'lab.xlsx', run, w2.db.results(run_id), w2.db)
        finally:
            w2.close()
        ws = load_workbook(x)['Результаты']
        head = [c_.value for c_ in ws[1]]
        line = next(r for r in ws.iter_rows(min_row=2, values_only=True) if r[head.index('X(CO₂), мол. доля')])
        self.assertAlmostEqual(line[head.index('Значение')], res['value'], delta=1e-12)
        self.assertIn('не взаимозаменяемы', line[head.index('Предупреждения')])
        self.assertIn('ЭКСТРАПОЛЯЦИЯ', line[head.index('Способ расчёта P по изохоре при Th общ.')])
        p_solv, p_iso = (line[head.index(k)] for k in ('P на линии расслоения при Th общ. (Mao 2013), бар',
                                                       'P по изохоре при Th общ. (Duan 1995), бар'))
        self.assertAlmostEqual(line[head.index('Расхождение двух P при Th общ., бар')], p_iso - p_solv, delta=1e-9)
        passports = ' '.join(str(r[2]) for r in load_workbook(x)['Паспорта'].iter_rows(min_row=2, values_only=True))
        self.assertIn('Gottschalk', passports)
        text = c.read_text(encoding='utf-8-sig')
        self.assertIn('не взаимозаменяемы', text)
        labrows = [[c_.value for c_ in r] for r in load_workbook(lab).active.iter_rows()]
        header = next(r for r in labrows if r[0] == '№ п/п')
        data = next(r for r in labrows if isinstance(r[0], int))
        self.assertAlmostEqual(data[header.index('ρ включения, строгая модель, г/см³')], 0.9399, delta=1e-4)
        self.assertIn('не взаимозаменяемы', data[header.index('Предупреждения модели')])

    def test_quick_calc(self):
        w = self.w
        w.q_kind.setCurrentIndex(w.q_kind.findData('Tm_ice'))
        w.q_t.setText('-5,0')
        w.quick_calc()
        self.assertIn('7,86463', w.q_out.toPlainText())
        w.q_kind.setCurrentIndex(w.q_kind.findData('Th_CO2'))
        w.q_t.setText('20')
        w.quick_calc()
        self.assertIn('не указано', w.q_out.toPlainText())   # ветвь не выбирается автоматически

    def test_observation_dialog(self):
        from fluid_app.gui.dialogs import ObservationDialog
        d = ObservationDialog(self.w, 'тест')
        d.kind.setCurrentIndex(d.kind.findData('Tm_clath'))
        d.temperature.setText('5,8')
        d.liquid.set_value(True)
        d._accept()
        self.assertEqual(d.result['temperature_c'], 5.8)
        self.assertIs(d.result['liquid_co2_present'], True)
        self.assertIsNone(d.result['vapor_co2_present'])
        self.assertIsNone(d.result['homogenization_to'])


if __name__ == '__main__':
    unittest.main()
