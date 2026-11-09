"""Главное окно FluidCalc."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox, QProgressBar,
                               QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QCheckBox)

from .. import APP_TITLE, __version__
from ..calc import Outcome, backend_versions, calculate_observation, passport_lines, format_value
from ..db import Database, DatabaseError
from ..exporter import (export_database_xlsx, export_observations_csv, export_results_csv, export_results_xlsx)
from ..methods import (HOMOGENIZATION, KINDS, METHODS, STATUS_RU, kind_label, methods_html)
from ..paths import default_db_path, log_file_path, project_root
from ..plots import GROUP_BY, PLOT_TYPES, make_figure, save_figure
from .dialogs import ImportDialog, ObservationDialog, TextDialog
from .widgets import HomogCombo, NumberEdit, TriStateCombo, passport_html

log = logging.getLogger(__name__)

ROLE = Qt.UserRole
STATUS_BG = {'ok': '#e2f0d9', 'error': '#f8d7da', 'skipped': '#ededed'}


class CalcWorker(QObject):
    """Расчёт в отдельном потоке: интерфейс не блокируется."""
    progress = Signal(int, int)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, observations: list[dict]):
        super().__init__()
        self.observations = observations

    @Slot()
    def run(self):
        try:
            out = []
            n = len(self.observations)
            for i, obs in enumerate(self.observations, start=1):
                out.append((obs, calculate_observation(obs)))
                if i % 10 == 0 or i == n:
                    self.progress.emit(i, n)
            self.finished.emit(out)
        except Exception as exc:  # noqa: BLE001
            log.exception('Сбой расчёта')
            self.failed.emit(str(exc))


def _flag_text(v):
    return '' if v is None else ('да' if v else 'нет')


class NumItem(QTableWidgetItem):
    """Ячейка с числом: отображение с десятичной запятой, сортировка по значению."""

    def __init__(self, v, digits=2):
        super().__init__('' if v is None else format_value(v, digits))
        self.sort_value = v
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        a = self.sort_value
        b = getattr(other, 'sort_value', None)
        if a is None or b is None:
            return (a is None) and (b is not None)
        return a < b


def _num_item(v, digits=2):
    return NumItem(v, digits)


class MainWindow(QMainWindow):
    def __init__(self, db_path: str | None = None):
        super().__init__()
        self.settings = QSettings('FluidCalc', 'FluidCalc')
        self.db: Database | None = None
        self._thread: QThread | None = None
        self._worker: CalcWorker | None = None
        self._pending_scope: tuple | None = None
        self.setWindowTitle(APP_TITLE)
        self.resize(1400, 860)
        self._build_ui()
        path = db_path or self.settings.value('db_path') or str(default_db_path())
        self.open_database(path)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self._build_actions()
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel('<b>Проекты и объекты</b>'))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Объект', 'Наблюд.'])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setStretchLastSection(False)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        ll.addWidget(self.tree)
        hint = QLabel('Правая кнопка мыши — добавить, переименовать или удалить.')
        hint.setStyleSheet('color:#52514e')
        hint.setWordWrap(True)
        ll.addWidget(hint)
        split.addWidget(left)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_obs_tab(), 'Измерения')
        self.tabs.addTab(self._build_results_tab(), 'Результаты')
        self.tabs.addTab(self._build_plot_tab(), 'Графики')
        self.tabs.addTab(self._build_quick_tab(), 'Быстрый расчёт')
        methods = QTextBrowser()
        methods.setOpenExternalLinks(False)
        methods.setHtml(methods_html())
        self.tabs.addTab(methods, 'Методики и ограничения')
        split.addWidget(self.tabs)
        split.setSizes([320, 1080])
        self.setCentralWidget(split)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setVisible(False)
        self.db_label = QLabel()
        self.statusBar().addWidget(self.db_label, 1)
        self.statusBar().addPermanentWidget(self.progress)

    def _act(self, text, slot, shortcut=None, tip=None):
        a = QAction(text, self)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if tip:
            a.setStatusTip(tip)
        return a

    def _build_actions(self):
        self.a_new_db = self._act('Создать базу…', self.new_database)
        self.a_open_db = self._act('Открыть базу…', self.choose_database, 'Ctrl+O')
        self.a_backup = self._act('Резервная копия базы…', self.backup_database)
        self.a_dump = self._act('Выгрузить всю базу в XLSX…', self.dump_database)
        self.a_import = self._act('Импорт CSV / Excel…', self.import_file, 'Ctrl+I',
                                  'Пакетный импорт измерений с картой полей и предпросмотром')
        self.a_example = self._act('Загрузить пример (examples/example_input.csv)', self.load_example)
        self.a_lab_import = self._act('Импорт лабораторной таблицы («Таблица 1/2/3»)…', self.import_lab_table,
                                      tip='Сводная таблица лаборатории: блоки по образцам с двухстрочной шапкой')
        self.a_lab_compare = self._act('Сверка лабораторной таблицы с расчётом…', self.compare_lab_table,
                                       tip='Пересчёт солёности и проверка плотностей таблицы; отчёт в XLSX')
        self.a_export_obs = self._act('Экспорт таблицы измерений (CSV)…', self.export_observations)
        self.a_export_res = self._act('Экспорт результатов…', self.export_results, 'Ctrl+E')
        self.a_quit = self._act('Выход', self.close, 'Ctrl+Q')
        self.a_calc_sel = self._act('Рассчитать выбранное', lambda: self.calculate(selected_only=True), 'F5',
                                    'Новый расчёт для объекта, выбранного в дереве')
        self.a_calc_all = self._act('Рассчитать всю базу', lambda: self.calculate(selected_only=False), 'Shift+F5')
        self.a_add_obs = self._act('Добавить наблюдение…', self.add_observation, 'Ctrl+N')
        self.a_project = self._act('Новый проект…', self.add_project)
        self.a_log = self._act('Журнал работы', self.show_log)
        self.a_about = self._act('О программе', self.about)

        m = self.menuBar().addMenu('&Файл')
        for a in (self.a_new_db, self.a_open_db, None, self.a_import, self.a_lab_import, self.a_lab_compare,
                  self.a_example, None, self.a_export_obs,
                  self.a_export_res, None, self.a_backup, self.a_dump, None, self.a_quit):
            m.addSeparator() if a is None else m.addAction(a)
        m = self.menuBar().addMenu('&Данные')
        for a in (self.a_project, self.a_add_obs):
            m.addAction(a)
        m = self.menuBar().addMenu('&Расчёт')
        m.addAction(self.a_calc_sel)
        m.addAction(self.a_calc_all)
        m = self.menuBar().addMenu('&Справка')
        m.addAction(self._act('Методики, источники и ограничения', lambda: self.tabs.setCurrentIndex(4)))
        m.addAction(self.a_log)
        m.addAction(self.a_about)
        tb = self.addToolBar('Основные действия')
        tb.setObjectName('main_toolbar')
        for a in (self.a_project, self.a_add_obs, self.a_import, self.a_calc_sel, self.a_calc_all,
                  self.a_export_res):
            tb.addAction(a)

    def _build_obs_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.obs_caption = QLabel()
        lay.addWidget(self.obs_caption)
        self.obs_cols = ['ID', 'Образец', 'Минерал', 'FIA', 'Включение', 'Тип', 'T, °C', '±, °C',
                         'Гомогенизация', 'Жидк. CO₂', 'Газ. CO₂', 'Раствор', 'Чистая CO₂', 'Фазы',
                         'Комментарий', 'Источник']
        self.obs_table = QTableWidget(0, len(self.obs_cols))
        self.obs_table.setHorizontalHeaderLabels(self.obs_cols)
        self.obs_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.obs_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.obs_table.setSortingEnabled(True)
        self.obs_table.doubleClicked.connect(self.edit_observation)
        lay.addWidget(self.obs_table)
        row = QHBoxLayout()
        for text, slot in (('Добавить…', self.add_observation), ('Изменить…', self.edit_observation),
                           ('Удалить', self.delete_observations)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        b = QPushButton('Рассчитать выбранное (F5)')
        b.clicked.connect(lambda: self.calculate(selected_only=True))
        row.addWidget(b)
        lay.addLayout(row)
        return w

    def _build_results_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        top = QHBoxLayout()
        top.addWidget(QLabel('Расчёт:'))
        self.run_combo = QComboBox()
        self.run_combo.setMinimumWidth(520)
        self.run_combo.currentIndexChanged.connect(self.show_run)
        top.addWidget(self.run_combo)
        top.addWidget(QLabel('Статус:'))
        self.status_filter = QComboBox()
        self.status_filter.addItem('все', None)
        for k, v in STATUS_RU.items():
            self.status_filter.addItem(v, k)
        self.status_filter.currentIndexChanged.connect(self.show_run)
        top.addWidget(self.status_filter)
        top.addStretch()
        b = QPushButton('Экспорт…')
        b.clicked.connect(self.export_results)
        top.addWidget(b)
        lay.addLayout(top)
        self.run_info = QLabel()
        self.run_info.setWordWrap(True)
        self.run_info.setStyleSheet('color:#52514e')
        lay.addWidget(self.run_info)
        split = QSplitter(Qt.Vertical)
        self.res_cols = ['Образец', 'Минерал', 'FIA', 'Включение', 'Наблюдение', 'T, °C', 'Статус',
                         'Результат', 'Значение', 'Ед.', 'P_sat CO₂, бар', 'Методика', 'Причина / примечание']
        self.res_table = QTableWidget(0, len(self.res_cols))
        self.res_table.setHorizontalHeaderLabels(self.res_cols)
        self.res_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.res_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.res_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.res_table.setSortingEnabled(True)
        self.res_table.itemSelectionChanged.connect(self._show_passport)
        split.addWidget(self.res_table)
        self.passport = QTextBrowser()
        self.passport.setHtml('<p>Выберите строку результата, чтобы увидеть паспорт: входные данные, '
                              'методику, источник, допущения, ограничения и версии программ.</p>')
        split.addWidget(self.passport)
        split.setSizes([480, 300])
        lay.addWidget(split)
        self._results: list[dict] = []
        self._run: dict | None = None
        return w

    def _build_plot_tab(self):
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        w = QWidget()
        lay = QVBoxLayout(w)
        top = QHBoxLayout()
        self.plot_type = QComboBox()
        for k, v in PLOT_TYPES.items():
            self.plot_type.addItem(v, k)
        self.plot_group = QComboBox()
        for k, v in GROUP_BY.items():
            self.plot_group.addItem(v, k)
        for wdg, lbl in ((self.plot_type, 'График:'), (self.plot_group, 'Группировка:')):
            top.addWidget(QLabel(lbl))
            top.addWidget(wdg)
            wdg.currentIndexChanged.connect(self.update_plot)
        top.addStretch()
        b = QPushButton('Сохранить PNG / SVG…')
        b.clicked.connect(self.save_plot)
        top.addWidget(b)
        lay.addLayout(top)
        note = QLabel('Данные — из расчёта, выбранного на вкладке «Результаты». Графики не содержат '
                      'интерпретаций (полей, трендов, изохор).')
        note.setStyleSheet('color:#52514e')
        lay.addWidget(note)
        self._figure = make_figure('th_salinity', [])
        self.canvas = FigureCanvasQTAgg(self._figure)
        lay.addWidget(self.canvas, 1)
        self._canvas_cls = FigureCanvasQTAgg
        self._plot_layout = lay
        return w

    def _build_quick_tab(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        left = QWidget()
        form = QFormLayout(left)
        self.q_kind = QComboBox()
        for k in ('Tm_ice', 'Tm_clath', 'Th_CO2'):
            self.q_kind.addItem(f'{KINDS[k][0]} — {METHODS[_method(k)]["title"]}', k)
        self.q_t = NumberEdit(placeholder='°C')
        self.q_u = NumberEdit(placeholder='±°C, необязательно')
        self.q_h = HomogCombo()
        self.q_l = TriStateCombo()
        self.q_v = TriStateCombo()
        self.q_b = TriStateCombo()
        self.q_p = QCheckBox('Принимаю приближение чистой CO₂')
        form.addRow('Наблюдение', self.q_kind)
        form.addRow('Температура, °C', self.q_t)
        form.addRow('Погрешность ±, °C', self.q_u)
        form.addRow('Гомогенизация CO₂', self.q_h)
        form.addRow('Жидкая CO₂', self.q_l)
        form.addRow('Газовая CO₂', self.q_v)
        form.addRow('Водный раствор', self.q_b)
        form.addRow('', self.q_p)
        b = QPushButton('Рассчитать')
        b.clicked.connect(self.quick_calc)
        self.q_t.returnPressed.connect(self.quick_calc)
        form.addRow('', b)
        note = QLabel('Быстрый расчёт не сохраняется в базе. Для журнала используйте вкладку «Измерения».')
        note.setWordWrap(True)
        note.setStyleSheet('color:#52514e')
        form.addRow(note)
        self.q_kind.currentIndexChanged.connect(self._quick_enabled)
        left.setMaximumWidth(460)
        lay.addWidget(left)
        self.q_out = QTextBrowser()
        lay.addWidget(self.q_out, 1)
        self._quick_enabled()
        return w

    # ------------------------------------------------------------------ база
    def open_database(self, path: str) -> bool:
        try:
            db = Database(path)
        except (DatabaseError, Exception) as exc:  # noqa: BLE001
            log.exception('Не удалось открыть базу %s', path)
            QMessageBox.critical(self, 'База данных', f'Не удалось открыть базу\n{path}\n\n{exc}')
            return False
        if self.db:
            self.db.close()
        self.db = db
        self.settings.setValue('db_path', str(path))
        self.db_label.setText(f'База: {path}   (схема v{db.schema_version()})')
        log.info('Открыта база %s', path)
        self.refresh_all()
        return True

    def new_database(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Создать базу', str(Path.home() / 'fluidcalc.sqlite'),
                                              'База FluidCalc (*.sqlite)')
        if path:
            if not path.endswith('.sqlite'):
                path += '.sqlite'
            if Path(path).exists():
                QMessageBox.warning(self, 'База', 'Файл уже существует — откройте его через «Открыть базу».')
                return
            self.open_database(path)

    def choose_database(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Открыть базу', str(Path(self.db.path).parent if self.db else Path.home()),
                                              'База FluidCalc (*.sqlite);;Все файлы (*)')
        if path:
            self.open_database(path)

    def backup_database(self):
        from datetime import datetime
        name = f'{self.db.path.stem}-копия-{datetime.now():%Y%m%d-%H%M}.sqlite'
        path, _ = QFileDialog.getSaveFileName(self, 'Резервная копия', str(self.db.path.parent / name),
                                              'База FluidCalc (*.sqlite)')
        if path:
            try:
                self.db.backup_to(path)
                QMessageBox.information(self, 'Резервная копия', f'Сохранено:\n{path}')
            except (DatabaseError, OSError) as exc:
                QMessageBox.critical(self, 'Резервная копия', str(exc))

    def dump_database(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Выгрузка базы', str(Path.home() / 'fluidcalc-выгрузка.xlsx'),
                                              'Excel (*.xlsx)')
        if path:
            if not path.lower().endswith('.xlsx'):
                path += '.xlsx'
            try:
                export_database_xlsx(self.db, path)
                QMessageBox.information(self, 'Выгрузка', f'Сохранено:\n{path}')
            except OSError as exc:
                QMessageBox.critical(self, 'Выгрузка', str(exc))

    # ------------------------------------------------------------------ дерево
    def refresh_all(self, keep_run: int | None = None):
        self.refresh_tree()
        self.refresh_observations()
        self.refresh_runs(keep_run)

    def refresh_tree(self):
        sel = self.selected_node()
        sel_key = (sel['level'], sel['id'], sel.get('mineral_id')) if sel else None
        expanded = set()
        it = self.tree.invisibleRootItem()
        stack = [it.child(i) for i in range(it.childCount())]
        while stack:
            x = stack.pop()
            d = x.data(0, ROLE)
            if x.isExpanded():
                expanded.add((d['level'], d['id'], d.get('mineral_id')))
            stack += [x.child(i) for i in range(x.childCount())]
        self.tree.blockSignals(True)
        self.tree.clear()
        counts = {r['inclusion_id']: r['n'] for r in self.db._all(
            'SELECT inclusion_id, COUNT(*) AS n FROM observations GROUP BY inclusion_id')}
        to_select = None

        def node(parent, text, data, n=None):
            nonlocal to_select
            item = QTreeWidgetItem(parent, [text, '' if n is None else str(n)])
            item.setData(0, ROLE, data)
            key = (data['level'], data['id'], data.get('mineral_id'))
            if key in expanded:
                item.setExpanded(True)
            if key == sel_key:
                to_select = item
            return item

        def add_inclusions(parent, sample_id, mineral_id, fia_id, base):
            total = 0
            for inc in self.db.inclusions(sample_id, mineral_id, fia_id):
                n = counts.get(inc['id'], 0)
                total += n
                label = inc['name'] + (f'  [{inc["inclusion_type"]}]' if inc['inclusion_type'] else '')
                node(parent, label, dict(base, level='inclusion', id=inc['id'], name=inc['name']), n)
            return total

        def add_mineral_level(parent, sample_id, mineral_id, base):
            total = 0
            for f in self.db.fias(sample_id, mineral_id):
                fi = node(parent, f'FIA {f["name"]}', dict(base, level='fia', id=f['id'], name=f['name'],
                                                           fia_id=f['id']))
                n = add_inclusions(fi, sample_id, mineral_id, f['id'], dict(base, fia_id=f['id']))
                fi.setText(1, str(n))
                total += n
            total += add_inclusions(parent, sample_id, mineral_id, None, dict(base, fia_id=None))
            return total

        for p in self.db.projects():
            pi = node(self.tree, p['name'], dict(level='project', id=p['id'], name=p['name'], project_id=p['id']))
            ptotal = 0
            for s in self.db.samples(p['id']):
                base = dict(project_id=p['id'], sample_id=s['id'])
                si = node(pi, f'Образец {s["name"]}', dict(base, level='sample', id=s['id'], name=s['name']))
                stotal = 0
                for m in self.db.minerals(s['id']):
                    mb = dict(base, mineral_id=m['id'])
                    mi = node(si, m['name'], dict(mb, level='mineral', id=m['id'], name=m['name']))
                    n = add_mineral_level(mi, s['id'], m['id'], mb)
                    mi.setText(1, str(n))
                    stotal += n
                has_unassigned = (self.db.fias(s['id'], None) or self.db.inclusions(s['id'], None, None))
                if has_unassigned:
                    nb = dict(base, mineral_id=None)
                    ni = node(si, '(минерал не указан)', dict(nb, level='mineral_none', id=s['id'], name=''))
                    ni.setForeground(0, QColor('#52514e'))
                    n = add_mineral_level(ni, s['id'], None, nb)
                    ni.setText(1, str(n))
                    stotal += n
                si.setText(1, str(stotal))
                ptotal += stotal
            pi.setText(1, str(ptotal))
            if not expanded:
                pi.setExpanded(True)
        self.tree.blockSignals(False)
        if to_select:
            self.tree.setCurrentItem(to_select)

    def selected_node(self) -> dict | None:
        items = self.tree.selectedItems() if hasattr(self, 'tree') else []
        return items[0].data(0, ROLE) if items else None

    def _selection_filter(self) -> tuple[str, tuple, str]:
        """SQL-условие для наблюдений выбранного узла и его подпись."""
        n = self.selected_node()
        if not n:
            return '1', (), 'вся база'
        lvl = n['level']
        if lvl == 'project':
            return 'project_id=?', (n['id'],), f'проект «{n["name"]}»'
        if lvl == 'sample':
            return 'sample_id=?', (n['id'],), f'образец {n["name"]}'
        if lvl == 'mineral':
            return 'mineral_id=?', (n['id'],), f'минерал {n["name"]}'
        if lvl == 'mineral_none':
            return 'sample_id=? AND mineral_id IS NULL', (n['sample_id'],), 'включения без минерала'
        if lvl == 'fia':
            return 'fia_id=?', (n['id'],), f'FIA {n["name"]}'
        return 'inclusion_id=?', (n['id'],), f'включение {n["name"]}'

    def _on_tree_selection(self):
        self.refresh_observations()

    def _tree_menu(self, pos):
        n = self.selected_node()
        menu = QMenu(self)
        menu.addAction('Новый проект…', self.add_project)
        if n:
            lvl = n['level']
            menu.addAction('Добавить образец…', self.add_sample)
            if lvl in ('sample', 'mineral', 'mineral_none', 'fia', 'inclusion'):
                menu.addAction('Добавить минерал…', self.add_mineral)
                menu.addAction('Добавить FIA…', self.add_fia)
                menu.addAction('Добавить включение…', self.add_inclusion)
            if lvl == 'inclusion':
                menu.addAction('Добавить наблюдение…', self.add_observation)
            menu.addSeparator()
            menu.addAction('Рассчитать выбранное', lambda: self.calculate(True))
            if lvl != 'mineral_none':
                menu.addSeparator()
                menu.addAction('Переименовать…', self.rename_node)
                menu.addAction('Удалить…', self.delete_node)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _ask_name(self, title, label, text=''):
        name, ok = QInputDialog.getText(self, title, label, text=text)
        return name.strip() if ok and name.strip() else None

    def _guard(self, fn, *args):
        try:
            return fn(*args)
        except DatabaseError as exc:
            QMessageBox.warning(self, 'Данные', str(exc))
        except Exception as exc:  # sqlite3.IntegrityError и др.
            log.exception('Ошибка операции с базой')
            QMessageBox.warning(self, 'Данные', f'Операция не выполнена: {exc}')
        return None

    def add_project(self):
        name = self._ask_name('Новый проект', 'Название проекта:')
        if name and self._guard(self.db.add_project, name):
            self.refresh_all()

    def _need(self, levels, msg):
        n = self.selected_node()
        if not n or n['level'] not in levels:
            QMessageBox.information(self, 'Выбор объекта', msg)
            return None
        return n

    def add_sample(self):
        n = self._need(('project', 'sample', 'mineral', 'mineral_none', 'fia', 'inclusion'),
                       'Выберите проект в дереве.')
        if n:
            name = self._ask_name('Новый образец', 'Название (номер) образца:')
            if name and self._guard(self.db.add_sample, n['project_id'], name):
                self.refresh_tree()

    def add_mineral(self):
        n = self._need(('sample', 'mineral', 'mineral_none', 'fia', 'inclusion'), 'Выберите образец в дереве.')
        if n:
            name = self._ask_name('Новый минерал', 'Минерал-хозяин (напр. кварц):')
            if name and self._guard(self.db.add_mineral, n['sample_id'], name):
                self.refresh_tree()

    def add_fia(self):
        n = self._need(('sample', 'mineral', 'mineral_none', 'fia', 'inclusion'),
                       'Выберите образец или минерал в дереве.')
        if n:
            name = self._ask_name('Новая FIA', 'Название ассоциации включений (FIA):')
            if name and self._guard(self.db.add_fia, n['sample_id'], n.get('mineral_id'), name):
                self.refresh_tree()

    def add_inclusion(self):
        n = self._need(('sample', 'mineral', 'mineral_none', 'fia', 'inclusion'),
                       'Выберите образец, минерал или FIA в дереве.')
        if n:
            name = self._ask_name('Новое включение', 'Номер включения:')
            if name:
                itype = self._ask_name('Тип включения', 'Тип включения (необязательно, напр. L+V, L+V+Lco2):') or ''
                if self._guard(self.db.add_inclusion, n['sample_id'], name, n.get('mineral_id'),
                               n.get('fia_id'), itype):
                    self.refresh_tree()

    _TABLES = {'project': 'projects', 'sample': 'samples', 'mineral': 'minerals', 'fia': 'fias',
               'inclusion': 'inclusions'}

    def rename_node(self):
        n = self.selected_node()
        if not n or n['level'] not in self._TABLES:
            return
        name = self._ask_name('Переименовать', 'Новое название:', n['name'])
        if name and name != n['name']:
            self._guard(self.db.rename, self._TABLES[n['level']], n['id'], name)
            self.refresh_all()

    def delete_node(self):
        n = self.selected_node()
        if not n or n['level'] not in self._TABLES:
            return
        where, args, label = self._selection_filter()
        cnt = self.db.count_observations(where, args)
        if QMessageBox.question(self, 'Удаление', f'Удалить {label} со всеми вложенными объектами и '
                                f'{cnt} наблюдениями?\nСохранённые расчёты останутся в истории.') \
                != QMessageBox.Yes:
            return
        self._guard(self.db.delete, self._TABLES[n['level']], n['id'])
        self.tree.clearSelection()
        self.refresh_all()

    # ------------------------------------------------------------------ наблюдения
    def refresh_observations(self):
        if not self.db:
            return
        where, args, label = self._selection_filter()
        obs = self.db.observations(where, args)
        self.obs_caption.setText(f'Наблюдения: {label} — {len(obs)}')
        t = self.obs_table
        t.setSortingEnabled(False)
        t.setRowCount(len(obs))
        for r, o in enumerate(obs):
            vals = [None, o['sample_name'], o['mineral_name'] or '', o['fia_name'] or '', o['inclusion_name'],
                    kind_label(o['kind']), None, None, HOMOGENIZATION.get(o['homogenization_to'], ''),
                    _flag_text(o['liquid_co2_present']), _flag_text(o['vapor_co2_present']),
                    _flag_text(o['aqueous_brine_present']), _flag_text(o['co2_purity_confirmed']),
                    o['phase_notes'] or '', o['comment'] or '', o['source'] or '']
            for c, v in enumerate(vals):
                if c == 0:
                    it = QTableWidgetItem()
                    it.setData(Qt.DisplayRole, o['id'])
                elif c == 6:
                    it = _num_item(o['temperature_c'])
                elif c == 7:
                    it = _num_item(o['uncertainty_c'])
                else:
                    it = QTableWidgetItem(v)
                it.setData(ROLE, o['id'])
                t.setItem(r, c, it)
        t.setSortingEnabled(True)
        t.resizeColumnsToContents()
        for c in (13, 14, 15):
            t.setColumnWidth(c, min(t.columnWidth(c), 220))

    def _selected_obs_ids(self) -> list[int]:
        rows = {i.row() for i in self.obs_table.selectedIndexes()}
        return [self.obs_table.item(r, 0).data(ROLE) for r in sorted(rows)]

    def _inclusion_label(self, inclusion_id: int) -> str:
        r = self.db._one('SELECT i.name, s.name AS s, p.name AS p FROM inclusions i JOIN samples s ON s.id=i.sample_id '
                         'JOIN projects p ON p.id=s.project_id WHERE i.id=?', (inclusion_id,))
        return f'{r["p"]} → образец {r["s"]} → {r["name"]}'

    def add_observation(self):
        n = self.selected_node()
        inc_id = n['id'] if n and n['level'] == 'inclusion' else None
        if inc_id is None:
            ids = self._selected_obs_ids()
            if ids:
                inc_id = self.db.observation(ids[0])['inclusion_id']
        if inc_id is None:
            QMessageBox.information(self, 'Новое наблюдение',
                                    'Выберите включение в дереве (или создайте его: правая кнопка мыши на образце).')
            return
        dlg = ObservationDialog(self, self._inclusion_label(inc_id))
        if dlg.exec() and dlg.result and self._guard(self.db.add_observation, inc_id, dlg.result):
            self.refresh_tree()
            self.refresh_observations()

    def edit_observation(self, *_):
        ids = self._selected_obs_ids()
        if not ids:
            return
        obs = self.db.observation(ids[0])
        dlg = ObservationDialog(self, self._inclusion_label(obs['inclusion_id']), obs)
        if dlg.exec() and dlg.result:
            res = dict(dlg.result)
            res['source'] = obs.get('source') or 'ручной ввод'
            self._guard(self.db.update_observation, obs['id'], res)
            self.refresh_observations()

    def delete_observations(self):
        ids = self._selected_obs_ids()
        if not ids:
            return
        if QMessageBox.question(self, 'Удаление', f'Удалить выбранные наблюдения ({len(ids)})?\n'
                                'Сохранённые расчёты останутся в истории.') != QMessageBox.Yes:
            return
        for i in ids:
            self._guard(self.db.delete, 'observations', i)
        self.refresh_tree()
        self.refresh_observations()

    # ------------------------------------------------------------------ импорт / экспорт
    def import_file(self, path: str | None = None):
        n = self.selected_node()
        dlg = ImportDialog(self, self.db, path if isinstance(path, str) else None,
                           n['project_id'] if n else None)
        if dlg.exec():
            self.refresh_all()

    def import_lab_table(self, path: str | None = None, *, ask: bool = True):
        """Импорт сводной таблицы лаборатории. Возвращает ImportReport или None."""
        from ..importer import file_sha256, import_rows
        from ..lab_table import read_lab_table, to_parsed_rows
        if not isinstance(path, str) or not path:
            path, _ = QFileDialog.getOpenFileName(self, 'Лабораторная таблица', str(Path.home()), 'Excel (*.xlsx *.xlsm)')
            if not path:
                return None
        try:
            table = read_lab_table(path)
        except Exception as exc:  # noqa: BLE001
            log.exception('Ошибка чтения лабораторной таблицы %s', path)
            QMessageBox.critical(self, 'Лабораторная таблица', f'Не удалось прочитать файл:\n{exc}')
            return None
        if not table.rows:
            QMessageBox.warning(self, 'Лабораторная таблица', '\n'.join(table.warnings) or 'Строки не найдены.')
            return None
        samples = sorted({r.sample for r in table.rows})
        n_co2 = sum(r.co2_bearing and 'Tm_clath' in r.measurements for r in table.rows)
        confirm = False
        if ask:
            names = [p['name'] for p in self.db.projects()]
            default = Path(path).stem
            name, ok = QInputDialog.getItem(self, 'Импорт лабораторной таблицы',
                                            f'Найдено включений: {len(table.rows)} (образцы: {", ".join(samples)}).\n'
                                            'Проект для импорта (можно ввести новое название):',
                                            names + ([default] if default not in names else []),
                                            len(names) if default not in names else names.index(default), True)
            if not ok or not name.strip():
                return None
            if n_co2:
                confirm = QMessageBox.question(
                    self, 'Условие уравнения Darling',
                    f'У {n_co2} включений с CO₂ есть Tm клатрата. В таблице не записано, сосуществовали ли при '
                    'окончательном плавлении клатрата жидкая CO₂, газовая CO₂ и раствор (условие Darling, 1991).\n\n'
                    'Подтверждаете это для всех таких включений? Если нет — солёность по клатрату будет '
                    'заблокирована до уточнения по журналу.',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes
        else:
            name = Path(path).stem
        pid = self.db.get_or_create_project(name.strip())
        parsed = to_parsed_rows(table, confirm_clathrate_phases=confirm)
        rep = import_rows(self.db, pid, parsed, source=Path(path).name)
        self.db.log_import(pid, path, file_sha256(path), None, {'format': 'lab_table', 'clathrate_phases_confirmed':
                                                                confirm}, rep.n_rows, rep.n_observations,
                           rep.n_errors, rep.n_duplicates)
        log.info('Импорт лабораторной таблицы %s: %s', path, rep)
        self.refresh_all()
        if ask:
            text = (f'Импортировано наблюдений: {rep.n_observations} (включений: {rep.n_rows_imported}).\n'
                    f'Строк с ошибками: {rep.n_errors}; дубликатов пропущено: {rep.n_duplicates}.\n\n'
                    'Результаты лаборатории (С%, d фл, Р фл) не импортированы как измерения — они сохранены в '
                    'комментариях наблюдений; для сравнения используйте «Сверка лабораторной таблицы».\n'
                    'Направление гомогенизации CO₂ в таблице не записано: плотность CO₂ будет заблокирована до '
                    'его ввода (двойной щелчок по наблюдению Th CO₂).')
            if table.warnings or rep.messages:
                text += '\n\n' + '\n'.join(table.warnings + rep.messages[:20])
            QMessageBox.information(self, 'Импорт завершён', text)
        return rep

    def compare_lab_table(self):
        from ..lab_compare import compare, salinity_verdict, write_comparison_xlsx
        from ..lab_table import read_lab_table
        src, _ = QFileDialog.getOpenFileName(self, 'Лабораторная таблица для сверки', str(Path.home()),
                                             'Excel (*.xlsx *.xlsm)')
        if not src:
            return
        dst, _ = QFileDialog.getSaveFileName(self, 'Сохранить сверку', str(Path(src).with_name(Path(src).stem + '-сверка.xlsx')),
                                             'Excel (*.xlsx)')
        if not dst:
            return
        if not dst.lower().endswith('.xlsx'):
            dst += '.xlsx'
        try:
            table = read_lab_table(src)
            checks, incons = compare(table)
            write_comparison_xlsx(table, dst)
        except Exception as exc:  # noqa: BLE001
            log.exception('Ошибка сверки %s', src)
            QMessageBox.critical(self, 'Сверка', str(exc))
            return
        major = [c for c in checks if salinity_verdict(c) == 'существенное расхождение']
        minor = sum(salinity_verdict(c) == 'небольшое расхождение' for c in checks)
        by_points = sum(c.explained_by_points for c in checks)
        dens = sum(c.density_status.startswith(('физически', 'невозможно', 'нечисл')) for c in checks)
        text = (f'Включений: {len(checks)}.\nСолёность: существенных расхождений {len(major)}, небольших {minor}; '
                f'посчитано по экспериментальным точкам вместо уравнения {by_points}.\n'
                f'Плотность флюида: физически невозможных или нечисловых значений {dens}.\n'
                f'Внутренних несогласованностей таблицы: {len(incons)}.\n')
        for c in major[:10]:
            text += f'\n• {c.row.sample} {c.row.inclusion}: расчёт {c.calc_salinity:.2f}, в таблице {c.lab_salinity:g}'
        QMessageBox.information(self, 'Сверка сохранена', text + f'\n\nФайл: {dst}')

    def load_example(self):
        path = project_root() / 'examples' / 'example_input.csv'
        if not path.exists():
            QMessageBox.warning(self, 'Пример', f'Файл не найден: {path}')
            return
        self.import_file(str(path))

    def export_observations(self):
        where, args, label = self._selection_filter()
        obs = self.db.observations(where, args)
        if not obs:
            QMessageBox.information(self, 'Экспорт', 'Нет наблюдений для экспорта.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Экспорт измерений', str(Path.home() / 'измерения.csv'),
                                              'CSV (*.csv)')
        if path:
            export_observations_csv(path, obs)
            QMessageBox.information(self, 'Экспорт', f'Сохранено {len(obs)} наблюдений ({label}):\n{path}\n\n'
                                    'Файл можно снова загрузить через импорт.')

    def export_results(self):
        if not self._run:
            QMessageBox.information(self, 'Экспорт', 'Нет выбранного расчёта. Сначала выполните расчёт (F5).')
            return
        default = Path.home() / f'fluidcalc-расчёт-{self._run["id"]}.xlsx'
        path, flt = QFileDialog.getSaveFileName(self, 'Экспорт результатов', str(default),
                                                'Excel с паспортами (*.xlsx);;CSV для русской локали (; и запятая) (*.csv);;'
                                                'CSV международный (, и точка) (*.csv)')
        if not path:
            return
        results = self.db.results(self._run['id'])
        try:
            if 'xlsx' in flt:
                if not path.lower().endswith('.xlsx'):
                    path += '.xlsx'
                export_results_xlsx(path, self._run, results)
            else:
                if not path.lower().endswith('.csv'):
                    path += '.csv'
                intl = 'международный' in flt
                export_results_csv(path, self._run, results, delimiter=',' if intl else ';',
                                   decimal_comma=not intl)
        except OSError as exc:
            QMessageBox.critical(self, 'Экспорт', str(exc))
            return
        log.info('Экспорт расчёта %s в %s', self._run['id'], path)
        QMessageBox.information(self, 'Экспорт', f'Сохранено ({len(results)} строк):\n{path}')

    # ------------------------------------------------------------------ расчёт
    def calculate(self, selected_only: bool = True):
        if self._thread is not None:
            QMessageBox.information(self, 'Расчёт', 'Предыдущий расчёт ещё выполняется.')
            return
        if selected_only:
            where, args, label = self._selection_filter()
        else:
            where, args, label = '1', (), 'вся база'
        obs = self.db.observations(where, args)
        if not obs:
            QMessageBox.information(self, 'Расчёт', f'Нет наблюдений ({label}).')
            return
        projects = {o['project_id'] for o in obs}
        project_id = projects.pop() if len(projects) == 1 else None
        self._pending_scope = (project_id, label)
        self.progress.setRange(0, len(obs))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.a_calc_sel.setEnabled(False)
        self.a_calc_all.setEnabled(False)
        self.statusBar().showMessage(f'Расчёт: {label}, наблюдений {len(obs)}…')
        self._thread = QThread(self)
        self._worker = CalcWorker(obs)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(lambda i, n: self.progress.setValue(i))
        self._worker.finished.connect(self._calc_done)
        self._worker.failed.connect(self._calc_failed)
        self._thread.start()

    def _finish_thread(self):
        self._thread.quit()
        self._thread.wait()
        self._worker.deleteLater()
        self._thread.deleteLater()
        self._thread = self._worker = None
        self.progress.setVisible(False)
        self.a_calc_sel.setEnabled(True)
        self.a_calc_all.setEnabled(True)

    @Slot(list)
    def _calc_done(self, items: list[tuple[dict, Outcome]]):
        self._finish_thread()
        project_id, label = self._pending_scope
        run_id = self._guard(self.db.save_run, project_id, label, backend_versions(), items)
        if run_id is None:
            return
        run = self.db.run(run_id)
        log.info('Расчёт №%s: %s, всего %s, ok %s, отказ %s, без расчёта %s', run_id, label, run['n_total'],
                 run['n_ok'], run['n_error'], run['n_skipped'])
        self.statusBar().showMessage(f'Расчёт №{run_id} сохранён: рассчитано {run["n_ok"]}, отказов {run["n_error"]}, '
                                     f'без расчёта {run["n_skipped"]}', 10000)
        self.refresh_runs(run_id)
        self.tabs.setCurrentIndex(1)

    @Slot(str)
    def _calc_failed(self, msg):
        self._finish_thread()
        QMessageBox.critical(self, 'Расчёт', f'Сбой расчёта: {msg}')

    def wait_for_calculation(self, timeout_ms: int = 60000):
        """Для тестов: дождаться завершения фонового расчёта."""
        from PySide6.QtCore import QElapsedTimer
        timer = QElapsedTimer()
        timer.start()
        while self._thread is not None and timer.elapsed() < timeout_ms:
            QApplication.processEvents()

    # ------------------------------------------------------------------ результаты
    def refresh_runs(self, select_id: int | None = None):
        current = select_id or (self._run['id'] if self._run else None)
        self.run_combo.blockSignals(True)
        self.run_combo.clear()
        for r in self.db.runs():
            self.run_combo.addItem(f'№{r["id"]} — {r["created_at"]} UTC — {r["scope"]} — рассчитано {r["n_ok"]}, '
                                   f'отказ {r["n_error"]}, без расчёта {r["n_skipped"]}', r['id'])
        i = self.run_combo.findData(current) if current else 0
        self.run_combo.setCurrentIndex(max(i, 0))
        self.run_combo.blockSignals(False)
        self.show_run()

    def show_run(self):
        run_id = self.run_combo.currentData()
        self._run = self.db.run(run_id) if run_id else None
        self._results = self.db.results(run_id) if run_id else []
        if not self._run:
            self.run_info.setText('Расчётов пока нет. Добавьте или импортируйте измерения и нажмите F5.')
        else:
            r = self._run
            self.run_info.setText(f'Каждый расчёт сохраняется отдельной версией и не перезаписывает прежние. '
                                  f'Версии: FluidCalc {r["app_version"]}, ядро {r["core_version"]}, Python '
                                  f'{r["python_version"]}, CoolProp {r["coolprop_version"]}.')
        status = self.status_filter.currentData()
        shown = [x for x in self._results if status is None or x['status'] == status]
        t = self.res_table
        t.setSortingEnabled(False)
        t.clearSelection()
        t.setRowCount(len(shown))
        for row, r in enumerate(shown):
            idx = self._results.index(r)
            vals = [r['sample_name'], r['mineral_name'] or '', r['fia_name'] or '', r['inclusion_name'],
                    kind_label(r['kind']), None, STATUS_RU.get(r['status'], r['status']), r['result_kind'] or '',
                    None, r['unit'] or '', None, r['model'] or '', r['message'] or '']
            for c, v in enumerate(vals):
                if c == 5:
                    it = _num_item(r['inputs'].get('temperature_c'))
                elif c == 8:
                    it = _num_item(r['value'], 5)
                elif c == 10:
                    it = _num_item(r['extras'].get('saturation_pressure_bar'), 3)
                else:
                    it = QTableWidgetItem(v)
                if c == 6:
                    it.setBackground(QColor(STATUS_BG.get(r['status'], '#ffffff')))
                it.setData(ROLE, idx)
                t.setItem(row, c, it)
        t.setSortingEnabled(True)
        t.resizeColumnsToContents()
        for c in (11, 12):
            t.setColumnWidth(c, min(t.columnWidth(c), 360))
        self.passport.setHtml('<p>Выберите строку результата, чтобы увидеть паспорт.</p>')
        self.update_plot()

    def _show_passport(self):
        items = self.res_table.selectedItems()
        if not items:
            return
        r = self._results[items[0].data(ROLE)]
        ctx = {k: r.get(k) for k in ('project_name', 'sample_name', 'mineral_name', 'fia_name', 'inclusion_name')}
        self.passport.setHtml(passport_html(passport_lines(r['inputs'], r, self._run, ctx)))

    # ------------------------------------------------------------------ графики
    def update_plot(self):
        if not hasattr(self, 'canvas'):
            return
        fig = make_figure(self.plot_type.currentData(), self._results, self.plot_group.currentData(), self._run)
        new_canvas = self._canvas_cls(fig)
        self._plot_layout.replaceWidget(self.canvas, new_canvas)
        self.canvas.setParent(None)
        self.canvas.deleteLater()
        self.canvas = new_canvas
        self._figure = fig
        self.canvas.draw_idle()

    def save_plot(self):
        name = f'fluidcalc-{self.plot_type.currentData()}'
        path, flt = QFileDialog.getSaveFileName(self, 'Сохранить график', str(Path.home() / f'{name}.png'),
                                                'PNG (*.png);;SVG (*.svg)')
        if path:
            ext = '.svg' if 'svg' in flt.lower() else '.png'
            if not path.lower().endswith(ext):
                path += ext
            save_figure(self._figure, path)
            QMessageBox.information(self, 'График', f'Сохранено:\n{path}')

    # ------------------------------------------------------------------ быстрый расчёт
    def _quick_enabled(self):
        k = self.q_kind.currentData()
        self.q_h.setEnabled(k == 'Th_CO2')
        self.q_p.setEnabled(k == 'Th_CO2')
        for w in (self.q_l, self.q_v, self.q_b):
            w.setEnabled(k == 'Tm_clath')

    def quick_calc(self):
        k = self.q_kind.currentData()
        try:
            t = self.q_t.value()
            u = self.q_u.value()
        except ValueError as exc:
            self.q_out.setHtml(f'<p style="color:#a4161a">Ошибка ввода числа: {exc}</p>')
            return
        obs = {'kind': k, 'temperature_c': t, 'uncertainty_c': u,
               'homogenization_to': self.q_h.value() if k == 'Th_CO2' else None,
               'liquid_co2_present': self.q_l.value() if k == 'Tm_clath' else None,
               'vapor_co2_present': self.q_v.value() if k == 'Tm_clath' else None,
               'aqueous_brine_present': self.q_b.value() if k == 'Tm_clath' else None,
               'co2_purity_confirmed': (True if self.q_p.isChecked() else None) if k == 'Th_CO2' else None}
        o = calculate_observation(obs)
        self.q_out.setHtml(passport_html(passport_lines(obs, o.__dict__), 'Быстрый расчёт (не сохраняется)'))

    # ------------------------------------------------------------------ справка
    def show_log(self):
        p = log_file_path()
        try:
            text = p.read_text(encoding='utf-8')[-200_000:]
        except OSError:
            text = '(журнал пуст)'
        TextDialog(self, f'Журнал: {p}', text).exec()

    def about(self):
        v = backend_versions()
        QMessageBox.about(self, 'О программе', (
            f'<b>{APP_TITLE}</b><br>Версия {__version__} (исследовательский прототип).<br><br>'
            f'Ядро fluid_core {v["core_version"]}; Python {v["python_version"]}; CoolProp {v["coolprop_version"]}; '
            f'{v["platform"]}.<br><br>'
            'Программа не является аттестованным ПО для публикационных оценок давления и состава. '
            'Расчёты выполняются локально, без обращения к интернету. '
            'Управление оборудованием Linkam не выполняется.<br><br>'
            f'Журнал: {log_file_path()}<br>База: {self.db.path if self.db else "—"}'))

    def closeEvent(self, event):
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
        if self.db:
            self.db.close()
        super().closeEvent(event)


def _method(kind):
    from ..methods import KIND_METHOD
    return KIND_METHOD[kind]
