"""Формирование отчёта о научной валидации (Markdown) и таблиц результатов (CSV)."""
from __future__ import annotations

import csv
import hashlib
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from .checkpoints import (CHECKPOINTS_CSV, EVIDENCE_TYPES, HERE, INDEPENDENCE, QUANTITY_RU, SOURCE_CSV,
                          UNITS_RU, Result)
from .datasets import (CHEN_CSV, EVIDENCE_RU, HALL_CSV, INDEPENDENCE_RU, KNOWN_CSV, NIST_SOURCE, NIST_TSV,
                       NIST_URL, NistRow, Reconciliation, SalinityRow, chen_statistics)

REPORT_MD = HERE / 'VALIDATION_REPORT.md'
RESULTS_DIR = HERE / 'results'
OPEN_QUESTIONS_DOC = 'docs/OPEN_VALIDATION_QUESTIONS.md'

STATUS_RU = {'PASS': 'PASS', 'FAIL': '**FAIL**', 'SKIPPED': 'SKIPPED', 'ERROR': '**ERROR**',
             'OUTSIDE_DOMAIN': 'SKIPPED: вне области ядра', 'COMPATIBLE': 'совместимо',
             'INCOMPATIBLE': '**несовместимо**'}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _versions() -> dict[str, str]:
    import fluid_core
    try:
        import CoolProp
        cp = CoolProp.__version__
    except ImportError:
        cp = 'не установлен'
    return {'Python': sys.version.split()[0], 'Платформа': platform.platform(),
            'fluid_core': getattr(fluid_core, '__version__', '?'), 'CoolProp': cp}


def _fmt(v: float | None, digits: int = 6) -> str:
    return '—' if v is None else f'{v:.{digits}g}'


def _fmt_dev(r: Result) -> str:
    if r.deviation is None:
        return '—'
    rel = r.rel_deviation
    return f'{r.deviation:+.3g} ({rel * 100:+.3g} %)' if rel is not None else f'{r.deviation:+.3g}'


def _cnt(items, attr, value):
    return sum(getattr(x, attr) == value for x in items)


# --- CSV ---------------------------------------------------------------------------
def write_results_csv(results: list[Result], path: Path | None = None) -> Path:
    path = path or RESULTS_DIR / 'checkpoints.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['id', 'method', 'temperature_c', 'quantity', 'unit', 'evidence_type', 'independence',
                    'expected', 'reference_rounding_half_unit', 'computed', 'deviation', 'rel_deviation', 'tolerance',
                    'within_reference_rounding', 'status', 'app_layer_consistent', 'gross_error_controls_detected',
                    'message'])
        for r in results:
            c = r.checkpoint
            w.writerow([c.id, c.method, c.temperature_c, c.quantity, c.unit, c.evidence_type, c.independence,
                        c.expected, '' if c.reference_rounding_half_unit is None else c.reference_rounding_half_unit,
                        '' if r.computed is None else repr(r.computed),
                        '' if r.deviation is None else f'{r.deviation:.6g}',
                        '' if r.rel_deviation is None else f'{r.rel_deviation:.6g}',
                        f'{c.tolerance():.6g}', '' if r.within_rounding is None else r.within_rounding,
                        r.status, '' if r.app_consistent is None else r.app_consistent,
                        '' if not r.controls else r.required_controls_detected, r.message])
    return path


def write_salinity_csv(rows: list[SalinityRow], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['id', 'temperature_c', 'expected_wt_pct', 'computed_wt_pct', 'deviation_wt_pct',
                    'relative_deviation_pct', 'abs_dS_dT', 'regression_tolerance', 'regression_status',
                    'experimental_envelope', 'experimental_status', 'role', 'evidence_type', 'independence',
                    'app_layer_consistent', 'reason'])
        for r in rows:
            w.writerow([r.id, r.temperature_c, r.expected, '' if r.computed is None else repr(r.computed),
                        '' if r.deviation is None else repr(r.deviation),
                        '' if r.rel_pct is None else f'{r.rel_pct:.6g}',
                        '' if r.slope is None else f'{r.slope:.8g}',
                        '' if r.regression_tol is None else f'{r.regression_tol:.8g}', r.regression,
                        '' if r.experimental_tol is None else f'{r.experimental_tol:.8g}', r.experimental, r.role,
                        r.meta['evidence_type'], r.meta['independence'],
                        '' if r.app_consistent is None else r.app_consistent, r.reason])
    return path


def write_nist_csv(rows: list[NistRow], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['id', 'temperature_k', 'temperature_c', 'quantity', 'unit', 'nist_printed', 'computed',
                    'deviation', 'rounding_half_unit', 'tolerance', 'deviation_over_half_unit', 'status',
                    'app_layer_consistent', 'reason'])
        for r in rows:
            w.writerow([r.id, r.temperature_k, r.temperature_c, r.quantity, r.unit, r.expected_text,
                        '' if r.computed is None else repr(r.computed),
                        '' if r.deviation is None else f'{r.deviation:.6g}', f'{r.rounding_half_unit:g}',
                        f'{r.tolerance:.6g}',
                        '' if r.deviation is None else f'{abs(r.deviation) / r.rounding_half_unit:.4f}',
                        r.status, '' if r.app_consistent is None else r.app_consistent, r.reason])
    return path


# --- Markdown ------------------------------------------------------------------------
def _checkpoint_table(results: list[Result]) -> list[str]:
    lines = ['| ID | Метод | T, °C | Величина | Опорное ± округл. | Расчёт ядра | Отклонение | Допуск | '
             'В пределах округления | Статус |',
             '|---|---|---:|---|---:|---:|---:|---:|:-:|:-:|']
    for r in results:
        c = r.checkpoint
        ref = f'{c.expected:.10g}' + (f' ± {c.reference_rounding_half_unit:g}'
                                      if c.reference_rounding_half_unit is not None else '')
        wr = {True: 'да', False: 'нет', None: '—'}[r.within_rounding]
        lines.append(f'| {c.id} | {c.method} | {c.temperature_c:g} | {QUANTITY_RU.get(c.quantity, c.quantity)}, '
                     f'{UNITS_RU.get(c.unit, c.unit)} | {ref} | {_fmt(r.computed, 7)} | {_fmt_dev(r)} | '
                     f'{c.tolerance():.3g} | {wr} | {STATUS_RU[r.status]} |')
    return lines


def _salinity_table(rows: list[SalinityRow], known_ids: set, printed_t: bool) -> list[str]:
    head = ('| ID | ' + ('T Chen, °C | ' if printed_t else '') +
            'T, °C | S эксп. | S ядра | Δ | Δ отн., % | Предел регрессии | Регрессия | Эксп. конверт | '
            'Эксп. совместимость | Примечание |')
    sep = '|---|' + ('---:|' if printed_t else '') + '---:|---:|---:|---:|---:|---:|:-:|---:|:-:|---|'
    lines = [head, sep]
    for r in rows:
        note = []
        if r.role == 'anchor':
            note.append('граничная опорная точка')
        if printed_t and r.meta['chen_printed_temperature_c'] != r.meta['temperature_c']:
            note.append('T по Darling (Chen печатает +1,34)')
        if r.reason:
            note.append('вне области ядра, без экстраполяции')
        if (r.id, 'regression') in known_ids or (r.id, 'experimental') in known_ids:
            note.append('известное открытое расхождение')
        if printed_t and r.computed is not None and r.temperature_c < -9.5:
            note.append('у перитектики')
        dev = '—' if r.deviation is None else f'{r.deviation:+.4f}'
        rel = '—' if r.rel_pct is None else f'{r.rel_pct:+.2f}'
        lines.append(
            f'| {r.id} | ' + (f'{float(r.meta["chen_printed_temperature_c"]):g} | ' if printed_t else '') +
            f'{r.temperature_c:g} | {r.expected:g} | {_fmt(r.computed, 7)} | {dev} | {rel} | '
            f'{_fmt(r.regression_tol, 4)} | {STATUS_RU[r.regression]} | {_fmt(r.experimental_tol, 4)} | '
            f'{STATUS_RU[r.experimental]} | {"; ".join(note)} |')
    return lines


def _models_section() -> list[str]:
    """Разделы 9–11: эталоны программ авторов, предел чистой воды, этап 1 против строгой модели."""
    from . import models as M
    L = ['', '## 9. Перенос модели H₂O–NaCl против программы авторов (HokieFlincs, прогон в Excel)', '',
         'Эталон — результаты HOKIEFLINCS_H2O-NACL (Steele-MacInnis et al., 2012), полученные пользователем в Excel '
         '(`validation/data/hokieflincs_oracle.csv`). Класс: reference_model_output — проверка ПЕРЕНОСА формул '
         '(те же уравнения, независимая программа), а не независимая проверка модели. Допуск: относительное '
         f'отклонение ≤ {M.TRANSCRIPTION_REL_TOL:g} (только машинное округление).', '',
         '| Случай | Статус | max |отн. отклонение| | Примечание |', '|---|:-:|---:|---|']
    for r in M.evaluate_hokieflincs():
        mx = max((abs(d) for d in r.deviations.values()), default=None)
        L.append(f'| {r.case} | {STATUS_RU.get(r.status, r.status)} | {"—" if mx is None else f"{mx:.1e}"} | '
                 f'{r.reason or ", ".join(r.deviations)} |')
    L += ['', '## 10. Предел чистой воды против IAPWS-95 (независимая характеристика)', '',
          'Корреляции HokieFlincs при солёности 0 сравниваются с IAPWS-95 (CoolProp). Отклонения — свойство '
          'опубликованных корреляций; формулы не изменялись.', '',
          '| Th, °C | Ph Atkinson, бар | P IAPWS-95, бар | ΔP, % | ρ Bodnar (1983) | ρ IAPWS-95 | Δρ, % |',
          '|---:|---:|---:|---:|---:|---:|---:|']
    for r in M.evaluate_pure_water():
        L.append(f'| {r.th_c:g} | {r.p_model:.3f} | {r.p_iapws:.3f} | {r.dp_pct:+.2f} | {r.rho_model:.4f} | '
                 f'{r.rho_iapws:.4f} | {r.drho_pct:+.2f}{" (у Tc)" if r.near_critical else ""} |')
    L += ['', 'Вывод: давление при Th согласуется с IAPWS-95 в пределах 1 %; плотность — в пределах 2 % вдали от '
              'критической точки, но у критической точки воды (360–370 °C) завышена на 6–18 %. Программа '
              'предупреждает, если Th ближе 30 °C к Tc(солёности).']
    rows = M.evaluate_stage1_vs_sm2018()
    st = M.stage1_statistics(rows)
    L += ['', '## 11. Плотность этапа 1 (объёмный баланс) против строгой модели Steele-MacInnis (2018)', '',
          'Эталон — программа H2O-NaCl-CO2 автора, прогон пользователем в Excel (`validation/data/sm2018_oracle.csv`), '
          'режим 1 с долей углекислотной фазы при комнатной температуре (23,5 °C в программе автора). Это '
          'характеристика упрощения, а не валидация: строгая модель учитывает растворённую CO₂ и составы фаз.', '',
          f'Случаев: {st["n"]}. Отклонение упрощённой плотности: от {st["min"]:+.2f} до {st["max"]:+.2f} %, среднее '
          f'{st["mean"]:+.2f} % (всегда ниже строгой модели). Солёность по уравнению Darling отличается от солёности '
          f'модели Steele-MacInnis не более чем на {st["max_abs_dS"]:.3f} мас. %.', '',
          '| Случай | Tm клатрата | Th CO₂ (ветвь) | φ, % | ρ этап 1 | ρ SM2018 | Δ, % |', '|---|---:|---|---:|---:|---:|---:|']
    for r in sorted(rows, key=lambda x: x.dev_pct):
        L.append(f'| {r.case} | {r.tm_clath:g} | {r.th_co2:g} ({r.branch}) | {r.phi_pct:g} | {r.rho_stage1:.4f} | '
                 f'{r.rho_sm2018:.4f} | {r.dev_pct:+.2f} |')
    return L + _co2_section()


def _co2_section() -> list[str]:
    """Раздел 12: чистая CO₂ по Duan et al. (1992a) — этап 2б, часть 1."""
    from . import models as M
    rows = M.evaluate_co2_duan1992()
    st = M.co2_statistics(rows)
    L = ['', '## 12. Чистая CO₂: уравнение Duan et al. (1992a) против Span & Wagner (1996) (этап 2б, часть 1)', '',
         'Модуль `fluid_core/co2_duan1992.py` — составная часть будущей модели H₂O–CO₂–NaCl (Steele-MacInnis, 2018); '
         'в интерфейс программы не подключён. Коэффициенты перенесены из программы автора. Сравнение с эталонным '
         'уравнением Span & Wagner (CoolProp) — НЕЗАВИСИМАЯ характеристика: молярный объём V и коэффициент '
         'фугитивности φ. Отклонения — свойство опубликованного уравнения; коэффициенты не подгонялись. Точки ниже '
         'кривой плавления CO₂ (твёрдая фаза) пропущены.', '',
         f'Точек: {st["n"]}. В области 0–500 °C, до 3 кбар (кроме окрестности критической точки): |ΔV| ≤ '
         f'{st["core_dv"]:.2f} %, |Δφ| ≤ {st["core_dphi"]:.2f} %. Во всей заявленной области 0–1000 °C, до 8 кбар: |ΔV| ≤ '
         f'{st["all_dv"]:.2f} %, |Δφ| ≤ {st["all_dphi"]:.2f} %. Ниже 0 °C (экстраполяция, как в программе автора): |ΔV| ≤ '
         f'{st["cold_dv"]:.2f} %, |Δφ| ≤ {st["cold_dphi"]:.2f} %.', '',
         '| T, °C | Точек | max |ΔV|, % | max |Δφ|, % | Сдвиг φ в схеме автора, % (жидкость) |', '|---:|---:|---:|---:|---:|']
    for t in M.CO2_GRID_T_C:
        g = [r for r in rows if r.t_c == t]
        liq = [abs(r.author_dphi_pct) for r in g if r.phase == 'liquid' and r.author_same_root]
        L.append(f'| {t:g} | {len(g)} | {max(abs(r.dv_pct) for r in g):.2f} | {max(abs(r.dphi_pct) for r in g):.2f} | '
                 f'{f"до {max(liq):.2f}" if liq else "—"} |')
    L += ['', 'Особенности вычислительной схемы программы автора (процедура Volume_CO2), установленные при переносе:', '',
          '1. Слагаемое Z − 1 − ln Z в ln φ вычисляется в точке, смещённой от корня на шаг конечной разности '
          f'(1·10⁻⁴ по приведённому объёму). Для жидкой CO₂ это сдвигает φ до {st["author_liquid_dphi"]:.1f} % '
          'на сетке этого раздела (больше при низких T и P); для газа сдвиг пренебрежим. Функция `state` даёт точное значение уравнения, '
          '`author_volume_and_lnphi` — значение программы автора (нужно для сверки с эталоном).',
          '2. Собственная критическая точка уравнения лежит выше 31,05 °C: примерно при 31–34 °C и 72–80 бар уравнение '
          'имеет несколько корней. Схема автора там может сойтись к метастабильному газовому корню или не сойтись; '
          '`state` выбирает устойчивый корень (наименьшая фугитивность) и выставляет признак `multiple_roots`.',
          '3. При 8 кбар и 580–905 °C схема автора сходится к нефизичному корню (V ≈ 9–12 см³/моль); '
          f'на сетке этого раздела таких точек: {len(st["author_other_root"])}.', '',
          'Линия насыщения: корреляции Span & Wagner (1996, ур. 3.13–3.15) в записи программы автора (округлённые '
          'критические константы) против полного уравнения Span & Wagner; и согласованность с уравнением Duan.', '',
          '| T, °C | P нас., бар | ΔP, % | ΔV жидк., % | ΔV пара, % | P Duan при V жидк. | P Duan при V пара | ln φ (V жидк.) | ln φ (V пара) |',
          '|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in M.evaluate_co2_saturation():
        L.append(f'| {r.t_c:g} | {r.p_eq:.3f} | {100 * (r.p_eq / r.p_sw - 1):+.3f} | {100 * (r.vl_eq / r.vl_sw - 1):+.2f} | '
                 f'{100 * (r.vv_eq / r.vv_sw - 1):+.2f} | {r.p_duan_liquid:.2f} | {r.p_duan_vapor:.2f} | '
                 f'{r.lnphi_liquid:+.4f} | {r.lnphi_vapor:+.4f} |')
    L += ['', 'Вывод: корреляции линии насыщения совпадают с полным уравнением (давление — до 0,02 %, объёмы — до 1,3 % '
              'у критической точки). Уравнение Duan на линии насыщения с ними согласовано не полностью: давление при '
              'объёме насыщенной жидкости отличается от давления насыщения до 13 %, а ln φ, вычисленный по объёму '
              'жидкости и по объёму пара, различается (в равновесии они должны совпадать). Поэтому при сверке с эталоном '
              'существенно, какой из объёмов подставляет программа автора в каждом месте алгоритма.']
    t5 = M.evaluate_duan_table5()
    worst = max(abs(m / x - 1) for _, _, x, m in t5)
    L += ['', 'Сверка с первоисточником. Коэффициенты уравнения совпадают с табл. 3 статьи Duan et al. (1992a) '
              '(проверено по скану). Коэффициенты фугитивности из табл. 5 статьи '
              f'(`validation/data/duan1992_table5.csv`, {len(t5)} значений: 0–1000 °C, 1–8000 бар) воспроизводятся '
              f'с наибольшим относительным отклонением {worst:.1e} — в пределах округления таблицы (4 знака). '
              'Класс: расчёт авторов модели — проверка ПЕРЕНОСА по первоисточнику.']
    return L + _clathrate_section()


def _clathrate_section() -> list[str]:
    """Раздел 13: границы устойчивости клатрата и свойства клатрата — этап 2б, часть 2."""
    from . import models as M
    rows = M.evaluate_clathrate_boundaries()
    st = M.clathrate_boundary_statistics(rows)
    L = ['', '## 13. Границы устойчивости клатрата CO₂: корреляции Steele-MacInnis (2018) против Bakker et al. (1996) '
             '(этап 2б, часть 2)', '',
         'Модуль `fluid_core/clathrate.py` (в интерфейс не подключён): четверные точки Q1 и Q2, поверхности плавления '
         'клатрата «раствор – пар – клатрат» (HLwGc) и «раствор – жидкая CO₂ – клатрат» (HLwLc), состав и объём '
         'клатрата. Сравнение — с табл. 2 и 4 статьи Bakker et al. (1996) (`validation/data/bakker1996_table4.csv`, '
         'выборка; расчёт авторов по их модели). Корреляции Steele-MacInnis подобраны в том числе по этим данным, '
         'поэтому это НЕ независимая проверка, а характеристика качества подбора и проверка переноса.', '',
         f'- Q1: температура — в пределах {st["q1_dt"]:.2f} °C, давление — в пределах {st["q1_dp_pct"]:.1f} %.',
         f'- Q2: температура совпадает с данными Chen (1972b) в пределах {st["q2_dt_chen"]:.2f} °C (то же уравнение '
         f'Darling), от модели Bakker отличается до {st["q2_dt_bakker"]:.2f} °C; давление — в пределах '
         f'{st["q2_dp_pct"]:.1f} %.',
         f'- HLwGc (между Q1 и Q2): давление — в пределах {st["gc_dp_pct"]:.1f} %.',
         f'- HLwLc (выше Q2): изоплеты очень крутые, поэтому сравнивается температура при давлении таблицы. До 1 кбар '
         f'— в пределах {st["lc_dt_to_1kbar"]:.1f} °C; выше 1 кбар — до {st["lc_dt_above_1kbar"]:.1f} °C. Причина: '
         'ур. 23 — прямая с постоянным наклоном, а изоплеты Bakker заметно искривлены (наклон растёт с давлением).', '',
         '| NaCl, мас. % | Элемент | T Bakker, °C | P Bakker, бар | T модели, °C | ΔT, °C | P модели, бар | ΔP, % |',
         '|---:|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        L.append(f'| {r.salinity:g} | {r.element} | {r.t_c:.2f} | {r.p_bar:.2f} | '
                 f'{"—" if r.t_model_c is None else f"{r.t_model_c:.2f}"} | {"—" if r.dt is None else f"{r.dt:+.2f}"} | '
                 f'{r.p_model_bar:.2f} | {r.dp_pct:+.1f} |')
    L += ['', 'Для Q1 и Q2 давление модели дано в точке модели; для HLwGc и HLwLc — при температуре таблицы; '
              'для HLwLc «T модели» — температура, при которой модель даёт давление таблицы. Большие ΔP у HLwLc вблизи '
              'Q2 — следствие сдвига температуры Q2 на доли градуса при наклоне более 100 бар/°C.', '',
          'Состав и плотность клатрата на кривой «раствор – пар – клатрат» без соли (модель van der Waals & '
          'Platteeuw с константами Parrish & Prausnitz в записи программы автора; φ CO₂ — по Duan):', '',
          '| T, °C | P, бар | Гидратное число n | Заполнение малых / больших полостей | V, см³/моль | ρ, г/см³ |',
          '|---:|---:|---:|---:|---:|---:|']
    for t, p, c, v, rho in M.evaluate_clathrate_properties():
        L.append(f'| {t:g} | {p:.2f} | {c.hydration_number:.3f} | {c.occupancy_small:.3f} / {c.occupancy_large:.3f} | '
                 f'{v:.3f} | {rho:.4f} |')
    L += ['', 'Гидратное число 6,1–6,5 (идеальное при полном заполнении — 5,75), плотность клатрата около 1,10 г/см³ — '
              'выше плотности раствора, как и указано в статье. Независимых табличных значений состава клатрата для '
              'сверки нет (у Bakker — только график); константы Ленгмюра взяты из программы автора.']
    return L + _brine_section()


def _brine_section() -> list[str]:
    """Раздел 14: растворимость CO₂, объёмы растворов, вода в углекислотной фазе — этап 2б, часть 3."""
    from . import models as M
    sol = M.evaluate_duan_sun_tables()
    far = [r for r in sol if not r.near_boiling and r.table >= 0.05]
    near = [r for r in sol if r.near_boiling]
    L = ['', '## 14. Растворимость CO₂ и объёмы фаз: Duan & Sun (2003), Duan et al. (2008), Spycher et al. (2003, 2005) '
             '(этап 2б, часть 3)', '',
         'Модуль `fluid_core/co2_brine.py` (в интерфейс не подключён): растворимость CO₂ в растворе NaCl, молярные '
         'объёмы воды, растворённых NaCl и CO₂, доля воды в углекислотной фазе.', '',
         '**Растворимость CO₂ — перенос против таблиц статьи.** Табл. 3 (вода) и 6 (4 моль/кг NaCl) статьи Duan & Sun '
         f'(2003) — расчёт авторов по их модели (`validation/data/duan_sun2003_tables.csv`, {len(sol)} значений: '
         '273–513 K, 1–2000 бар). Коэффициент фугитивности CO₂ — модуль части 1, давление пара воды — ур. B1 статьи. '
         f'Совпадают все {sum(r.ok for r in sol)} из {len(sol)} значений; наибольшее относительное отклонение '
         f'{100 * max(abs(r.dev) for r in far):.2f} % (таблица напечатана с 4 знаками после запятой). '
         f'В {len(near)} точках у кривой кипения воды (P < 2·P пара) допуск расширен до '
         f'{100 * M.DUAN_SUN_NEAR_BOILING_TOL:g} %: там результат чувствителен к принятому давлению пара; наибольшее '
         f'отклонение {100 * max(abs(r.dev) for r in near):.1f} %. Коэффициенты табл. 2 статьи сверены по тексту.', '',
         '**Объём воды (Hu et al., 2007) против IAPWS-95 (CoolProp) — независимая характеристика.** '
         'Наибольшее отклонение по давлениям 1–2000 бар (жидкая вода):', '',
         '| T, °C | ' + ' | '.join(f'{t:g}' for t in M.WATER_VOLUME_T_C) + ' |',
         '|---|' + '---:|' * len(M.WATER_VOLUME_T_C)]
    wv = M.evaluate_water_volume()
    L.append('| max |ΔV|, % | ' + ' | '.join(f'{wv[t]:.3f}' for t in M.WATER_VOLUME_T_C) + ' |')
    L += ['', 'До 200 °C — в пределах 0,03 % (как заявлено в Duan et al., 2008, для 273–473 K); выше 200 °C уравнение '
              'выходит за свою область и быстро теряет точность. В модели Steele-MacInnis (2018) эти объёмы используются '
              'только при низких температурах (плавление клатрата, гомогенизация CO₂, комнатная температура).', '',
          '**Плотность раствора NaCl без CO₂ против Bodnar (1983) из этапа 2а** (на кривой жидкость–пар; две разные '
          'корреляции, сравнение характеризует согласованность моделей, отклонение в %):', '',
          '| NaCl, мас. % | ' + ' | '.join(f'{t:g} °C' for t in M.BRINE_T_C) + ' |', '|---:|' + '---:|' * len(M.BRINE_T_C)]
    bd = M.evaluate_brine_density()
    for sal in M.BRINE_S_WT:
        L.append(f'| {sal:g} | ' + ' | '.join(f'{100 * (a / b - 1):+.2f}' for x, _, a, b in bd if x == sal) + ' |')
    L += ['', 'До 200 °C две модели согласуются в пределах 0,2 %; выше расходятся (до −10 % при 300 °C и 20 мас. %), '
              'что отражает границу применимости регрессий автора для объёма NaCl. Первоисточники (Rogers & Pitzer, '
              '1982; Hu et al., 2007) не получены — коэффициенты взяты из программы автора. Коэффициенты объёма '
              'растворённой CO₂ сверены с табл. 3 статьи Duan et al. (2008); контрольное значение из той же статьи: '
              'кажущийся объём CO₂ при 276,15 K и 34,75 МПа — 31 ± 0,9 см³/моль (Ohsumi et al.), модуль даёт 31,4.', '',
          '**Характерные значения при низких температурах** (φ CO₂ и объём углекислотной фазы — по Duan, часть 1):', '',
          '| T, °C | P, бар | NaCl, мас. % | Фаза CO₂ | CO₂ в растворе, моль/кг | ρ раствора, г/см³ | H₂O в фазе CO₂, мол. % |',
          '|---:|---:|---:|---|---:|---:|---:|']
    for t, p, sal, ph, m, rho, y in M.evaluate_phase_examples():
        L.append(f'| {t:g} | {p:g} | {sal:g} | {PHASE_RU.get(ph, ph)} | {m:.4f} | {rho:.4f} | {100 * y:.3f} |')
    L += ['', 'Доля воды в углекислотной фазе (Spycher et al.) не сверена с первоисточником: статья 2003 г. с константами '
              'не получена, в статье 2005 г. их нет. В программе автора в формулу подставляется молярный объём чистой '
              'CO₂ по Duan, а не объём по уравнению Редлиха–Квонга, как у Spycher; перенесено по программе.']
    rp = M.evaluate_rogers_pitzer()
    L += ['', '**Сверка с первоисточниками (2026-11-10).** Константы Spycher et al. (2003, табл. 1 и 2), уравнение воды '
              'Hu et al. (2007, ур. 2 и табл. 3) и коэффициенты 10–28 обоих наборов Rogers & Pitzer (1982, табл. 2) '
              'совпадают с перенесёнными из программы автора. Параметры B и 2C модуля воспроизводят табл. A-1 '
              f'Rogers & Pitzer при 400 бар (`validation/data/rogers_pitzer1982_a1_400bar.csv`, {len(rp)} строк, '
              f'0–300 °C) с наибольшим отклонением {max(max(abs(r.b_rel_dev), abs(r.c_rel_dev)) for r in rp):.1e} '
              '(округление таблицы).', '',
          'Предельный объём NaCl V° и наклон Дебая–Хюккеля Av программа автора берёт не из статьи, а из собственных '
          'упрощённых регрессий по табл. A-1. Их сравнение с таблицей при 400 бар:', '',
          '| T, °C | Av таблица | Av регрессия | V° таблица, см³/моль | V° регрессия | ΔV°, см³/моль |',
          '|---:|---:|---:|---:|---:|---:|']
    for r in rp:
        L.append(f'| {r.t_c:g} | {r.av_table:.3f} | {r.av_regression:.3f} | {r.v0_table:.2f} | {r.v0_regression:.2f} | '
                 f'{r.v0_regression - r.v0_table:+.2f} |')
    L += ['', 'До 150 °C регрессии близки к таблице (V° — в пределах 0,05 см³/моль; Av при 0 °C занижен на 4,5 %); '
              'при 200 °C и выше непригодны. Это и есть причина расхождения плотности раствора с Bodnar (1983) выше '
              '200 °C. Для модели включений это не существенно: объёмы раствора используются только при низких '
              'температурах.']
    return L + _mode1_section()


def _mode1_section() -> list[str]:
    """Раздел 15: режим 1 модели H₂O–CO₂–NaCl против эталонного прогона программы автора — этап 2б, часть 4."""
    from . import models as M
    rows = M.evaluate_mode1_vs_sm2018()
    keys = ('X_NaCl', 'X_CO2', 'wt_pct_NaCl', 'V', 'rho')
    worst = {k: max(abs(r.deviations[k]) for r in rows) for k in keys}
    exact = {k: max(abs(r.exact_deviations[k]) for r in rows) for k in keys}
    L = ['', '## 15. Режимы 1–3 модели H₂O–CO₂–NaCl против программы автора (Steele-MacInnis, 2018) (этап 2б, часть 4)', '',
         '**Режим 1.** Модуль `fluid_core/h2o_co2_nacl.py`, функция `mode1` (в интерфейс не подключён): Tm клатрата ≤ Th CO₂, задана '
         'объёмная доля углекислотных фаз. Эталон — прогон программы автора пользователем в Excel '
         '(`validation/data/sm2018_oracle.csv`), доля задана при комнатной температуре (23,5 °C). Класс: '
         'reference_model_output — проверка ПЕРЕНОСА всего алгоритма и составных моделей частей 1–3 (те же уравнения, '
         'независимая программа), а не независимая проверка модели. Допуск: относительное отклонение ≤ '
         f'{M.SM2018_SOLVER_REL_TOL:g} — программа автора останавливает итерации при невязках 1·10⁻⁵…1·10⁻⁷, поэтому '
         'совпадение до машинной точности невозможно.', '',
         f'Случаев: {len(rows)}; PASS {sum(r.status == "PASS" for r in rows)}, FAIL '
         f'{sum(r.status == "FAIL" for r in rows)}. Наибольшие относительные отклонения: '
         + '; '.join(f'{NAMES_RU[k]} — {worst[k]:.1e}' for k in keys) + '.', '',
         '| Случай | Tm клатрата | Th CO₂ (ветвь) | φ, % | Статус | Δ X(CO₂) | Δ V | Δ ρ | Δ ρ при точном φ(CO₂) |',
         '|---|---:|---|---:|:-:|---:|---:|---:|---:|']
    for r in rows:
        L.append(f'| {r.case} | {r.tm_clath:g} | {r.th_co2:g} ({r.branch}) | {r.phi_pct:g} | '
                 f'{STATUS_RU.get(r.status, r.status)} | {r.deviations["X_CO2"]:+.1e} | {r.deviations["V"]:+.1e} | '
                 f'{r.deviations["rho"]:+.1e} | {r.exact_deviations["rho"]:+.1e} |')
    L += ['', 'Влияние особенности программы автора (сдвиг ln φ жидкой CO₂, Q22): если вместо её вычислительной схемы '
              'взять точное решение уравнения Duan, результаты меняются не более чем на: '
              + '; '.join(f'{NAMES_RU[k]} — {exact[k]:.1e}' for k in keys)
              + '. Для плотности и солёности это пренебрежимо мало; заметнее всего — в мольной доле CO₂.', '',
          '**Режимы 2 и 3** (функции `mode2`, `mode3`). В этих режимах программа автора выдаёт результат не в точке '
          'сходимости: в режиме 2 — в предпоследней точке метода Ньютона (невязка доли фаз до 0,001), в режиме 3 — '
          'при остановке деления пополам на расхождении объёмов 0,02 см³/моль. Вариант `author` повторяет эти '
          'итерации и сверяется с эталоном; вариант `exact` решает те же уравнения до сходимости.', '',
          '| Случай | Режим | Входные данные | Статус | max |Δ| (author) | Δ солёности (exact) | Δ X(CO₂) (exact) | Δ ρ (exact) |',
          '|---|:-:|---|:-:|---:|---:|---:|---:|']
    rows23 = M.evaluate_modes23_vs_sm2018()
    for r in rows23:
        L.append(f'| {r.case} | {r.mode} | {r.inputs} | {STATUS_RU.get(r.status, r.status)} | '
                 f'{max(abs(d) for d in r.deviations.values()):.1e} | {r.exact_deviations["wt_pct_NaCl"]:+.1e} | '
                 f'{r.exact_deviations["X_CO2"]:+.1e} | {r.exact_deviations["rho"]:+.1e} |')
    L += ['', 'Вывод: перенос режимов 2 и 3 совпадает с программой автора (режим 3 — до машинной точности, так как '
              'деление пополам воспроизводится шаг в шаг). Решение до сходимости отличается от результата программы '
              f'автора: по солёности — до {100 * max(abs(r.exact_deviations["wt_pct_NaCl"]) for r in rows23):.2f} % '
              f'относительных, по плотности — до {100 * max(abs(r.exact_deviations["rho"]) for r in rows23):.3f} %. '
              'Это погрешность критериев остановки программы автора, а не модели; она на порядки меньше погрешности '
              'измерений, но при сравнении с программой автора её нужно иметь в виду (Q29).', '',
          f'Итого сверено с эталоном {len(rows) + len(rows23)} случаев из 41 (все, где задана доля углекислотных фаз). '
          'Не проверено: два случая режима 1 с заданной Th общ. вместо φ (нужна модель Mao et al., 2013 — часть 5), '
          'режим 4 (в эталоне нет), давления на изохоре (часть 5).']
    return L + _convergence_section()


def _convergence_section() -> list[str]:
    """Раздел 16: решение по умолчанию — критерии остановки, невязки, допустимость, устойчивость."""
    from . import models as M
    from fluid_core import h2o_co2_nacl as H
    c = M.evaluate_converged_solution()
    L = ['', '## 16. Решение по умолчанию: сошедшееся; отличие от программы автора (Q22, Q29 — решено 2026-11-10)', '',
         'По решению пользователя функции `mode1`, `mode2`, `mode3` по умолчанию выдают сошедшееся решение '
         "(`numerics='exact'`). Вариант «как у автора» (`numerics='author'`) сохранён только для сравнительных тестов "
         'с эталоном (разд. 15); отдельного переключателя для пользователя нет.', '',
         '**В чём отличие.**', '',
         '| | Программа автора (`author`) | FluidCalc по умолчанию (`exact`) |', '|---|---|---|',
         '| Коэффициент фугитивности CO₂ вне линии насыщения | слагаемое Z − 1 − ln Z берётся в точке, смещённой от '
         'корня на шаг конечной разности (Q22) | точное значение уравнения Duan et al. (1992a) |',
         '| Режим 1, солёность при Th CO₂ | метод Ньютона до |ΔV| ≤ 1·10⁻⁵ см³/моль | метод секущих до относительного '
         'шага 1·10⁻¹³ |',
         '| Режим 2, давление плавления клатрата | метод Ньютона; остановка при невязке доли фаз ≤ 0,001; результат '
         'берётся в последней вычисленной точке, до заключительного уточнения | метод секущих до относительного шага '
         '1·10⁻¹² |',
         '| Режим 3, солёность при Tm клатрата | деление пополам до расхождения объёмов ≤ 0,02 см³/моль | деление '
         'пополам до расхождения объёмов ≤ 1·10⁻¹⁰ см³/моль |',
         '| Доля φ при другой температуре | простая итерация до расхождения 1·10⁻⁷ | метод секущих до относительного '
         'шага 1·10⁻¹² |',
         '| Проверка результата | нет | невязки исходных уравнений и физическая допустимость; при нарушении — ошибка, '
         'результат не выдаётся |', '',
         'Величина отличия на эталонных случаях — в разд. 15: режим 1 — плотность до 0,002 %, мольная доля CO₂ до '
         '0,04 %; режимы 2–3 — солёность до 0,3 % относительных, плотность до 0,012 %.', '',
         '**Проверка невязок.** После решения независимо вычисляются невязки исходных уравнений статьи: равенство '
         'объёмов включения при двух температурах (ур. 5 = ур. 9 или 12), согласие долей фаз по балансам NaCl, H₂O и '
         'объёму (ур. 1, 4, 6), положение солёности на границе устойчивости клатрата (ур. 19–23), заданная доля φ. '
         'Допустимые невязки: ' + '; '.join(f'{RES_RU[k]} — {v:g}' for k, v in H.RESIDUAL_LIMITS.items())
         + '. При превышении возбуждается `ConvergenceError` («сходимость не достигнута»).', '',
         f'На всех {c["n"]} случаях эталона с заданной φ: сошлись все ({"да" if c["all_converged"] else "НЕТ"}); '
         'наибольшие невязки: ' + '; '.join(f'{RES_RU[k]} — {v:.1e}' for k, v in c['residuals'].items())
         + f'. Баланс CO₂ при Tm клатрата в режиме 1 (в алгоритме не используется, контрольная величина) выполняется '
         f'с относительной точностью {c["co2_balance"]:.1e}.', '',
         '**Физическая допустимость.** Проверяются: положительность количеств компонентов и объёма; объёмные доли всех '
         'фаз при каждой температуре фазового перехода в пределах 0…1; в режиме 2 — давление плавления клатрата по '
         'нужную сторону от линии насыщения CO₂ и не ниже давления при Th CO₂; в режиме 3 — давление плавления клатрата '
         'не выше давления насыщения CO₂. При нарушении возбуждается `NonPhysicalSolutionError` с указанием причины '
         '(например, при заданных Th CO₂ в пар и малой φ жидкой CO₂ при Tm клатрата быть не может — это не режим 1). '
         f'На эталонных случаях нарушений: {c["violations"]}; наименьшая объёмная доля фазы — {c["min_fraction"]:.4f}.', '',
         '**Устойчивость к допуску.** Критерии остановки всех решателей ослаблялись в 10², 10⁴ и 10⁶ раз '
         f'({len(M.TOLERANCE_CASES)} случаев, все режимы). Наибольшее относительное изменение плотности, солёности, '
         'мольной доли CO₂ и молярного объёма относительно решения по умолчанию:', '',
         '| Ослабление допуска | ' + ' | '.join(f'×{s:.0e}' for s in M.TOLERANCE_SCALES) + ' |',
         '|---|' + '---:|' * len(M.TOLERANCE_SCALES),
         '| Изменение результата | ' + ' | '.join(f'{c["sensitivity"][s]:.1e}' for s in M.TOLERANCE_SCALES) + ' |', '',
         'Результат меняется пропорционально допуску и при штатном допуске установился с запасом в несколько порядков: '
         'решение устойчиво, дальнейшее ужесточение допуска его не меняет.']
    return L + _isochore_section()


def _isochore_section() -> list[str]:
    """Раздел 17: изохора, линия расслоения и Th общ. — этап 2б, часть 5."""
    from . import models as M
    iso = M.evaluate_isochore_vs_sm2018()
    mao = M.evaluate_mao_tables()
    salty = [abs(g / x - 1) for m, _, _, x, g in mao if m > 0]
    fresh_low = [abs(g / x - 1) for m, tk, _, x, g in mao if m == 0 and tk < 503]
    fresh_high = [abs(g / x - 1) for m, tk, _, x, g in mao if m == 0 and tk > 523]
    tt = M.evaluate_th_total_vs_sm2018()
    L = ['', '## 17. Изохора (Duan et al., 1995), линия расслоения (Mao et al., 2013) и расчёт по Th общ. '
             '(этап 2б, часть 5)', '',
         'Модули `fluid_core/duan1995.py` и `fluid_core/mao2013.py`; расчёт по Th общ. — параметр '
         '`total_homogenization_c` функций `mode1`–`mode3` (в интерфейс не подключено).', '',
         f'**Изохора — перенос против программы автора.** Для состава и молярного объёма каждого из {iso["n"]} случаев '
         'эталона вычислены давления при 350, 400, 450 и 500 °C, наклон и свободный член прямой и давление при Th общ. '
         f'Наибольшее относительное отклонение от эталона — {iso["worst"]:.1e} (допуск {M.ISOCHORE_REL_TOL:g}; '
         'остаток объясняется числом π, записанным в программе автора с 9 знаками). Эта проверка не зависит от '
         'решателей режимов: на вход подаются состав и объём из эталона.', '',
         'Особенности процедуры автора, установленные при переносе: (1) расчёт ведётся при 623, 673, 723 и 773 K, то '
         'есть при 349,85…499,85 °C, а подписаны эти точки и участвуют в регрессии как 350…500 °C — давление занижено '
         f'до {100 * iso["label_shift"]:.2f} %; (2) изохора заменяется прямой по четырём точкам — отклонение прямой от '
         f'самих точек до {100 * iso["curvature"]:.2f} %; (3) давление при Th общ. получается подстановкой Th общ. в эту '
         'прямую, то есть экстраполяцией за пределы 350–500 °C.', '',
         f'**Линия расслоения — перенос против таблиц статьи.** Табл. 7 и 9 Mao et al. (2013) '
         f'(`validation/data/mao2013_tables.csv`, {len(mao)} значений). Раствор 2 моль/кг NaCl (273–723 K, оба набора '
         f'параметров): наибольшее отклонение {100 * max(salty):.1f} % (у кривой кипения раствора — из-за другого '
         'уравнения давления пара: у автора программы Atkinson, 2002). Чистая вода ниже 503 K: '
         f'{100 * max(fresh_low):.2f} %. Чистая вода выше 523 K: до {100 * max(fresh_high):.0f} % — статья для воды без '
         'соли применяет низкотемпературный набор параметров до 647 K (примечание к табл. 4), а программа автора '
         'всегда переключается на высокотемпературный. Проверено: с низкотемпературным набором таблица воспроизводится '
         'до 0,5 %. Перенесено по программе; вопрос Q30.', '',
         '**Расчёт по Th общ. против программы автора.** Доля углекислотной фазы подбирается так, чтобы объём '
         'включения равнялся объёму однородного раствора на линии расслоения при Th общ. (гомогенизация в водную '
         'жидкость — задаётся только явно). Программа автора останавливает подбор при расхождении объёмов '
         '0,05 см³/моль.', '',
         '| Случай | Th общ., °C | max |Δ| (author) | φ автора | φ сошедшаяся | Δ X(CO₂) (exact) | Δ V (exact) | Δ ρ (exact) | '
         'P расслоения, бар | P по прямой изохоры, бар |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in tt:
        L.append(f'| {r.case} | {r.th_total:g} | {r.author_dev:.1e} | {r.phi_author:.4f} | {r.phi_exact:.4f} | '
                 f'{r.exact["X_CO2"]:+.1e} | {r.exact["V"]:+.1e} | {r.exact["rho"]:+.1e} | {r.p_solvus_exact:.0f} | '
                 f'{r.p_line_exact:.0f} |')
    L += ['', 'Вывод: перенос совпадает с программой автора; сошедшееся решение отличается от её результата по мольной '
              f'доле CO₂ до {100 * max(abs(r.exact["X_CO2"]) for r in tt):.1f} %, по плотности до '
              f'{100 * max(abs(r.exact["rho"]) for r in tt):.2f} % (критерий остановки автора).', '',
          'Два замечания к самой модели (не к переносу). Во-первых, давление при Th общ. программа автора выдаёт по '
          'прямой изохоры, и оно почти вдвое выше давления на линии расслоения, из которого найдена доля фаз '
          '(последние два столбца); программа помечает такие случаи «Ph,tot exceeds range of solvus model». Эти два '
          'давления описывают одно и то же состояние и должны совпадать — вопрос Q31. Во-вторых, объём однородного '
          'раствора при Th общ. вычисляется моделью объёмов раствора, которая выше 150–200 °C теряет точность '
          '(разд. 14, Q28), поэтому результаты расчёта по Th общ. выше 200 °C следует считать ориентировочными.', '',
          'Итого с эталоном сверены все 41 случай: состав, объём и плотность (разд. 15 и этот раздел) и давления на '
          'изохоре. Константы CO₂ и параметры смешения уравнения Duan et al. (1995) найдены в тексте статьи; '
          'параметры H₂O и NaCl (Anderko & Pitzer, 1993) по первоисточнику не сверены (Q32).']
    return L


RES_RU = {'volume_cm3_mol': 'объём, см³/моль', 'fraction': 'доля фаз', 'boundary_pressure_bar': 'давление на границе '
          'клатрата, бар'}
NAMES_RU = {'X_NaCl': 'мольная доля NaCl', 'X_CO2': 'мольная доля CO₂', 'wt_pct_NaCl': 'солёность',
            'V': 'молярный объём', 'rho': 'плотность'}


PHASE_RU = {'liquid': 'жидкость', 'vapor': 'пар', 'supercritical': 'сверхкритическая'}


def write_report(results: list[Result], hall: list[SalinityRow], chen: list[SalinityRow], nist: list[NistRow],
                 rec: Reconciliation, path: Path = REPORT_MD) -> Path:
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    indep = [r for r in results if r.checkpoint.independent]
    repro = [r for r in results if not r.checkpoint.independent]
    known_ids = {(k.id, k.criterion) for k in rec.known_reproduced + rec.known_not_reproduced}
    hall_in = [r for r in hall if r.computed is not None]
    hall_exp = [r for r in hall_in if r.role != 'anchor']
    st = chen_statistics(chen)

    def counts(rs):
        return ', '.join(f'{s} {sum(r.status == s for r in rs)}' for s in ('PASS', 'FAIL', 'SKIPPED', 'ERROR'))

    def rc(rows, attr):
        return ', '.join(f'{STATUS_RU[s].strip("*")} {_cnt(rows, attr, s)}'
                         for s in (('PASS', 'FAIL', 'OUTSIDE_DOMAIN') if attr == 'regression'
                                   else ('COMPATIBLE', 'INCOMPATIBLE', 'OUTSIDE_DOMAIN')))

    L = ['# Отчёт о научной валидации расчётного ядра FluidCalc', '',
         f'Сформирован автоматически: {now} (`python -m validation`). Не редактируйте вручную.', '',
         '> **Научный статус.** Проверено воспроизведение экспериментальной **калибровочной базы** солевых '
         'уравнений (Hall et al. 1988 для Bodnar 1993; Chen 1972 для Darling 1991) и численное совпадение расчёта '
         'CO₂ с выгрузкой NIST WebBook. Калибровочные данные независимы от кода FluidCalc, но использовались при '
         'построении уравнений и **не являются** отложенной выборкой для проверки прогностической точности. '
         'Независимость модели NIST WebBook от CoolProp не установлена. Полная независимая валидация моделей '
         f'не завершена — см. `{OPEN_QUESTIONS_DOC}`.', '',
         '## Окружение и входные данные', '']
    L += [f'- {k}: {v}' for k, v in _versions().items()]
    for label, p in (('Калибровочные данные Hall', HALL_CSV), ('Калибровочные данные Chen', CHEN_CSV),
                     ('Выгрузка NIST (без изменений)', NIST_TSV), ('Контрольные точки', CHECKPOINTS_CSV),
                     ('Исходный CSV аудита 2026-11-06', SOURCE_CSV), ('Реестр расхождений', KNOWN_CSV)):
        L.append(f'- {label}: `{p.relative_to(HERE.parent)}`, SHA-256 `{_sha(p)}`')

    L += ['', '## Сводка', '',
          '| Набор | Класс свидетельства / независимость | Записей | Критерий | Результат |',
          '|---|---|---:|---|---|',
          f'| Hall 1988 → Bodnar 1993 | {EVIDENCE_RU["experiment_reproduced_in_compilation"]}; калибровочные данные | '
          f'{len(hall)} (в т.ч. 1 граничная опорная) | регрессия | {rc(hall, "regression")} |',
          f'| | | | эксп. совместимость | {rc(hall, "experimental")} |',
          f'| Chen 1972 → Darling 1991 | {EVIDENCE_RU["experiment"]}; калибровочные данные | {len(chen)} | регрессия | '
          f'{rc(chen, "regression")} |',
          f'| | | | эксп. совместимость | {rc(chen, "experimental")} |',
          f'| NIST WebBook, насыщение CO₂ | {EVIDENCE_RU["reference_table"]}; независимость модели не установлена | '
          f'{len(nist)} | округление выгрузки | PASS {_cnt(nist, "status", "PASS")}, FAIL {_cnt(nist, "status", "FAIL")}, '
          f'SKIPPED {_cnt(nist, "status", "SKIPPED")}, ERROR {_cnt(nist, "status", "ERROR")} |']
    for ev, label in EVIDENCE_TYPES.items():
        rs = [r for r in results if r.checkpoint.evidence_type == ev]
        if rs:
            L.append(f'| Контрольные точки: {label} | `{ev}` | {len(rs)} | допуск точки | {counts(rs)} |')
    L += ['', 'Критерии не сводятся к одному общему PASS. Регрессионный критерий отвечает на вопрос, соответствует '
              'ли расчёт заявленному авторами уравнения качеству аппроксимации; экспериментальный — укладывается ли '
              'отклонение в оценки ошибок, приведённые в источнике. Оценки «±» источников не являются стандартными '
              'неопределённостями: уровень доверия в них не задан. Строки вне области ядра показаны как SKIPPED с '
              'причиной, а не как PASS или численная ошибка.', '']

    L += ['## Реестр расхождений', '',
          'Известные открытые расхождения (`validation/known_discrepancies.csv`) сохраняют статус FAIL / '
          'несовместимо; допуски, формулы и границы применимости ради прохождения не менялись.', '',
          f'- Воспроизведено известных расхождений: {len(rec.known_reproduced)}.',
          '- Известных расхождений, которые больше не воспроизводятся (требуют пересмотра): '
          f'{len(rec.known_not_reproduced)}' +
          (': ' + ', '.join(f'{k.id}/{k.criterion}' for k in rec.known_not_reproduced)
           if rec.known_not_reproduced else '') + '.',
          f'- Новых незарегистрированных расхождений: {len(rec.new_discrepancies)}' +
          (': ' + ', '.join(f'{i}/{c}={s}' for i, c, s in rec.new_discrepancies)
           if rec.new_discrepancies else '') + '.',
          '', '| ID | Критерий | Ожидаемый статус | Вопрос | Пояснение |', '|---|---|---|---|---|']
    for k in rec.known_reproduced + rec.known_not_reproduced:
        L.append(f'| {k.id} | {k.criterion} | {k.expected_status} | {k.open_question} | {k.note} |')

    # 1. Hall
    L += ['', '## 1. Hall, Sterner & Bodnar (1988) → Bodnar (1993)', '',
          'Источник: Hall D.L., Sterner S.M., Bodnar R.J. (1988) Freezing point depression of NaCl–KCl–H₂O '
          'solutions. Econ. Geol. 83, 197–202, DOI 10.2113/gsecongeo.83.1.197. Числа взяты из воспроизведения '
          'первичных измерений: IUPAC Solubility Data Series vol. 47 (1991), карточка J.W. Lorimer, печ. с. 208 / '
          'PDF-с. 237 (https://srdata.nist.gov/solubility/IUPAC/SDS-47/SDS-47.pdf), столбец mass %. '
          'Полный текст оригинальной статьи не сверялся.', '',
          'Оценки ошибки источника: ±0,05 K по температуре, ±0,02 мас. % по составу (уровень доверия не указан).', '',
          '- Предел регрессии: `0,05 + 0,005 + |dS/dT|·0,005` мас. % (остатки регрессии по Bodnar + округление '
          'состава + перенос округления температуры).',
          '- Экспериментальный конверт: `0,02 + 0,005 + |dS/dT|·(0,05 + 0,005)` мас. %.',
          '- |dS/dT| вычисляется численно по функции ядра и служит только для переноса ошибки температуры.', '']
    L += _salinity_table(hall, known_ids, printed_t=False)
    L += ['', f'Итог: в области ядра {len(hall_in)} записей ({len(hall_exp)} экспериментальных и 1 граничная '
              'опорная точка чистой воды, которая не считается дополнительным экспериментом). Регрессия: '
              f'PASS {_cnt(hall_in, "regression", "PASS")}, FAIL {_cnt(hall_in, "regression", "FAIL")}; '
              f'экспериментально совместимы {_cnt(hall_in, "experimental", "COMPATIBLE")} из {len(hall_in)}. '
              f'Максимальное |Δ| = {max(abs(r.deviation) for r in hall_in):.5f} мас. %. '
              'Строка −21,21 °C хранится как SKIPPED (вне области ядра −21,1…0 °C): это ограничение интерфейса '
              'ядра, а не неуспешная аппроксимация; защита не обходится.']

    # 2. Chen
    L += ['', '## 2. Chen (1972) → Darling (1991)', '',
          'Источник: Chen H.-S. (1972b) The properties of carbon dioxide hydrate. OSW R&D Progress Report No. 830, '
          'табл. 5, с. 30 / PDF-с. 44 (https://stacks.cdc.gov/view/cdc/236586/cdc_236586_DS1.pdf); сверка: '
          'Darling R.S. (1991) GCA 55, 3869–3871, табл. 1, с. 3870, DOI 10.1016/0016-7037(91)90079-K. '
          'Расчётная табл. 9 Chen и трёхфазные измерения табл. 4 не использовались. Точка Darling +10 °C / 0 мас. % '
          '(нет в табл. 5 Chen) не добавлялась. Давление опыта (psia) — не давление захвата включения.', '',
          'Darling приводит среднее отклонение 1,33 % и максимальное 5,61 % — это **относительные** проценты '
          'от экспериментального содержания соли, не процентные пункты и не измерительная неопределённость.', '',
          '- Предел регрессии: `0,0561·S_эксп + 0,005 + |dS/dT|·0,005` мас. %.',
          '- Экспериментальный конверт: `0,01·S_эксп + 0,005 + |dS/dT|·(0,025 + 0,005)` мас. % '
          '(по погрешностям в подписи таблицы Darling; уровень доверия не задан).', '']
    L += _salinity_table(chen, known_ids, printed_t=True)
    L += ['', f'Итог: в области ядра {st["n_inside"]} строк, вне области {st["n_outside"]} (−10,08 и −10,40 °C, '
              f'без экстраполяции). Максимальное |Δ| = {st["max_abs"]:.5f} мас. %; максимальное относительное '
              f'{st["max_rel_pct"]:.4f} % при {st["max_rel_at_c"]:+g} °C; среднее абсолютное относительное '
              f'{st["mean_abs_rel_pct"]:.4f} %. Отличие от 1,33 % у Darling не доказывает ошибку: исключены две строки '
              f'вне диапазона и нулевая опорная точка. {st["n_incompatible"]} из {st["n_inside"]} строк не укладываются '
              'в узкий экспериментальный конверт: совпадение с пределом 5,61 % не означает точности расчёта ±1 %.', '',
          'Строка CH72-29: Chen печатает +1,34 °C, Darling в табл. 1 — −1,34 °C; принято значение Darling, исходное '
          'сохранено в `validation/data/chen1972_darling.csv`. У перитектики источники обсуждают −9,6 и −10,0 °C '
          '(24,2 мас. %); предел формулы ядра (−10 °C) не меняется.']

    # 3. NIST
    measured = [r for r in nist if r.deviation is not None]
    worst = max(measured, key=lambda r: abs(r.deviation) / r.rounding_half_unit) if measured else None
    L += ['', '## 3. NIST WebBook: насыщение чистой CO₂ (−50…+30 °C)', '',
          f'Источник: {NIST_SOURCE}; запрос: {NIST_URL}. Выгрузка хранится без изменений: '
          f'`{NIST_TSV.relative_to(HERE.parent)}`. Значения получены от NIST, а не рассчитаны CoolProp.', '',
          'Допуск: половина последнего напечатанного разряда + 1·10⁻⁸·|значение| (численный запас). Это критерий '
          'совпадения с данной выгрузкой, а не физическая неопределённость уравнения состояния.', '',
          f'{INDEPENDENCE_RU["external_implementation_model_not_independently_verified"].capitalize()}: '
          'выгрузка WebBook не маркирует версию EOS, поэтому практически полное совпадение не доказывает '
          'независимость модели. Первичная статья Span & Wagner (1996), табл. 34, — тоже рассчитанные значения, '
          'а не эксперимент.', '',
          '| T, K | T, °C | Величина | NIST (как напечатано) | CoolProp | Δ | ½ разряда | Допуск | '
          '|Δ| / ½ разряда | Статус |',
          '|---:|---:|---|---:|---:|---:|---:|---:|---:|:-:|']
    for r in nist:
        dev = '—' if r.deviation is None else f'{r.deviation:+.2e}'
        ratio = '—' if r.deviation is None else f'{abs(r.deviation) / r.rounding_half_unit:.3f}'
        L.append(f'| {r.temperature_k} | {r.temperature_c:g} | {QUANTITY_RU[r.quantity]}, {UNITS_RU[r.unit]} | '
                 f'{r.expected_text} | {_fmt(r.computed, 10)} | {dev} | {r.rounding_half_unit:g} | '
                 f'{r.tolerance:.3g} | {ratio} | {STATUS_RU[r.status]} |')
    if worst is not None:
        L += ['', f'Наибольшее отношение |Δ| / (½ разряда) = {abs(worst.deviation) / worst.rounding_half_unit:.3f} '
                  f'({worst.id}): совпадение в пределах округления выгрузки, но с малым запасом; при смене версии '
                  'CoolProp этот критерий потребует повторной проверки.']

    # 4–6. контрольные точки
    L += ['', '## 4. Независимые округлённые значения (аудит 2026-11-06)', '',
          '`reference_rounding_half_unit` — половина единицы последнего напечатанного знака опорного значения '
          '(неопределённость округления), а не стандартная неопределённость.', ''] + _checkpoint_table(indep) + ['']
    for r in indep:
        c = r.checkpoint
        L.append(f'- **{c.id}** — {EVIDENCE_TYPES[c.evidence_type]}; независимость: {INDEPENDENCE[c.independence]}. '
                 f'Источник: {c.source}{"; DOI " + c.doi if c.doi else ""}{"; " + c.url if c.url else ""}. '
                 f'Допуск: {c.tolerance_basis}. {c.comment}.' + (f' {r.message}' if r.message else ''))
    n_out = sum(r.within_rounding is False for r in indep)
    if n_out:
        L += ['', f'У {n_out} из {len(indep)} точек отклонение больше интервала округления опорного значения; они '
                  'проходят только грубый допуск. Таблицы ASHRAE отличаются и от NIST WebBook (раздел 3), поэтому '
                  'для точной численной проверки CO₂ используется выгрузка NIST.']
    L += ['', '## 5. Пересчёт по проверяемым уравнениям (НЕ независимая проверка)', '',
          'Совпадение подтверждает только то, что коэффициенты и форма уравнений перенесены в код без искажений.',
          ''] + _checkpoint_table(repro)
    L += ['', '## 6. Контрольные искажения (способность допуска обнаружить ошибку)', '',
          'Обязательные искажения (ошибочная ветвь насыщения, температура в кельвинах) должны обнаруживаться. '
          'Информационные (сдвиг температуры) показывают разрешающую способность допуска.', '',
          '| ID | Искажение | Тип | Отклонение от опорного | Допуск | Обнаружено |', '|---|---|---|---:|---:|:-:|']
    for r in indep:
        for c in r.controls:
            dev = _fmt(c.deviation, 4) if c.deviation is not None else 'ядро отказало (вне области)'
            mark = 'да' if c.detected else ('**НЕТ**' if c.required else 'нет')
            L.append(f'| {r.checkpoint.id} | {c.label} | {"обязательное" if c.required else "информационное"} | '
                     f'{dev} | {r.checkpoint.tolerance():.3g} | {mark} |')
    coarse = [r for r in indep if r.undetected_informative]
    if coarse:
        L += ['', 'Ограничение разрешающей способности: допуск не обнаруживает информационное искажение для '
                  + ', '.join(f'{r.checkpoint.id} ({", ".join(r.undetected_informative)})' for r in coarse) + '.']

    # 7. приложение
    cons = [r.app_consistent for r in results] + [r.app_consistent for r in hall + chen + nist]
    checked = [c for c in cons if c is not None]
    L += ['', '## 7. Согласованность приложения с ядром', '',
          'Те же входные данные пропущены через `fluid_app.calc` (путь расчёта графического интерфейса).', '',
          f'Проверено значений: {len(checked)}; расхождений: {sum(not c for c in checked)}.']

    L += ['', '## 8. Замечания о моделях', '',
          '- **Bodnar (1993).** На калибровочных данных Hall et al. (1988) одно открытое расхождение с пределом '
          'регрессии (HSB88-02, −1,72 °C); все точки в области ядра совместимы с экспериментальными оценками ошибки. '
          'До сверки оригинала статьи ошибку формулы не объявлять, температуру не исправлять, допуск не расширять. '
          'Нижняя граница −21,1 °C не менялась.',
          '- **Darling (1991).** На калибровочных данных Chen (1972) все строки в области ядра — в пределах '
          f'опубликованного максимума отклонения 5,61 % (относительные проценты); {st["n_incompatible"]} строк вне '
          'узкого экспериментального конверта. Результат относится к водно-солевой части и применим только при '
          'сосуществовании водного раствора, жидкой и газовой CO₂ в момент плавления клатрата.',
          '- **Span & Wagner (1996) / CoolProp.** Совпадение с NIST WebBook до последнего напечатанного разряда '
          'при −50…+30 °C (обе ветви). Это подтверждает реализацию и выбор ветвей, но не независимую точность EOS. '
          'Таблицы ASHRAE отличаются и от CoolProp, и от NIST (до ≈0,9 %).',
          ] + _models_section() + [
          '', '## Открытые вопросы', '',
          f'Вынесены в отдельный документ `{OPEN_QUESTIONS_DOC}` (идентификаторы Q… используются в реестре '
          'расхождений).',
          '', '## Источники', '',
          '- Bodnar R.J. (1993) GCA 57, 683–684. DOI 10.1016/0016-7037(93)90378-A',
          '- Hall D.L., Sterner S.M., Bodnar R.J. (1988) Econ. Geol. 83, 197–202. DOI 10.2113/gsecongeo.83.1.197; '
          'IUPAC Solubility Data Series vol. 47 (1991): https://srdata.nist.gov/solubility/IUPAC/SDS-47/SDS-47.pdf',
          '- Darling R.S. (1991) GCA 55, 3869–3871. DOI 10.1016/0016-7037(91)90079-K',
          '- Chen H.-S. (1972b) OSW R&D Progress Report No. 830: '
          'https://stacks.cdc.gov/view/cdc/236586/cdc_236586_DS1.pdf',
          '- Span R., Wagner W. (1996) J. Phys. Chem. Ref. Data 25, 1509–1596. DOI 10.1063/1.555991 '
          '(реализация: CoolProp, Bell et al. 2014, DOI 10.1021/ie4033999)',
          '- NIST Chemistry WebBook, SRD 69: https://webbook.nist.gov/chemistry/fluid/',
          '- Université de Lille, Fluid inclusions: '
          'https://fluid-inclusions.univ-lille.fr/co/004_ice_melting_H2O-NaCl_inclusion.html',
          '- ASHRAE Handbook — Refrigeration, Ch. 3: '
          'https://handbook.ashrae.org/Handbooks/R26/SI/r26_ch03/r26_ch03_si.aspx',
          '- Аудиты и выгрузки: `validation/sources/` (см. `validation/sources/PROVENANCE.md`)', '']
    path.write_text('\n'.join(L), encoding='utf-8')
    return path
