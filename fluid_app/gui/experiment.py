"""Ход эксперимента: создание включения одним диалогом, условная схема включения, сеансы и этапы
охлаждения/нагревания, панель «Ход эксперимента» над таблицей измерений.

Панель и таблица показывают одни и те же записи таблицы observations: у наблюдения есть необязательная
ссылка на этап (stage_id), копий измерений нет. Ничего не подставляется: неизвестные температуры и даты
остаются «не указано», наблюдаемые фазы исходного состояния не переносятся в фазовые условия наблюдений.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDateTime, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDateTimeEdit, QDialog, QDialogButtonBox,
                               QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPushButton, QRadioButton, QScrollArea,
                               QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ..db import DIRECTIONS, SESSION_DATE_FORMAT, Database, DatabaseError
from ..methods import HOMOGENIZATION, kind_label
from .widgets import NumberEdit

MUTED = 'color:#52514e'
DIRECTION_STYLE = {      # направление: (стрелка, цвет линии и заголовка, фон карточки)
    'cooling': ('↓', '#1f5f9e', '#eef5fc'),
    'heating': ('↑', '#b04a1f', '#fdf1ea'),
}
SKETCH_NOTE = ('Условная схема. Размер пузырька не является измерением φ; «газ» не означает чистую CO₂; '
               'твёрдая фаза не определяется как галит или клатрат. Эти отметки описывают только вид включения '
               'при указанной температуре и не заполняют фазовые условия других наблюдений.')
FIA_HINT = ('Группа совместно образованных включений (FIA) — включения, захваченные одновременно: в одной зоне '
            'роста или в одной залеченной трещине. Не используйте это поле для произвольной группировки '
            '(по размеру, типу или месту в препарате).')


# --- форматирование ------------------------------------------------------------------
def fmt_temp(v: float) -> str:
    return (f'{v:+g}' if v > 0 else f'{v:g}').replace('.', ',').replace('-', '−') + ' °C'


def fmt_session_date(value: str | None) -> str:
    if not value:
        return 'дата опыта не указана'
    try:
        return datetime.strptime(value, SESSION_DATE_FORMAT).strftime('%d.%m.%Y %H:%M')
    except ValueError:
        return value


def phases_text(liquid, vapor, solid) -> str:
    if liquid is None and vapor is None and solid is None:
        return 'фазы не указаны'
    names = [n for n, v in (('жидкость', liquid), ('газ', vapor), ('твёрдая фаза', solid)) if v]
    return ' + '.join(names) if names else 'фазы не указаны'


def initial_temp_text(temperature_c, room) -> str:
    if temperature_c is not None:
        return f'при {fmt_temp(temperature_c)}'
    return 'при комнатной температуре (точное значение не указано)' if room else 'температура наблюдения не указана'


def session_title(s: dict) -> str:
    return f'Сеанс {s["number"]} · {fmt_session_date(s["started_at"])}' + (' · завершён' if s['finished'] else '')


def stage_title(st: dict) -> str:
    return f'Этап {st["number"]} · {DIRECTIONS[st["direction"]]} {DIRECTION_STYLE[st["direction"]][0]}'


def stage_start_text(st: dict) -> str:
    if st['start_temperature_c'] is not None:
        return f'начало: {fmt_temp(st["start_temperature_c"])}'
    return 'начало: комнатная (значение не указано)' if st['start_room'] else 'начало не указано'


def stage_end_text(st: dict) -> str:
    if st['end_temperature_c'] is not None:
        return f'окончание: {fmt_temp(st["end_temperature_c"])}'
    return 'окончание не указано'


def observation_text(o: dict) -> str:
    return f'{kind_label(o["kind"])}  {fmt_temp(o["temperature_c"])}'


def observation_tooltip(o: dict) -> str:
    parts = [f'Наблюдение № {o["id"]}: {observation_text(o)}']
    if o.get('uncertainty_c') is not None:
        parts.append(f'погрешность ± {o["uncertainty_c"]:g} °C'.replace('.', ','))
    if o.get('homogenization_to'):
        parts.append(f'гомогенизация: {HOMOGENIZATION[o["homogenization_to"]]}')
    if o.get('comment'):
        parts.append(o['comment'])
    parts.append('Щелчок — изменить; правая кнопка — привязка к этапу, удаление.')
    return '\n'.join(parts)


# --- условная схема включения ----------------------------------------------------------
class InclusionSketch(QWidget):
    """Условный рисунок включения: контур, жидкость, пузырёк газа, кристалл. Размеры фаз ничего не измеряют."""

    def __init__(self, parent=None, compact: bool = False):
        super().__init__(parent)
        self.liquid = self.vapor = self.solid = None
        self.setMinimumSize(120, 84) if compact else self.setMinimumSize(190, 130)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed if compact else QSizePolicy.Preferred)

    def set_phases(self, liquid, vapor, solid):
        self.liquid, self.vapor, self.solid = liquid, vapor, solid
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        m = 6.0
        r = QRectF(m, m, w - 2 * m, h - 2 * m)
        # контур включения — слегка неправильный «отрицательный кристалл»
        x0, y0, rw, rh = r.x(), r.y(), r.width(), r.height()
        path = QPainterPath()
        path.moveTo(x0 + 0.10 * rw, y0 + 0.50 * rh)
        path.cubicTo(x0 + 0.02 * rw, y0 + 0.12 * rh, x0 + 0.30 * rw, y0 + 0.00 * rh, x0 + 0.55 * rw, y0 + 0.05 * rh)
        path.cubicTo(x0 + 0.85 * rw, y0 + 0.08 * rh, x0 + 1.00 * rw, y0 + 0.30 * rh, x0 + 0.94 * rw, y0 + 0.58 * rh)
        path.cubicTo(x0 + 0.90 * rw, y0 + 0.92 * rh, x0 + 0.62 * rw, y0 + 1.00 * rh, x0 + 0.40 * rw, y0 + 0.95 * rh)
        path.cubicTo(x0 + 0.18 * rw, y0 + 0.92 * rh, x0 + 0.14 * rw, y0 + 0.78 * rh, x0 + 0.10 * rw, y0 + 0.50 * rh)
        nothing = not (self.liquid or self.vapor or self.solid)
        fill = QColor('#cfe6f7') if self.liquid else QColor('#f7f7f5')
        p.setPen(QPen(QColor('#3a3a3a'), 2.0))
        p.setBrush(QBrush(fill))
        p.drawPath(path)
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1))
        p.setFont(font)
        if nothing:
            p.setPen(QColor('#6b6b68'))
            p.drawText(r, Qt.AlignCenter, 'фазы не указаны')
            return
        p.setClipPath(path)
        if self.liquid:
            p.setPen(QColor('#1f5f9e'))
            p.drawText(QRectF(x0 + 0.42 * rw, y0 + 0.68 * rh, 0.3 * rw, 0.22 * rh), Qt.AlignCenter, 'Ж')
        if self.vapor:
            d = min(rw, rh) * 0.42
            c = QPointF(x0 + 0.33 * rw, y0 + 0.42 * rh)
            p.setPen(QPen(QColor('#3a3a3a'), 1.6))
            p.setBrush(QBrush(QColor('#ffffff')))
            p.drawEllipse(c, d / 2, d / 2)
            p.setPen(QPen(QColor('#b9b9b6'), 1.2))
            p.drawArc(QRectF(c.x() - d * 0.32, c.y() - d * 0.32, d * 0.64, d * 0.64), 100 * 16, 70 * 16)
            p.setPen(QColor('#3a3a3a'))
            p.drawText(QRectF(c.x() - d / 2, c.y() - d / 2, d, d), Qt.AlignCenter, 'Г')
        if self.solid:
            s = min(rw, rh) * 0.26
            cx, cy = x0 + 0.72 * rw, y0 + 0.45 * rh
            p.setPen(QPen(QColor('#3a3a3a'), 1.4))
            p.setBrush(QBrush(QColor('#efe6c9')))
            front = QRectF(cx - s / 2, cy - s / 2 + s * 0.18, s, s)
            k = s * 0.28      # условный кубик в аксонометрии
            p.drawPolygon(QPolygonF([front.topLeft(), QPointF(front.left() + k, front.top() - k),
                                     QPointF(front.right() + k, front.top() - k), front.topRight()]))
            p.drawPolygon(QPolygonF([front.topRight(), QPointF(front.right() + k, front.top() - k),
                                     QPointF(front.right() + k, front.bottom() - k), front.bottomRight()]))
            p.drawRect(front)
            p.drawText(front, Qt.AlignCenter, 'Тв')


class PhaseStateEditor(QWidget):
    """Наблюдаемые фазы и температура наблюдения исходного состояния включения, со схемой."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        left = QVBoxLayout()
        left.addWidget(QLabel('Наблюдаемые фазы:'))
        self.liquid = QCheckBox('жидкость')
        self.vapor = QCheckBox('газ')
        self.solid = QCheckBox('твёрдая фаза')
        for cb in (self.liquid, self.vapor, self.solid):
            left.addWidget(cb)
            cb.toggled.connect(self._update)
        self.state = QLabel()
        self.state.setStyleSheet(MUTED)
        left.addWidget(self.state)
        left.addSpacing(6)
        left.addWidget(QLabel('Температура этого наблюдения:'))
        self.t_none = QRadioButton('не указана')
        self.t_room = QRadioButton('комнатная, точное значение не указано')
        self.t_value = QRadioButton('значение:')
        self.temperature = NumberEdit(placeholder='°C')
        self.temperature.setMaximumWidth(90)
        self._group = QButtonGroup(self)
        for rb in (self.t_none, self.t_room, self.t_value):
            self._group.addButton(rb)
        row = QHBoxLayout()
        row.addWidget(self.t_value)
        row.addWidget(self.temperature)
        row.addWidget(QLabel('°C'))
        row.addStretch()
        left.addWidget(self.t_none)
        left.addWidget(self.t_room)
        left.addLayout(row)
        left.addStretch()
        self.t_none.setChecked(True)
        self.t_value.toggled.connect(self.temperature.setEnabled)
        self.temperature.setEnabled(False)
        self.temperature.textEdited.connect(lambda: self.t_value.setChecked(True))
        lay.addLayout(left, 1)
        right = QVBoxLayout()
        self.sketch = InclusionSketch()
        right.addWidget(self.sketch, 1)
        cap = QLabel('Условная схема')
        cap.setAlignment(Qt.AlignCenter)
        cap.setStyleSheet(MUTED)
        right.addWidget(cap)
        lay.addLayout(right, 1)
        self._update()

    def _update(self):
        liquid, vapor, solid = self.phases()
        self.sketch.set_phases(liquid, vapor, solid)
        self.state.setText('Отмечено: ' + phases_text(liquid, vapor, solid) if liquid is not None
                           else 'Ничего не отмечено — фазы «не указано»')

    def phases(self) -> tuple:
        vals = (self.liquid.isChecked(), self.vapor.isChecked(), self.solid.isChecked())
        return vals if any(vals) else (None, None, None)

    def values(self) -> tuple:
        """(жидкость, газ, твёрдая фаза, температура, комнатная). ValueError при ошибке ввода числа."""
        t = None
        if self.t_value.isChecked():
            t = self.temperature.value()
            if t is None:
                raise ValueError('введите значение температуры или выберите другой вариант')
        return (*self.phases(), t, self.t_room.isChecked())

    def set_values(self, liquid, vapor, solid, temperature_c, room):
        self.liquid.setChecked(bool(liquid))
        self.vapor.setChecked(bool(vapor))
        self.solid.setChecked(bool(solid))
        if temperature_c is not None:
            self.temperature.set_value(temperature_c)
            self.t_value.setChecked(True)
        else:
            self.temperature.clear()
            (self.t_room if room else self.t_none).setChecked(True)
        self._update()

    def reset(self):
        self.set_values(None, None, None, None, False)


def _note_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(MUTED)
    return lab


def _buttons(dialog: QDialog, accept) -> QDialogButtonBox:
    bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    bb.button(QDialogButtonBox.Save).setText('Сохранить')
    bb.button(QDialogButtonBox.Cancel).setText('Отмена')
    bb.accepted.connect(accept)
    bb.rejected.connect(dialog.reject)
    return bb


# --- создание включения одним окном -----------------------------------------------------
class AddInclusionDialog(QDialog):
    """Единый диалог: образец, минерал, группа (FIA), номер, наблюдаемые фазы, температура, примечание.

    Узлы дерева создаются автоматически и без дубликатов; включение с уже занятым номером не создаётся."""
    added = Signal(int)

    def __init__(self, parent, db: Database, project_id: int | None = None, sample: str = '', mineral: str = '',
                 fia: str = ''):
        super().__init__(parent)
        self.db = db
        self.last_id: int | None = None
        self._number_auto = True
        self.setWindowTitle('Добавить включение')
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.project = QComboBox()
        for p in db.projects():
            self.project.addItem(p['name'], p['id'])
        if project_id is not None:
            self.project.setCurrentIndex(max(0, self.project.findData(project_id)))
        self.sample = self._editable('выберите или введите имя нового образца')
        self.mineral = self._editable('необязательно; выберите или введите')
        self.fia = self._editable('необязательно; выберите или введите')
        self.fia.setToolTip(FIA_HINT)
        self.number = QLineEdit()
        self.number.setMaximumWidth(140)
        self.number.textEdited.connect(self._number_edited)
        self.inclusion_type = QLineEdit()
        self.inclusion_type.setPlaceholderText('необязательно, обозначение лаборатории, напр. L+V')
        form.addRow('Проект', self.project)
        form.addRow('Образец *', self.sample)
        form.addRow('Минерал', self.mineral)
        form.addRow('Группа совместно образованных\nвключений (необязательно)', self.fia)
        form.addRow('', _note_label(FIA_HINT))
        form.addRow('Номер включения *', self.number)
        form.addRow('Тип включения', self.inclusion_type)
        lay.addLayout(form)
        box = QGroupBox('Исходное состояние включения')
        bl = QVBoxLayout(box)
        self.state = PhaseStateEditor()
        bl.addWidget(self.state)
        bl.addWidget(_note_label(SKETCH_NOTE))
        lay.addWidget(box)
        nf = QFormLayout()
        self.note = QLineEdit()
        nf.addRow('Примечание', self.note)
        lay.addLayout(nf)
        self.status = QLabel()
        self.status.setStyleSheet('color:#2e6b2e')
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch()
        self.add_btn = QPushButton('Добавить')
        self.add_btn.setDefault(True)
        self.next_btn = QPushButton('Добавить и создать следующее')
        close = QPushButton('Закрыть')
        self.add_btn.clicked.connect(lambda: self._add(False))
        self.next_btn.clicked.connect(lambda: self._add(True))
        close.clicked.connect(self.reject)
        for b in (self.add_btn, self.next_btn, close):
            row.addWidget(b)
        lay.addLayout(row)

        self.project.currentIndexChanged.connect(self._fill_samples)
        self.sample.editTextChanged.connect(self._sample_changed)
        self.mineral.editTextChanged.connect(self._fill_fias)
        self._fill_samples(keep=sample)
        self.mineral.setEditText(mineral or '')
        self._fill_fias()
        self.fia.setEditText(fia or '')

    @staticmethod
    def _editable(placeholder: str) -> QComboBox:
        cb = QComboBox()
        cb.setEditable(True)
        cb.setInsertPolicy(QComboBox.NoInsert)
        cb.lineEdit().setPlaceholderText(placeholder)
        cb.setCurrentIndex(-1)
        return cb

    # --- списки зависят от выбранного выше -------------------------------------------
    def _refill(self, combo: QComboBox, names: list[str], keep: str | None = None):
        text = combo.currentText() if keep is None else keep
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(names)
        combo.setCurrentIndex(-1)
        combo.setEditText(text)
        combo.blockSignals(False)

    def _sample_id(self) -> int | None:
        pid = self.project.currentData()
        name = self.sample.currentText().strip()
        if pid is None or not name:
            return None
        row = self.db._one('SELECT id FROM samples WHERE project_id=? AND name=?', (pid, name))
        return row['id'] if row else None

    def _mineral_id(self, sample_id: int | None) -> int | None:
        name = self.mineral.currentText().strip()
        if sample_id is None or not name:
            return None
        row = self.db._one('SELECT id FROM minerals WHERE sample_id=? AND name=?', (sample_id, name))
        return row['id'] if row else None

    def _fill_samples(self, *_args, keep: str | None = None):
        pid = self.project.currentData()
        names = [s['name'] for s in self.db.samples(pid)] if pid is not None else []
        self._refill(self.sample, names, keep)
        self._sample_changed()

    def _sample_changed(self, *_):
        sid = self._sample_id()
        self._refill(self.mineral, [m['name'] for m in self.db.minerals(sid)] if sid is not None else [])
        self._fill_fias()
        self._suggest_number()

    def _fill_fias(self, *_):
        sid = self._sample_id()
        names = []
        if sid is not None:
            has_mineral = bool(self.mineral.currentText().strip())
            mid = self._mineral_id(sid)
            if not has_mineral or mid is not None:
                names = [f['name'] for f in self.db.fias(sid, mid)]
        self._refill(self.fia, names)

    def _number_edited(self, _text):
        self._number_auto = False

    def _suggest_number(self):
        if self._number_auto:
            self.number.setText(self.db.next_inclusion_name(self._sample_id()))

    # --- запись ------------------------------------------------------------------------
    def _add(self, make_next: bool) -> bool:
        pid = self.project.currentData()
        sample = self.sample.currentText().strip()
        mineral = self.mineral.currentText().strip()
        fia = self.fia.currentText().strip()
        name = self.number.text().strip()
        if pid is None:
            QMessageBox.warning(self, 'Добавить включение', 'Сначала создайте проект (кнопка «Создать проект»).')
            return False
        if not sample or not name:
            QMessageBox.warning(self, 'Добавить включение', 'Укажите образец и номер включения.')
            return False
        try:
            liquid, vapor, solid, temp, room = self.state.values()
        except ValueError as exc:
            QMessageBox.warning(self, 'Ошибка ввода', f'Температура наблюдения: {exc}')
            return False
        sid = self._sample_id()
        if sid is not None and self.db.find_inclusion(sid, name):
            QMessageBox.warning(self, 'Добавить включение',
                                f'Включение «{name}» уже есть в образце {sample}. Выберите другой номер.')
            return False
        try:
            sid = self.db.get_or_create_sample(pid, sample)
            mid = self.db.get_or_create_mineral(sid, mineral) if mineral else None
            fid = self.db.get_or_create_fia(sid, mid, fia) if fia else None
            inc_id = self.db.add_inclusion(sid, name, mid, fid, self.inclusion_type.text().strip(),
                                           self.note.text().strip())
            self.db.set_initial_state(inc_id, liquid, vapor, solid, temp, room)
        except DatabaseError as exc:
            QMessageBox.warning(self, 'Добавить включение', str(exc))
            return False
        except Exception as exc:  # noqa: BLE001 — sqlite3.IntegrityError и др.
            QMessageBox.warning(self, 'Добавить включение', f'Операция не выполнена: {exc}')
            return False
        self.last_id = inc_id
        self.added.emit(inc_id)
        if not make_next:
            self.accept()
            return True
        # следующее включение: образец, минерал и группа сохраняются, остальное очищается
        self.status.setText(f'Добавлено включение {name} (образец {sample}). Можно вводить следующее.')
        self._number_auto = True
        self._fill_samples(keep=sample)
        self.mineral.setEditText(mineral)
        self._fill_fias()
        self.fia.setEditText(fia)
        self.state.reset()
        self.inclusion_type.clear()
        self.note.clear()
        self.number.setFocus()
        self.number.selectAll()
        return True


class InitialStateDialog(QDialog):
    """Правка исходного состояния включения (фазы, температура наблюдения) и примечания."""

    def __init__(self, parent, inclusion_label: str, inc):
        super().__init__(parent)
        self.setWindowTitle('Исходное состояние включения')
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f'<b>Включение:</b> {inclusion_label}'))
        self.state = PhaseStateEditor()
        v = [None if inc[k] is None else bool(inc[k]) for k in ('initial_liquid', 'initial_vapor', 'initial_solid')]
        self.state.set_values(*v, inc['initial_temperature_c'], bool(inc['initial_room']))
        lay.addWidget(self.state)
        lay.addWidget(_note_label(SKETCH_NOTE))
        form = QFormLayout()
        self.inclusion_type = QLineEdit(inc['inclusion_type'] or '')
        self.note = QLineEdit(inc['description'] or '')
        form.addRow('Тип включения', self.inclusion_type)
        form.addRow('Примечание', self.note)
        lay.addLayout(form)
        lay.addWidget(_buttons(self, self._accept))
        self.result = None

    def _accept(self):
        try:
            self.result = {'state': self.state.values(), 'note': self.note.text().strip(),
                           'inclusion_type': self.inclusion_type.text().strip()}
        except ValueError as exc:
            QMessageBox.warning(self, 'Ошибка ввода', f'Температура наблюдения: {exc}')
            return
        self.accept()


# --- сеансы и этапы ----------------------------------------------------------------------
class SessionDialog(QDialog):
    """Сеанс: дата и время ОПЫТА (редактируется; может быть не указана) и примечание."""

    def __init__(self, parent, inclusion_label: str, session: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle('Сеанс' if session else 'Новый сеанс')
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f'<b>Включение:</b> {inclusion_label}'))
        form = QFormLayout()
        self.date = QDateTimeEdit()
        self.date.setDisplayFormat('dd.MM.yyyy HH:mm')
        self.date.setCalendarPopup(True)
        self.unknown = QCheckBox('дата опыта не указана')
        self.unknown.toggled.connect(lambda on: self.date.setEnabled(not on))
        row = QHBoxLayout()
        row.addWidget(self.date)
        row.addWidget(self.unknown)
        row.addStretch()
        self.note = QLineEdit()
        form.addRow('Дата и время опыта', row)
        form.addRow('Примечание', self.note)
        lay.addLayout(form)
        hint = ('Дата опыта — когда проводился эксперимент; её можно изменить позже. Дата ввода данных '
                'записывается автоматически и отдельно.')
        if session is None:
            hint += ' Для нового сеанса предложены текущие дата и время — исправьте, если опыт был раньше.'
        lay.addWidget(_note_label(hint))
        if session and session['started_at']:
            self.date.setDateTime(QDateTime.fromString(session['started_at'], 'yyyy-MM-dd HH:mm'))
        else:
            now = QDateTime.currentDateTime()
            self.date.setDateTime(now.addSecs(-now.time().second()))
            self.unknown.setChecked(bool(session))       # у существующего сеанса без даты — «не указана»
        if session:
            self.note.setText(session['note'] or '')
        lay.addWidget(_buttons(self, self._accept))
        self.result = None

    def _accept(self):
        started = None if self.unknown.isChecked() else self.date.dateTime().toString('yyyy-MM-dd HH:mm')
        self.result = {'started_at': started, 'note': self.note.text().strip() or None}
        self.accept()


class StageDialog(QDialog):
    """Этап охлаждения или нагревания. Начальная и конечная температуры — только если известны."""

    def __init__(self, parent, title: str, direction: str = 'cooling', stage: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle('Этап' if stage else 'Новый этап')
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f'<b>{title}</b>'))
        form = QFormLayout()
        self.direction = QComboBox()
        for k, v in DIRECTIONS.items():
            self.direction.addItem(v, k)
        self.s_none = QRadioButton('не указана')
        self.s_room = QRadioButton('комнатная, точное значение не указано')
        self.s_value = QRadioButton('значение:')
        self.start = NumberEdit(placeholder='°C')
        self.start.setMaximumWidth(90)
        self._group = QButtonGroup(self)
        for rb in (self.s_none, self.s_room, self.s_value):
            self._group.addButton(rb)
        self.s_none.setChecked(True)
        self.start.setEnabled(False)
        self.s_value.toggled.connect(self.start.setEnabled)
        self.start.textEdited.connect(lambda: self.s_value.setChecked(True))
        sl = QVBoxLayout()
        sl.addWidget(self.s_none)
        sl.addWidget(self.s_room)
        row = QHBoxLayout()
        row.addWidget(self.s_value)
        row.addWidget(self.start)
        row.addWidget(QLabel('°C'))
        row.addStretch()
        sl.addLayout(row)
        self.end = NumberEdit(placeholder='°C; пусто — не указана')
        self.note = QLineEdit()
        form.addRow('Направление', self.direction)
        form.addRow('Начальная температура', sl)
        form.addRow('Конечная температура', self.end)
        form.addRow('Примечание', self.note)
        lay.addLayout(form)
        lay.addWidget(_note_label('Температуры этапа необязательны; окончание можно заполнить позже. Программа не '
                                  'подставляет значения и не достраивает переходы между этапами и сеансами.'))
        src = stage or {'direction': direction}
        self.direction.setCurrentIndex(self.direction.findData(src['direction']))
        if stage:
            if stage['start_temperature_c'] is not None:
                self.start.set_value(stage['start_temperature_c'])
                self.s_value.setChecked(True)
            elif stage['start_room']:
                self.s_room.setChecked(True)
            self.end.set_value(stage['end_temperature_c'])
            self.note.setText(stage['note'] or '')
        lay.addWidget(_buttons(self, self._accept))
        self.result = None

    def _accept(self):
        try:
            start = self.start.value() if self.s_value.isChecked() else None
            if self.s_value.isChecked() and start is None:
                raise ValueError('введите начальную температуру или выберите другой вариант')
            end = self.end.value()
        except ValueError as exc:
            QMessageBox.warning(self, 'Ошибка ввода', f'Температура этапа: {exc}')
            return
        self.result = {'direction': self.direction.currentData(), 'start_temperature_c': start,
                       'start_room': self.s_room.isChecked(), 'end_temperature_c': end,
                       'note': self.note.text().strip() or None}
        self.accept()


class AssignStageDialog(QDialog):
    """Ручная привязка наблюдений к этапу (или снятие привязки). История эксперимента не угадывается."""

    def __init__(self, parent, db: Database, inclusion_id: int, inclusion_label: str, observations: list[dict],
                 checked_ids: set[int] | None = None):
        super().__init__(parent)
        self.setWindowTitle('Привязать наблюдения к этапу')
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f'<b>Включение:</b> {inclusion_label}'))
        lay.addWidget(QLabel('Наблюдения:'))
        self.list = QListWidget()
        for o in observations:
            where = (f'сеанс {o["session_number"]}, этап {o["stage_position"]}' if o.get('stage_id') is not None
                     else 'без привязки к сеансу')
            it = QListWidgetItem(f'№ {o["id"]}: {observation_text(o)} — {where}')
            it.setData(Qt.UserRole, o['id'])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if checked_ids is None or o['id'] in checked_ids else Qt.Unchecked)
            self.list.addItem(it)
        lay.addWidget(self.list)
        form = QFormLayout()
        self.stage = QComboBox()
        self.stage.addItem('Без привязки к сеансу', None)
        for s in db.sessions(inclusion_id):
            for st in db.stages(s['id']):
                self.stage.addItem(f'{session_title(s)} — {stage_title(st)}', st['id'])
        if self.stage.count() > 1:
            self.stage.setCurrentIndex(1)
        form.addRow('Этап', self.stage)
        lay.addLayout(form)
        text = 'Привязку выполняет оператор по журналу опыта; сами измерения при этом не меняются.'
        if self.stage.count() == 1:
            text += ' У включения пока нет этапов: создайте сеанс и этап в панели «Ход эксперимента».'
        lay.addWidget(_note_label(text))
        lay.addWidget(_buttons(self, self._accept))
        self.result = None

    def _accept(self):
        ids = [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
               if self.list.item(i).checkState() == Qt.Checked]
        self.result = (ids, self.stage.currentData())
        self.accept()


# --- панель «Ход эксперимента» -------------------------------------------------------------
class MarkButton(QPushButton):
    """Кликабельная отметка наблюдения (та же запись, что и строка таблицы измерений)."""

    def __init__(self, obs: dict, panel: 'ExperimentPanel'):
        super().__init__(observation_text(obs))
        self.obs_id = obs['id']
        self.linked = obs.get('stage_id') is not None
        self.panel = panel
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(observation_tooltip(obs))
        self.setStyleSheet('QPushButton{text-align:left;padding:2px 6px;border:1px solid #b9b9b6;border-radius:4px;'
                           'background:#ffffff;color:#1f1f1f} QPushButton:hover{background:#fff6cc}')
        self.clicked.connect(lambda: panel.edit_requested.emit(self.obs_id))
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _menu(self, pos):
        menu = QMenu(self)
        menu.addAction('Изменить…', lambda: self.panel.edit_requested.emit(self.obs_id))
        menu.addAction('Привязать к этапу…', lambda: self.panel.assign_requested.emit([self.obs_id]))
        if self.linked:
            menu.addAction('Снять привязку к этапу', lambda: self.panel.unlink(self.obs_id))
        menu.addSeparator()
        menu.addAction('Удалить наблюдение…', lambda: self.panel.delete_requested.emit(self.obs_id))
        menu.exec(self.mapToGlobal(pos))


class StageTimeline(QWidget):
    """Вертикальная температурная линия этапа: теплее — выше, холоднее — ниже; стрелка показывает направление
    этапа. Отметки упорядочены по температуре; расстояния между ними условные (не масштаб)."""
    LINE_X = 11

    def __init__(self, stage: dict, observations: list[dict], panel: 'ExperimentPanel'):
        super().__init__()
        self.direction = stage['direction']
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 2, 2, 2)
        lay.setSpacing(4)
        start, end = QLabel(stage_start_text(stage)), QLabel(stage_end_text(stage))
        for lab in (start, end):
            lab.setStyleSheet(MUTED)
        # сверху всегда «теплее»: при охлаждении начало этапа вверху, при нагревании — внизу
        top, bottom = (start, end) if self.direction == 'cooling' else (end, start)
        lay.addWidget(top)
        self.marks: list[MarkButton] = []
        for o in sorted(observations, key=lambda x: (-x['temperature_c'], x['id'])):
            b = MarkButton(o, panel)
            self.marks.append(b)
            lay.addWidget(b)
        if not observations:
            empty = QLabel('наблюдений пока нет')
            empty.setStyleSheet(MUTED)
            lay.addWidget(empty)
        lay.addWidget(bottom)
        self._ends = (top, bottom)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        color = QColor(DIRECTION_STYLE[self.direction][1])
        x = self.LINE_X
        y0 = self._ends[0].geometry().center().y()
        y1 = self._ends[1].geometry().center().y()
        p.setPen(QPen(color, 2))
        p.drawLine(QPointF(x, y0), QPointF(x, y1))
        p.setBrush(QBrush(color))
        tip, sign = (y1, 1) if self.direction == 'cooling' else (y0, -1)      # остриё стрелки
        p.drawPolygon(QPolygonF([QPointF(x, tip + 5 * sign), QPointF(x - 5, tip - 4 * sign),
                                 QPointF(x + 5, tip - 4 * sign)]))
        tail = y0 if self.direction == 'cooling' else y1
        p.setBrush(QBrush(QColor('#ffffff')))
        p.drawEllipse(QPointF(x, tail), 4, 4)
        p.setBrush(QBrush(color))
        for b in self.marks:
            cy = b.geometry().center().y()
            p.drawEllipse(QPointF(x, cy), 4, 4)
            p.drawLine(QPointF(x + 4, cy), QPointF(b.geometry().left(), cy))


def _card(bg: str = '#ffffff', border: str = '#c4c4c0') -> QFrame:
    f = QFrame()
    f.setObjectName('card')
    f.setStyleSheet(f'QFrame#card{{background:{bg};border:1px solid {border};border-radius:6px}} '
                    'QFrame#card QLabel{color:#1f1f1f}')
    f.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
    return f


def _small_button(text: str, slot, tip: str = '') -> QPushButton:
    b = QPushButton(text)
    b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    return b


class ExperimentPanel(QWidget):
    """Сворачиваемая панель «Ход эксперимента» выбранного включения: исходное состояние и последовательные
    карточки этапов по сеансам. Работает с теми же записями, что и таблица измерений."""
    changed = Signal()                    # изменены сеансы, этапы, привязки или исходное состояние
    add_requested = Signal(int)           # stage_id: добавить наблюдение в этап (существующий диалог)
    edit_requested = Signal(int)          # obs_id: изменить наблюдение (существующий диалог)
    delete_requested = Signal(int)        # obs_id
    assign_requested = Signal(list)       # [obs_id, …]: привязать к этапу
    toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db: Database | None = None
        self.inclusion_id: int | None = None
        self.inclusion_label = ''
        self.stage_cards: dict[int, QFrame] = {}
        self.timelines: dict[int, StageTimeline] = {}
        self.unlinked_marks: list[MarkButton] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        head = QHBoxLayout()
        self.toggle = QToolButton()
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.DownArrow)
        self.toggle.setText('Ход эксперимента')
        self.toggle.setCheckable(True)
        self.toggle.setChecked(True)
        self.toggle.setAutoRaise(True)
        self.toggle.setStyleSheet('QToolButton{font-weight:bold}')
        self.toggle.toggled.connect(self._on_toggle)
        head.addWidget(self.toggle)
        self.caption = QLabel()
        self.caption.setStyleSheet(MUTED)
        head.addWidget(self.caption, 1)
        self.new_session_btn = _small_button('Новый сеанс…', self.new_session,
                                             'Начать новый сеанс измерений этого включения (в другой день — новый сеанс)')
        head.addWidget(self.new_session_btn)
        lay.addLayout(head)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.StyledPanel)
        lay.addWidget(self.scroll, 1)
        self.set_inclusion(None, None, '')

    # --- состояние -------------------------------------------------------------------
    def is_expanded(self) -> bool:
        return self.toggle.isChecked()

    def set_expanded(self, on: bool):
        self.toggle.setChecked(on)

    def has_body(self) -> bool:
        return self.is_expanded() and self.inclusion_id is not None

    def _on_toggle(self, on: bool):
        self.toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self._apply_visibility()
        self.toggled.emit(on)

    def _apply_visibility(self):
        self.scroll.setVisible(self.has_body())
        self.new_session_btn.setVisible(self.inclusion_id is not None)

    def set_inclusion(self, db: Database | None, inclusion_id: int | None, label: str):
        self.db, self.inclusion_id, self.inclusion_label = db, inclusion_id, label
        self.refresh()

    # --- построение ------------------------------------------------------------------
    def refresh(self):
        self.stage_cards, self.timelines, self.unlinked_marks = {}, {}, []
        self._apply_visibility()
        if self.db is None or self.inclusion_id is None or self.db.inclusion(self.inclusion_id) is None:
            self.inclusion_id = None
            self._apply_visibility()
            self.caption.setText('выберите включение в дереве, чтобы увидеть и вести ход эксперимента')
            self._set_content(QWidget())
            return
        db, inc_id = self.db, self.inclusion_id
        inc = db.inclusion(inc_id)
        obs = db.observations('inclusion_id=?', (inc_id,))
        by_stage: dict = {}
        for o in obs:
            by_stage.setdefault(o['stage_id'], []).append(o)
        sessions = db.sessions(inc_id)
        self.caption.setText(f'включение {inc["name"]}: сеансов {len(sessions)}, наблюдений {len(obs)}'
                             + (f', без привязки к сеансу {len(by_stage.get(None, []))}' if by_stage.get(None) else ''))
        content = QWidget()
        row = QHBoxLayout(content)
        row.setContentsMargins(6, 6, 6, 6)
        row.setSpacing(8)
        row.addWidget(self._initial_card(inc), 0, Qt.AlignTop)
        for s in sessions:
            row.addWidget(self._arrow(), 0, Qt.AlignVCenter)
            row.addWidget(self._session_card(s, by_stage), 0, Qt.AlignTop)
        if by_stage.get(None):
            row.addWidget(self._unlinked_card(by_stage[None]), 0, Qt.AlignTop)
        if not sessions:
            hint = _note_label('Сеансов пока нет. Нажмите «Новый сеанс…», затем добавьте этап «Охлаждение» или '
                               '«Нагревание» и вносите наблюдения прямо в этап. Таблицей ниже можно пользоваться '
                               'и без сеансов.')
            hint.setMaximumWidth(360)
            row.addWidget(hint, 0, Qt.AlignTop)
        row.addStretch(1)
        self._set_content(content)

    def _set_content(self, widget: QWidget):
        # прежнее содержимое удаляется отложенно: обновление может идти из обработчика кнопки этого содержимого
        old = self.scroll.takeWidget()
        if old is not None:
            old.hide()
            old.deleteLater()
        self.scroll.setWidget(widget)

    @staticmethod
    def _arrow() -> QLabel:
        lab = QLabel('→')
        lab.setStyleSheet('color:#6b6b68;font-size:16pt')
        return lab

    def _initial_card(self, inc) -> QFrame:
        card = _card()
        v = QVBoxLayout(card)
        v.addWidget(QLabel('<b>Исходное состояние</b>'))
        phases = [None if inc[k] is None else bool(inc[k]) for k in ('initial_liquid', 'initial_vapor', 'initial_solid')]
        sketch = InclusionSketch(compact=True)
        sketch.set_phases(*phases)
        v.addWidget(sketch)
        cap = QLabel('Условная схема')
        cap.setAlignment(Qt.AlignCenter)
        cap.setStyleSheet(MUTED)
        cap.setToolTip(SKETCH_NOTE)
        v.addWidget(cap)
        for text in (phases_text(*phases), initial_temp_text(inc['initial_temperature_c'], inc['initial_room'])):
            lab = QLabel(text)
            lab.setWordWrap(True)
            v.addWidget(lab)
        if inc['description']:
            v.addWidget(_note_label(inc['description']))
        v.addWidget(_small_button('Изменить…', self.edit_initial))
        v.addStretch()
        card.setFixedWidth(190)
        self.initial_card = card
        return card

    def _session_card(self, s: dict, by_stage: dict) -> QFrame:
        card = _card('#fafaf8')
        v = QVBoxLayout(card)
        head = QHBoxLayout()
        title = QLabel(f'<b>{session_title(s)}</b>')
        head.addWidget(title)
        head.addStretch()
        sid = s['id']
        if not s['finished']:
            head.addWidget(_small_button('+ Охлаждение', lambda: self.new_stage(sid, 'cooling'),
                                         'Добавить этап охлаждения в конец сеанса'))
            head.addWidget(_small_button('+ Нагревание', lambda: self.new_stage(sid, 'heating'),
                                         'Добавить этап нагревания в конец сеанса'))
            head.addWidget(_small_button('Завершить сеанс', lambda: self.finish_session(sid, True),
                                         'Сеанс закрывается для новых этапов; исследование можно продолжить позже '
                                         'новым сеансом или вернуться к этому'))
        else:
            head.addWidget(_small_button('Продолжить сеанс', lambda: self.finish_session(sid, False),
                                         'Снова открыть сеанс для добавления этапов и наблюдений'))
        more = QToolButton()
        more.setText('⋯')
        more.setPopupMode(QToolButton.InstantPopup)
        more.setToolTip('Изменить дату и примечание сеанса, удалить сеанс')
        menu = QMenu(more)
        menu.addAction('Изменить дату и примечание…', lambda: self.edit_session(sid))
        menu.addAction('Удалить сеанс…', lambda: self.delete_session(sid))
        more.setMenu(menu)
        head.addWidget(more)
        v.addLayout(head)
        if s['note']:
            v.addWidget(_note_label(s['note']))
        row = QHBoxLayout()
        row.setSpacing(6)
        stages = self.db.stages(sid)
        for i, st in enumerate(stages):
            if i:
                row.addWidget(self._arrow(), 0, Qt.AlignVCenter)
            row.addWidget(self._stage_card(s, st, by_stage.get(st['id'], [])), 0, Qt.AlignTop)
        if not stages:
            row.addWidget(_note_label('Этапов пока нет: добавьте «Охлаждение» или «Нагревание».'
                                      if not s['finished'] else 'В сеансе нет этапов.'))
        row.addStretch()
        v.addLayout(row)
        v.addStretch()
        return card

    def _stage_card(self, s: dict, st: dict, observations: list[dict]) -> QFrame:
        _arrow, color, bg = DIRECTION_STYLE[st['direction']]
        card = _card(bg, color)
        v = QVBoxLayout(card)
        head = QHBoxLayout()
        title = QLabel(f'<b>{stage_title(st)}</b>')
        title.setStyleSheet(f'color:{color}')
        head.addWidget(title)
        head.addStretch()
        stid = st['id']
        more = QToolButton()
        more.setText('⋯')
        more.setPopupMode(QToolButton.InstantPopup)
        more.setToolTip('Изменить или удалить этап')
        menu = QMenu(more)
        menu.addAction('Изменить этап…', lambda: self.edit_stage(stid))
        menu.addAction('Удалить этап…', lambda: self.delete_stage(stid))
        more.setMenu(menu)
        head.addWidget(more)
        v.addLayout(head)
        if st['note']:
            v.addWidget(_note_label(st['note']))
        tl = StageTimeline(st, observations, self)
        v.addWidget(tl)
        add = _small_button('Добавить наблюдение', lambda: self.add_requested.emit(stid),
                            'Открыть диалог наблюдения; запись появится и здесь, и в таблице измерений')
        v.addWidget(add)
        v.addStretch()
        card.setMinimumWidth(215)
        card.add_button = add
        self.stage_cards[stid] = card
        self.timelines[stid] = tl
        return card

    def _unlinked_card(self, observations: list[dict]) -> QFrame:
        card = _card('#f4f4f1')
        v = QVBoxLayout(card)
        v.addWidget(QLabel(f'<b>Без привязки к сеансу ({len(observations)})</b>'))
        v.addWidget(_note_label('Сеанс и этап этих наблюдений не записаны. Программа не восстанавливает ход опыта: '
                                'привязать можно только вручную.'))
        for o in sorted(observations, key=lambda x: (-x['temperature_c'], x['id'])):
            b = MarkButton(o, self)
            self.unlinked_marks.append(b)
            v.addWidget(b)
        ids = [o['id'] for o in observations]
        v.addWidget(_small_button('Привязать к этапу…', lambda: self.assign_requested.emit(ids)))
        v.addStretch()
        card.setFixedWidth(250)
        self.unlinked_card = card
        return card

    # --- действия --------------------------------------------------------------------
    def _guard(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except DatabaseError as exc:
            QMessageBox.warning(self, 'Ход эксперимента', str(exc))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, 'Ход эксперимента', f'Операция не выполнена: {exc}')
        return None

    def _done(self):
        self.refresh()
        self.changed.emit()

    def edit_initial(self):
        inc = self.db.inclusion(self.inclusion_id)
        dlg = InitialStateDialog(self, self.inclusion_label, inc)
        if dlg.exec() and dlg.result:
            inc_id = self.inclusion_id

            def save():
                self.db.set_initial_state(inc_id, *dlg.result['state'])
                self.db.set_inclusion_note(inc_id, dlg.result['note'])
                self.db.set_inclusion_type(inc_id, dlg.result['inclusion_type'])
            self._guard(save)
            self._done()

    def new_session(self):
        if self.inclusion_id is None:
            return None
        dlg = SessionDialog(self, self.inclusion_label)
        if dlg.exec() and dlg.result:
            sid = self._guard(self.db.add_session, self.inclusion_id, dlg.result['started_at'], dlg.result['note'])
            self._done()
            return sid
        return None

    def edit_session(self, session_id: int):
        dlg = SessionDialog(self, self.inclusion_label, self.db.session(session_id))
        if dlg.exec() and dlg.result:
            self._guard(self.db.update_session, session_id, **dlg.result)
            self._done()

    def finish_session(self, session_id: int, finished: bool):
        self._guard(self.db.set_session_finished, session_id, finished)
        self._done()

    def delete_session(self, session_id: int):
        s = self.db.session(session_id)
        n = self.db.count_observations('session_id=?', (session_id,))
        if QMessageBox.question(self, 'Удаление сеанса',
                                f'Удалить «{session_title(s)}» со всеми этапами?\nНаблюдения ({n}) не удаляются: '
                                'они останутся в таблице «без привязки к сеансу».') != QMessageBox.Yes:
            return
        self._guard(self.db.delete_session, session_id)
        self._done()

    def new_stage(self, session_id: int, direction: str):
        s = self.db.session(session_id)
        dlg = StageDialog(self, session_title(s), direction)
        if dlg.exec() and dlg.result:
            stid = self._guard(self.db.add_stage, session_id, **dlg.result)
            self._done()
            return stid
        return None

    def edit_stage(self, stage_id: int):
        st = self.db.stage(stage_id)
        dlg = StageDialog(self, f'{session_title(self.db.session(st["session_id"]))} — этап {st["number"]}',
                          stage=st)
        if dlg.exec() and dlg.result:
            self._guard(self.db.update_stage, stage_id, **dlg.result)
            self._done()

    def delete_stage(self, stage_id: int):
        st = self.db.stage(stage_id)
        n = self.db.count_observations('stage_id=?', (stage_id,))
        if QMessageBox.question(self, 'Удаление этапа',
                                f'Удалить «{stage_title(st)}»?\nНаблюдения ({n}) не удаляются: они останутся в '
                                'таблице «без привязки к сеансу».') != QMessageBox.Yes:
            return
        self._guard(self.db.delete_stage, stage_id)
        self._done()

    def unlink(self, obs_id: int):
        self._guard(self.db.set_observation_stage, obs_id, None)
        self._done()
