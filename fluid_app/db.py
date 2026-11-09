"""Хранение данных в SQLite: иерархия проект → образец → минерал → FIA → включение →
наблюдения, неизменяемые версии расчётов, журнал импорта. Миграции через PRAGMA user_version.
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

_KIND_CHECK = ', '.join(f"'{k}'" for k in KINDS)

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
]
SCHEMA_VERSION = len(MIGRATIONS)

OBS_FLAG_COLUMNS = ('liquid_co2_present', 'vapor_co2_present', 'aqueous_brine_present', 'co2_purity_confirmed')
OBS_COLUMNS = ('kind', 'temperature_c', 'uncertainty_c', 'homogenization_to', *OBS_FLAG_COLUMNS,
               'phase_notes', 'comment', 'source')


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
            with self.conn:
                self.conn.executescript('BEGIN;' + MIGRATIONS[v] + f'; PRAGMA user_version = {v + 1};')
            # executescript завершает транзакцию сам; повторно включаем внешние ключи
            self.conn.execute('PRAGMA foreign_keys = ON')

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
    def add_observation(self, inclusion_id: int, obs: dict) -> int:
        vals = _obs_values(obs)
        ts = now_utc()
        with self.conn:
            return self.conn.execute(
                f'INSERT INTO observations(inclusion_id, {", ".join(OBS_COLUMNS)}, created_at, updated_at) '
                f'VALUES (?, {", ".join("?" * len(OBS_COLUMNS))}, ?, ?)', (inclusion_id, *vals, ts, ts)).lastrowid

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
            for k in OBS_FLAG_COLUMNS:
                d[k] = _i2b(d[k])
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
                                                  *OBS_FLAG_COLUMNS, 'phase_notes', 'comment', 'source')}
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
        if table not in ('projects', 'samples', 'minerals', 'fias', 'inclusions', 'observations',
                         'calc_runs', 'results', 'import_log'):
            raise DatabaseError(table)
        cur = self.conn.execute(f'SELECT * FROM {table} ORDER BY id')
        return [c[0] for c in cur.description], [tuple(r) for r in cur.fetchall()]


_OBS_CONTEXT_SQL = """
SELECT o.*, i.name AS inclusion_name, i.inclusion_type, i.sample_id, i.mineral_id, i.fia_id,
       i.carbonic_fraction, i.carbonic_fraction_unc, i.carbonic_fraction_method, i.carbonic_fraction_temp_c,
       s.name AS sample_name, s.project_id, p.name AS project_name,
       m.name AS mineral_name, f.name AS fia_name
FROM observations o
JOIN inclusions i ON i.id = o.inclusion_id
JOIN samples s ON s.id = i.sample_id
JOIN projects p ON p.id = s.project_id
LEFT JOIN minerals m ON m.id = i.mineral_id
LEFT JOIN fias f ON f.id = i.fia_id
"""


def _req(value: str, label: str) -> str:
    v = (value or '').strip()
    if not v:
        raise DatabaseError(f'{label}: значение не может быть пустым.')
    return v


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
    return (kind, float(t), None if u is None else float(u), h,
            *(_b2i(obs.get(k)) for k in OBS_FLAG_COLUMNS),
            obs.get('phase_notes') or None, obs.get('comment') or None, obs.get('source') or None)
