"""Запуск: python -m fluid_app [путь_к_базе.sqlite]"""
from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler

from . import APP_NAME, APP_TITLE, __version__
from .paths import log_file_path


def setup_logging() -> None:
    handler = RotatingFileHandler(log_file_path(), maxBytes=2_000_000, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    root.addHandler(console)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='fluid_app', description=APP_TITLE)
    parser.add_argument('database', nargs='?', help='файл базы .sqlite (по умолчанию ~/.local/share/fluidcalc/)')
    parser.add_argument('--version', action='version', version=f'{APP_NAME} {__version__}')
    args = parser.parse_args(argv)
    setup_logging()
    log = logging.getLogger('fluid_app')
    log.info('Запуск %s %s, Python %s', APP_NAME, __version__, sys.version.split()[0])

    from PySide6.QtCore import QLocale, QTranslator, QLibraryInfo
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName('FluidCalc')
    app.setDesktopFileName('fluidcalc')
    QLocale.setDefault(QLocale(QLocale.Russian, QLocale.Russia))
    translator = QTranslator(app)    # русские стандартные кнопки Qt, если перевод установлен
    if translator.load(QLocale(QLocale.Russian), 'qtbase', '_', QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)
    from .paths import project_root
    icon = project_root() / 'fluid_app' / 'resources' / 'fluidcalc.svg'
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    def excepthook(exc_type, exc, tb):
        log.critical('Необработанная ошибка', exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)
    sys.excepthook = excepthook

    from .gui.main_window import MainWindow
    win = MainWindow(args.database)
    win.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
