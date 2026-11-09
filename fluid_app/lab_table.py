"""Чтение лабораторной сводной таблицы («Таблица 1/2/3»: блоки по образцам с двухстрочной шапкой).

Формат (Excel, один лист, несколько блоков):
    строка «Обр.» → название образца (и пласт);
    шапка из двух строк: «№ п/п | № обр. | Тгом. Т°С | тип включения | Т тр. газа | Тэвт Т°С |
    Тпл. г-гил. | Тпл. льда | С% экв.NaCl | Газ | Тгом. част. | d фл г/см3 | Рфл бар | форма вкл. | местонах вкл.»;
    строки «группаN» — группировка, выполненная исследователем (не FIA);
    строки «сред.» — итоговые строки, пропускаются.

«Тпл. г-гил.» — температура плавления газогидрата (клатрата CO₂); в шапке опечатка (подтверждено лабораторией).

Измерения превращаются в наблюдения FluidCalc. Результаты лаборатории (С%, d фл, Р фл) НЕ импортируются как
измерения: они сохраняются отдельно для сравнения (см. tools/compare_lab_table.py). Фазовые признаки для
уравнения Darling, направление гомогенизации CO₂ и чистота CO₂ в таблице не записаны и не угадываются.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from .importer import ParsedRow

# Столбцы по тексту двухстрочной шапки (верхняя + нижняя строка, нормализованные)
_HEADER_RULES = [
    ('row_no', lambda top, bot: top.startswith('№') and 'п/п' in bot),
    ('inclusion', lambda top, bot: top.startswith('№') and 'обр' in bot),
    ('Th_total', lambda top, bot: top.startswith('тгом') and 'част' not in bot),
    ('Th_CO2', lambda top, bot: top.startswith('тгом') and 'част' in bot),
    ('inclusion_type', lambda top, bot: top.startswith('тип')),
    ('Tm_CO2', lambda top, bot: top.startswith('т тр')),
    ('Te', lambda top, bot: top.startswith('тэвт')),
    ('Tm_clath', lambda top, bot: top.startswith('тпл') and ('г-гил' in bot or 'гидр' in bot or 'клат' in bot)),
    ('Tm_ice', lambda top, bot: top.startswith('тпл') and 'льд' in bot),
    ('lab_salinity', lambda top, bot: top.startswith('с%') or top.startswith('c%')),
    ('gas', lambda top, bot: top.startswith('газ')),
    ('lab_density', lambda top, bot: top.startswith('d фл')),
    ('lab_pressure', lambda top, bot: top.startswith('рфл') or top.startswith('p фл')),
    ('shape', lambda top, bot: top.startswith('форма')),
    ('location', lambda top, bot: top.startswith('местонах')),
]
KIND_COLUMNS = ('Th_total', 'Tm_CO2', 'Te', 'Tm_clath', 'Tm_ice', 'Th_CO2')
LAB_RESULT_COLUMNS = ('lab_salinity', 'lab_density', 'lab_pressure')


def _norm(v) -> str:
    if v is None:
        return ''
    s = str(v).replace(' ', ' ').strip().lower().replace('ё', 'е')
    return re.sub(r'\s+', ' ', s)


def _num(v):
    """Число или None; нечисловой текст возвращается как ('bad', текст)."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, bool):
        return ('bad', str(v))
    if isinstance(v, (int, float)):
        return None if isinstance(v, float) and math.isnan(v) else float(v)
    s = str(v).strip().replace('−', '-').replace(' ', '')
    if re.fullmatch(r'[-+]?\d+([.,]\d+)?', s):
        return float(s.replace(',', '.'))
    return ('bad', str(v).strip())


@dataclass
class LabRow:
    sample: str
    layer: str
    group: str
    sheet_row: int
    row_no: object
    inclusion: str
    inclusion_type: str
    gas: str
    shape: str
    location: str
    measurements: dict = field(default_factory=dict)   # kind -> float
    lab_results: dict = field(default_factory=dict)    # lab_salinity/lab_density/lab_pressure -> float | ('bad', text)
    problems: list[str] = field(default_factory=list)

    @property
    def co2_bearing(self) -> bool:
        t = _norm(self.inclusion_type)
        return 'со2' in t or 'co2' in t or 'со3' in t or 'с02' in t


@dataclass
class LabTable:
    path: str
    rows: list[LabRow]
    warnings: list[str]


def read_lab_table(path: str | Path, sheet: str | None = None) -> LabTable:
    from openpyxl import load_workbook
    wb = load_workbook(str(path), read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb.worksheets[0]
        grid = [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()
    rows: list[LabRow] = []
    warnings: list[str] = []
    sample = layer = group = ''
    cols: dict[str, int] | None = None
    i = 0
    while i < len(grid):
        r = grid[i]
        cells = [_norm(c) for c in r]
        # строка образца: «Обр.» / «Обр,» в любой из первых ячеек, название — в следующей
        for j, c in enumerate(cells[:4]):
            if c.startswith('обр') and j + 1 < len(r) and r[j + 1] not in (None, ''):
                sample = str(r[j + 1]).strip()
                layer = str(r[j + 2]).strip() if j + 2 < len(r) and r[j + 2] not in (None, '') else ''
                group = ''
                cols = None
                break
        # шапка: строка, где первая ячейка «№», и следующая строка с «п/п»
        if cells and cells[0].startswith('№') and i + 1 < len(grid):
            bottom = [_norm(c) for c in grid[i + 1]]
            cols = {}
            for j, top in enumerate(cells):
                bot = bottom[j] if j < len(bottom) else ''
                for key, rule in _HEADER_RULES:
                    if key not in cols and rule(top, bot):
                        cols[key] = j
                        break
            missing = [k for k in ('inclusion', 'Th_total') if k not in cols]
            if missing:
                warnings.append(f'Строка {i + 1}: в шапке не найдены столбцы {missing}; блок пропущен.')
                cols = None
            i += 2
            continue
        if cols is not None:
            joined = ' '.join(c for c in cells if c)
            if re.fullmatch(r'группа\s*\d+', joined):
                group = joined.replace('группа', 'группа ').replace('  ', ' ')
            elif isinstance(r[cols.get('row_no', 0)], (int, float)) and not isinstance(r[cols.get('row_no', 0)], bool):
                rows.append(_make_row(r, cols, sample, layer, group, i + 1))
            elif any(c.startswith('сред') for c in cells):
                pass                                    # итоговая строка исследователя
        i += 1
    if not rows:
        warnings.append('Не найдено ни одной строки включения. Проверьте формат таблицы.')
    return LabTable(str(path), rows, warnings)


def _make_row(r, cols, sample, layer, group, sheet_row) -> LabRow:
    def cell(key):
        j = cols.get(key)
        return r[j] if j is not None and j < len(r) else None

    def text(key):
        v = cell(key)
        return '' if v is None else str(v).strip()

    row = LabRow(sample=sample, layer=layer, group=group, sheet_row=sheet_row, row_no=cell('row_no'),
                 inclusion=text('inclusion'), inclusion_type=text('inclusion_type'), gas=text('gas'),
                 shape=text('shape'), location=text('location'))
    if not row.inclusion:
        row.problems.append('нет номера включения')
    if not sample:
        row.problems.append('не найдено название образца над таблицей')
    for key in KIND_COLUMNS:
        v = _num(cell(key))
        if isinstance(v, tuple):
            row.problems.append(f'{key}: нечисловое значение «{v[1]}»')
        elif v is not None:
            row.measurements[key] = v
    for key in LAB_RESULT_COLUMNS:
        v = _num(cell(key))
        if v is not None:
            row.lab_results[key] = v
            if isinstance(v, tuple):
                row.problems.append(f'{key}: нечисловое значение «{v[1]}» (результат лаборатории)')
    return row


def to_parsed_rows(table: LabTable, *, confirm_clathrate_phases: bool = False) -> list[ParsedRow]:
    """Преобразовать в строки импорта FluidCalc.

    confirm_clathrate_phases — явное подтверждение оператора, что во включениях с CO₂ при окончательном
    плавлении клатрата сосуществовали жидкая CO₂, газовая CO₂ и раствор. По умолчанию не подтверждено:
    наличие этих фаз при комнатной температуре само по себе этого не доказывает.
    """
    out = []
    for lr in table.rows:
        p = ParsedRow(lr.sheet_row, sample=lr.sample, inclusion=lr.inclusion, inclusion_type=lr.inclusion_type)
        p.errors = [x for x in lr.problems if '(результат лаборатории)' not in x]
        p.warnings = [x for x in lr.problems if '(результат лаборатории)' in x]
        notes = [x for x in (lr.layer, lr.group and f'{lr.group} (группировка исследователя, не FIA)',
                             lr.shape and f'форма: {lr.shape}', lr.location and f'местоположение: {lr.location}',
                             lr.gas and f'газ: {lr.gas}') if x]
        lab = '; '.join(f'{k}={v if not isinstance(v, tuple) else v[1]}' for k, v in lr.lab_results.items())
        comment = 'Импорт лабораторной таблицы' + (f'. Значения лаборатории: {lab}' if lab else '')
        for kind, t in lr.measurements.items():
            obs = {'kind': kind, 'temperature_c': t, 'uncertainty_c': None, 'homogenization_to': None,
                   'liquid_co2_present': None, 'vapor_co2_present': None, 'aqueous_brine_present': None,
                   'co2_purity_confirmed': None, 'phase_notes': '; '.join(notes) or None, 'comment': comment}
            if kind == 'Tm_clath' and confirm_clathrate_phases and lr.co2_bearing:
                obs.update(liquid_co2_present=True, vapor_co2_present=True, aqueous_brine_present=True,
                           comment=comment + '. Сосуществование фаз при плавлении клатрата подтверждено '
                                             'оператором при импорте')
            p.observations.append(obs)
        if not p.observations and not p.errors:
            p.warnings.append('нет измерений')
        out.append(p)
    return out
