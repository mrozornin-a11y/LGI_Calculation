"""Пути к данным пользователя (XDG) и журналу. Только локальные файлы."""
from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    base = os.environ.get('XDG_DATA_HOME') or str(Path.home() / '.local' / 'share')
    d = Path(base) / 'fluidcalc'
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_db_path() -> Path:
    return data_dir() / 'fluidcalc.sqlite'


def log_file_path() -> Path:
    d = data_dir() / 'logs'
    d.mkdir(parents=True, exist_ok=True)
    return d / 'fluidcalc.log'
