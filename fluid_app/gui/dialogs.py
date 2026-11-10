"""Диалоги: ввод наблюдения, импорт CSV/XLSX с картой полей и предпросмотром."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from .. import importer
from ..db import Database, DatabaseError
from ..methods import KINDS, KIND_ORDER, KIND_NO_CALC_REASON, HOMOGENIZATION, kind_label
from .widgets import HomogCombo, NumberEdit, TriStateCombo

log = logging.getLogger(__name__)

REQUIREMENTS = {
    'Tm_ice': 'Для расчёта (Bodnar, 1993) нужна только температура; область: −21,1…0 °C.',
    'Tm_clath': ('Для расчёта (Darling, 1991) нужно подтвердить наличие жидкой CO₂, газовой CO₂ и водного '
                 'раствора при окончательном плавлении клатрата; область: −10…+10 °C.'),
    'Th_CO2': ('Для расчёта плотности чистой CO₂ (Span & Wagner, 1996 / CoolProp) нужно явно указать '
               'направление гомогенизации (жидкость или газ) и принять приближение чистой CO₂.'),
}


class ObservationDialog(QDialog):
    """Ввод / правка одного наблюдения. Никакие поля не заполняются предполагаемыми значениями."""

    def __init__(self, parent, inclusion_label: str, obs: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle('Наблюдение' if obs else 'Новое наблюдение')
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f'<b>Включение:</b> {inclusion_label}'))
        form = QFormLayout()
        self.kind = QComboBox()
        for k in KIND_ORDER:
            self.kind.addItem(f'{KINDS[k][0]} — {KINDS[k][1]}', k)
        self.temperature = NumberEdit(placeholder='°C, напр. −5,2')
        self.uncertainty = NumberEdit(placeholder='±°C (необязательно)')
        self.homog = HomogCombo()
        self.liquid = TriStateCombo()
        self.vapor = TriStateCombo()
        self.brine = TriStateCombo()
        self.purity = QCheckBox('Принимаю приближение чистой CO₂ (это не доказательство состава)')
        self.phase_notes = QLineEdit()
        self.comment = QLineEdit()
        form.addRow('Тип наблюдения *', self.kind)
        form.addRow('Температура, °C *', self.temperature)
        form.addRow('Погрешность ±, °C', self.uncertainty)
        form.addRow('Направление гомогенизации', self.homog)
        form.addRow('Жидкая CO₂ при плавлении клатрата', self.liquid)
        form.addRow('Газовая CO₂ при плавлении клатрата', self.vapor)
        form.addRow('Водный раствор при плавлении клатрата', self.brine)
        form.addRow('', self.purity)
        form.addRow('Описание фаз', self.phase_notes)
        form.addRow('Комментарий', self.comment)
        lay.addLayout(form)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet('color:#52514e')
        lay.addWidget(self.hint)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText('Сохранить')
        bb.button(QDialogButtonBox.Cancel).setText('Отмена')
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.kind.currentIndexChanged.connect(self._update_enabled)
        if obs:
            self.kind.setCurrentIndex(self.kind.findData(obs['kind']))
            self.temperature.set_value(obs['temperature_c'])
            self.uncertainty.set_value(obs.get('uncertainty_c'))
            self.homog.set_value(obs.get('homogenization_to'))
            self.liquid.set_value(obs.get('liquid_co2_present'))
            self.vapor.set_value(obs.get('vapor_co2_present'))
            self.brine.set_value(obs.get('aqueous_brine_present'))
            self.purity.setChecked(obs.get('co2_purity_confirmed') is True)
            self.phase_notes.setText(obs.get('phase_notes') or '')
            self.comment.setText(obs.get('comment') or '')
        self._update_enabled()
        self.result: dict | None = None

    def _update_enabled(self):
        k = self.kind.currentData()
        self.homog.setEnabled(k in ('Th_CO2', 'Th_total'))
        for w in (self.liquid, self.vapor, self.brine):
            w.setEnabled(k == 'Tm_clath')
        self.purity.setEnabled(k in ('Th_CO2', 'Tm_clath'))
        self.hint.setText(REQUIREMENTS.get(k) or KIND_NO_CALC_REASON.get(k, ''))

    def _accept(self):
        k = self.kind.currentData()
        try:
            t = self.temperature.value()
            if t is None:
                raise ValueError('Температура обязательна.')
        except ValueError as exc:
            QMessageBox.warning(self, 'Ошибка ввода', f'Температура: {exc}')
            return
        try:
            u = self.uncertainty.value()
            if u is not None and u < 0:
                raise ValueError('не может быть отрицательной')
        except ValueError as exc:
            QMessageBox.warning(self, 'Ошибка ввода', f'Погрешность: {exc}')
            return
        self.result = {
            'kind': k, 'temperature_c': t, 'uncertainty_c': u,
            'homogenization_to': self.homog.value() if k in ('Th_CO2', 'Th_total') else None,
            'liquid_co2_present': self.liquid.value() if k == 'Tm_clath' else None,
            'vapor_co2_present': self.vapor.value() if k == 'Tm_clath' else None,
            'aqueous_brine_present': self.brine.value() if k == 'Tm_clath' else None,
            'co2_purity_confirmed': ((True if self.purity.isChecked() else None)
                                     if k in ('Th_CO2', 'Tm_clath') else None),
            'phase_notes': self.phase_notes.text().strip() or None,
            'comment': self.comment.text().strip() or None,
            'source': 'ручной ввод',
        }
        self.accept()


NEW_PROJECT = '__new__'


class ImportDialog(QDialog):
    """Пакетный импорт: выбор файла → карта полей → проверка → импорт. Исходный файл не изменяется."""

    def __init__(self, parent, db: Database, path: str | None = None, project_id: int | None = None):
        super().__init__(parent)
        self.db = db
        self.table: importer.Table | None = None
        self.parsed: list[importer.ParsedRow] | None = None
        self.report: importer.ImportReport | None = None
        self.imported_project_id: int | None = None
        self.setWindowTitle('Импорт измерений из CSV / Excel')
        self.resize(1100, 760)
        lay = QVBoxLayout(self)

        top = QGroupBox('Файл')
        tl = QFormLayout(top)
        row = QHBoxLayout()
        self.path_edit = QLineEdit(path or '')
        self.path_edit.setReadOnly(True)
        browse = QPushButton('Выбрать…')
        browse.clicked.connect(self._browse)
        row.addWidget(self.path_edit)
        row.addWidget(browse)
        tl.addRow('Файл', row)
        opts = QHBoxLayout()
        self.sheet = QComboBox()
        self.encoding = QComboBox()
        for label, v in (('авто', None), ('UTF-8', 'utf-8-sig'), ('Windows-1251', 'cp1251')):
            self.encoding.addItem(label, v)
        self.delimiter = QComboBox()
        for label, v in (('авто', None), ('; (точка с запятой)', ';'), (', (запятая)', ','), ('табуляция', '\t')):
            self.delimiter.addItem(label, v)
        reread = QPushButton('Перечитать')
        reread.clicked.connect(self._load)
        for w, lbl in ((self.sheet, 'Лист:'), (self.encoding, 'Кодировка:'), (self.delimiter, 'Разделитель:')):
            opts.addWidget(QLabel(lbl))
            opts.addWidget(w)
        opts.addWidget(reread)
        opts.addStretch()
        tl.addRow('Параметры', opts)
        prow = QHBoxLayout()
        self.project = QComboBox()
        for p in db.projects():
            self.project.addItem(p['name'], p['id'])
        self.project.addItem('➕ новый проект…', NEW_PROJECT)
        if project_id is not None:
            self.project.setCurrentIndex(max(0, self.project.findData(project_id)))
        self.new_project = QLineEdit()
        self.new_project.setPlaceholderText('Название нового проекта')
        self.project.currentIndexChanged.connect(
            lambda: self.new_project.setVisible(self.project.currentData() == NEW_PROJECT))
        self.new_project.setVisible(self.project.currentData() == NEW_PROJECT)
        prow.addWidget(self.project)
        prow.addWidget(self.new_project)
        tl.addRow('Импорт в проект', prow)
        lay.addWidget(top)

        self.tabs = QTabWidget()
        # карта полей
        mw = QWidget()
        ml = QVBoxLayout(mw)
        ml.addWidget(QLabel('Сопоставьте поля программы со столбцами файла. Поддерживаются длинный формат '
                            '(столбцы «тип измерения» + «температура», как в examples/example_input.csv) и '
                            'широкий формат (отдельный столбец на Tm лёд, Th CO₂ и т. д.). * — обязательные поля. '
                            'Пустые ячейки остаются пустыми.'))
        self.map_table = QTableWidget(len(importer.TARGET_FIELDS), 2)
        self.map_table.setHorizontalHeaderLabels(['Поле программы', 'Столбец файла'])
        self.map_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.map_table.horizontalHeader().setStretchLastSection(True)
        self.map_table.verticalHeader().setVisible(False)
        self.map_combos: dict[str, QComboBox] = {}
        for i, (key, (label, _)) in enumerate(importer.TARGET_FIELDS.items()):
            it = QTableWidgetItem(label)
            it.setFlags(Qt.ItemIsEnabled)
            self.map_table.setItem(i, 0, it)
            cb = QComboBox()
            cb.currentIndexChanged.connect(self._invalidate)
            self.map_table.setCellWidget(i, 1, cb)
            self.map_combos[key] = cb
        ml.addWidget(self.map_table)
        self.tabs.addTab(mw, '1. Карта полей')
        # исходные данные
        self.raw_table = QTableWidget()
        self.raw_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabs.addTab(self.raw_table, '2. Исходные данные')
        # проверка
        cw = QWidget()
        cl = QVBoxLayout(cw)
        self.summary = QLabel('Нажмите «Проверить».')
        self.summary.setWordWrap(True)
        cl.addWidget(self.summary)
        self.check_table = QTableWidget(0, 8)
        self.check_table.setHorizontalHeaderLabels(['Строка', 'Статус', 'Образец', 'Минерал', 'FIA', 'Включение',
                                                    'Измерения', 'Ошибки / предупреждения'])
        self.check_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.check_table.horizontalHeader().setStretchLastSection(True)
        cl.addWidget(self.check_table)
        self.tabs.addTab(cw, '3. Проверка')
        lay.addWidget(self.tabs, 1)

        brow = QHBoxLayout()
        self.skip_dup = QCheckBox('Пропускать точные дубликаты уже имеющихся наблюдений')
        self.skip_dup.setChecked(True)
        brow.addWidget(self.skip_dup)
        brow.addStretch()
        self.check_btn = QPushButton('Проверить')
        self.check_btn.clicked.connect(self._check)
        self.import_btn = QPushButton('Импортировать корректные строки')
        self.import_btn.setEnabled(False)
        self.import_btn.clicked.connect(self._import)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.reject)
        for b in (self.check_btn, self.import_btn, close):
            brow.addWidget(b)
        lay.addLayout(brow)
        if path:
            self._load()

    # --- действия -------------------------------------------------------------
    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Файл с измерениями', str(Path.home()),
                                              'Таблицы (*.csv *.txt *.tsv *.xlsx *.xlsm);;Все файлы (*)')
        if path:
            self.path_edit.setText(path)
            self.sheet.blockSignals(True)
            self.sheet.clear()
            self.sheet.blockSignals(False)
            self._load()

    def _load(self):
        path = self.path_edit.text()
        if not path:
            return
        try:
            is_xlsx = path.lower().endswith(('.xlsx', '.xlsm'))
            if is_xlsx and self.sheet.count() == 0:
                self.sheet.addItems(importer.xlsx_sheets(path))
            self.sheet.setEnabled(is_xlsx)
            self.encoding.setEnabled(not is_xlsx)
            self.delimiter.setEnabled(not is_xlsx)
            self.table = importer.read_table(path, sheet=self.sheet.currentText() or None,
                                             encoding=self.encoding.currentData(),
                                             delimiter=self.delimiter.currentData())
        except Exception as exc:  # noqa: BLE001 — показать любую ошибку чтения пользователю
            log.exception('Ошибка чтения %s', path)
            QMessageBox.critical(self, 'Ошибка чтения', f'Не удалось прочитать файл:\n{exc}')
            self.table = None
            return
        t = self.table
        self.raw_table.setColumnCount(len(t.headers))
        self.raw_table.setHorizontalHeaderLabels(t.headers)
        shown = t.rows[:300]
        self.raw_table.setRowCount(len(shown))
        for r, row in enumerate(shown):
            for c, v in enumerate(row):
                self.raw_table.setItem(r, c, QTableWidgetItem(v))
        self.raw_table.setVerticalHeaderLabels([str(i) for i in range(2, len(shown) + 2)])
        auto = importer.auto_mapping(t.headers)
        for key, cb in self.map_combos.items():
            cb.blockSignals(True)
            cb.clear()
            cb.addItem('— не использовать —', None)
            for h in t.headers:
                cb.addItem(h, h)
            if auto.get(key):
                cb.setCurrentIndex(cb.findData(auto[key]))
            cb.blockSignals(False)
        extra = ''
        if t.encoding:
            extra = f'; кодировка {t.encoding}, разделитель «{"Tab" if t.delimiter == chr(9) else t.delimiter}»'
        self.summary.setText(f'Прочитано строк данных: {len(t.rows)}{extra}. Проверьте карту полей и нажмите «Проверить».')
        self._invalidate()
        self.tabs.setCurrentIndex(0)

    def mapping(self) -> dict:
        return {k: cb.currentData() for k, cb in self.map_combos.items()}

    def _invalidate(self):
        self.parsed = None
        self.import_btn.setEnabled(False)

    def _check(self):
        if self.table is None:
            QMessageBox.information(self, 'Импорт', 'Сначала выберите файл.')
            return
        mapping = self.mapping()
        errs = importer.validate_mapping(mapping)
        if errs:
            QMessageBox.warning(self, 'Карта полей', '\n'.join(errs))
            return
        self.parsed = importer.parse_rows(self.table, mapping)
        ok = sum(p.ok for p in self.parsed)
        bad = sum(bool(p.errors) for p in self.parsed)
        empty = len(self.parsed) - ok - bad
        n_obs = sum(len(p.observations) for p in self.parsed if p.ok)
        self.summary.setText(f'Строк: {len(self.parsed)}; корректных: {ok} (наблюдений: {n_obs}); '
                             f'с ошибками: {bad} — не будут импортированы; без измерений: {empty}.')
        self.check_table.setRowCount(len(self.parsed))
        for r, p in enumerate(self.parsed):
            status = 'ошибка' if p.errors else ('корректна' if p.ok else 'пропуск')
            meas = '; '.join(f'{kind_label(o["kind"])} = ' + f'{o["temperature_c"]:g}'.replace('.', ',') +
                             (f' ({HOMOGENIZATION[o["homogenization_to"]]})' if o.get('homogenization_to') else '')
                             for o in p.observations)
            vals = [str(p.row_number), status, p.sample, p.mineral, p.fia, p.inclusion, meas,
                    '; '.join(p.errors + p.warnings)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 1:
                    it.setBackground(QColor({'ошибка': '#f8d7da', 'корректна': '#e2f0d9'}.get(status, '#ededed')))
                self.check_table.setItem(r, c, it)
        self.check_table.resizeColumnsToContents()
        self.tabs.setCurrentIndex(2)
        self.import_btn.setEnabled(ok > 0)

    def _import(self):
        if not self.parsed:
            return
        pid = self.project.currentData()
        try:
            if pid == NEW_PROJECT:
                name = self.new_project.text().strip()
                if not name:
                    QMessageBox.warning(self, 'Импорт', 'Укажите название нового проекта.')
                    return
                pid = self.db.get_or_create_project(name)
            path = self.path_edit.text()
            rep = importer.import_rows(self.db, pid, self.parsed, source=Path(path).name,
                                       skip_duplicates=self.skip_dup.isChecked())
            self.db.log_import(pid, path, importer.file_sha256(path), self.table.sheet, self.mapping(),
                               rep.n_rows, rep.n_observations, rep.n_errors, rep.n_duplicates)
        except DatabaseError as exc:
            QMessageBox.critical(self, 'Импорт', str(exc))
            return
        log.info('Импорт %s: %s', self.path_edit.text(), rep)
        self.report = rep
        self.imported_project_id = pid
        text = (f'Импортировано наблюдений: {rep.n_observations} (строк: {rep.n_rows_imported} из {rep.n_rows}).\n'
                f'Строк с ошибками: {rep.n_errors}; пропущено дубликатов: {rep.n_duplicates}; '
                f'строк без измерений: {rep.n_empty}.')
        if rep.messages:
            text += '\n\n' + '\n'.join(rep.messages[:30])
            if len(rep.messages) > 30:
                text += f'\n… и ещё {len(rep.messages) - 30}'
        QMessageBox.information(self, 'Импорт завершён', text)
        self.accept()


class TextDialog(QDialog):
    def __init__(self, parent, title: str, text: str):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 600)
        lay = QVBoxLayout(self)
        ed = QPlainTextEdit(text)
        ed.setReadOnly(True)
        lay.addWidget(ed)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


PHI_METHODS = ['визуальная оценка', 'подсчёт площадей', 'другое']


class CarbonicFractionDialog(QDialog):
    """Объёмная доля углекислотной фазы (жидкая + газовая CO₂) включения при комнатной температуре."""

    def __init__(self, parent, inclusion_label: str, inc):
        super().__init__(parent)
        self.setWindowTitle('Доля углекислотной фазы')
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f'<b>Включение:</b> {inclusion_label}'))
        form = QFormLayout()
        self.value = NumberEdit(placeholder='%, напр. 30 (пусто — не определена)')
        self.unc = NumberEdit(placeholder='± %, напр. 10')
        self.method = QComboBox()
        self.method.setEditable(True)
        self.method.addItems(PHI_METHODS)
        self.temp = NumberEdit(placeholder='°C, напр. 22 (комнатная)')
        form.addRow('φ, % объёма включения', self.value)
        form.addRow('Погрешность ±, %', self.unc)
        form.addRow('Способ оценки', self.method)
        form.addRow('Температура оценки, °C', self.temp)
        lay.addLayout(form)
        hint = QLabel('φ — доля всей углекислотной фазы (жидкая + газовая CO₂) в объёме включения. Используется '
                      'строгой моделью H₂O–CO₂–NaCl и объёмным балансом; основная неопределённость результата — '
                      'именно φ. Для строгой модели температура оценки обязательна и должна быть не ниже Tm клатрата; '
                      'программа её не подставляет.')
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#52514e')
        lay.addWidget(hint)
        if inc is not None and inc['carbonic_fraction'] is not None:
            self.value.set_value(100 * inc['carbonic_fraction'])
            if inc['carbonic_fraction_unc'] is not None:
                self.unc.set_value(100 * inc['carbonic_fraction_unc'])
            if inc['carbonic_fraction_method']:
                self.method.setCurrentText(inc['carbonic_fraction_method'])
            if inc['carbonic_fraction_temp_c'] is not None:
                self.temp.set_value(inc['carbonic_fraction_temp_c'])
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText('Сохранить')
        bb.button(QDialogButtonBox.Cancel).setText('Отмена')
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.result = None

    def _accept(self):
        try:
            v, u, t = self.value.value(), self.unc.value(), self.temp.value()
            if v is not None and not 0 <= v <= 100:
                raise ValueError('φ должна быть от 0 до 100 %')
            if u is not None and not 0 <= u <= 100:
                raise ValueError('погрешность должна быть от 0 до 100 %')
        except ValueError as exc:
            QMessageBox.warning(self, 'Ошибка ввода', str(exc))
            return
        self.result = (None if v is None else v / 100, None if u is None else u / 100,
                       self.method.currentText().strip() or None, t)
        self.accept()
