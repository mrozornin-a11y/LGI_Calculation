"""Сверка результатов лабораторной таблицы с расчётом FluidCalc.

Проверяется только то, что можно проверить без непроверенных моделей:
  * солёность: пересчёт по Bodnar (1993) / Darling (1991) из той же температуры;
  * внутренняя согласованность: одинаковая температура → одинаковая солёность;
  * плотность флюида: физическая возможность (объёмно-взвешенная плотность фаз не может быть
    больше плотности самой плотной фазы);
  * CO₂: признаки примесей (Tm CO₂) и близость Th CO₂ к критической точке.
Давление лаборатории не пересчитывается: метод суммы парциальных давлений CO₂ и H₂O программой
не реализуется (см. docs/LAB_METHOD_REVIEW.md).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from fluid_core.co2 import CRITICAL_POINT_C, TRIPLE_POINT_C
from fluid_core.salinity import bodnar_1993, darling_1991

from .lab_table import LabRow, LabTable

# Пороги расхождения солёности, мас. % NaCl-экв.:
#  0,2 — округление табличного значения до 0,1 (±0,05) + отсчёт температуры с шагом 0,1 °C
#        (dS/dT до ≈1,8 мас. %/°C → ±0,09) с запасом;
#  0,5 — расхождение, которое нельзя объяснить округлением и разными таблицами.
SALINITY_MINOR = 0.2
SALINITY_MAJOR = 0.5
# Насыщенный раствор NaCl при 20 °C ≈ 1,20 г/см³ (CRC Handbook) — физический верхний предел для
# водно-солевого флюида с CO₂ при солёности до насыщения NaCl.
SATURATED_BRINE_DENSITY = 1.20
NEAR_CRITICAL_C = 1.0          # предупреждать, если Th CO₂ ближе 1 °C к критической точке
CO2_TM_IMPURITY_C = 0.4        # Tm CO₂ ниже тройной точки более чем на 0,4 °C → вероятны примеси


POINTS_MATCH = 0.15            # совпадение с интерполяцией по точкам (округление до 0,1 + запас)
_CHEN_POINTS: list[tuple[float, float]] | None = None


def _chen_points() -> list[tuple[float, float]]:
    """Экспериментальные точки Chen (1972) в редакции Darling (1991, табл. 1) + опорная точка +10 °C / 0 %.

    Источник — validation/data/chen1972_darling.csv (перенос сверен аудитором по сканам). Повторяющиеся
    температуры усредняются. Используется ТОЛЬКО для объяснения лабораторных значений, не для расчёта.
    """
    global _CHEN_POINTS
    if _CHEN_POINTS is None:
        import csv
        from collections import defaultdict
        from .paths import project_root
        path = project_root() / 'validation' / 'data' / 'chen1972_darling.csv'
        groups = defaultdict(list)
        try:
            with open(path, encoding='utf-8', newline='') as fh:
                for r in csv.DictReader(fh):
                    groups[float(r['temperature_c'])].append(float(r['expected_wt_pct']))
        except OSError:
            _CHEN_POINTS = []
            return _CHEN_POINTS
        groups[10.0].append(0.0)
        _CHEN_POINTS = sorted((t, sum(v) / len(v)) for t, v in groups.items())
    return _CHEN_POINTS


def chen_points_salinity(t: float) -> float | None:
    pts = _chen_points()
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= t <= x1:
            return y0 + (y1 - y0) * (t - x0) / (x1 - x0)
    return None


def brine_density_estimate(salinity_wt_pct: float) -> float:
    """Ориентировочная плотность раствора NaCl при 20 °C, г/см³ (аппроксимация справочных значений CRC:
    5 % — 1,034; 10 % — 1,071; 16 % — 1,116). Используется только как ориентир для проверки, не в расчётах."""
    return 0.9982 + 0.0072 * salinity_wt_pct


@dataclass
class RowCheck:
    row: LabRow
    method: str = ''                 # Bodnar (1993) / Darling (1991)
    input_t: float | None = None
    lab_salinity: float | None = None
    calc_salinity: float | None = None
    salinity_status: str = ''        # согласуется / небольшое расхождение / существенное расхождение / нет данных
    points_salinity: float | None = None   # интерполяция по экспериментальным точкам Chen/Darling (как табл. 9.3)
    explained_by_points: bool = False      # расхождение с уравнением объясняется интерполяцией по точкам
    density_status: str = ''
    notes: list[str] = field(default_factory=list)

    @property
    def delta(self):
        if self.calc_salinity is None or self.lab_salinity is None:
            return None
        return self.lab_salinity - self.calc_salinity


def check_row(r: LabRow) -> RowCheck:
    c = RowCheck(r)
    m = r.measurements
    lab_s = r.lab_results.get('lab_salinity')
    c.lab_salinity = lab_s if isinstance(lab_s, float) else None
    try:
        if 'Tm_ice' in m:
            c.method, c.input_t = 'Bodnar (1993), Tm лёд', m['Tm_ice']
            c.calc_salinity = bodnar_1993(m['Tm_ice']).salinity_wt_pct_nacl_eq + 0.0
        elif 'Tm_clath' in m:
            c.method, c.input_t = 'Darling (1991), Tm клатрат', m['Tm_clath']
            c.calc_salinity = darling_1991(m['Tm_clath'], liquid_co2_present=True, vapor_co2_present=True,
                                           aqueous_brine_present=True).salinity_wt_pct_nacl_eq
    except ValueError as exc:
        c.notes.append(f'Пересчёт невозможен: {exc}')
    if c.delta is None:
        c.salinity_status = 'нет данных'
    elif abs(c.delta) <= SALINITY_MINOR:
        c.salinity_status = 'согласуется'
    elif abs(c.delta) <= SALINITY_MAJOR:
        c.salinity_status = 'небольшое расхождение'
    else:
        c.salinity_status = 'существенное расхождение'
    if 'Tm_clath' in m and c.calc_salinity is not None:
        c.points_salinity = chen_points_salinity(m['Tm_clath'])
        if (c.points_salinity is not None and c.lab_salinity is not None and c.salinity_status != 'согласуется'
                and abs(c.lab_salinity - c.points_salinity) <= POINTS_MATCH):
            c.explained_by_points = True
            c.notes.append(f'Значение таблицы соответствует линейной интерполяции по экспериментальным точкам '
                           f'Chen (1972) / Darling (1991, табл. 1) ({c.points_salinity:.2f}), а не уравнению Darling: '
                           'методическое различие, а не арифметическая ошибка')
    if 'Tm_clath' in m and c.method.startswith('Darling'):
        c.notes.append('Darling: сосуществование жидкой CO₂, газовой CO₂ и раствора при плавлении клатрата в '
                       'таблице не зафиксировано; при пересчёте принято как условие уравнения')

    d = r.lab_results.get('lab_density')
    if isinstance(d, tuple):
        c.density_status = f'нечисловое значение «{d[1]}»'
    elif isinstance(d, float):
        ref_s = c.calc_salinity if c.calc_salinity is not None else c.lab_salinity
        if d > SATURATED_BRINE_DENSITY:
            c.density_status = (f'физически невозможно: больше плотности насыщенного раствора NaCl '
                                f'(≈{SATURATED_BRINE_DENSITY:.2f} г/см³)')
        elif ref_s is not None and d > brine_density_estimate(ref_s) + 0.02:
            c.density_status = (f'невозможно при объёмном усреднении: больше плотности раствора '
                                f'{ref_s:.1f} мас. % (≈{brine_density_estimate(ref_s):.3f} г/см³), а CO₂ легче раствора')
        else:
            c.density_status = 'в физически возможных пределах (точность не проверялась)'
    if 'Tm_CO2' in m:
        dep = (TRIPLE_POINT_C) - m['Tm_CO2']
        if dep > CO2_TM_IMPURITY_C:
            c.notes.append(f'Tm CO₂ = {m["Tm_CO2"]:g} °C ниже тройной точки чистой CO₂ на {dep:.1f} °C: вероятны '
                           'примеси (CH₄, N₂). Приближение чистой CO₂ и уравнение Darling — с оговоркой; нужен Раман')
    if 'Th_CO2' in m:
        prox = CRITICAL_POINT_C - m['Th_CO2']
        if prox < NEAR_CRITICAL_C:
            c.notes.append(f'Th CO₂ = {m["Th_CO2"]:g} °C в {prox:.2f} °C от критической точки: плотность сильно '
                           'зависит от ветви (жидкость/газ), а ветвь в таблице не записана')
        else:
            c.notes.append('Направление гомогенизации CO₂ в таблице не записано: плотность CO₂ (жидкая или газовая '
                           'ветвь) по таблице однозначно не определяется')
    if 'lab_pressure' in r.lab_results:
        c.notes.append('Давление лаборатории не проверяется: метод суммы парциальных давлений CO₂ и H₂O '
                       'программой не используется')
    return c


def salinity_verdict(c: RowCheck) -> str:
    if c.salinity_status in ('согласуется', 'нет данных'):
        return c.salinity_status
    if c.explained_by_points:
        return 'по экспериментальным точкам (табл. 9.3), не по уравнению'
    return c.salinity_status


def internal_inconsistencies(checks: list[RowCheck]) -> list[str]:
    """Одинаковая входная температура (тем же методом) → разные значения солёности в таблице.

    Различия в пределах округления (≤ 0,15 мас. %) не считаются несогласованностью."""
    by = defaultdict(set)
    ids = defaultdict(list)
    for c in checks:
        if c.input_t is not None and c.lab_salinity is not None:
            by[(c.method, c.input_t)].add(c.lab_salinity)
            ids[(c.method, c.input_t)].append(f'{c.row.sample} {c.row.inclusion}')
    out = []
    for (method, t), vals in sorted(by.items()):
        if len(vals) > 1 and max(vals) - min(vals) > 0.15:     # больше округления до 0,1
            out.append(f'{method}: T = {t:g} °C → в таблице {", ".join(f"{v:g}" for v in sorted(vals))} '
                       f'({"; ".join(ids[(method, t)])})')
    return out


def compare(table: LabTable) -> tuple[list[RowCheck], list[str]]:
    checks = [check_row(r) for r in table.rows]
    return checks, internal_inconsistencies(checks)


def write_comparison_xlsx(table: LabTable, path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    checks, incons = compare(table)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Сверка'
    head = ['Образец', 'Пласт', 'Группа', 'Включение', 'Тип', 'Th общ., °C', 'Te, °C', 'Tm CO₂, °C', 'Tm клатрат, °C',
            'Tm лёд, °C', 'Th CO₂, °C', 'Метод пересчёта', 'С% лаборатории', 'С% FluidCalc', 'Разность (лаб − расчёт)',
            'Солёность', 'С% по точкам Chen/Darling (как табл. 9.3)', 'd фл лаборатории, г/см³', 'Плотность: проверка',
            'Р фл лаборатории, бар', 'Замечания']
    ws.append(head)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical='top')
    fills = {'согласуется': 'E2F0D9', 'небольшое расхождение': 'FFF2CC', 'существенное расхождение': 'F8D7DA',
             'по экспериментальным точкам (табл. 9.3), не по уравнению': 'DDEBF7'}
    for c in checks:
        r, m = c.row, c.row.measurements
        d = r.lab_results.get('lab_density')
        ws.append([r.sample, r.layer, r.group, r.inclusion, r.inclusion_type, m.get('Th_total'), m.get('Te'),
                   m.get('Tm_CO2'), m.get('Tm_clath'), m.get('Tm_ice'), m.get('Th_CO2'), c.method, c.lab_salinity,
                   None if c.calc_salinity is None else round(c.calc_salinity, 3),
                   None if c.delta is None else round(c.delta, 3), salinity_verdict(c),
                   None if c.points_salinity is None else round(c.points_salinity, 3),
                   d[1] if isinstance(d, tuple) else d, c.density_status, r.lab_results.get('lab_pressure'),
                   ' | '.join(c.notes)])
        row = ws.max_row
        if salinity_verdict(c) in fills:
            ws.cell(row, 16).fill = PatternFill('solid', fgColor=fills[salinity_verdict(c)])
        if c.density_status.startswith(('физически', 'невозможно', 'нечисл')):
            ws.cell(row, 19).fill = PatternFill('solid', fgColor='F8D7DA')
    widths = [8, 8, 10, 10, 16, 8, 8, 8, 8, 8, 8, 22, 9, 9, 10, 22, 12, 10, 40, 10, 90]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = w
    ws.freeze_panes = 'E2'

    s = wb.create_sheet('Итоги')
    s.append(['Показатель', 'Значение'])
    sal = [c for c in checks if c.delta is not None]
    for status in ('согласуется', 'по экспериментальным точкам (табл. 9.3), не по уравнению',
                   'небольшое расхождение', 'существенное расхождение'):
        s.append([f'Солёность: {status}', sum(salinity_verdict(c) == status for c in sal)])
    dens = [c for c in checks if c.density_status]
    s.append(['Плотность: значений', len(dens)])
    s.append(['Плотность: физически невозможных / нечисловых',
              sum(c.density_status.startswith(('физически', 'невозможно', 'нечисл')) for c in dens)])
    s.append([])
    s.append(['Внутренние несогласованности таблицы'])
    for x in incons or ['не обнаружено']:
        s.append([x])
    s.append([])
    s.append(['Пороги: «согласуется» — |разность| ≤ 0,2 мас. % (округление до 0,1 и отсчёт T с шагом 0,1 °C); '
              '«существенное» — > 0,5 мас. %. Ориентир плотности раствора NaCl — CRC Handbook, 20 °C.'])
    s.column_dimensions['A'].width = 110
    s.column_dimensions['B'].width = 12
    wb.save(str(path))
