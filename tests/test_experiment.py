"""Ход эксперимента (схема v4): создание включения одним диалогом, сеансы и этапы, синхронизация панели и
таблицы, старые базы, перенос сведений о сеансах через экспорт/импорт. Расчёты не затрагиваются."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from fluid_app import calc, exporter, importer
from fluid_app.db import MIGRATIONS, SCHEMA_VERSION, Database, DatabaseError

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
    HAVE_QT = True
except ImportError:
    HAVE_QT = False


def _tree(db):
    pid = db.add_project('П')
    sid = db.add_sample(pid, 'Бр-1')
    return pid, sid, db.add_inclusion(sid, '1')


class TestExperimentDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.db = Database(self.dir / 'db.sqlite')

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_migration_from_v3_keeps_data_and_leaves_observations_unlinked(self):
        path = self.dir / 'old.sqlite'
        c = sqlite3.connect(path)
        c.executescript(''.join(MIGRATIONS[:3]) + '; PRAGMA user_version = 3;')
        c.executescript("""
            INSERT INTO projects(id, name, created_at) VALUES (1, 'Старый', '2026-01-01');
            INSERT INTO samples(id, project_id, name, created_at) VALUES (1, 1, 'Бр-2', '2026-01-01');
            INSERT INTO inclusions(id, sample_id, name, carbonic_fraction) VALUES (7, 1, '1-1', 0.3);
            INSERT INTO observations(id, inclusion_id, kind, temperature_c, created_at, updated_at)
                VALUES (41, 7, 'Tm_ice', -5.2, 'a', 'b'), (42, 7, 'Th_total', 250, 'a', 'b');
            INSERT INTO calc_runs(id, created_at) VALUES (1, '2026-01-02');
            INSERT INTO results(id, run_id, observation_id, kind, inputs_json, status, value)
                VALUES (5, 1, 41, 'Tm_ice', '{}', 'ok', 8.14);
        """)
        c.commit()
        c.close()
        db = Database(path)
        self.assertEqual(db.schema_version(), SCHEMA_VERSION)
        self.assertTrue(list(self.dir.glob('old.bak-v3-*.sqlite')))            # штатная резервная копия
        rows = {o['id']: o for o in db.observations()}
        self.assertEqual(sorted(rows), [41, 42])
        for o in rows.values():                                              # история опыта не выдумывается
            self.assertIsNone(o['stage_id'])
            self.assertIsNone(o['session_number'])
        inc = db.inclusion(7)
        self.assertEqual(inc['carbonic_fraction'], 0.3)
        self.assertEqual([inc[k] for k in ('initial_liquid', 'initial_vapor', 'initial_solid',
                                           'initial_temperature_c', 'initial_room')], [None, None, None, None, 0])
        self.assertEqual(db.sessions(7), [])
        res = db.results(1)                                                  # прежний результат на месте
        self.assertEqual((res[0]['observation_id'], res[0]['value']), (41, 8.14))
        self.assertEqual(db.conn.execute('PRAGMA foreign_key_check').fetchall(), [])
        out = {o.kind: o for _, o in calc.calculate_all(db.observations())}  # расчёт по старым данным работает
        self.assertEqual(out['Tm_ice'].status, 'ok')
        db.close()

    def test_sessions_stages_and_reopen(self):
        _, _, iid = _tree(self.db)
        s1 = self.db.add_session(iid, '2026-11-16 10:30', 'охлаждение')
        c1 = self.db.add_stage(s1, 'cooling', None, True, -100.0)             # начало — комнатная без значения
        o1 = self.db.add_observation(iid, {'kind': 'Tm_ice', 'temperature_c': -5.2}, c1)
        self.db.set_session_finished(s1, True)
        path = self.db.path
        self.db.close()
        self.db = Database(path)                                             # «перезапуск программы»
        s = self.db.sessions(iid)
        self.assertEqual([(x['number'], x['started_at'], x['finished']) for x in s],
                         [(1, '2026-11-16 10:30', True)])
        st = self.db.stages(s1)[0]
        self.assertEqual((st['direction'], st['start_temperature_c'], st['start_room'], st['end_temperature_c']),
                         ('cooling', None, True, -100.0))                    # 20 °C не подставлено
        s2 = self.db.add_session(iid, '17.11.2026 09:00')                    # другой день — новый сеанс
        h1 = self.db.add_stage(s2, 'heating')                                # температуры неизвестны
        st2 = self.db.stage(h1)
        self.assertEqual((st2['start_temperature_c'], st2['start_room'], st2['end_temperature_c']),
                         (None, False, None))
        o2 = self.db.add_observation(iid, {'kind': 'Th_total', 'temperature_c': 250.0}, h1)
        o3 = self.db.add_observation(iid, {'kind': 'Th_total', 'temperature_c': 251.5}, h1)   # повторное измерение
        obs = {o['id']: o for o in self.db.observations()}
        self.assertEqual((obs[o1]['session_number'], obs[o1]['stage_position'], obs[o1]['stage_direction']),
                         (1, 1, 'cooling'))
        self.assertEqual((obs[o2]['session_number'], obs[o2]['session_started_at']), (2, '2026-11-17 09:00'))
        self.assertEqual(obs[o3]['stage_id'], h1)
        # дата опыта редактируется и отделена от даты ввода
        created = self.db.session(s2)['created_at']
        self.db.update_session(s2, started_at='2026-11-10 08:00', note=None)
        self.assertEqual(self.db.session(s2)['created_at'], created)
        self.assertEqual([x['id'] for x in self.db.sessions(iid)], [s2, s1])  # порядок — по дате опыта
        self.db.update_session(s2, started_at=None, note=None)               # дата может быть не указана
        self.assertIsNone(self.db.session(s2)['started_at'])
        with self.assertRaises(DatabaseError):
            self.db.update_session(s2, started_at='вчера', note=None)
        # правка наблюдения не теряет привязку; удаление этапа не удаляет наблюдения
        self.db.update_observation(o2, {'kind': 'Th_total', 'temperature_c': 252.0})
        self.assertEqual(self.db.observation(o2)['stage_id'], h1)
        self.db.delete_stage(h1)
        self.assertIsNone(self.db.observation(o2)['stage_id'])
        self.assertEqual(len(self.db.observations()), 3)
        self.db.delete_session(s1)
        self.assertIsNone(self.db.observation(o1)['stage_id'])
        self.assertEqual(len(self.db.observations()), 3)

    def test_stage_rules(self):
        pid, sid, iid = _tree(self.db)
        other = self.db.add_inclusion(sid, '2')
        s = self.db.add_session(iid)
        st = self.db.add_stage(s, 'cooling')
        with self.assertRaises(DatabaseError):                               # этап другого включения
            self.db.add_observation(other, {'kind': 'Tm_ice', 'temperature_c': -1.0}, st)
        with self.assertRaises(DatabaseError):
            self.db.add_stage(s, 'sideways')
        with self.assertRaises(DatabaseError):                               # и значение, и «комнатная»
            self.db.add_stage(s, 'heating', 20.0, True)
        with self.assertRaises(DatabaseError):
            self.db.set_initial_state(iid, True, True, None, 20.0, True)
        a, b = self.db.add_stage(s, 'heating'), self.db.add_stage(s, 'cooling')
        self.assertEqual([x['number'] for x in self.db.stages(s)], [1, 2, 3])
        self.db.delete_stage(a)
        self.assertEqual([(x['id'], x['number']) for x in self.db.stages(s)], [(st, 1), (b, 2)])
        oid = self.db.add_observation(iid, {'kind': 'Tm_ice', 'temperature_c': -1.0})
        self.db.set_observation_stage(oid, b)
        self.assertEqual(self.db.observation(oid)['stage_id'], b)
        self.db.delete('inclusions', iid)                                    # каскад: сеансы и этапы включения
        self.assertEqual(self.db._all('SELECT * FROM sessions'), [])
        self.assertEqual(self.db._all('SELECT * FROM stages'), [])

    def test_next_inclusion_name(self):
        pid, sid, _ = _tree(self.db)
        self.assertEqual(self.db.next_inclusion_name(None), '1')
        self.assertEqual(self.db.next_inclusion_name(sid), '2')
        self.db.add_inclusion(sid, '7')
        self.db.add_inclusion(sid, '1-а')
        self.assertEqual(self.db.next_inclusion_name(sid), '8')

    def test_calculation_ignores_experiment_structure(self):
        _, sid, iid = _tree(self.db)
        other = self.db.add_inclusion(sid, '2')
        for inc in (iid, other):
            self.db.add_observation(inc, {'kind': 'Tm_ice', 'temperature_c': -5.2})
            self.db.add_observation(inc, {'kind': 'Th_total', 'temperature_c': 250.0, 'homogenization_to': 'liquid'})
        s = self.db.add_session(iid, '2026-11-16 10:00')
        st = self.db.add_stage(s, 'cooling', 25.0, False, -100.0)
        for o in self.db.observations('inclusion_id=?', (iid,)):
            self.db.set_observation_stage(o['id'], st)
        self.db.set_initial_state(iid, True, True, False, None, True)
        items = calc.calculate_all(self.db.observations())
        items += calc.derive_inclusion_results(items)
        by_inc: dict = {}
        for obs, out in items:
            by_inc.setdefault(obs['inclusion_name'], []).append((out.kind, out.status, out.value, out.message))
        self.assertEqual(by_inc['1'], by_inc['2'])      # привязка к этапу и исходное состояние на расчёт не влияют
        self.assertTrue(any(k == 'aq_pvt' and s == 'ok' for k, s, _, _ in by_inc['1']))

    def test_export_import_keeps_sessions_and_stages(self):
        pid, sid, iid = _tree(self.db)
        self.db.set_initial_state(iid, True, True, None, None, True)
        self.db.set_inclusion_note(iid, 'у края зерна')
        s1 = self.db.add_session(iid, '2026-11-16 10:30', 'первый день')
        c1 = self.db.add_stage(s1, 'cooling', None, True, -100.0, 'быстро')
        h1 = self.db.add_stage(s1, 'heating', -100.0, False, None)
        self.db.set_session_finished(s1, True)
        s2 = self.db.add_session(iid, None)
        h2 = self.db.add_stage(s2, 'heating')
        self.db.add_observation(iid, {'kind': 'Te', 'temperature_c': -21.5}, h1)
        self.db.add_observation(iid, {'kind': 'Tm_ice', 'temperature_c': -5.2}, h1)
        self.db.add_observation(iid, {'kind': 'Tm_ice', 'temperature_c': -5.3}, h1)       # повтор
        self.db.add_observation(iid, {'kind': 'Th_total', 'temperature_c': 250.0}, h2)
        self.db.add_observation(iid, {'kind': 'Th_total', 'temperature_c': 249.0})        # без привязки
        out = exporter.export_observations_csv(self.dir / 'obs.csv', self.db.observations())
        t = importer.read_table(out)
        parsed = importer.parse_rows(t, importer.auto_mapping(t.headers))
        self.assertTrue(all(p.ok for p in parsed), [p.errors for p in parsed])
        db2 = Database(self.dir / 'new.sqlite')
        rep = importer.import_rows(db2, db2.add_project('Новый'), parsed, source='obs.csv')
        self.assertEqual((rep.n_observations, rep.n_errors), (5, 0))

        def picture(db):
            return sorted((o['kind'], o['temperature_c'], o['session_number'], o['session_started_at'],
                           o['session_note'], o['session_finished'], o['stage_position'], o['stage_direction'],
                           o['stage_start_c'], o['stage_start_room'], o['stage_end_c'], o['stage_note'],
                           o['initial_liquid'], o['initial_vapor'], o['initial_solid'], o['initial_temperature_c'],
                           o['initial_room'], o['inclusion_note']) for o in db.observations())
        self.assertEqual(picture(db2), picture(self.db))
        inc2 = db2.observations()[0]['inclusion_id']
        self.assertEqual(len(db2.sessions(inc2)), 2)
        # этап охлаждения без наблюдений в таблицу измерений не попадает — нумерация этапов при этом сохранена
        self.assertEqual([x['number'] for x in db2.stages(db2.sessions(inc2)[0]['id'])], [2])
        # повторный импорт того же файла не создаёт ни дубликатов наблюдений, ни новых сеансов и этапов
        rep = importer.import_rows(db2, 1, parsed, source='obs.csv')
        self.assertEqual((rep.n_observations, rep.n_duplicates), (0, 5))
        self.assertEqual(len(db2.sessions(inc2)), 2)
        self.assertEqual(len(db2._all('SELECT * FROM stages')), 2)
        # полная выгрузка базы содержит листы сеансов и этапов (включая этапы без наблюдений)
        from openpyxl import load_workbook
        wb = load_workbook(exporter.export_database_xlsx(self.db, self.dir / 'dump.xlsx'))
        self.assertIn('sessions', wb.sheetnames)
        self.assertEqual(wb['stages'].max_row, 1 + 3)
        db2.close()

    def test_old_format_file_imports_without_sessions(self):
        t = importer.read_table(Path(__file__).resolve().parent.parent / 'examples' / 'example_input.csv')
        parsed = importer.parse_rows(t, importer.auto_mapping(t.headers))
        pid = self.db.add_project('Пример')
        rep = importer.import_rows(self.db, pid, parsed, source='x')
        self.assertGreater(rep.n_observations, 0)
        self.assertTrue(all(o['stage_id'] is None for o in self.db.observations()))
        self.assertEqual(self.db._all('SELECT * FROM sessions'), [])


@unittest.skipUnless(HAVE_QT, 'PySide6 недоступен')
class TestExperimentGui(unittest.TestCase):
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

    # --- вспомогательное: «ответы пользователя» в модальных диалогах -----------------
    def _observation(self, kind, text):
        """Подмена exec() существующего диалога наблюдения: заполнить и сохранить."""
        from fluid_app.gui.dialogs import ObservationDialog

        def fake_exec(dlg):
            dlg.kind.setCurrentIndex(dlg.kind.findData(kind))
            dlg.temperature.setText(text)
            dlg._accept()
            return dlg.result is not None
        return mock.patch.object(ObservationDialog, 'exec', fake_exec)

    def _table_ids(self):
        from fluid_app.gui.main_window import ROLE
        t = self.w.obs_table
        return sorted(t.item(r, 0).data(ROLE) for r in range(t.rowCount()))

    def _panel_ids(self):
        p = self.w.exp_panel
        ids = [b.obs_id for tl in p.timelines.values() for b in tl.marks] + [b.obs_id for b in p.unlinked_marks]
        return sorted(ids)

    def test_add_inclusion_dialog(self):
        from fluid_app.gui.experiment import AddInclusionDialog
        w = self.w
        pid = w.db.add_project('Проект')
        dlg = AddInclusionDialog(w, w.db, pid)
        self.assertEqual(dlg.number.text(), '1')                             # предложен свободный номер
        dlg.sample.setEditText('Бр-1')                                       # новый образец вводом имени
        dlg.mineral.setEditText('кварц')
        dlg.fia.setEditText('А')
        self.assertIn('совместно образованных', dlg.fia.toolTip())
        dlg.state.liquid.setChecked(True)
        dlg.state.vapor.setChecked(True)
        self.assertEqual((dlg.state.sketch.liquid, dlg.state.sketch.vapor, dlg.state.sketch.solid),
                         (True, True, False))                                # схема следует за галочками
        dlg.state.t_room.setChecked(True)
        dlg.note.setText('у края')
        self.assertTrue(dlg._add(True))                                      # «Добавить и создать следующее»
        self.assertEqual(dlg.result(), 0)                                    # окно не закрыто (не «принято»)
        self.assertEqual((dlg.sample.currentText(), dlg.mineral.currentText(), dlg.fia.currentText()),
                         ('Бр-1', 'кварц', 'А'))                             # образец, минерал и группа сохранены
        self.assertEqual(dlg.number.text(), '2')
        self.assertFalse(dlg.state.liquid.isChecked())
        self.assertEqual(dlg.note.text(), '')
        dlg.state.solid.setChecked(True)
        dlg.state.temperature.setText('22,5')
        dlg.state.t_value.setChecked(True)
        self.assertTrue(dlg._add(False))
        # повторное добавление того же номера отклоняется, узлы дерева не дублируются
        dlg2 = AddInclusionDialog(w, w.db, pid, 'Бр-1', 'кварц', 'А')
        self.assertEqual(dlg2.number.text(), '3')
        dlg2.number.setText('2')
        dlg2._number_edited('2')
        with mock.patch.object(QMessageBox, 'warning') as warn:
            self.assertFalse(dlg2._add(False))
        self.assertIn('уже есть', warn.call_args[0][2])
        dlg2.number.setText('3')
        self.assertTrue(dlg2._add(False))
        db = w.db
        self.assertEqual([len(db._all(f'SELECT * FROM {t}')) for t in ('samples', 'minerals', 'fias', 'inclusions')],
                         [1, 1, 1, 3])
        incs = {r['name']: r for r in db._all('SELECT * FROM inclusions')}
        self.assertEqual([incs['1'][k] for k in ('initial_liquid', 'initial_vapor', 'initial_solid',
                                                 'initial_temperature_c', 'initial_room', 'description')],
                         [1, 1, 0, None, 1, 'у края'])                       # комнатная — без числа
        self.assertEqual([incs['2'][k] for k in ('initial_liquid', 'initial_vapor', 'initial_solid',
                                                 'initial_temperature_c', 'initial_room')], [0, 0, 1, 22.5, 0])
        self.assertEqual([incs['3'][k] for k in ('initial_liquid', 'initial_vapor', 'initial_solid',
                                                 'initial_temperature_c', 'initial_room')], [None, None, None, None, 0])
        self.assertIsNotNone(incs['1']['fia_id'])
        self.assertEqual(db._all('SELECT * FROM observations'), [])          # фазы не создают наблюдений
        w.refresh_all()
        self.assertTrue(w.select_inclusion(incs['2']['id']))
        self.assertEqual(w.exp_panel.inclusion_id, incs['2']['id'])

    def test_panel_and_table_show_the_same_records(self):
        from fluid_app.gui.experiment import AssignStageDialog, SessionDialog, StageDialog
        w = self.w
        pid = w.db.add_project('Проект')
        sid = w.db.add_sample(pid, 'Бр-1')
        iid = w.db.add_inclusion(sid, '1')
        old = w.db.add_observation(iid, {'kind': 'Te', 'temperature_c': -21.0})      # «старое» наблюдение
        w.refresh_all()
        w.select_inclusion(iid)
        panel = w.exp_panel
        self.assertTrue(panel.has_body())
        self.assertEqual([b.obs_id for b in panel.unlinked_marks], [old])            # «Без привязки к сеансу»
        self.assertEqual(panel.timelines, {})

        def session_exec(dlg):
            dlg.date.setDateTime(dlg.date.dateTime().fromString('2026-11-16 10:30', 'yyyy-MM-dd HH:mm'))
            dlg._accept()
            return True

        def stage_exec(dlg):
            dlg.end.setText('-100')
            dlg.s_room.setChecked(True)
            dlg._accept()
            return True
        with mock.patch.object(SessionDialog, 'exec', session_exec):
            s1 = panel.new_session()
        with mock.patch.object(StageDialog, 'exec', stage_exec):
            c1 = panel.new_stage(s1, 'cooling')
        st = w.db.stage(c1)
        self.assertEqual((st['direction'], st['start_room'], st['start_temperature_c'], st['end_temperature_c']),
                         ('cooling', True, None, -100.0))
        # «Добавить наблюдение» на карточке этапа открывает существующий диалог наблюдения
        with self._observation('Tm_ice', '-5,2'):
            panel.stage_cards[c1].add_button.click()
        with self._observation('Tm_clath', '7,5'):
            panel.stage_cards[c1].add_button.click()
        with self._observation('Tm_ice', '-5,3'):                                    # повтор того же перехода
            panel.stage_cards[c1].add_button.click()
        self.assertEqual(len(w.db.observations()), 4)                               # копий нет
        self.assertEqual(self._table_ids(), self._panel_ids())
        temps = [w.db.observation(b.obs_id)['temperature_c'] for b in panel.timelines[c1].marks]
        self.assertEqual(temps, [7.5, -5.2, -5.3])                                   # сверху теплее
        # таблица показывает сеанс и этап тех же записей
        t = w.obs_table
        cells = {t.item(r, 0).data(0x0100): (t.item(r, 17).text(), t.item(r, 18).text()) for r in range(t.rowCount())}
        self.assertEqual(cells[old], ('—', '—'))
        self.assertEqual({v for k, v in cells.items() if k != old}, {('1 · 16.11.2026 10:30', '1 · охлаждение')})
        # щелчок по отметке — правка существующим диалогом; изменение видно в обоих представлениях
        mark = panel.timelines[c1].marks[1]
        oid = mark.obs_id
        with self._observation('Tm_ice', '-5,6'):
            mark.click()
        self.assertEqual(w.db.observation(oid)['temperature_c'], -5.6)
        self.assertEqual(w.db.observation(oid)['stage_id'], c1)
        self.assertIn('−5,6', [b.text() for b in panel.timelines[c1].marks][-1])
        row = next(r for r in range(t.rowCount()) if t.item(r, 0).data(0x0100) == oid)
        self.assertEqual(t.item(row, 6).sort_value, -5.6)
        # правка из таблицы видна на схеме
        t.selectRow(row)
        with self._observation('Tm_ice', '-5,9'):
            w.edit_observation()
        self.assertTrue(any('−5,9' in b.text() for b in w.exp_panel.timelines[c1].marks))
        # ручная привязка старого наблюдения
        with mock.patch.object(AssignStageDialog, 'exec', lambda d: (d._accept(), True)[1]):
            w.assign_observations([old])
        self.assertEqual(w.db.observation(old)['stage_id'], c1)
        self.assertEqual(panel.unlinked_marks, [])
        # удаление из схемы удаляет строку таблицы
        with mock.patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            panel.delete_requested.emit(old)
        self.assertIsNone(w.db.observation(old))
        self.assertEqual(self._table_ids(), self._panel_ids())
        self.assertEqual(len(self._table_ids()), 3)
        # обычный табличный ввод без этапа по-прежнему работает
        with self._observation('Th_total', '250'):
            w.add_observation()
        self.assertEqual(len(panel.unlinked_marks), 1)
        self.assertEqual(self._table_ids(), self._panel_ids())
        # завершить сеанс; после перезапуска — нагревание другим днём
        panel.finish_session(s1, True)
        w.close()
        from fluid_app.gui.main_window import MainWindow
        self.w = w = MainWindow(str(self.dbpath))
        w.select_inclusion(iid)
        panel = w.exp_panel
        self.assertEqual(sorted(panel.timelines), [c1])
        self.assertTrue(w.db.session(s1)['finished'])

        def session2_exec(dlg):
            dlg.date.setDateTime(dlg.date.dateTime().fromString('2026-11-17 09:15', 'yyyy-MM-dd HH:mm'))
            dlg.note.setText('нагревание')
            dlg._accept()
            return True
        with mock.patch.object(SessionDialog, 'exec', session2_exec):
            s2 = panel.new_session()
        with mock.patch.object(StageDialog, 'exec', lambda d: (d._accept(), True)[1]):
            h1 = panel.new_stage(s2, 'heating')
        st = w.db.stage(h1)
        self.assertEqual((st['direction'], st['start_temperature_c'], st['start_room'], st['end_temperature_c']),
                         ('heating', None, False, None))                             # ничего не подставлено
        with self._observation('Th_total', '251'):
            panel.stage_cards[h1].add_button.click()
        self.assertEqual([s['started_at'] for s in w.db.sessions(iid)], ['2026-11-16 10:30', '2026-11-17 09:15'])
        self.assertEqual(self._table_ids(), self._panel_ids())
        # расчёт допускает повторные измерения по-прежнему: предупреждение/отказ ядра не изменены
        w.calculate(selected_only=False)
        w.wait_for_calculation()
        self.assertEqual(w._run['n_total'], len(w._results))
        self.assertTrue(any(r['kind'] == 'Tm_ice' and r['status'] == 'ok' for r in w._results))

    def test_panel_collapse_and_no_inclusion(self):
        w = self.w
        pid = w.db.add_project('Проект')
        sid = w.db.add_sample(pid, 'Бр-1')
        iid = w.db.add_inclusion(sid, '1')
        w.refresh_all()
        panel = w.exp_panel
        self.assertFalse(panel.has_body())                    # включение не выбрано — панель занимает одну строку
        self.assertLess(panel.maximumHeight(), 60)
        w.select_inclusion(iid)
        self.assertTrue(panel.has_body())
        self.assertGreater(panel.maximumHeight(), 1000)
        panel.set_expanded(False)
        self.assertLess(panel.maximumHeight(), 60)
        panel.set_expanded(True)
        self.assertTrue(panel.has_body())


if __name__ == '__main__':
    unittest.main()
