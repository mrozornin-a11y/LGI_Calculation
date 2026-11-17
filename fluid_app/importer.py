"""Импорт CSV / XLSX: чтение без изменения исходного файла, карта полей,
разбор с построчной диагностикой и запись в базу.

Пустые ячейки остаются пустыми (None) — предполагаемые значения не подставляются.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from .db import Database, DatabaseError
from .methods import KINDS, kind_label

MAX_ROWS = 100_000

# --- описание целевых полей ----------------------------------------------------
# ключ -> (подпись, синонимы заголовков в нижнем регистре)
TARGET_FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    'sample': ('Образец *', ('sample_id', 'sample', 'образец', 'проба', 'номер образца', '№ образца')),
    'mineral': ('Минерал', ('mineral', 'минерал', 'host', 'минерал-хозяин')),
    'fia': ('FIA (ассоциация)', ('fia', 'fia_id', 'ассоциация', 'ассоциация включений', 'группа')),
    'inclusion': ('Включение *', ('inclusion_id', 'inclusion', 'fi', 'fi_id', 'включение', '№ включения',
                                  'номер включения')),
    'inclusion_type': ('Тип включения', ('inclusion_type', 'type', 'тип включения', 'тип')),
    'kind': ('Тип измерения (длинный формат)', ('method', 'kind', 'measurement', 'тип измерения', 'измерение',
                                                'параметр')),
    'temperature': ('Температура, °C (длинный формат)', ('temperature_c', 'temperature', 't', 't_c',
                                                         'температура', 't, °c', 't,°c')),
    'homogenization_to': ('Направление гомогенизации (длинный формат)',
                          ('homogenization_to', 'homogenization', 'направление гомогенизации', 'гомогенизация в')),
    'Tm_ice': ('Tm лёд, °C', ('tm_ice', 'tmice', 'tm ice', 'tm лёд', 'tm лед', 'tm(ice)', 'тпл льда')),
    'Tm_clath': ('Tm клатрат, °C', ('tm_clath', 'tmclath', 'tm clath', 'tm_cl', 'tm клатрат', 'tm(clath)',
                                     'тпл клатрата')),
    'Tm_CO2': ('Tm CO₂, °C', ('tm_co2', 'tmco2', 'tm co2', 'tm(co2)', 'тпл co2')),
    'Th_CO2': ('Th CO₂, °C', ('th_co2', 'thco2', 'th co2', 'th(co2)', 'тгом co2')),
    'Th_CO2_mode': ('Th CO₂: направление', ('th_co2_mode', 'th_co2_to', 'th co2 mode', 'гомогенизация co2')),
    'Th_total': ('Th общ., °C', ('th_total', 'th_tot', 'thtot', 'th', 'th total', 'th общ', 'тгом')),
    'Th_total_mode': ('Th общ.: направление', ('th_total_mode', 'th_total_to', 'th mode', 'гомогенизация')),
    'Te': ('Te, °C', ('te', 't_e', 'teut', 'эвтектика', 'te, °c')),
    'Tm_hydrohalite': ('Tm гидрогалит, °C', ('tm_hydrohalite', 'tm_hh', 'tm hh', 'tm гидрогалит', 'tm гидрогалита',
                                               'тпл гидрогалита')),
    'T_diss_halite': ('T раств. галита, °C', ('t_diss_halite', 'tm_halite', 'ts_halite', 'ts nacl', 'tm halite',
                                               't раств. галита', 'т раств галита', 'растворение галита')),
    'uncertainty': ('Погрешность ±, °C', ('uncertainty_c', 'uncertainty', 'error', 'погрешность', '±')),
    'liquid_co2_present': ('Жидкая CO₂ присутствует', ('liquid_co2_present', 'l_co2', 'жидкая co2')),
    'vapor_co2_present': ('Газовая CO₂ присутствует', ('vapor_co2_present', 'v_co2', 'газовая co2')),
    'aqueous_brine_present': ('Водный раствор присутствует', ('aqueous_brine_present', 'brine', 'водный раствор')),
    'co2_purity_confirmed': ('Приближение чистой CO₂ принято', ('co2_purity_confirmed', 'pure_co2',
                                                                 'чистая co2')),
    'vapor_present_at_transition': ('Пар присутствует при растворении галита',
                                    ('vapor_present_at_transition', 'vapor_at_halite', 'пар при растворении галита')),
    'phase_identified': ('Фаза определена как гидрогалит', ('phase_identified', 'hydrohalite_identified',
                                                              'гидрогалит определён', 'гидрогалит определен')),
    'carbonic_fraction': ('Доля углекислотной фазы φ, %', ('carbonic_fraction_pct', 'carbonic_fraction', 'phi_co2',
                                                         'φ', 'phi', 'доля co2', 'доля углекислоты',
                                                         'доля углекислотной фазы')),
    'carbonic_fraction_unc': ('Погрешность φ ±, %', ('carbonic_fraction_unc_pct', 'carbonic_fraction_unc', 'phi_unc',
                                                      'погрешность φ', 'погрешность доли')),
    'carbonic_fraction_method': ('Способ оценки φ', ('carbonic_fraction_method', 'phi_method', 'способ оценки φ',
                                                     'способ оценки доли')),
    'phase_notes': ('Описание фаз', ('phase_notes', 'phases', 'фазы', 'фазовый состав', 'описание фаз')),
    'comment': ('Комментарий', ('comment', 'comments', 'note', 'notes', 'комментарий', 'примечание')),
    # ход эксперимента (необязательно): сеанс и этап, к которым относится наблюдение
    'session_number': ('Сеанс №', ('session_number', 'session_no', 'сеанс', 'сеанс №', '№ сеанса')),
    'session_date': ('Дата сеанса (дата опыта)', ('session_date', 'session_started_at', 'дата сеанса',
                                                  'дата опыта')),
    'session_note': ('Примечание к сеансу', ('session_note', 'примечание к сеансу')),
    'session_finished': ('Сеанс завершён', ('session_finished', 'сеанс завершён', 'сеанс завершен')),
    'stage_number': ('Этап №', ('stage_number', 'stage_no', 'этап', 'этап №', '№ этапа')),
    'stage_direction': ('Этап: охлаждение / нагревание', ('stage_direction', 'направление этапа')),
    'stage_start': ('Этап: начальная температура, °C', ('stage_start_c', 'stage_start', 'начало этапа')),
    'stage_start_room': ('Этап: начало при комнатной температуре (значение не указано)',
                         ('stage_start_room', 'начало этапа комнатная')),
    'stage_end': ('Этап: конечная температура, °C', ('stage_end_c', 'stage_end', 'конец этапа')),
    'stage_note': ('Примечание к этапу', ('stage_note', 'примечание к этапу')),
    # исходное состояние включения (необязательно)
    'initial_liquid': ('Исходно наблюдается жидкость', ('initial_liquid', 'исходно жидкость')),
    'initial_vapor': ('Исходно наблюдается газ', ('initial_vapor', 'исходно газ')),
    'initial_solid': ('Исходно наблюдается твёрдая фаза', ('initial_solid', 'исходно твёрдая фаза',
                                                             'исходно твердая фаза')),
    'initial_temperature': ('Температура исходного наблюдения, °C', ('initial_temperature_c', 'initial_temperature',
                                                                      'температура исходного наблюдения')),
    'initial_room': ('Исходное наблюдение при комнатной температуре (значение не указано)',
                     ('initial_room', 'исходно комнатная')),
    'inclusion_note': ('Примечание к включению', ('inclusion_note', 'примечание к включению')),
}
_DIRECTION = {'cooling': 'cooling', 'охлаждение': 'cooling', 'cool': 'cooling', 'heating': 'heating',
              'нагревание': 'heating', 'нагрев': 'heating', 'heat': 'heating'}
WIDE_KINDS = ('Tm_ice', 'Tm_clath', 'Tm_CO2', 'Th_CO2', 'Th_total', 'Te', 'Tm_hydrohalite', 'T_diss_halite')
FLAG_KEYS = ('liquid_co2_present', 'vapor_co2_present', 'aqueous_brine_present', 'co2_purity_confirmed',
             'vapor_present_at_transition', 'phase_identified')
FLAG_RELEVANCE = {
    'liquid_co2_present': ('Tm_clath',),
    'vapor_co2_present': ('Tm_clath',),
    'aqueous_brine_present': ('Tm_clath',),
    'co2_purity_confirmed': ('Th_CO2', 'Tm_clath'),
    'vapor_present_at_transition': ('T_diss_halite',),
    'phase_identified': ('Tm_hydrohalite',),
    'homogenization_to': ('Th_CO2', 'Th_total'),
}

_KIND_ALIASES = {
    'bodnar': 'Tm_ice', 'tm_ice': 'Tm_ice', 'tmice': 'Tm_ice', 'tm лёд': 'Tm_ice', 'tm лед': 'Tm_ice', 'ice': 'Tm_ice',
    'darling': 'Tm_clath', 'tm_clath': 'Tm_clath', 'tm клатрат': 'Tm_clath', 'clathrate': 'Tm_clath',
    'clath': 'Tm_clath',
    'co2': 'Th_CO2', 'th_co2': 'Th_CO2', 'th co2': 'Th_CO2',
    'tm_co2': 'Tm_CO2', 'tm co2': 'Tm_CO2',
    'th_total': 'Th_total', 'th_tot': 'Th_total', 'th общ.': 'Th_total', 'th общ': 'Th_total', 'th': 'Th_total',
    'te': 'Te', 'эвтектика': 'Te',
    'tm_hydrohalite': 'Tm_hydrohalite', 'tm гидрогалит': 'Tm_hydrohalite', 'hydrohalite': 'Tm_hydrohalite',
    't_diss_halite': 'T_diss_halite', 't раств. галита': 'T_diss_halite', 'halite': 'T_diss_halite',
}
_TRUE = {'true', 'yes', 'y', '1', 'да', 'д', '+', 'истина', 'x', 'х'}
_FALSE = {'false', 'no', 'n', '0', 'нет', 'н', '-', '−', 'ложь'}
_HOMOG = {
    'liquid': 'liquid', 'l': 'liquid', 'ж': 'liquid', 'жидкость': 'liquid', 'в жидкость': 'liquid',
    'lv-l': 'liquid', 'l+v→l': 'liquid',
    'vapor': 'vapor', 'vapour': 'vapor', 'v': 'vapor', 'г': 'vapor', 'газ': 'vapor', 'в газ': 'vapor',
    'lv-v': 'vapor', 'l+v→v': 'vapor',
    'critical': 'critical', 'c': 'critical', 'крит': 'critical', 'критическая': 'critical', 'к': 'critical',
}


@dataclass
class Table:
    headers: list[str]
    rows: list[list[str]]
    sheet: str | None = None
    encoding: str | None = None
    delimiter: str | None = None


@dataclass
class ParsedRow:
    row_number: int                       # номер строки в исходном файле (1 — заголовок)
    sample: str = ''
    mineral: str = ''
    fia: str = ''
    inclusion: str = ''
    inclusion_type: str = ''
    observations: list[dict] = field(default_factory=list)
    inclusion_props: dict = field(default_factory=dict)   # свойства включения (φ и др.)
    initial_state: dict = field(default_factory=dict)     # исходное состояние включения и примечание к нему
    experiment: dict = field(default_factory=dict)        # сеанс и этап наблюдений этой строки (если заданы)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and bool(self.observations)


# --- чтение ------------------------------------------------------------------------
def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b''):
            h.update(chunk)
    return h.hexdigest()


def xlsx_sheets(path: str | Path) -> list[str]:
    from openpyxl import load_workbook
    wb = load_workbook(str(path), read_only=True, data_only=True)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def _cell_text(v) -> str:
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, float):
        if math.isnan(v):
            return ''
        return repr(v) if v != int(v) else f'{v:.1f}'
    return str(v).strip()


def read_table(path: str | Path, *, sheet: str | None = None, encoding: str | None = None,
               delimiter: str | None = None) -> Table:
    """Прочитать CSV/TXT или XLSX. Исходный файл открывается только на чтение."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in ('.xlsx', '.xlsm'):
        from openpyxl import load_workbook
        wb = load_workbook(str(path), read_only=True, data_only=True)
        try:
            ws = wb[sheet] if sheet else wb.worksheets[0]
            raw = [[_cell_text(c) for c in r] for r in ws.iter_rows(values_only=True)]
            sheet_name = ws.title
        finally:
            wb.close()
        return _to_table(raw, sheet=sheet_name)
    if suffix == '.xls':
        raise ValueError('Формат .xls (Excel 97–2003) не поддерживается: сохраните файл как .xlsx или CSV.')
    data = path.read_bytes()
    text, used = _decode(data, encoding)
    if delimiter is None:
        delimiter = sniff_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=''), delimiter=delimiter)
    raw = [[c.strip() for c in r] for r in reader]
    return _to_table(raw, encoding=used, delimiter=delimiter)


def _decode(data: bytes, encoding: str | None) -> tuple[str, str]:
    if encoding:
        return data.decode(encoding), encoding
    for enc in ('utf-8-sig', 'cp1251'):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode('latin-1'), 'latin-1'


def sniff_delimiter(text: str) -> str:
    sample = '\n'.join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters=',;\t|').delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in (';', '\t', ',')}
        best = max(counts, key=counts.get)
        return best if counts[best] else ','


def _to_table(raw: list[list[str]], **kw) -> Table:
    raw = [r for r in raw if any(c != '' for c in r)]
    if not raw:
        raise ValueError('Файл пуст: нет ни заголовка, ни данных.')
    if len(raw) - 1 > MAX_ROWS:
        raise ValueError(f'Слишком много строк (>{MAX_ROWS}).')
    headers = [h.strip() for h in raw[0]]
    while headers and headers[-1] == '':
        headers.pop()
    if not headers:
        raise ValueError('Не найдена строка заголовков.')
    seen: dict[str, int] = {}
    for i, h in enumerate(headers):
        if h == '':
            headers[i] = h = f'Столбец {i + 1}'
        if h in seen:
            seen[h] += 1
            headers[i] = f'{h} ({seen[h]})'
        else:
            seen[h] = 1
    width = len(headers)
    rows = [(r + [''] * width)[:width] for r in raw[1:]]
    return Table(headers, rows, **kw)


# --- карта полей ---------------------------------------------------------------------
def _norm(h: str) -> str:
    return re.sub(r'\s+', ' ', h.strip().lower().replace('ё', 'е')).replace('₂', '2')


def auto_mapping(headers: list[str]) -> dict[str, str | None]:
    """Предложить соответствие целевых полей заголовкам (пользователь подтверждает)."""
    norm = {_norm(h): h for h in headers}
    mapping: dict[str, str | None] = {}
    used: set[str] = set()
    for key, (label, synonyms) in TARGET_FIELDS.items():
        mapping[key] = None
        plain = label.replace(' *', '')
        candidates = (*synonyms, plain, plain.replace(', °C', ''))
        for s in candidates:
            h = norm.get(_norm(s))
            if h and h not in used:
                mapping[key] = h
                used.add(h)
                break
    return mapping


def validate_mapping(mapping: dict[str, str | None]) -> list[str]:
    errs = []
    if not mapping.get('sample'):
        errs.append('Не задан столбец «Образец».')
    if not mapping.get('inclusion'):
        errs.append('Не задан столбец «Включение».')
    long_fmt = bool(mapping.get('kind')) or bool(mapping.get('temperature'))
    if long_fmt and not (mapping.get('kind') and mapping.get('temperature')):
        errs.append('Для длинного формата нужны оба столбца: «Тип измерения» и «Температура».')
    if not long_fmt and not any(mapping.get(k) for k in WIDE_KINDS):
        errs.append('Не задан ни один столбец с температурами измерений.')
    return errs


# --- разбор значений -------------------------------------------------------------------
def parse_number(text: str) -> float | None:
    s = (text or '').strip().replace('−', '-').replace('–', '-').replace(' ', '').replace(' ', '')
    if s == '':
        return None
    s = s.replace(',', '.')
    v = float(s)          # ValueError при нечисловом значении
    if not math.isfinite(v):
        raise ValueError('не конечное число')
    return v


def parse_flag(text: str) -> bool | None:
    s = (text or '').strip().lower()
    if s == '':
        return None
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    raise ValueError(f'ожидается да/нет (true/false, 1/0), получено «{text}»')


def parse_homogenization(text: str) -> str | None:
    s = (text or '').strip().lower()
    if s == '':
        return None
    if s in _HOMOG:
        return _HOMOG[s]
    raise ValueError(f'направление гомогенизации «{text}» не распознано (жидкость/газ/критическая)')


def parse_kind(text: str) -> str:
    s = (text or '').strip()
    if s in KINDS:
        return s
    k = _KIND_ALIASES.get(_norm(s))
    if k is None:
        raise ValueError(f'тип измерения «{text}» не распознан')
    return k


def parse_rows(table: Table, mapping: dict[str, str | None]) -> list[ParsedRow]:
    idx = {k: table.headers.index(v) for k, v in mapping.items() if v}

    def cell(row, key):
        i = idx.get(key)
        return row[i].strip() if i is not None else ''

    parsed: list[ParsedRow] = []
    for n, row in enumerate(table.rows, start=2):
        p = ParsedRow(n, sample=cell(row, 'sample'), mineral=cell(row, 'mineral'), fia=cell(row, 'fia'),
                      inclusion=cell(row, 'inclusion'), inclusion_type=cell(row, 'inclusion_type'))
        if not p.sample:
            p.errors.append('пустое поле «Образец»')
        if not p.inclusion:
            p.errors.append('пустое поле «Включение»')
        common: dict = {'phase_notes': cell(row, 'phase_notes') or None, 'comment': cell(row, 'comment') or None}
        for key, label in (('uncertainty', 'погрешность'),):
            try:
                u = parse_number(cell(row, key))
                if u is not None and u < 0:
                    raise ValueError('отрицательная')
                common['uncertainty_c'] = u
            except ValueError as exc:
                p.errors.append(f'{label}: {exc}')
        for key, label in (('carbonic_fraction', 'доля углекислотной фазы'), ('carbonic_fraction_unc', 'погрешность φ')):
            try:
                v = parse_number(cell(row, key))
                if v is not None:
                    if not 0 <= v <= 100:
                        raise ValueError('должна быть от 0 до 100 %')
                    p.inclusion_props[key] = v / 100
            except ValueError as exc:
                p.errors.append(f'{label}: {exc}')
        if cell(row, 'carbonic_fraction_method'):
            p.inclusion_props['carbonic_fraction_method'] = cell(row, 'carbonic_fraction_method')
        if p.inclusion_props and 'carbonic_fraction' not in p.inclusion_props:
            p.warnings.append('погрешность/способ оценки φ без самой φ — не сохраняются')
            p.inclusion_props = {}
        for key in FLAG_KEYS:
            try:
                common[key] = parse_flag(cell(row, key))
            except ValueError as exc:
                p.errors.append(f'{TARGET_FIELDS[key][0]}: {exc}')
        _parse_experiment(p, lambda key: cell(row, key))

        def add(kind, ttext, htext, hlabel):
            try:
                t = parse_number(ttext)
            except ValueError:
                p.errors.append(f'{kind_label(kind)}: «{ttext}» не является числом')
                return
            if t is None:
                return
            try:
                h = parse_homogenization(htext)
            except ValueError as exc:
                p.errors.append(f'{hlabel}: {exc}')
                return
            if h is not None and kind not in FLAG_RELEVANCE['homogenization_to']:
                p.warnings.append(f'направление гомогенизации не относится к {kind_label(kind)} и не сохранено')
            obs = dict(common, kind=kind, temperature_c=t, homogenization_to=h)
            # Признаки относятся только к своим наблюдениям: фазы при плавлении клатрата — к Tm клатрат,
            # принятие чистой CO₂ — к Th CO₂, направление гомогенизации — к Th CO₂ / Th общ.
            for key in FLAG_RELEVANCE:
                if kind not in FLAG_RELEVANCE[key]:
                    obs[key] = None
            p.observations.append(obs)

        if mapping.get('kind'):
            ktext = cell(row, 'kind')
            ttext = cell(row, 'temperature')
            if ktext == '' and ttext == '':
                pass
            elif ktext == '':
                p.errors.append('пустой тип измерения при заданной температуре')
            else:
                try:
                    add(parse_kind(ktext), ttext, cell(row, 'homogenization_to'), 'направление гомогенизации')
                    if ttext == '':
                        p.errors.append(f'тип измерения «{ktext}» без температуры')
                except ValueError as exc:
                    p.errors.append(str(exc))
        for kind in WIDE_KINDS:
            if mapping.get(kind):
                mode_key = {'Th_CO2': 'Th_CO2_mode', 'Th_total': 'Th_total_mode'}.get(kind)
                add(kind, cell(row, kind), cell(row, mode_key) if mode_key else '',
                    TARGET_FIELDS[mode_key][0] if mode_key else '')
        if not p.errors and not p.observations:
            p.warnings.append('в строке нет измерений — строка будет пропущена')
        parsed.append(p)
    return parsed


def _parse_experiment(p: ParsedRow, cell) -> None:
    """Сеанс, этап и исходное состояние включения. Пустые ячейки остаются «не указано»."""
    def conv(key, fn):
        try:
            return fn(cell(key))
        except ValueError as exc:
            p.errors.append(f'{TARGET_FIELDS[key][0]}: {exc}')
            return None

    ini = {'liquid': conv('initial_liquid', parse_flag), 'vapor': conv('initial_vapor', parse_flag),
           'solid': conv('initial_solid', parse_flag), 'temperature_c': conv('initial_temperature', parse_number),
           'room': bool(conv('initial_room', parse_flag)), 'note': cell('inclusion_note') or None}
    if ini['temperature_c'] is not None and ini['room']:
        p.errors.append('исходное состояние: задано и значение температуры, и «комнатная, значение не указано»')
    if any(v not in (None, False) for v in ini.values()):
        p.initial_state = ini
    session_keys = ('session_number', 'session_date', 'session_note', 'session_finished')
    stage_keys = ('stage_number', 'stage_direction', 'stage_start', 'stage_start_room', 'stage_end', 'stage_note')
    has_stage = any(cell(k) for k in stage_keys)
    if not has_stage and not any(cell(k) for k in session_keys):
        return
    if not has_stage:
        p.warnings.append('сеанс указан без этапа — наблюдения строки останутся без привязки к сеансу')
        return
    direction = _DIRECTION.get(cell('stage_direction').lower())
    if direction is None:
        p.errors.append(f'направление этапа «{cell("stage_direction")}» не распознано (охлаждение/нагревание)')
        return

    def integer(text):
        v = parse_number(text)
        if v is not None and (v != int(v) or v < 1):
            raise ValueError('ожидается целый номер, начиная с 1')
        return None if v is None else int(v)
    exp = {'session_number': conv('session_number', integer), 'session_date': cell('session_date') or None,
           'session_note': cell('session_note') or None,
           'session_finished': bool(conv('session_finished', parse_flag)),
           'stage_number': conv('stage_number', integer), 'stage_direction': direction,
           'stage_start_c': conv('stage_start', parse_number),
           'stage_start_room': bool(conv('stage_start_room', parse_flag)),
           'stage_end_c': conv('stage_end', parse_number), 'stage_note': cell('stage_note') or None}
    if exp['stage_start_c'] is not None and exp['stage_start_room']:
        p.errors.append('начало этапа: задано и значение температуры, и «комнатная, значение не указано»')
    if exp['session_date']:
        from .db import _session_date
        try:
            exp['session_date'] = _session_date(exp['session_date'])
        except DatabaseError as exc:
            p.errors.append(str(exc))
    p.experiment = exp


def _resolve_stage(db: Database, inc_id: int, exp: dict, cache: dict) -> int:
    """Найти или создать сеанс и этап строки импорта (без дубликатов при повторном импорте)."""
    skey = (inc_id, exp['session_number'], exp['session_date'], exp['session_note'])
    sessions = cache.setdefault('sessions', {})
    if skey not in sessions:
        claimed = set(sessions.values())
        found = next((x for x in db.sessions(inc_id) if x['id'] not in claimed and
                      x['started_at'] == exp['session_date'] and (x['note'] or None) == exp['session_note']), None)
        if found:
            sessions[skey] = found['id']
        else:
            sessions[skey] = db.add_session(inc_id, exp['session_date'], exp['session_note'])
            if exp['session_finished']:
                db.set_session_finished(sessions[skey], True)
    session_id = sessions[skey]
    stages = db.stages(session_id)
    number = exp['stage_number']
    if number is None:        # номер этапа не задан: этап определяется направлением и температурами
        for st in stages:
            if (st['direction'], st['start_temperature_c'], st['start_room'], st['end_temperature_c'],
                    st['note']) == (exp['stage_direction'], exp['stage_start_c'], exp['stage_start_room'],
                                    exp['stage_end_c'], exp['stage_note']):
                return st['id']
    else:
        for st in stages:
            if st['position'] == number:
                if st['direction'] != exp['stage_direction']:
                    raise DatabaseError(f'этап {number} этого сеанса уже существует с другим направлением')
                return st['id']
    return db.add_stage(session_id, exp['stage_direction'], exp['stage_start_c'], exp['stage_start_room'],
                        exp['stage_end_c'], exp['stage_note'], position=number)


@dataclass
class ImportReport:
    n_rows: int = 0
    n_rows_imported: int = 0
    n_observations: int = 0
    n_errors: int = 0
    n_duplicates: int = 0
    n_empty: int = 0
    messages: list[str] = field(default_factory=list)


def import_rows(db: Database, project_id: int, parsed: list[ParsedRow], *, source: str,
                skip_duplicates: bool = True) -> ImportReport:
    """Записать корректные строки в базу. Строки с ошибками не импортируются."""
    rep = ImportReport(n_rows=len(parsed))
    cache: dict = {}
    for p in parsed:
        if p.errors:
            rep.n_errors += 1
            rep.messages.append(f'Строка {p.row_number}: ' + '; '.join(p.errors))
            continue
        if not p.observations:
            rep.n_empty += 1
            continue
        try:
            sample_id = db.get_or_create_sample(project_id, p.sample)
            mineral_id = db.get_or_create_mineral(sample_id, p.mineral) if p.mineral else None
            fia_id = db.get_or_create_fia(sample_id, mineral_id, p.fia) if p.fia else None
            inc = db.find_inclusion(sample_id, p.inclusion)
            if inc is None:
                inc_id = db.add_inclusion(sample_id, p.inclusion, mineral_id, fia_id, p.inclusion_type)
            else:
                if (mineral_id is not None and inc['mineral_id'] != mineral_id) or \
                        (fia_id is not None and inc['fia_id'] != fia_id):
                    raise DatabaseError(f'включение «{p.inclusion}» уже существует с другим минералом/FIA')
                inc_id = inc['id']
            props = p.inclusion_props
            if props.get('carbonic_fraction') is not None:
                cur = db.inclusion(inc_id)
                if cur['carbonic_fraction'] is None:
                    db.set_carbonic_fraction(inc_id, props['carbonic_fraction'], props.get('carbonic_fraction_unc'),
                                             props.get('carbonic_fraction_method'), None)
                elif abs(cur['carbonic_fraction'] - props['carbonic_fraction']) > 1e-9:
                    rep.messages.append(f'Строка {p.row_number}: φ включения «{p.inclusion}» уже задана '
                                        f'({100 * cur["carbonic_fraction"]:g} %), значение файла '
                                        f'({100 * props["carbonic_fraction"]:g} %) не применено')
            ini = p.initial_state
            if ini:
                cur = db.inclusion(inc_id)
                if (cur['initial_liquid'] is None and cur['initial_vapor'] is None and cur['initial_solid'] is None
                        and cur['initial_temperature_c'] is None and not cur['initial_room']):
                    db.set_initial_state(inc_id, ini['liquid'], ini['vapor'], ini['solid'], ini['temperature_c'],
                                         ini['room'])
                if ini['note'] and not cur['description']:
                    db.set_inclusion_note(inc_id, ini['note'])
            stage_id = _resolve_stage(db, inc_id, p.experiment, cache) if p.experiment else None
            added = 0
            for obs in p.observations:
                obs = dict(obs, source=f'{source}, строка {p.row_number}')
                if skip_duplicates and db.observation_exists(inc_id, obs):
                    rep.n_duplicates += 1
                    continue
                db.add_observation(inc_id, obs, stage_id)
                added += 1
            rep.n_observations += added
            if added:
                rep.n_rows_imported += 1
        except DatabaseError as exc:
            rep.n_errors += 1
            rep.messages.append(f'Строка {p.row_number}: {exc}')
    return rep
