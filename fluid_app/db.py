"""Хранение данных в SQLite: иерархия проект → образец → минерал → FIA → включение →
наблюдения; ход эксперимента: включение → сеансы → этапы охлаждения/нагревания → наблюдения;
неизменяемые версии расчётов, журнал импорта. Миграции через PRAGMA user_version.
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .methods import KINDS

log = logging.getLogger(__name__)

# Перечень типов наблюдений схемы v1 зафиксирован: новые типы добавляются миграцией, а не правкой v1.
_KIND_CHECK = ', '.join(f"'{k}'" for k in ('Tm_ice', 'Tm_clath', 'Tm_CO2', 'Th_CO2', 'Th_total', 'Te'))

MIGRATIONS: list[str] = [
    # v1 — исходная схема
    f"""
    CREATE TABLE projects(
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        created_at TEXT NOT NULL);
    CREATE TABLE samples(
        id INTEGER PRIMARY KEY,
        project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        description TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(project_id, name));
    CREATE TABLE minerals(
        id INTEGER PRIMARY KEY,
        sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        description TEXT,
        UNIQUE(sample_id, name));
    CREATE TABLE fias(
        id INTEGER PRIMARY KEY,
        sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
        mineral_id INTEGER REFERENCES minerals(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        description TEXT);
    CREATE TABLE inclusions(
        id INTEGER PRIMARY KEY,
        sample_id INTEGER NOT NULL REFERENCES samples(id) ON DELETE CASCADE,
        mineral_id INTEGER REFERENCES minerals(id) ON DELETE CASCADE,
        fia_id INTEGER REFERENCES fias(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        inclusion_type TEXT,
        description TEXT,
        UNIQUE(sample_id, name));
    CREATE TABLE observations(
        id INTEGER PRIMARY KEY,
        inclusion_id INTEGER NOT NULL REFERENCES inclusions(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK(kind IN ({_KIND_CHECK})),
        temperature_c REAL NOT NULL,
        uncertainty_c REAL CHECK(uncertainty_c IS NULL OR uncertainty_c >= 0),
        homogenization_to TEXT CHECK(homogenization_to IS NULL OR homogenization_to IN ('liquid','vapor','critical')),
        liquid_co2_present INTEGER CHECK(liquid_co2_present IS NULL OR liquid_co2_present IN (0,1)),
        vapor_co2_present INTEGER CHECK(vapor_co2_present IS NULL OR vapor_co2_present IN (0,1)),
        aqueous_brine_present INTEGER CHECK(aqueous_brine_present IS NULL OR aqueous_brine_present IN (0,1)),
        co2_purity_confirmed INTEGER CHECK(co2_purity_confirmed IS NULL OR co2_purity_confirmed IN (0,1)),
        phase_notes TEXT,
        comment TEXT,
        source TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL);
    CREATE INDEX idx_obs_inclusion ON observations(inclusion_id);
    CREATE TABLE calc_runs(
        id INTEGER PRIMARY KEY,
        created_at TEXT NOT NULL,
        project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
        scope TEXT,
        app_version TEXT, core_version TEXT, python_version TEXT,
        coolprop_version TEXT, platform TEXT,
        n_total INTEGER, n_ok INTEGER, n_error INTEGER, n_skipped INTEGER);
    CREATE TABLE results(
        id INTEGER PRIMARY KEY,
        run_id INTEGER NOT NULL REFERENCES calc_runs(id) ON DELETE CASCADE,
        observation_id INTEGER REFERENCES observations(id) ON DELETE SET NULL,
        project_name TEXT, sample_name TEXT, mineral_name TEXT, fia_name TEXT, inclusion_name TEXT,
        kind TEXT NOT NULL,
        inputs_json TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('ok','error','skipped')),
        method_key TEXT, result_kind TEXT, value REAL, unit TEXT,
        extras_json TEXT, model TEXT, doi TEXT, citation TEXT,
        assumptions TEXT, scope TEXT, warnings_json TEXT,
        message TEXT, message_original TEXT);
    CREATE INDEX idx_results_run ON results(run_id);
    CREATE TABLE import_log(
        id INTEGER PRIMARY KEY,
        created_at TEXT NOT NULL,
        project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
        file_name TEXT, file_sha256 TEXT, sheet TEXT, mapping_json TEXT,
        n_rows INTEGER, n_imported INTEGER, n_errors INTEGER, n_duplicates INTEGER);
    """,
    # v2 — объёмная доля углекислотной фазы включения (оценка при комнатной температуре)
    """
    ALTER TABLE inclusions ADD COLUMN carbonic_fraction REAL
        CHECK(carbonic_fraction IS NULL OR (carbonic_fraction >= 0 AND carbonic_fraction <= 1));
    ALTER TABLE inclusions ADD COLUMN carbonic_fraction_unc REAL
        CHECK(carbonic_fraction_unc IS NULL OR (carbonic_fraction_unc >= 0 AND carbonic_fraction_unc <= 1));
    ALTER TABLE inclusions ADD COLUMN carbonic_fraction_method TEXT;
    ALTER TABLE inclusions ADD COLUMN carbonic_fraction_temp_c REAL;
    """,
    # v3 — новые типы наблюдений (Tm гидрогалита, T растворения галита), фазовые условия при переходе, данные
    # КР-спектроскопии для Tm CO₂; независимое ограничение условий захвата и сведения о составе солей включения.
    # Таблица наблюдений пересоздаётся: в v1 перечень типов был зашит в CHECK; теперь тип проверяет приложение.
    # Данные и номера (id) наблюдений сохраняются; миграция выполняется при выключенных внешних ключах.
    """
    CREATE TABLE observations_v3(
        id INTEGER PRIMARY KEY,
        inclusion_id INTEGER NOT NULL REFERENCES inclusions(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        temperature_c REAL NOT NULL,
        uncertainty_c REAL CHECK(uncertainty_c IS NULL OR uncertainty_c >= 0),
        homogenization_to TEXT CHECK(homogenization_to IS NULL OR homogenization_to IN ('liquid','vapor','critical')),
        liquid_co2_present INTEGER CHECK(liquid_co2_present IS NULL OR liquid_co2_present IN (0,1)),
        vapor_co2_present INTEGER CHECK(vapor_co2_present IS NULL OR vapor_co2_present IN (0,1)),
        aqueous_brine_present INTEGER CHECK(aqueous_brine_present IS NULL OR aqueous_brine_present IN (0,1)),
        co2_purity_confirmed INTEGER CHECK(co2_purity_confirmed IS NULL OR co2_purity_confirmed IN (0,1)),
        phase_notes TEXT,
        comment TEXT,
        source TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        vapor_present_at_transition INTEGER
            CHECK(vapor_present_at_transition IS NULL OR vapor_present_at_transition IN (0,1)),
        phase_identified INTEGER CHECK(phase_identified IS NULL OR phase_identified IN (0,1)),
        raman_species TEXT);
    INSERT INTO observations_v3(id, inclusion_id, kind, temperature_c, uncertainty_c, homogenization_to,
        liquid_co2_present, vapor_co2_present, aqueous_brine_present, co2_purity_confirmed, phase_notes, comment,
        source, created_at, updated_at)
      SELECT id, inclusion_id, kind, temperature_c, uncertainty_c, homogenization_to, liquid_co2_present,
        vapor_co2_present, aqueous_brine_present, co2_purity_confirmed, phase_notes, comment, source, created_at,
        updated_at FROM observations;
    DROP TABLE observations;
    ALTER TABLE observations_v3 RENAME TO observations;
    CREATE INDEX idx_obs_inclusion ON observations(inclusion_id);
    ALTER TABLE inclusions ADD COLUMN other_salts_confirmed INTEGER
        CHECK(other_salts_confirmed IS NULL OR other_salts_confirmed IN (0,1));
    ALTER TABLE inclusions ADD COLUMN trap_temperature_c REAL;
    ALTER TABLE inclusions ADD COLUMN trap_temperature_max_c REAL;
    ALTER TABLE inclusions ADD COLUMN trap_pressure_bar REAL;
    ALTER TABLE inclusions ADD COLUMN trap_pressure_max_bar REAL;
    ALTER TABLE inclusions ADD COLUMN trap_constraint_source TEXT;
    ALTER TABLE inclusions ADD COLUMN coeval_documented INTEGER
        CHECK(coeval_documented IS NULL OR coeval_documented IN (0,1));
    ALTER TABLE inclusions ADD COLUMN coeval_note TEXT;
    """,
    # v4 — ход эксперимента: сеансы (дата опыта задаётся оператором и не равна дате ввода), последовательные этапы
    # охлаждения/нагревания, привязка наблюдения к этапу; исходное состояние включения (наблюдаемые фазы и температура
    # наблюдения). Все новые поля необязательны: прежние наблюдения остаются «без привязки к сеансу», прежние
    # включения — с исходным состоянием «не указано». Расчёты эти сведения не используют.
    """
    CREATE TABLE sessions(
        id INTEGER PRIMARY KEY,
        inclusion_id INTEGER NOT NULL REFERENCES inclusions(id) ON DELETE CASCADE,
        started_at TEXT,
        note TEXT,
        finished INTEGER NOT NULL DEFAULT 0 CHECK(finished IN (0,1)),
        created_at TEXT NOT NULL);
    CREATE INDEX idx_sessions_inclusion ON sessions(inclusion_id);
    CREATE TABLE stages(
        id INTEGER PRIMARY KEY,
        session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        direction TEXT NOT NULL CHECK(direction IN ('cooling','heating')),
        start_temperature_c REAL,
        start_room INTEGER NOT NULL DEFAULT 0 CHECK(start_room IN (0,1)),
        end_temperature_c REAL,
        note TEXT,
        created_at TEXT NOT NULL);
    CREATE INDEX idx_stages_session ON stages(session_id);
    ALTER TABLE observations ADD COLUMN stage_id INTEGER REFERENCES stages(id) ON DELETE SET NULL;
    CREATE INDEX idx_obs_stage ON observations(stage_id);
    ALTER TABLE inclusions ADD COLUMN initial_liquid INTEGER CHECK(initial_liquid IS NULL OR initial_liquid IN (0,1));
    ALTER TABLE inclusions ADD COLUMN initial_vapor INTEGER CHECK(initial_vapor IS NULL OR initial_vapor IN (0,1));
    ALTER TABLE inclusions ADD COLUMN initial_solid INTEGER CHECK(initial_solid IS NULL OR initial_solid IN (0,1));
    ALTER TABLE inclusions ADD COLUMN initial_temperature_c REAL;
    ALTER TABLE inclusions ADD COLUMN initial_room INTEGER NOT NULL DEFAULT 0 CHECK(initial_room IN (0,1));
    """,
]
SCHEMA_VERSION = len(MIGRATIONS)

OBS_FLAG_COLUMNS = ('liquid_co2_present', 'vapor_co2_present', 'aqueous_brine_present', 'co2_purity_confirmed')
OBS_EXTRA_FLAG_COLUMNS = ('vapor_present_at_transition', 'phase_identified')      # схема v3
RAMAN_SPECIES_VALUES = ('CO2', 'CO2+CH4', 'CO2+N2', 'CO2+CH4+N2')
# первые восемь столбцов определяют «то же самое наблюдение» при поиске дубликатов — порядок не менять
OBS_COLUMNS = ('kind', 'temperature_c', 'uncertainty_c', 'homogenization_to', *OBS_FLAG_COLUMNS,
               'phase_notes', 'comment', 'source', *OBS_EXTRA_FLAG_COLUMNS, 'raman_species')
INCLUSION_CONTEXT_COLUMNS = ('other_salts_confirmed', 'trap_temperature_c', 'trap_temperature_max_c',
                             'trap_pressure_bar', 'trap_pressure_max_bar', 'trap_constraint_source',
                             'coeval_documented', 'coeval_note')


INITIAL_PHASE_COLUMNS = ('initial_liquid', 'initial_vapor', 'initial_solid')                      # схема v4
DIRECTIONS = {'cooling': 'Охлаждение', 'heating': 'Нагревание'}
SESSION_DATE_FORMAT = '%Y-%m-%d %H:%M'       # дата и время опыта (местное время лаборатории), вводит оператор


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def _b2i(v):
    return None if v is None else int(bool(v))


def _i2b(v):
    return None if v is None else bool(v)


class DatabaseError(Exception):
    pass


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existed = self.path.exists() and self.path.stat().st_size > 0
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys = ON')
        self._migrate(existed)

    # --- служебное ---------------------------------------------------------
    def _migrate(self, existed: bool) -> None:
        version = self.conn.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA_VERSION:
            raise DatabaseError(f'База создана более новой версией программы (схема {version} > {SCHEMA_VERSION}).')
        if version == SCHEMA_VERSION:
            return
        if existed and version > 0:
            backup = self.path.with_name(f'{self.path.stem}.bak-v{version}-{datetime.now():%Y%m%d-%H%M%S}{self.path.suffix}')
            self.backup_to(backup)
            log.info('Резервная копия перед миграцией: %s', backup)
        for v in range(version, SCHEMA_VERSION):
            log.info('Миграция схемы %s -> %s', v, v + 1)
            # пересоздание таблиц допустимо только при выключенных внешних ключах (иначе DROP TABLE обнулит ссылки
            # результатов на наблюдения); PRAGMA действует только вне транзакции
            self.conn.commit()
            self.conn.execute('PRAGMA foreign_keys = OFF')
            try:
                with self.conn:
                    self.conn.executescript('BEGIN;' + MIGRATIONS[v] + f'; PRAGMA user_version = {v + 1};')
            finally:
                self.conn.commit()
                self.conn.execute('PRAGMA foreign_keys = ON')
            broken = self.conn.execute('PRAGMA foreign_key_check').fetchall()
            if broken:
                raise DatabaseError(f'После миграции схемы {v} -> {v + 1} нарушены ссылки между таблицами '
                                    f'({len(broken)}); используйте резервную копию.')

    def close(self) -> None:
        self.conn.close()

    def backup_to(self, target: str | Path) -> Path:
        target = Path(target)
        if target.resolve() == self.path.resolve():
            raise DatabaseError('Резервная копия не может совпадать с рабочим файлом базы.')
        tmp = target.with_suffix(target.suffix + '.tmp')
        dst = sqlite3.connect(str(tmp))
        try:
            self.conn.backup(dst)
        finally:
            dst.close()
        shutil.move(str(tmp), str(target))
        return target

    def schema_version(self) -> int:
        return self.conn.execute('PRAGMA user_version').fetchone()[0]

    def _one(self, sql: str, args: Iterable = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, tuple(args)).fetchone()

    def _all(self, sql: str, args: Iterable = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, tuple(args)).fetchall()

    # --- иерархия ------------------------------------------------------------
    def add_project(self, name: str, description: str = '') -> int:
        name = _req(name, 'Название проекта')
        with self.conn:
            return self.conn.execute('INSERT INTO projects(name, description, created_at) VALUES (?,?,?)',
                                     (name, description, now_utc())).lastrowid

    def get_or_create_project(self, name: str) -> int:
        row = self._one('SELECT id FROM projects WHERE name=?', (name.strip(),))
        return row['id'] if row else self.add_project(name)

    def projects(self) -> list[sqlite3.Row]:
        return self._all('SELECT * FROM projects ORDER BY name COLLATE NOCASE')

    def add_sample(self, project_id: int, name: str, description: str = '') -> int:
        name = _req(name, 'Название образца')
        with self.conn:
            return self.conn.execute('INSERT INTO samples(project_id, name, description, created_at) VALUES (?,?,?,?)',
                                     (project_id, name, description, now_utc())).lastrowid

    def get_or_create_sample(self, project_id: int, name: str) -> int:
        row = self._one('SELECT id FROM samples WHERE project_id=? AND name=?', (project_id, name.strip()))
        return row['id'] if row else self.add_sample(project_id, name)

    def samples(self, project_id: int) -> list[sqlite3.Row]:
        return self._all('SELECT * FROM samples WHERE project_id=? ORDER BY name COLLATE NOCASE', (project_id,))

    def add_mineral(self, sample_id: int, name: str, description: str = '') -> int:
        name = _req(name, 'Название минерала')
        with self.conn:
            return self.conn.execute('INSERT INTO minerals(sample_id, name, description) VALUES (?,?,?)',
                                     (sample_id, name, description)).lastrowid

    def get_or_create_mineral(self, sample_id: int, name: str) -> int:
        row = self._one('SELECT id FROM minerals WHERE sample_id=? AND name=?', (sample_id, name.strip()))
        return row['id'] if row else self.add_mineral(sample_id, name)

    def minerals(self, sample_id: int) -> list[sqlite3.Row]:
        return self._all('SELECT * FROM minerals WHERE sample_id=? ORDER BY name COLLATE NOCASE', (sample_id,))

    def add_fia(self, sample_id: int, mineral_id: int | None, name: str, description: str = '') -> int:
        name = _req(name, 'Название FIA')
        if self._find_fia(sample_id, mineral_id, name):
            raise DatabaseError(f'FIA «{name}» уже существует на этом уровне.')
        with self.conn:
            return self.conn.execute('INSERT INTO fias(sample_id, mineral_id, name, description) VALUES (?,?,?,?)',
                                     (sample_id, mineral_id, name, description)).lastrowid

    def _find_fia(self, sample_id, mineral_id, name):
        return self._one('SELECT id FROM fias WHERE sample_id=? AND mineral_id IS ? AND name=?',
                         (sample_id, mineral_id, name.strip()))

    def get_or_create_fia(self, sample_id: int, mineral_id: int | None, name: str) -> int:
        row = self._find_fia(sample_id, mineral_id, name)
        return row['id'] if row else self.add_fia(sample_id, mineral_id, name)

    def fias(self, sample_id: int, mineral_id: int | None) -> list[sqlite3.Row]:
        return self._all('SELECT * FROM fias WHERE sample_id=? AND mineral_id IS ? ORDER BY name COLLATE NOCASE',
                         (sample_id, mineral_id))

    def add_inclusion(self, sample_id: int, name: str, mineral_id: int | None = None,
                      fia_id: int | None = None, inclusion_type: str = '', description: str = '') -> int:
        name = _req(name, 'Название включения')
        if fia_id is not None:
            fia = self._one('SELECT * FROM fias WHERE id=?', (fia_id,))
            if fia is None or fia['sample_id'] != sample_id:
                raise DatabaseError('FIA принадлежит другому образцу.')
            if fia['mineral_id'] is not None:
                if mineral_id is not None and mineral_id != fia['mineral_id']:
                    raise DatabaseError('FIA принадлежит другому минералу.')
                mineral_id = fia['mineral_id']
        if self._one('SELECT id FROM inclusions WHERE sample_id=? AND name=?', (sample_id, name)):
            raise DatabaseError(f'Включение «{name}» уже есть в этом образце.')
        with self.conn:
            return self.conn.execute(
                'INSERT INTO inclusions(sample_id, mineral_id, fia_id, name, inclusion_type, description) '
                'VALUES (?,?,?,?,?,?)', (sample_id, mineral_id, fia_id, name, inclusion_type, description)).lastrowid

    def find_inclusion(self, sample_id: int, name: str) -> sqlite3.Row | None:
        return self._one('SELECT * FROM inclusions WHERE sample_id=? AND name=?', (sample_id, name.strip()))

    def inclusion(self, inclusion_id: int) -> sqlite3.Row | None:
        return self._one('SELECT * FROM inclusions WHERE id=?', (inclusion_id,))

    def set_carbonic_fraction(self, inclusion_id: int, fraction: float | None, uncertainty: float | None = None,
                              method: str | None = None, temperature_c: float | None = None) -> None:
        """Объёмная доля углекислотной фазы (жидкая + газовая CO₂), доли единицы 0…1. None — не определена."""
        if fraction is not None and not 0 <= fraction <= 1:
            raise DatabaseError('Доля углекислотной фазы должна быть от 0 до 100 %.')
        if uncertainty is not None and not 0 <= uncertainty <= 1:
            raise DatabaseError('Погрешность доли должна быть от 0 до 100 %.')
        if fraction is None:
            uncertainty = method = temperature_c = None
        with self.conn:
            self.conn.execute('UPDATE inclusions SET carbonic_fraction=?, carbonic_fraction_unc=?, '
                              'carbonic_fraction_method=?, carbonic_fraction_temp_c=? WHERE id=?',
                              (fraction, uncertainty, method or None, temperature_c, inclusion_id))

    def set_inclusion_context(self, inclusion_id: int, **fields) -> None:
        """Сведения о включении для интерпретации: состав солей и независимое ограничение условий захвата.

        Допустимые поля — INCLUSION_CONTEXT_COLUMNS. Температура и давление: одиночное значение (trap_*_c / _bar)
        или диапазон (вместе с trap_*_max_*). Задаётся не более одного типа ограничения.
        """
        unknown = set(fields) - set(INCLUSION_CONTEXT_COLUMNS)
        if unknown:
            raise DatabaseError(f'Неизвестные поля включения: {sorted(unknown)}')
        row = self.inclusion(inclusion_id)
        if row is None:
            raise DatabaseError('Включение не найдено.')
        new = {k: row[k] for k in INCLUSION_CONTEXT_COLUMNS}
        new.update(fields)
        for k in ('other_salts_confirmed', 'coeval_documented'):
            new[k] = _b2i(new[k])
        for lo, hi, label in (('trap_temperature_c', 'trap_temperature_max_c', 'температуры'),
                              ('trap_pressure_bar', 'trap_pressure_max_bar', 'давления')):
            if new[hi] is not None and new[lo] is None:
                raise DatabaseError(f'Верхняя граница {label} задана без нижней.')
        if new['trap_temperature_c'] is not None and new['trap_pressure_bar'] is not None:
            raise DatabaseError('Независимое ограничение задаётся либо по температуре, либо по давлению, но не '
                                'по обоим сразу.')
        if new['trap_pressure_bar'] is not None and new['trap_pressure_bar'] <= 0:
            raise DatabaseError('Давление должно быть положительным.')
        for k in ('trap_constraint_source', 'coeval_note'):
            new[k] = (new[k] or '').strip() or None
        with self.conn:
            self.conn.execute(
                f'UPDATE inclusions SET {", ".join(c + "=?" for c in INCLUSION_CONTEXT_COLUMNS)} WHERE id=?',
                (*(new[c] for c in INCLUSION_CONTEXT_COLUMNS), inclusion_id))

    def set_initial_state(self, inclusion_id: int, liquid: bool | None, vapor: bool | None, solid: bool | None,
                          temperature_c: float | None = None, room: bool = False) -> None:
        """Исходное состояние включения: наблюдаемые фазы (None — не указано) и температура наблюдения.

        Температура — конкретное значение ЛИБО признак «комнатная, точное значение не указано» (room=True);
        число вместо неизвестной комнатной температуры не подставляется. Это описание наблюдения, а не состав:
        расчёты эти поля не используют."""
        if temperature_c is not None and room:
            raise DatabaseError('Укажите либо значение температуры, либо «комнатная, точное значение не указано».')
        with self.conn:
            self.conn.execute('UPDATE inclusions SET initial_liquid=?, initial_vapor=?, initial_solid=?, '
                              'initial_temperature_c=?, initial_room=? WHERE id=?',
                              (_b2i(liquid), _b2i(vapor), _b2i(solid), temperature_c, int(bool(room)), inclusion_id))

    def set_inclusion_note(self, inclusion_id: int, note: str | None) -> None:
        with self.conn:
            self.conn.execute('UPDATE inclusions SET description=? WHERE id=?', ((note or '').strip() or None,
                                                                                 inclusion_id))

    def set_inclusion_type(self, inclusion_id: int, inclusion_type: str | None) -> None:
        with self.conn:
            self.conn.execute('UPDATE inclusions SET inclusion_type=? WHERE id=?', ((inclusion_type or '').strip(),
                                                                                    inclusion_id))

    def next_inclusion_name(self, sample_id: int | None) -> str:
        """Следующий свободный номер включения в образце: наибольший числовой номер + 1 (для нового образца — 1)."""
        if sample_id is None:
            return '1'
        nums = [int(r['name']) for r in self._all('SELECT name FROM inclusions WHERE sample_id=?', (sample_id,))
                if r['name'].strip().isdigit()]
        return str(max(nums) + 1 if nums else 1)

    # --- сеансы и этапы эксперимента ---------------------------------------------
    def add_session(self, inclusion_id: int, started_at: str | None = None, note: str | None = None) -> int:
        """Новый сеанс. started_at — дата и время ОПЫТА ('ГГГГ-ММ-ДД ЧЧ:ММ', None — не указана); дата ввода
        записывается отдельно (created_at) и с датой опыта не смешивается."""
        started_at = _session_date(started_at)
        with self.conn:
            return self.conn.execute('INSERT INTO sessions(inclusion_id, started_at, note, created_at) '
                                     'VALUES (?,?,?,?)', (inclusion_id, started_at, (note or '').strip() or None,
                                                          now_utc())).lastrowid

    def update_session(self, session_id: int, *, started_at: str | None, note: str | None) -> None:
        started_at = _session_date(started_at)
        with self.conn:
            self.conn.execute('UPDATE sessions SET started_at=?, note=? WHERE id=?',
                              (started_at, (note or '').strip() or None, session_id))

    def set_session_finished(self, session_id: int, finished: bool) -> None:
        with self.conn:
            self.conn.execute('UPDATE sessions SET finished=? WHERE id=?', (int(bool(finished)), session_id))

    def delete_session(self, session_id: int) -> None:
        """Удалить сеанс с этапами. Наблюдения НЕ удаляются — остаются «без привязки к сеансу»."""
        with self.conn:
            self.conn.execute('DELETE FROM sessions WHERE id=?', (session_id,))

    def sessions(self, inclusion_id: int) -> list[dict]:
        """Сеансы включения по дате опыта (без даты — в конце), с порядковым номером 'number'."""
        rows = self._all("SELECT * FROM sessions WHERE inclusion_id=? ORDER BY COALESCE(started_at, '9999'), id",
                         (inclusion_id,))
        return [dict(r, number=n, finished=bool(r['finished'])) for n, r in enumerate(rows, start=1)]

    def session(self, session_id: int) -> dict | None:
        r = self._one('SELECT * FROM sessions WHERE id=?', (session_id,))
        if r is None:
            return None
        return next(s for s in self.sessions(r['inclusion_id']) if s['id'] == session_id)

    def add_stage(self, session_id: int, direction: str, start_temperature_c: float | None = None,
                  start_room: bool = False, end_temperature_c: float | None = None, note: str | None = None,
                  position: int | None = None) -> int:
        """Новый этап в конце последовательности сеанса. Температуры необязательны и не подставляются.

        position — номер этапа при переносе данных (импорт); обычно не задаётся."""
        _stage_check(direction, start_temperature_c, start_room)
        if self._one('SELECT id FROM sessions WHERE id=?', (session_id,)) is None:
            raise DatabaseError('Сеанс не найден.')
        pos = position
        if pos is None:
            pos = self._one('SELECT COALESCE(MAX(position), 0) + 1 AS p FROM stages WHERE session_id=?',
                            (session_id,))['p']
        elif self._one('SELECT id FROM stages WHERE session_id=? AND position=?', (session_id, pos)):
            raise DatabaseError(f'Этап {pos} в этом сеансе уже существует.')
        with self.conn:
            return self.conn.execute(
                'INSERT INTO stages(session_id, position, direction, start_temperature_c, start_room, '
                'end_temperature_c, note, created_at) VALUES (?,?,?,?,?,?,?,?)',
                (session_id, pos, direction, start_temperature_c, int(bool(start_room)), end_temperature_c,
                 (note or '').strip() or None, now_utc())).lastrowid

    def update_stage(self, stage_id: int, *, direction: str, start_temperature_c: float | None,
                     start_room: bool, end_temperature_c: float | None, note: str | None) -> None:
        _stage_check(direction, start_temperature_c, start_room)
        with self.conn:
            self.conn.execute('UPDATE stages SET direction=?, start_temperature_c=?, start_room=?, '
                              'end_temperature_c=?, note=? WHERE id=?',
                              (direction, start_temperature_c, int(bool(start_room)), end_temperature_c,
                               (note or '').strip() or None, stage_id))

    def delete_stage(self, stage_id: int) -> None:
        """Удалить этап. Наблюдения НЕ удаляются — остаются «без привязки к сеансу». Следующие этапы сеанса
        сдвигаются на один номер."""
        r = self._one('SELECT session_id, position FROM stages WHERE id=?', (stage_id,))
        if r is None:
            return
        with self.conn:
            self.conn.execute('DELETE FROM stages WHERE id=?', (stage_id,))
            self.conn.execute('UPDATE stages SET position = position - 1 WHERE session_id=? AND position>?',
                              (r['session_id'], r['position']))

    def stages(self, session_id: int) -> list[dict]:
        rows = self._all('SELECT * FROM stages WHERE session_id=? ORDER BY position, id', (session_id,))
        return [dict(r, number=r['position'], start_room=bool(r['start_room'])) for r in rows]

    def stage(self, stage_id: int) -> dict | None:
        r = self._one('SELECT * FROM stages WHERE id=?', (stage_id,))
        if r is None:
            return None
        return next(s for s in self.stages(r['session_id']) if s['id'] == stage_id)

    def inclusions(self, sample_id: int, mineral_id: int | None, fia_id: int | None) -> list[sqlite3.Row]:
        return self._all('SELECT * FROM inclusions WHERE sample_id=? AND mineral_id IS ? AND fia_id IS ? '
                         'ORDER BY name COLLATE NOCASE', (sample_id, mineral_id, fia_id))

    def rename(self, table: str, row_id: int, name: str) -> None:
        if table not in ('projects', 'samples', 'minerals', 'fias', 'inclusions'):
            raise DatabaseError(table)
        name = _req(name, 'Название')
        try:
            with self.conn:
                self.conn.execute(f'UPDATE {table} SET name=? WHERE id=?', (name, row_id))
        except sqlite3.IntegrityError as exc:
            raise DatabaseError(f'Название «{name}» уже занято на этом уровне.') from exc

    def delete(self, table: str, row_id: int) -> None:
        if table not in ('projects', 'samples', 'minerals', 'fias', 'inclusions', 'observations'):
            raise DatabaseError(table)
        with self.conn:
            self.conn.execute(f'DELETE FROM {table} WHERE id=?', (row_id,))

    def count_observations(self, where: str, args: Iterable) -> int:
        return self._one(f'SELECT COUNT(*) AS n FROM ({_OBS_CONTEXT_SQL}) WHERE {where}', args)['n']

    # --- наблюдения ----------------------------------------------------------
    def add_observation(self, inclusion_id: int, obs: dict, stage_id: int | None = None) -> int:
        """Добавить наблюдение. stage_id — необязательная привязка к этапу сеанса того же включения."""
        vals = _obs_values(obs)
        if stage_id is not None:
            self._check_stage(inclusion_id, stage_id)
        ts = now_utc()
        with self.conn:
            return self.conn.execute(
                f'INSERT INTO observations(inclusion_id, {", ".join(OBS_COLUMNS)}, created_at, updated_at, stage_id) '
                f'VALUES (?, {", ".join("?" * len(OBS_COLUMNS))}, ?, ?, ?)',
                (inclusion_id, *vals, ts, ts, stage_id)).lastrowid

    def _check_stage(self, inclusion_id: int, stage_id: int) -> None:
        row = self._one('SELECT se.inclusion_id FROM stages st JOIN sessions se ON se.id = st.session_id '
                        'WHERE st.id=?', (stage_id,))
        if row is None:
            raise DatabaseError('Этап не найден.')
        if row['inclusion_id'] != inclusion_id:
            raise DatabaseError('Этап относится к другому включению.')

    def set_observation_stage(self, obs_id: int, stage_id: int | None) -> None:
        """Привязать наблюдение к этапу (или снять привязку: stage_id=None). Само измерение не меняется."""
        row = self._one('SELECT inclusion_id FROM observations WHERE id=?', (obs_id,))
        if row is None:
            raise DatabaseError('Наблюдение не найдено.')
        if stage_id is not None:
            self._check_stage(row['inclusion_id'], stage_id)
        with self.conn:
            self.conn.execute('UPDATE observations SET stage_id=? WHERE id=?', (stage_id, obs_id))

    def update_observation(self, obs_id: int, obs: dict) -> None:
        vals = _obs_values(obs)
        with self.conn:
            self.conn.execute(
                f'UPDATE observations SET {", ".join(c + "=?" for c in OBS_COLUMNS)}, updated_at=? WHERE id=?',
                (*vals, now_utc(), obs_id))

    def observation_exists(self, inclusion_id: int, obs: dict) -> bool:
        vals = _obs_values(obs)
        keys = OBS_COLUMNS[:8]
        cond = ' AND '.join(f'{k} IS ?' for k in keys)
        return self._one(f'SELECT id FROM observations WHERE inclusion_id=? AND {cond}',
                         (inclusion_id, *vals[:8])) is not None

    def observations(self, where: str = '1', args: Iterable = ()) -> list[dict]:
        rows = self._all(f'SELECT * FROM ({_OBS_CONTEXT_SQL}) WHERE {where} '
                         'ORDER BY project_name, sample_name, mineral_name, fia_name, inclusion_name, kind, id', args)
        out = []
        for r in rows:
            d = dict(r)
            for k in (*OBS_FLAG_COLUMNS, *OBS_EXTRA_FLAG_COLUMNS, 'other_salts_confirmed', 'coeval_documented',
                      *INITIAL_PHASE_COLUMNS):
                d[k] = _i2b(d[k])
            if d['session_id'] is None:
                d['session_number'] = None
            out.append(d)
        return out

    def observation(self, obs_id: int) -> dict | None:
        r = self.observations('id=?', (obs_id,))
        return r[0] if r else None

    # --- версии расчётов -------------------------------------------------------
    def save_run(self, project_id: int | None, scope: str, versions: dict,
                 items: list[tuple[dict, Any]]) -> int:
        """Сохранить новый расчёт. items — пары (наблюдение с контекстом, Outcome)."""
        n_ok = sum(o.status == 'ok' for _, o in items)
        n_err = sum(o.status == 'error' for _, o in items)
        n_skip = sum(o.status == 'skipped' for _, o in items)
        with self.conn:
            run_id = self.conn.execute(
                'INSERT INTO calc_runs(created_at, project_id, scope, app_version, core_version, python_version, '
                'coolprop_version, platform, n_total, n_ok, n_error, n_skipped) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (now_utc(), project_id, scope, versions['app_version'], versions['core_version'],
                 versions['python_version'], versions['coolprop_version'], versions['platform'],
                 len(items), n_ok, n_err, n_skip)).lastrowid
            for obs, o in items:
                inputs = {k: obs.get(k) for k in ('kind', 'temperature_c', 'uncertainty_c', 'homogenization_to',
                                                  *OBS_FLAG_COLUMNS, 'phase_notes', 'comment', 'source',
                                                  *OBS_EXTRA_FLAG_COLUMNS, 'raman_species')}
                inputs.update(obs.get('extra_inputs') or {})       # входы производных расчётов по включению
                self.conn.execute(
                    'INSERT INTO results(run_id, observation_id, project_name, sample_name, mineral_name, fia_name, '
                    'inclusion_name, kind, inputs_json, status, method_key, result_kind, value, unit, extras_json, '
                    'model, doi, citation, assumptions, scope, warnings_json, message, message_original) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (run_id, obs.get('id'), obs.get('project_name'), obs.get('sample_name'), obs.get('mineral_name'),
                     obs.get('fia_name'), obs.get('inclusion_name'), o.kind,
                     json.dumps(inputs, ensure_ascii=False), o.status, o.method_key, o.result_kind, o.value, o.unit,
                     json.dumps(o.extras, ensure_ascii=False), o.model, o.doi, o.citation, o.assumptions, o.scope,
                     json.dumps(o.warnings, ensure_ascii=False), o.message, o.message_original))
        return run_id

    def runs(self, project_id: int | None = None) -> list[dict]:
        if project_id is None:
            rows = self._all('SELECT * FROM calc_runs ORDER BY id DESC')
        else:
            rows = self._all('SELECT * FROM calc_runs WHERE project_id=? ORDER BY id DESC', (project_id,))
        return [dict(r) for r in rows]

    def run(self, run_id: int) -> dict | None:
        r = self._one('SELECT * FROM calc_runs WHERE id=?', (run_id,))
        return dict(r) if r else None

    def results(self, run_id: int) -> list[dict]:
        out = []
        for r in self._all('SELECT * FROM results WHERE run_id=? ORDER BY id', (run_id,)):
            d = dict(r)
            d['inputs'] = json.loads(d.pop('inputs_json') or '{}')
            d['extras'] = json.loads(d.pop('extras_json') or '{}')
            d['warnings'] = json.loads(d.pop('warnings_json') or '[]')
            out.append(d)
        return out

    # --- журнал импорта ------------------------------------------------------
    def log_import(self, project_id: int, file_name: str, sha256: str, sheet: str | None,
                   mapping: dict, n_rows: int, n_imported: int, n_errors: int, n_duplicates: int) -> int:
        with self.conn:
            return self.conn.execute(
                'INSERT INTO import_log(created_at, project_id, file_name, file_sha256, sheet, mapping_json, '
                'n_rows, n_imported, n_errors, n_duplicates) VALUES (?,?,?,?,?,?,?,?,?,?)',
                (now_utc(), project_id, file_name, sha256, sheet, json.dumps(mapping, ensure_ascii=False),
                 n_rows, n_imported, n_errors, n_duplicates)).lastrowid

    def table_rows(self, table: str) -> tuple[list[str], list[tuple]]:
        if table not in ('projects', 'samples', 'minerals', 'fias', 'inclusions', 'sessions', 'stages',
                         'observations', 'calc_runs', 'results', 'import_log'):
            raise DatabaseError(table)
        cur = self.conn.execute(f'SELECT * FROM {table} ORDER BY id')
        return [c[0] for c in cur.description], [tuple(r) for r in cur.fetchall()]


_OBS_CONTEXT_SQL = """
SELECT o.*, i.name AS inclusion_name, i.inclusion_type, i.sample_id, i.mineral_id, i.fia_id,
       i.carbonic_fraction, i.carbonic_fraction_unc, i.carbonic_fraction_method, i.carbonic_fraction_temp_c,
       i.other_salts_confirmed, i.trap_temperature_c, i.trap_temperature_max_c, i.trap_pressure_bar,
       i.trap_pressure_max_bar, i.trap_constraint_source, i.coeval_documented, i.coeval_note,
       i.initial_liquid, i.initial_vapor, i.initial_solid, i.initial_temperature_c, i.initial_room,
       i.description AS inclusion_note,
       s.name AS sample_name, s.project_id, p.name AS project_name,
       m.name AS mineral_name, f.name AS fia_name,
       st.session_id, st.position AS stage_position, st.direction AS stage_direction,
       st.start_temperature_c AS stage_start_c, st.start_room AS stage_start_room,
       st.end_temperature_c AS stage_end_c, st.note AS stage_note,
       se.started_at AS session_started_at, se.note AS session_note, se.finished AS session_finished,
       (SELECT COUNT(*) FROM sessions x WHERE x.inclusion_id = se.inclusion_id AND
            (COALESCE(x.started_at, '9999') < COALESCE(se.started_at, '9999') OR
             (COALESCE(x.started_at, '9999') = COALESCE(se.started_at, '9999') AND x.id <= se.id))) AS session_number
FROM observations o
JOIN inclusions i ON i.id = o.inclusion_id
JOIN samples s ON s.id = i.sample_id
JOIN projects p ON p.id = s.project_id
LEFT JOIN minerals m ON m.id = i.mineral_id
LEFT JOIN fias f ON f.id = i.fia_id
LEFT JOIN stages st ON st.id = o.stage_id
LEFT JOIN sessions se ON se.id = st.session_id
"""


def _req(value: str, label: str) -> str:
    v = (value or '').strip()
    if not v:
        raise DatabaseError(f'{label}: значение не может быть пустым.')
    return v


def _session_date(value: str | None) -> str | None:
    v = (value or '').strip()
    if not v:
        return None
    for fmt in (SESSION_DATE_FORMAT, '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d',
                '%d.%m.%Y %H:%M', '%d.%m.%Y'):
        try:
            return datetime.strptime(v, fmt).strftime(SESSION_DATE_FORMAT)
        except ValueError:
            continue
    raise DatabaseError(f'Дата сеанса «{value}» не распознана (ожидается ГГГГ-ММ-ДД ЧЧ:ММ или ДД.ММ.ГГГГ ЧЧ:ММ).')


def _stage_check(direction, start_temperature_c, start_room) -> None:
    if direction not in DIRECTIONS:
        raise DatabaseError(f'Недопустимое направление этапа: {direction!r}')
    if start_temperature_c is not None and start_room:
        raise DatabaseError('Начало этапа: укажите либо значение температуры, либо «комнатная, значение не указано».')


def _obs_values(obs: dict) -> tuple:
    kind = obs.get('kind')
    if kind not in KINDS:
        raise DatabaseError(f'Неизвестный тип наблюдения: {kind!r}')
    t = obs.get('temperature_c')
    if t is None:
        raise DatabaseError('Температура обязательна.')
    u = obs.get('uncertainty_c')
    if u is not None and u < 0:
        raise DatabaseError('Погрешность не может быть отрицательной.')
    h = obs.get('homogenization_to') or None
    if h not in (None, 'liquid', 'vapor', 'critical'):
        raise DatabaseError(f'Недопустимое направление гомогенизации: {h!r}')
    raman = obs.get('raman_species') or None
    if raman not in (None, *RAMAN_SPECIES_VALUES):
        raise DatabaseError(f'Недопустимое значение данных КР-спектроскопии: {raman!r}')
    return (kind, float(t), None if u is None else float(u), h,
            *(_b2i(obs.get(k)) for k in OBS_FLAG_COLUMNS),
            obs.get('phase_notes') or None, obs.get('comment') or None, obs.get('source') or None,
            *(_b2i(obs.get(k)) for k in OBS_EXTRA_FLAG_COLUMNS), raman)
