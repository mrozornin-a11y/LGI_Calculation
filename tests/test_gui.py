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
        self.assertEqual(self.w._run['n_total'], 27)
        self.assertEqual(self.w.res_table.rowCount(), 27)
        self.w.res_table.selectRow(0)
        self.assertIn('Паспорт', self.w.passport.toHtml())
        self.w.plot_type.setCurrentIndex(0)
        self.w.update_plot()
        self.assertTrue(self.w._figure.axes)

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
