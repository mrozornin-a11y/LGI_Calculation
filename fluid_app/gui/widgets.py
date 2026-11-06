"""Мелкие общие элементы интерфейса."""
from __future__ import annotations

from html import escape

from PySide6.QtWidgets import QComboBox, QLineEdit

from ..importer import parse_number


class TriStateCombo(QComboBox):
    """Логический признак: не указано / да / нет (None / True / False)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.addItem('не указано', None)
        self.addItem('да', True)
        self.addItem('нет', False)

    def value(self):
        return self.currentData()

    def set_value(self, v):
        self.setCurrentIndex({None: 0, True: 1, False: 2}[None if v is None else bool(v)])


class HomogCombo(QComboBox):
    def __init__(self, parent=None, allow_critical=True):
        super().__init__(parent)
        self.addItem('не указано', None)
        self.addItem('в жидкость (L)', 'liquid')
        self.addItem('в газ (V)', 'vapor')
        if allow_critical:
            self.addItem('критическая', 'critical')

    def value(self):
        return self.currentData()

    def set_value(self, v):
        i = self.findData(v)
        self.setCurrentIndex(i if i >= 0 else 0)


class NumberEdit(QLineEdit):
    """Число с точкой или запятой; пусто — None."""

    def __init__(self, parent=None, placeholder=''):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)

    def value(self):
        return parse_number(self.text())   # ValueError при ошибке

    def set_value(self, v):
        self.setText('' if v is None else f'{v:g}'.replace('.', ','))


def passport_html(rows: list[tuple[str, str]], title: str = 'Паспорт результата') -> str:
    css = ('<style>td{padding:3px 6px;vertical-align:top} td.k{color:#52514e;white-space:nowrap}'
           ' .warn{color:#8a5a00} .err{color:#a4161a}</style>')
    out = [css, f'<h3>{escape(title)}</h3><table>']
    for k, v in rows:
        cls = ''
        if k == 'Предупреждение':
            cls = ' class="warn"'
        elif k in ('Причина', 'Сообщение ядра (исходное)'):
            cls = ' class="err"'
        out.append(f'<tr><td class="k">{escape(k)}</td><td{cls}>{escape(str(v))}</td></tr>')
    out.append('</table>')
    return ''.join(out)
