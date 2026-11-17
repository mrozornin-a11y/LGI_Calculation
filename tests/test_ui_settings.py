"""Масштаб шрифта (меню «Вид») и доля углекислотной фазы в диалоге «Добавить включение»."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, 'PySide6 недоступен')
class TestFontScale(unittest.TestCase):
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
        from fluid_app.gui import fontscale
        from fluid_app.gui.main_window import MainWindow
        self.fs = fontscale
        self.dbpath = Path(self.tmp.name) / f'{self.id()}.sqlite'
        self.w = MainWindow(str(self.dbpath))
        self.base = fontscale._state['base']

    def tearDown(self):
        self.w.set_font_scale(100)
        self.w.close()

    def _size(self, cls=None):
        f = self.app.font() if cls is None else self.app.font(cls)
        return f.pointSizeF()

    def test_scale_applies_to_whole_application_and_persists(self):
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QToolTip
        from fluid_app.gui.main_window import MainWindow
        base = self.base[None].pointSizeF()
        self.assertEqual(self.fs.current_scale(), 100)
        self.assertAlmostEqual(self._size(), base)
        row0 = self.w.obs_table.verticalHeader().defaultSectionSize()
        self.w.set_font_scale(150)
        self.assertAlmostEqual(self._size(), base * 1.5)
        for cls in ('QMenu', 'QMenuBar', 'QMessageBox', 'QHeaderView', 'QPushButton', 'QTipLabel'):
            self.assertAlmostEqual(self._size(cls), self.base[cls].pointSizeF() * 1.5, msg=cls)
        self.assertAlmostEqual(QToolTip.font().pointSizeF(), self.base['QTipLabel'].pointSizeF() * 1.5)
        self.assertAlmostEqual(self.w.tree.font().pointSizeF(), base * 1.5)          # дерево проекта
        self.assertAlmostEqual(self.w.menuBar().font().pointSizeF(), self.base['QMenuBar'].pointSizeF() * 1.5)
        self.assertGreater(self.w.obs_table.verticalHeader().defaultSectionSize(), row0)   # строки таблиц выше
        self.assertTrue(self.w.font_scale_actions[150].isChecked())
        self.assertEqual(int(QSettings('FluidCalc', 'FluidCalc').value(self.fs.SETTINGS_KEY)), 150)
        # диалоги, созданные после смены масштаба, получают крупный шрифт и крупные строки таблиц
        from fluid_app.gui.dialogs import ImportDialog
        dlg = ImportDialog(self.w, self.w.db)
        dlg.show()
        self.app.processEvents()
        self.assertAlmostEqual(dlg.font().pointSizeF(), base * 1.5)
        self.assertEqual(dlg.check_table.verticalHeader().defaultSectionSize(), self.fs.row_height(dlg.check_table))
        dlg.close()
        # «перезапуск»: новое окно читает масштаб из QSettings
        self.w.close()
        self.fs.apply_font_scale(100)                      # как при новом запуске: шрифт системный
        self.w = MainWindow(str(self.dbpath))
        self.assertEqual(self.fs.current_scale(), 150)
        self.assertAlmostEqual(self._size(), base * 1.5)
        self.assertTrue(self.w.font_scale_actions[150].isChecked())
        # «По умолчанию»
        self.w.a_font_default.trigger()
        self.assertEqual(self.fs.current_scale(), 100)
        self.assertAlmostEqual(self._size(), base)
        self.assertAlmostEqual(self._size('QMenu'), self.base['QMenu'].pointSizeF())
        self.assertEqual(int(QSettings('FluidCalc', 'FluidCalc').value(self.fs.SETTINGS_KEY)), 100)

    def test_steps_and_limits(self):
        self.assertEqual(self.fs.SCALES[0], 100)
        self.assertEqual(self.fs.SCALES[-1], 175)
        steps = [b - a for a, b in zip(self.fs.SCALES, self.fs.SCALES[1:])]
        self.assertTrue(all(10 <= d <= 25 for d in steps), steps)
        self.assertFalse(self.w.a_font_smaller.isEnabled())
        self.w.a_font_bigger.trigger()
        self.assertEqual(self.fs.current_scale(), 110)
        for _ in range(10):
            self.w.a_font_bigger.trigger()
        self.assertEqual(self.fs.current_scale(), 175)       # не больше 175 %
        self.assertFalse(self.w.a_font_bigger.isEnabled())
        self.w.a_font_smaller.trigger()
        self.assertEqual(self.fs.current_scale(), 150)
        # повреждённое или устаревшее значение в настройках
        self.assertEqual(self.fs.clamp_scale('abc'), 100)
        self.assertEqual(self.fs.clamp_scale(None), 100)
        self.assertEqual(self.fs.clamp_scale(400), 175)
        self.assertEqual(self.fs.clamp_scale('120'), 125)
        # масштаб не накапливается: повторное применение того же значения даёт тот же размер
        self.fs.apply_font_scale(150)
        self.fs.apply_font_scale(150)
        self.assertAlmostEqual(self._size(), self.base[None].pointSizeF() * 1.5)

    def test_layout_follows_scale(self):
        """Размеры, заданные в пикселях, растут вместе со шрифтом; диалог помещается на экран."""
        from fluid_app.gui.experiment import AddInclusionDialog
        db = self.w.db
        pid = db.add_project('П')
        sid = db.add_sample(pid, 'Бр-1')
        iid = db.add_inclusion(sid, '1')
        self.w.refresh_all()
        self.w.select_inclusion(iid)
        w100 = self.w.exp_panel.initial_card.width()
        self.w.set_font_scale(175)
        self.assertEqual(self.w.exp_panel.initial_card.width(), self.fs.px(190))
        self.assertGreater(self.w.exp_panel.initial_card.width(), w100)
        dlg = AddInclusionDialog(self.w, db, pid)
        avail = (dlg.screen() or self.app.primaryScreen()).availableGeometry()
        self.assertLessEqual(dlg.height(), avail.height())
        self.assertLessEqual(dlg.width(), avail.width())
        # кнопки вне прокручиваемой области — видны при любой высоте окна
        self.assertFalse(dlg._scroll_area.widget().isAncestorOf(dlg.add_btn))


@unittest.skipUnless(HAVE_QT, 'PySide6 недоступен')
class TestCarbonicFractionInAddInclusion(unittest.TestCase):
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
        self.pid = self.w.db.add_project('Проект')

    def tearDown(self):
        self.w.close()

    def _dialog(self):
        from fluid_app.gui.experiment import AddInclusionDialog
        dlg = AddInclusionDialog(self.w, self.w.db, self.pid)
        dlg.sample.setEditText('Бр-1')
        return dlg

    def _inc(self, name):
        return self.w.db._one('SELECT * FROM inclusions WHERE name=?', (name,))

    def test_saved_reopened_and_cleared_for_next(self):
        from fluid_app.gui.dialogs import CarbonicFractionDialog
        dlg = self._dialog()
        self.assertEqual(dlg.phi.value.text(), '')
        self.assertEqual(dlg.phi.method.currentText(), '')          # способ оценки заранее не выбран
        dlg.phi.value.setText('30')
        dlg.phi.unc.setText('5')
        dlg.phi.method.setCurrentText('подсчёт площадей')
        dlg.phi.temp.setText('23,5')
        self.assertTrue(dlg._add(True))                              # «Добавить и создать следующее»
        inc = self._inc('1')
        self.assertAlmostEqual(inc['carbonic_fraction'], 0.30)
        self.assertAlmostEqual(inc['carbonic_fraction_unc'], 0.05)
        self.assertEqual(inc['carbonic_fraction_method'], 'подсчёт площадей')
        self.assertEqual(inc['carbonic_fraction_temp_c'], 23.5)
        # поля φ очищены вместе с остальными индивидуальными характеристиками
        for w in (dlg.phi.value, dlg.phi.unc, dlg.phi.temp):
            self.assertEqual(w.text(), '')
        self.assertEqual(dlg.phi.method.currentText(), '')
        self.assertEqual(dlg.sample.currentText(), 'Бр-1')
        self.assertTrue(dlg._add(False))                             # следующее — без φ
        inc2 = self._inc('2')
        self.assertEqual([inc2[k] for k in ('carbonic_fraction', 'carbonic_fraction_unc', 'carbonic_fraction_method',
                                            'carbonic_fraction_temp_c')], [None, None, None, None])
        # повторное открытие тем же диалогом, что и из контекстного меню
        fr = CarbonicFractionDialog(self.w, '1', self.w.db.inclusion(inc['id']))
        self.assertEqual((fr.value.text(), fr.unc.text(), fr.method.currentText(), fr.temp.text()),
                         ('30', '5', 'подсчёт площадей', '23,5'))
        # правка через контекстное меню включения сохраняется прежним способом
        self.w.refresh_all()
        self.w.select_inclusion(inc['id'])

        def fake_exec(d):
            d.value.setText('35')
            d._accept()
            return True
        with mock.patch.object(CarbonicFractionDialog, 'exec', fake_exec):
            self.w.edit_carbonic_fraction()
        self.assertAlmostEqual(self.w.db.inclusion(inc['id'])['carbonic_fraction'], 0.35)
        self.assertAlmostEqual(self.w.db.inclusion(inc['id'])['carbonic_fraction_unc'], 0.05)
        self.assertIn('φ=35%', self.w.tree.currentItem().text(0))

    def test_validation(self):
        dlg = self._dialog()
        for text in ('150', '-1', 'abc'):
            dlg.phi.value.setText(text)
            with mock.patch.object(QMessageBox, 'warning') as warn:
                self.assertFalse(dlg._add(False), text)
            self.assertIn('Доля углекислотной фазы', warn.call_args[0][2])
        dlg.phi.value.setText('30')
        dlg.phi.unc.setText('120')
        with mock.patch.object(QMessageBox, 'warning'):
            self.assertFalse(dlg._add(False))
        # погрешность, способ или температура без самой доли — не сохраняются молча
        dlg.phi.clear()
        dlg.phi.temp.setText('22')
        with mock.patch.object(QMessageBox, 'warning') as warn:
            self.assertFalse(dlg._add(False))
        self.assertIn('без самой доли', warn.call_args[0][2])
        self.assertEqual(self.w.db._all('SELECT * FROM inclusions'), [])    # ничего не создано
        self.assertEqual(self.w.db._all('SELECT * FROM samples'), [])
        dlg.phi.clear()
        dlg.phi.value.setText('0')                                           # граница диапазона
        self.assertTrue(dlg._add(False))
        self.assertEqual(self._inc('1')['carbonic_fraction'], 0.0)
        dlg2 = self._dialog()
        dlg2.phi.value.setText('100')
        self.assertTrue(dlg2._add(False))
        self.assertEqual(self._inc('2')['carbonic_fraction'], 1.0)

    def test_calculation_uses_same_storage(self):
        """φ из диалога включения попадает в расчёт так же, как φ из контекстного меню."""
        from fluid_app import calc
        db = self.w.db
        dlg = self._dialog()
        dlg.phi.value.setText('30')
        dlg.phi.temp.setText('23,5')
        self.assertTrue(dlg._add(False))
        a = self._inc('1')['id']
        sid = self._inc('1')['sample_id']
        b = db.add_inclusion(sid, '2')
        db.set_carbonic_fraction(b, 0.30, None, None, 23.5)
        for inc in (a, b):
            db.add_observation(inc, {'kind': 'Th_CO2', 'temperature_c': 25.0, 'homogenization_to': 'liquid',
                                     'co2_purity_confirmed': True})
            db.add_observation(inc, {'kind': 'Tm_clath', 'temperature_c': 8.0, 'liquid_co2_present': True,
                                     'vapor_co2_present': True, 'aqueous_brine_present': True})
        items = calc.calculate_all(db.observations())
        items += calc.derive_inclusion_results(items)
        by_inc: dict = {}
        for obs, out in items:
            by_inc.setdefault(obs['inclusion_name'], []).append((out.kind, out.status, out.value))
        self.assertEqual(by_inc['1'], by_inc['2'])
        self.assertTrue(any(k == 'bulk_density' and s == 'ok' for k, s, _ in by_inc['1']))


if __name__ == '__main__':
    unittest.main()
