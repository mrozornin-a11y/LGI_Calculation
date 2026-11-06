"""Экспорт результатов расчёта (CSV / XLSX) с паспортом методик и полная выгрузка базы."""
from __future__ import annotations

import csv
from pathlib import Path

from .calc import passport_lines
from .db import Database
from .methods import (METHODS, GENERAL_LIMITATIONS, NOT_IMPLEMENTED_MODELS, PENDING_VALIDATION,
                      HOMOGENIZATION, STATUS_RU, kind_label)

RESULT_COLUMNS = [
    ('Расчёт №', lambda run, r: run['id']),
    ('Проект', lambda run, r: r['project_name']),
    ('Образец', lambda run, r: r['sample_name']),
    ('Минерал', lambda run, r: r['mineral_name'] or ''),
    ('FIA', lambda run, r: r['fia_name'] or ''),
    ('Включение', lambda run, r: r['inclusion_name']),
    ('ID наблюдения', lambda run, r: r['observation_id'] if r['observation_id'] is not None else ''),
    ('Тип наблюдения', lambda run, r: kind_label(r['kind'])),
    ('T, °C', lambda run, r: r['inputs'].get('temperature_c')),
    ('Погрешность ±, °C', lambda run, r: r['inputs'].get('uncertainty_c')),
    ('Направление гомогенизации', lambda run, r: HOMOGENIZATION.get(r['inputs'].get('homogenization_to'), '')),
    ('Жидкая CO₂', lambda run, r: _flag(r['inputs'].get('liquid_co2_present'))),
    ('Газовая CO₂', lambda run, r: _flag(r['inputs'].get('vapor_co2_present'))),
    ('Водный раствор', lambda run, r: _flag(r['inputs'].get('aqueous_brine_present'))),
    ('Чистая CO₂ принята', lambda run, r: _flag(r['inputs'].get('co2_purity_confirmed'))),
    ('Статус', lambda run, r: STATUS_RU.get(r['status'], r['status'])),
    ('Результат', lambda run, r: r['result_kind'] or ''),
    ('Значение', lambda run, r: r['value']),
    ('Единицы', lambda run, r: r['unit'] or ''),
    ('P_sat CO₂, бар', lambda run, r: r['extras'].get('saturation_pressure_bar')),
    ('Мольный объём CO₂, см³/моль', lambda run, r: r['extras'].get('molar_volume_cm3_mol')),
    ('До крит. точки CO₂, °C', lambda run, r: r['extras'].get('critical_proximity_c')),
    ('Значение при T−u', lambda run, r: r['extras'].get('sensitivity_t_minus_u')),
    ('Значение при T+u', lambda run, r: r['extras'].get('sensitivity_t_plus_u')),
    ('Методика', lambda run, r: r['model'] or ''),
    ('DOI', lambda run, r: r['doi'] or ''),
    ('Источник', lambda run, r: r['citation'] or ''),
    ('Область применимости', lambda run, r: r['scope'] or ''),
    ('Допущения', lambda run, r: r['assumptions'] or ''),
    ('Предупреждения', lambda run, r: ' | '.join(r['warnings'] or [])),
    ('Причина отказа / примечание', lambda run, r: r['message'] or ''),
    ('Сообщение ядра (исходное)', lambda run, r: r['message_original'] or ''),
    ('Источник данных', lambda run, r: r['inputs'].get('source') or ''),
    ('Дата расчёта (UTC)', lambda run, r: run['created_at']),
    ('Версия FluidCalc', lambda run, r: run['app_version']),
    ('Версия ядра', lambda run, r: run['core_version']),
    ('Версия CoolProp', lambda run, r: run['coolprop_version']),
]


def _flag(v):
    return '' if v is None else ('да' if v else 'нет')


def result_table(run: dict, results: list[dict]) -> tuple[list[str], list[list]]:
    headers = [c[0] for c in RESULT_COLUMNS]
    rows = [[fn(run, r) for _, fn in RESULT_COLUMNS] for r in results]
    return headers, rows


def _csv_value(v, decimal_comma: bool):
    if v is None:
        return ''
    if isinstance(v, float):
        s = f'{v:.9g}'
        return s.replace('.', ',') if decimal_comma else s
    return v


def export_results_csv(path: str | Path, run: dict, results: list[dict], *, delimiter: str = ';',
                       decimal_comma: bool = True) -> Path:
    """CSV в UTF-8 с BOM. По умолчанию «;» и десятичная запятая — для русской локали Excel/LibreOffice."""
    path = Path(path)
    headers, rows = result_table(run, results)
    with path.open('w', encoding='utf-8-sig', newline='') as fh:
        w = csv.writer(fh, delimiter=delimiter)
        w.writerow(headers)
        for row in rows:
            w.writerow([_csv_value(v, decimal_comma) for v in row])
    return path


def export_results_xlsx(path: str | Path, run: dict, results: list[dict]) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    path = Path(path)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Результаты'
    headers, rows = result_table(run, results)
    ws.append(headers)
    bold = Font(bold=True)
    for c in ws[1]:
        c.font = bold
        c.alignment = Alignment(wrap_text=True, vertical='top')
    fills = {'рассчитано': 'E2F0D9', 'отказ': 'F8D7DA', 'не рассчитывается': 'EDEDED'}
    status_col = headers.index('Статус') + 1
    for row in rows:
        ws.append(row)
        fill = fills.get(row[status_col - 1])
        if fill:
            ws.cell(ws.max_row, status_col).fill = PatternFill('solid', fgColor=fill)
    for i, h in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(10, min(45, len(h) + 4))
    ws.freeze_panes = 'A2'

    ps = wb.create_sheet('Паспорта')
    ps.append(['Строка результата', 'Поле', 'Значение'])
    for c in ps[1]:
        c.font = bold
    for n, r in enumerate(results, start=1):
        ctx = {k: r.get(k) for k in ('project_name', 'sample_name', 'mineral_name', 'fia_name', 'inclusion_name')}
        for k, v in passport_lines(r['inputs'], r, run, ctx):
            ps.append([n, k, v])
    ps.column_dimensions['B'].width = 38
    ps.column_dimensions['C'].width = 120

    info = wb.create_sheet('Расчёт')
    for k, v in (('Расчёт №', run['id']), ('Дата (UTC)', run['created_at']), ('Охват', run['scope']),
                 ('Всего наблюдений', run['n_total']), ('Рассчитано', run['n_ok']),
                 ('Отказов', run['n_error']), ('Не рассчитывается', run['n_skipped']),
                 ('FluidCalc', run['app_version']), ('Ядро fluid_core', run['core_version']),
                 ('Python', run['python_version']), ('CoolProp', run['coolprop_version']),
                 ('Платформа', run['platform'])):
        info.append([k, v])
    info.column_dimensions['A'].width = 24
    info.column_dimensions['B'].width = 60

    ms = wb.create_sheet('Методики и источники')
    ms.append(['Методика', 'Входные данные', 'Результат', 'Уравнение', 'Область применимости', 'Источник', 'DOI',
               'Допущения', 'Ограничения'])
    for c in ms[1]:
        c.font = bold
    for m in METHODS.values():
        ms.append([m['title'], m['input'], m['output'], m['equation'], m['range'], m['citation'],
                   'https://doi.org/' + m['doi'], ' '.join(m['assumptions']), ' '.join(m['limitations'])])
    for col in 'ABCDEFGHI':
        ms.column_dimensions[col].width = 40

    ls = wb.create_sheet('Ограничения')
    ls.append(['Общие ограничения'])
    ls['A1'].font = bold
    for x in GENERAL_LIMITATIONS:
        ls.append([x])
    ls.append([])
    ls.append(['Не реализованные научные модели', 'Назначение', 'DOI'])
    ls.cell(ls.max_row, 1).font = bold
    for row in NOT_IMPLEMENTED_MODELS:
        ls.append(list(row))
    ls.append([])
    ls.append(['Незавершённая научная проверка'])
    ls.cell(ls.max_row, 1).font = bold
    for x in PENDING_VALIDATION:
        ls.append([x])
    ls.column_dimensions['A'].width = 100
    ls.column_dimensions['B'].width = 60
    ls.column_dimensions['C'].width = 40
    wb.save(str(path))
    return path


def export_database_xlsx(db: Database, path: str | Path) -> Path:
    """Резервная выгрузка всех таблиц базы в XLSX (по листу на таблицу)."""
    from openpyxl import Workbook
    path = Path(path)
    wb = Workbook()
    wb.remove(wb.active)
    for table in ('projects', 'samples', 'minerals', 'fias', 'inclusions', 'observations',
                  'calc_runs', 'results', 'import_log'):
        ws = wb.create_sheet(table)
        cols, rows = db.table_rows(table)
        ws.append(cols)
        for r in rows:
            ws.append(list(r))
    wb.save(str(path))
    return path


def export_observations_csv(path: str | Path, observations: list[dict], *, delimiter: str = ';') -> Path:
    """Таблица измерений в формате, который снова читается импортом (длинный формат)."""
    path = Path(path)
    headers = ['sample_id', 'mineral', 'fia', 'inclusion_id', 'inclusion_type', 'kind', 'temperature_c',
               'uncertainty_c', 'homogenization_to', 'liquid_co2_present', 'vapor_co2_present',
               'aqueous_brine_present', 'co2_purity_confirmed', 'phase_notes', 'comment']
    with path.open('w', encoding='utf-8-sig', newline='') as fh:
        w = csv.writer(fh, delimiter=delimiter)
        w.writerow(headers)
        for o in observations:
            def fl(v):
                return '' if v is None else ('true' if v else 'false')
            w.writerow([o['sample_name'], o['mineral_name'] or '', o['fia_name'] or '', o['inclusion_name'],
                        o['inclusion_type'] or '', o['kind'], repr(o['temperature_c']),
                        '' if o['uncertainty_c'] is None else repr(o['uncertainty_c']),
                        o['homogenization_to'] or '', fl(o['liquid_co2_present']), fl(o['vapor_co2_present']),
                        fl(o['aqueous_brine_present']), fl(o['co2_purity_confirmed']),
                        o['phase_notes'] or '', o['comment'] or ''])
    return path
