"""Масштаб шрифта всего приложения (меню «Вид → Размер шрифта»).

Масштаб применяется к шрифту приложения по умолчанию И к шрифтам классов, которые платформа задаёт отдельно
(на Windows — меню, строка меню, окна сообщений, подсказки, строка состояния; на KDE — также кнопки, заголовки
таблиц и др.). Исходные шрифты запоминаются при первом применении, поэтому масштаб всегда отсчитывается от
системного шрифта, а не накапливается. Высота строк таблиц пересчитывается по шрифту (Qt сам её не меняет).
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QFrame, QScrollArea, QTableView, QToolTip,
                               QVBoxLayout, QWidget)

SCALES = (100, 110, 125, 150, 175)          # %, шаг 10–25 %
DEFAULT_SCALE = 100
SETTINGS_KEY = 'font_scale'
# классы со «своими» шрифтами платформы (QApplicationPrivate::initializeWidgetFontHash)
FONT_CLASSES = ('QMenu', 'QMenuBar', 'QMenuItem', 'QMessageBox', 'QLabel', 'QTipLabel', 'QStatusBar',
                'QMdiSubWindowTitleBar', 'QDockWidgetTitle', 'QPushButton', 'QCheckBox', 'QRadioButton',
                'QToolButton', 'QAbstractItemView', 'QListView', 'QHeaderView', 'QListBox', 'QComboMenuItem',
                'QComboLineEdit', 'QSmallFont', 'QMiniFont', 'QGroupBox', 'QTabButton', 'QTabBar')

_state: dict = {'app': None, 'base': None, 'scale': DEFAULT_SCALE, 'filter': None}


def clamp_scale(value) -> int:
    """Ближайший допустимый масштаб; нечисловое значение — масштаб по умолчанию."""
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        return DEFAULT_SCALE
    return min(SCALES, key=lambda s: (abs(s - v), s))


def current_scale() -> int:
    return _state['scale']


def factor() -> float:
    return _state['scale'] / 100.0


def px(n: float) -> int:
    """Размер в пикселях, заданный для масштаба 100 %, — для текущего масштаба шрифта."""
    return int(round(n * factor()))


def _scaled(font: QFont, scale: int) -> QFont:
    f = QFont(font)
    if font.pointSizeF() > 0:
        f.setPointSizeF(font.pointSizeF() * scale / 100.0)
    elif font.pixelSize() > 0:
        f.setPixelSize(max(1, round(font.pixelSize() * scale / 100.0)))
    return f


def _base_fonts(app) -> dict:
    if _state['app'] is not app or _state['base'] is None:
        base = {None: QFont(app.font())}                 # шрифт по умолчанию — первым (см. apply_font_scale)
        for cls in FONT_CLASSES:
            base[cls] = QFont(app.font(cls))
        _state.update(app=app, base=base, scale=DEFAULT_SCALE, filter=None)
    return _state['base']


def row_height(view: QWidget) -> int:
    """Высота строки таблицы под текущий шрифт (при 9 pt — стандартные для Qt 30 пикселей)."""
    return max(24, int(round(QFontMetrics(view.font()).height() * 1.75)))


def fit_table(view: QTableView) -> None:
    view.verticalHeader().setDefaultSectionSize(row_height(view))


class _TablePolisher(QObject):
    """Таблицы, создаваемые после смены масштаба (диалоги импорта и т. п.), получают высоту строк по шрифту."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Polish and isinstance(obj, QTableView):
            fit_table(obj)
        return False


def apply_font_scale(scale) -> int:
    """Установить масштаб шрифта всего приложения. Возвращает применённый масштаб (%)."""
    app = QApplication.instance()
    scale = clamp_scale(scale)
    base = _base_fonts(app)
    # QApplication.setFont(font) без имени класса сбрасывает шрифты классов, поэтому сначала — общий шрифт
    for cls, font in base.items():
        if cls is None:
            app.setFont(_scaled(font, scale))
        else:
            app.setFont(_scaled(font, scale), cls)
    QToolTip.setFont(_scaled(base['QTipLabel'], scale))
    _state['scale'] = scale
    if _state['filter'] is None:
        _state['filter'] = _TablePolisher(app)
        app.installEventFilter(_state['filter'])
    for w in app.allWidgets():
        if isinstance(w, QTableView):
            fit_table(w)
        elif isinstance(w, QAbstractItemView):
            w.doItemsLayout()
    return scale


def step_scale(direction: int) -> int:
    """Следующий (direction > 0) или предыдущий допустимый масштаб."""
    i = SCALES.index(current_scale())
    return SCALES[max(0, min(len(SCALES) - 1, i + (1 if direction > 0 else -1)))]


# --- диалоги с прокруткой: при крупном шрифте окно не выходит за экран -----------------
def scroll_body(dialog: QDialog) -> tuple[QVBoxLayout, QVBoxLayout]:
    """Разметка диалога: прокручиваемое содержимое + неподвижная нижняя строка кнопок.

    Возвращает (разметка содержимого, разметка всего окна — для кнопок)."""
    outer = QVBoxLayout(dialog)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    body = QWidget()
    lay = QVBoxLayout(body)
    lay.setContentsMargins(0, 0, 0, 0)
    area.setWidget(body)
    outer.addWidget(area, 1)
    dialog._scroll_area = area
    return lay, outer


def fit_to_screen(dialog: QDialog) -> None:
    """Начальный размер диалога со scroll_body: по содержимому, но не больше доступной области экрана."""
    area = getattr(dialog, '_scroll_area', None)
    hint = dialog.sizeHint()
    if area is not None:
        body = area.widget().sizeHint()
        bar = area.verticalScrollBar().sizeHint().width()
        m = dialog.layout().contentsMargins()
        rest = sum(dialog.layout().itemAt(i).sizeHint().height() + dialog.layout().spacing()
                   for i in range(1, dialog.layout().count()))
        width = max(hint.width(), body.width() + bar + m.left() + m.right(), dialog.minimumWidth())
        height = body.height() + rest + m.top() + m.bottom() + 4
    else:
        width, height = hint.width(), hint.height()
    screen = dialog.screen() or QApplication.primaryScreen()
    if screen is not None:
        avail = screen.availableGeometry()
        width = min(width, int(avail.width() * 0.95))
        height = min(height, int(avail.height() * 0.9))
    dialog.resize(width, height)
