"""Экспорт результатов расчёта (CSV / XLSX) с паспортом методик и полная выгрузка базы."""
from __future__ import annotations

import csv
from pathlib import Path

from .calc import passport_lines
from .db import Database
from .methods import (METHODS, GENERAL_LIMITATIONS, NOT_IMPLEMENTED_MODELS, PENDING_VALIDATION,
                      HOMOGENIZATION, STATUS_RU, CATEGORY_RU, INTERPRETATION_STATUS_RU, kind_label, method_category,
                      status_label)

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
    ('Пар при растворении галита', lambda run, r: _flag(r['inputs'].get('vapor_present_at_transition'))),
    ('Фаза определена как гидрогалит', lambda run, r: _flag(r['inputs'].get('phase_identified'))),
    ('КР-спектроскопия газовой фазы', lambda run, r: r['inputs'].get('raman_species') or ''),
    ('Вид сведений', lambda run, r: CATEGORY_RU[method_category(r.get('method_key'))]),
    ('Статус', lambda run, r: status_label(r['status'], r.get('method_key'))),
    ('Результат', lambda run, r: r['result_kind'] or ''),
    ('Значение', lambda run, r: r['value']),
    ('Единицы', lambda run, r: r['unit'] or ''),
    ('P_sat CO₂, бар', lambda run, r: r['extras'].get('saturation_pressure_bar')),
    ('Мольный объём CO₂, см³/моль', lambda run, r: r['extras'].get('molar_volume_cm3_mol')),
    ('До крит. точки CO₂, °C', lambda run, r: r['extras'].get('critical_proximity_c')),
    ('Режим модели H₂O–CO₂–NaCl', lambda run, r: r['extras'].get('mode_title') or ''),
    ('X(H₂O), мол. доля', lambda run, r: r['extras'].get('x_h2o')),
    ('X(CO₂), мол. доля', lambda run, r: r['extras'].get('x_co2')),
    ('X(NaCl), мол. доля', lambda run, r: r['extras'].get('x_nacl')),
    ('Солёность валовая, мас. %', lambda run, r: r['extras'].get('salinity_bulk_wt_pct')),
    ('Молярный объём включения, см³/моль', lambda run, r: r['extras'].get('molar_volume_cm3_mol')
     if 'x_co2' in r['extras'] else None),
    ('P при Tm клатрата (внутри включения), бар', lambda run, r: r['extras'].get('pressure_at_tm_clath_bar')),
    ('P при Th CO₂ (насыщение CO₂), бар', lambda run, r: r['extras'].get('pressure_at_th_co2_bar')),
    ('P на линии расслоения при Th общ. (Mao 2013), бар',
     lambda run, r: r['extras'].get('pressure_solvus_th_total_bar')),
    ('P по изохоре при Th общ. (Duan 1995), бар', lambda run, r: r['extras'].get('pressure_isochore_th_total_bar')),
    ('Способ расчёта P по изохоре при Th общ.',
     lambda run, r: r['extras'].get('pressure_isochore_th_total_method') or ''),
    ('Расхождение двух P при Th общ., бар', lambda run, r: r['extras'].get('pressure_th_total_difference_bar')),
    ('Расхождение двух P при Th общ., %', lambda run, r: r['extras'].get('pressure_th_total_difference_pct')),
    ('Изохора (T °C → P бар)', lambda run, r: '; '.join(f'{t:.0f} → {p:.0f}' for t, p in r['extras']['isochore'])
     if r['extras'].get('isochore') else ''),
    ('Заключение интерпретации', lambda run, r: r['message'] if method_category(r.get('method_key')) ==
     'interpretation' and r['status'] == 'ok' else ''),
    ('Условия захвата: T, °C', lambda run, r: _trap_cell(r, 'temperature_c', 'temperature_range_c', 1)),
    ('Условия захвата: P, бар', lambda run, r: _trap_cell(r, 'pressure_bar', 'pressure_range_bar', 0)),
    ('Условия захвата: формулировка', lambda run, r: r['extras'].get('wording') or ''),
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


def _trap_cell(r, single, rng, digits):
    """Значение или диапазон условий захвата для строки результата «Условия захвата»."""
    ex = r['extras']
    if not ex.get('constraint'):
        return None
    if ex.get(rng):
        return f'{ex[rng][0]:.{digits}f} … {ex[rng][1]:.{digits}f}'
    return ex.get(single)


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
    fills = {'рассчитано': 'E2F0D9', 'отказ': 'F8D7DA', 'не рассчитывается': 'EDEDED',
             INTERPRETATION_STATUS_RU: 'DDEBF7'}
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
               'aqueous_brine_present', 'co2_purity_confirmed', 'phase_notes', 'comment', 'carbonic_fraction_pct',
               'carbonic_fraction_unc_pct', 'carbonic_fraction_method', 'vapor_present_at_transition',
               'phase_identified']
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
                        o['phase_notes'] or '', o['comment'] or '',
                        '' if o.get('carbonic_fraction') is None else repr(100 * o['carbonic_fraction']),
                        '' if o.get('carbonic_fraction_unc') is None else repr(100 * o['carbonic_fraction_unc']),
                        o.get('carbonic_fraction_method') or '', fl(o.get('vapor_present_at_transition')),
                        fl(o.get('phase_identified'))])
    return path


# --- Экспорт в формате лабораторной сводной таблицы («Таблица 1/2/3») ------------------------
LAB_HEADERS = ['№ п/п', '№ вкл.', 'Th общ., °C', 'Тип включения', 'Tm CO₂, °C', 'Тэвт, °C', 'Tm клатрата, °C',
               'Tm льда, °C', 'Солёность, мас. % NaCl-экв.', 'Метод солёности', 'Th CO₂, °C', 'Гомог. CO₂',
               'ρ CO₂, г/см³', 'φ CO₂, %', 'ρ включения, г/см³', 'Ph при Th (мин.), бар', 'dP/dT изохоры, бар/°C',
               'ρ включения, строгая модель, г/см³', 'X(CO₂), мол. %', 'Солёность валовая, мас. %',
               'P расслоения при Th общ., бар', 'P по изохоре при Th общ., бар', 'Предупреждения модели',
               'Tm гидрогалита, °C', 'Солёность по гидрогалиту, мас. % NaCl', 'T раств. галита, °C',
               'Солёность по галиту, мас. % NaCl', 'Te: интерпретация (не состав)', 'Tm CO₂: интерпретация',
               'Условия захвата при независимом ограничении', 'Замечания']
_HOMOG_SHORT = {'liquid': 'Ж', 'vapor': 'Г', 'critical': 'крит.'}


def _natural_key(s: str):
    import re
    return [int(x) if x.isdigit() else x for x in re.split(r'(\d+)', s or '')]


def _first_value(ok_rows, digits):
    return round(ok_rows[0]['value'], digits) if len(ok_rows) == 1 and ok_rows[0]['value'] is not None else None


def _messages(ok_rows):
    return ' | '.join(r['message'] for r in ok_rows if r['message']) or None


def _trap_text(ok_rows):
    if not ok_rows:
        return None
    r = ok_rows[0]
    t, p = _trap_cell(r, 'temperature_c', 'temperature_range_c', 1), _trap_cell(r, 'pressure_bar',
                                                                              'pressure_range_bar', 0)
    fmt = lambda v, d: v if isinstance(v, str) else f'{v:.{d}f}'            # noqa: E731
    return f'{fmt(t, 1)} °C; {fmt(p, 0)} бар — {r["extras"].get("wording", "")}'


def _pvtx_cells(ok_rows: list[dict]) -> list:
    """Столбцы строгой модели H₂O–CO₂–NaCl для лабораторной раскладки (пустые, если расчёта нет)."""
    if not ok_rows:
        return [None] * 6
    r = ok_rows[0]
    ex = r['extras']

    def rnd(key, digits, scale=1.0):
        return None if ex.get(key) is None else round(scale * ex[key], digits)
    return [round(r['value'], 4), rnd('x_co2', 2, 100.0), rnd('salinity_bulk_wt_pct', 2),
            rnd('pressure_solvus_th_total_bar', 0), rnd('pressure_isochore_th_total_bar', 0),
            ' | '.join(r['warnings'] or [])]


def _lab_rows(results: list[dict], inclusion_types: dict):
    by_inc: dict = {}
    for r in results:
        by_inc.setdefault((r['sample_name'], r['inclusion_name']), []).append(r)
    samples: dict = {}
    for (sample, inc), rs in by_inc.items():
        def temps(kind):
            vals = [x['inputs'].get('temperature_c') for x in rs if x['kind'] == kind]
            vals = [v for v in vals if v is not None]
            return '; '.join(f'{v:g}' for v in vals) if len(vals) > 1 else (vals[0] if vals else None)

        def ok(kind):
            return [x for x in rs if x['kind'] == kind and x['status'] == 'ok']
        sal, method = None, ''
        if ok('Tm_clath'):
            sal, method = ok('Tm_clath')[0]['value'], 'Darling (1991)'
        elif ok('Tm_ice'):
            sal, method = ok('Tm_ice')[0]['value'], 'Bodnar (1993)'
        co2 = [x for x in rs if x['kind'] == 'Th_CO2']
        homog = '; '.join(_HOMOG_SHORT.get(x['inputs'].get('homogenization_to'), '?') for x in co2)
        rho_c = ok('Th_CO2')[0]['value'] if len(ok('Th_CO2')) == 1 else None
        dens = [x for x in rs if x['kind'] == 'bulk_density']
        phi = dens[0]['inputs'].get('carbonic_fraction') if dens else None
        rho_b = ok('bulk_density')[0]['value'] if ok('bulk_density') else None
        aq = ok('aq_pvt')
        ph = slope = None
        if aq:
            rho_b, ph, slope = aq[0]['value'], aq[0]['extras'].get('Ph_bar'), aq[0]['extras'].get('dPdT_bar_per_C')
        notes = [f'{kind_label(x["kind"])}: {x["message"]}' for x in rs if x['status'] == 'error' and x['message']]
        samples.setdefault(sample, []).append([
            inc, temps('Th_total'), inclusion_types.get((sample, inc), ''), temps('Tm_CO2'), temps('Te'),
            temps('Tm_clath'), temps('Tm_ice'), None if sal is None else round(sal, 2), method, temps('Th_CO2'),
            homog, None if rho_c is None else round(rho_c, 4), None if phi is None else round(100 * phi, 1),
            None if rho_b is None else round(rho_b, 3), None if ph is None else round(ph, 1),
            None if slope is None else round(slope, 2), *_pvtx_cells(ok('co2_pvtx')),
            temps('Tm_hydrohalite'), _first_value(ok('Tm_hydrohalite'), 2), temps('T_diss_halite'),
            _first_value(ok('T_diss_halite'), 2), _messages(ok('Te')), _messages(ok('Tm_CO2')),
            _trap_text(ok('trapping')), ' | '.join(notes)])
    return samples


def export_lab_format_xlsx(path, run: dict, results: list[dict], db: Database | None = None) -> Path:
    """Результаты расчёта в раскладке лабораторной сводной таблицы: блок на образец, пересчитанные столбцы.

    Давление захвата в таблице отсутствует намеренно; метод суммы парциальных давлений не используется."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    path = Path(path)
    types = {}
    if db is not None:
        for row in db._all('SELECT s.name AS s, i.name AS i, i.inclusion_type AS t FROM inclusions i '
                           'JOIN samples s ON s.id = i.sample_id'):
            types[(row['s'], row['i'])] = row['t'] or ''
    samples = _lab_rows(results, types)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Сводная таблица'
    bold = Font(bold=True)
    ws.append([f'Расчёт № {run["id"]} от {run["created_at"]} UTC; FluidCalc {run["app_version"]}, ядро '
               f'{run["core_version"]}, CoolProp {run["coolprop_version"]}'])
    for sample in sorted(samples, key=_natural_key):
        ws.append([])
        ws.append([f'Образец {sample}'])
        ws.cell(ws.max_row, 1).font = bold
        ws.append(LAB_HEADERS)
        for c in ws[ws.max_row]:
            c.font = bold
            c.alignment = Alignment(wrap_text=True, vertical='top')
        for n, row in enumerate(sorted(samples[sample], key=lambda r: _natural_key(r[0])), start=1):
            ws.append([n] + row)
    ws.append([])
    for line in (
            'Солёность: Bodnar (1993) по Tm льда; Darling (1991) по Tm клатрата — по уравнению, а не по табличным '
            'точкам. Значения — NaCl-эквивалент, не химический анализ.',
            'ρ CO₂ — плотность чистой CO₂ на линии насыщения при Th CO₂ (Span & Wagner, 1996) по записанному '
            'направлению гомогенизации (Ж — в жидкость, Г — в газ).',
            'ρ включения — объёмный баланс фаз: φ·ρ(CO₂) + (1 − φ)·ρ(раствора NaCl при 20 °C, CRC). Растворённая CO₂ '
            'не учитывается; точность ограничена оценкой φ.',
            'Водно-солевые включения (H₂O–NaCl, гомогенизация в жидкость): ρ включения и Ph — HokieFlincs '
            '(Atkinson, 2002; Bodnar, 1983; Bodnar & Vityk, 1994). Ph — давление при Th, т. е. МИНИМАЛЬНОЕ давление '
            'захвата; давление захвата = Ph + dP/dT·(T захвата − Th) при независимой оценке T захвата.',
            'Включения с CO₂, строгая модель H₂O–CO₂–NaCl (Steele-MacInnis, 2018): плотность, мольная доля CO₂ и '
            'валовая солёность — сошедшееся решение уравнений модели. Сумма «парциальных» давлений CO₂ и воды '
            'термодинамически неверна и не используется.',
            'P расслоения при Th общ. (Mao et al., 2013) и P по изохоре при Th общ. (Duan et al., 1995; ниже 300 °C — '
            'экстраполяция) — два РАЗНЫХ расчёта; они не взаимозаменяемы и НЕ являются давлением захвата. '
            'Предупреждения модели приведены в отдельном столбце.',
            'Солёность по гидрогалиту — только бинарная система H₂O–NaCl (Steele-MacInnis et al., 2011, предел Ψ = 1) '
            'и только если фаза определена как гидрогалит; по галиту — Sterner et al. (1988), только если при '
            'растворении галита присутствует пар. Интерпретации Te и Tm CO₂ — диагностические, состав по ним не '
            'определяется.',
            'Условия захвата при независимом ограничении — точка на изохоре при заданной оператором температуре или '
            'давлении; это не условия минералообразования, если одновременность с ростом минерала не документирована.',
            'Th не является температурой образования без доказательства гетерогенного захвата в пределах FIA.'):
        ws.append([line])
    widths = [7, 10, 9, 18, 9, 9, 10, 9, 12, 15, 9, 8, 10, 8, 11, 11, 11, 12, 10, 11, 12, 12, 80, 10, 12, 10, 12, 60,
              60, 60, 80]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    wb.save(str(path))
    return path
