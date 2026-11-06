"""Формирование отчёта о научной валидации (Markdown) и таблицы результатов (CSV)."""
from __future__ import annotations

import csv
import hashlib
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from .checkpoints import (CHECKPOINTS_CSV, EVIDENCE_TYPES, HERE, INDEPENDENCE, QUANTITY_RU, SOURCE_CSV,
                          UNITS_RU, Result)

REPORT_MD = HERE / 'VALIDATION_REPORT.md'
RESULTS_CSV = HERE / 'validation_results.csv'

STATUS_RU = {'PASS': 'PASS', 'FAIL': '**FAIL**', 'SKIPPED': 'SKIPPED', 'ERROR': '**ERROR**'}

MODEL_NOTES = [
    ('Darling (1991)',
     'По данным аудита (абстракт первоисточника), уравнение воспроизводит экспериментальные точки со средним '
     'отклонением 1,33 % и максимальным 5,61 %. Это характеристика самого эмпирического уравнения относительно '
     'данных, на которых оно построено, а НЕ погрешность отдельного измерения и не доверительный интервал '
     'результата. В расчёт погрешности программы эти числа не подставляются.'),
    ('Darling (1991)',
     'Результат относится к водно-солевой части включения, а не к валовому составу, и применим только при '
     'плавлении клатрата в присутствии жидкой CO₂, газовой CO₂ и солевого раствора.'),
    ('Bodnar (1993)',
     'Нижняя граница ядра −21,1 °C не расширяется до сверки таблицы и фазовой ветви первоисточника '
     '(эвтектика H₂O–NaCl ≈ −21,2 °C).'),
    ('Span & Wagner (1996) / CoolProp',
     'Сравнение с округлёнными таблицами ASHRAE — грубая независимая проверка (ветвь, единицы, шкала '
     'температуры). Она не подтверждает CoolProp на уровне заявленной неопределённости уравнения состояния; '
     'для этого нужна сверка с NIST REFPROP / таблицами Span & Wagner.'),
]

OPEN_QUESTIONS = [
    'Нет ни одной экспериментальной контрольной точки (evidence_type = experiment) ни для Bodnar, ни для Darling: '
    'нужны табличные экспериментальные данные первоисточников (Bodnar 1993 и использованные им данные; '
    'экспериментальные точки, на которых построено уравнение Darling 1991).',
    'Нет точной справочной таблицы для CO₂ (NIST REFPROP или таблицы Span & Wagner 1996) с допусками на '
    'уровне неопределённости EOS; NIST WebBook из среды разработки был недоступен.',
    'Поведение у критической точки CO₂ (сходимость ветвей) не проверено независимыми данными.',
    'Учебный пример Université de Lille, вероятно, рассчитан по тому же уравнению Bodnar — это проверка '
    'реализации, а не физической точности.',
    'Происхождение и версия корреляций в таблицах ASHRAE не установлены; наблюдаемые отклонения CoolProp от '
    'ASHRAE (до ≈0,9 %) превышают интервал округления таблицы — причина (иная корреляция/версия) не выяснена.',
    'Граница −21,1 °C для Bodnar требует сверки с таблицей и фазовой ветвью первоисточника.',
    'Калибровка термостолика Linkam и распространение неопределённости измерений не выполнялись.',
]


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
    if v is None:
        return '—'
    return f'{v:.{digits}g}'


def _fmt_dev(r: Result) -> str:
    if r.deviation is None:
        return '—'
    rel = r.rel_deviation
    return f'{r.deviation:+.3g} ({rel * 100:+.3g} %)' if rel is not None else f'{r.deviation:+.3g}'


def write_results_csv(results: list[Result], path: Path = RESULTS_CSV) -> Path:
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['id', 'method', 'temperature_c', 'quantity', 'unit', 'evidence_type', 'independence',
                    'expected', 'reference_uncertainty', 'computed', 'deviation', 'rel_deviation', 'tolerance',
                    'within_reference_rounding', 'status', 'app_layer_consistent', 'gross_error_controls_detected',
                    'message'])
        for r in results:
            c = r.checkpoint
            w.writerow([c.id, c.method, c.temperature_c, c.quantity, c.unit, c.evidence_type, c.independence,
                        c.expected, c.reference_uncertainty if c.reference_uncertainty is not None else '',
                        '' if r.computed is None else repr(r.computed),
                        '' if r.deviation is None else f'{r.deviation:.6g}',
                        '' if r.rel_deviation is None else f'{r.rel_deviation:.6g}',
                        f'{c.tolerance():.6g}', '' if r.within_rounding is None else r.within_rounding,
                        r.status, '' if r.app_consistent is None else r.app_consistent,
                        '' if not r.controls else r.required_controls_detected, r.message])
    return path


def _table(results: list[Result]) -> list[str]:
    lines = ['| ID | Метод | T, °C | Величина | Опорное ± округл. | Расчёт ядра | Отклонение | Допуск | '
             'В пределах округления | Статус |',
             '|---|---|---:|---|---:|---:|---:|---:|:-:|:-:|']
    for r in results:
        c = r.checkpoint
        ref = f'{c.expected:.10g}' + (f' ± {c.reference_uncertainty:g}' if c.reference_uncertainty is not None else '')
        wr = {True: 'да', False: 'нет', None: '—'}[r.within_rounding]
        lines.append(f'| {c.id} | {c.method} | {c.temperature_c:g} | {QUANTITY_RU.get(c.quantity, c.quantity)}, '
                     f'{UNITS_RU.get(c.unit, c.unit)} | {ref} | {_fmt(r.computed, 7)} | {_fmt_dev(r)} | '
                     f'{c.tolerance():.3g} | {wr} | {STATUS_RU[r.status]} |')
    return lines


def write_report(results: list[Result], path: Path = REPORT_MD) -> Path:
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    indep = [r for r in results if r.checkpoint.independent]
    repro = [r for r in results if not r.checkpoint.independent]

    def counts(rs):
        return ', '.join(f'{s} {sum(r.status == s for r in rs)}' for s in ('PASS', 'FAIL', 'SKIPPED', 'ERROR'))

    L = ['# Отчёт о научной валидации расчётного ядра FluidCalc', '',
         f'Сформирован автоматически: {now} (`python -m validation`). Не редактируйте вручную.', '',
         '> Автоматическая проверка контрольных точек показывает, что код воспроизводит опорные значения в '
         'заданных допусках. Совпадение с пересчётом того же уравнения **не является** независимой '
         'экспериментальной проверкой. Экспериментальных контрольных точек в наборе пока нет.', '',
         '## Окружение', '']
    for k, v in _versions().items():
        L.append(f'- {k}: {v}')
    L += [f'- Контрольные точки: `validation/checkpoints.csv`, SHA-256 `{_sha(CHECKPOINTS_CSV)}`',
          f'- Исходные данные аудита: `validation/sources/`, SHA-256 CSV `{_sha(SOURCE_CSV)}`', '',
          '## Сводка', '',
          '| Класс свидетельства | Точек | Результат |', '|---|---:|---|']
    for ev, label in EVIDENCE_TYPES.items():
        rs = [r for r in results if r.checkpoint.evidence_type == ev]
        L.append(f'| {label} (`{ev}`) | {len(rs)} | {counts(rs) if rs else "нет данных"} |')
    L += ['', f'Итого независимых (внешних) точек: {len(indep)} — {counts(indep)}.  ',
          f'Итого точек пересчёта уравнения: {len(repro)} — {counts(repro)}.', '']

    L += ['## A. Независимые справочные значения', '',
          'Опорные значения получены из источников, не связанных с кодом FluidCalc. Уровень независимости указан '
          'для каждой точки.', ''] + _table(indep) + ['']
    for r in indep:
        c = r.checkpoint
        L.append(f'- **{c.id}** — {EVIDENCE_TYPES[c.evidence_type]}; независимость: {INDEPENDENCE[c.independence]}. '
                 f'Источник: {c.source}{"; DOI " + c.doi if c.doi else ""}{"; " + c.url if c.url else ""}. '
                 f'Допуск: {c.tolerance_basis}. {c.comment}.' + (f' {r.message}' if r.message else ''))
    n_out = sum(r.within_rounding is False for r in indep)
    if n_out:
        L += ['', f'Замечание: у {n_out} из {len(indep)} независимых точек отклонение больше интервала '
                  'округления опорного значения. Они проходят только грубый допуск; совпадение на уровне '
                  'неопределённости модели этими данными не подтверждено.']

    L += ['', '## B. Пересчёт по проверяемым уравнениям (НЕ независимая проверка)', '',
          'Опорные значения получены подстановкой в опубликованные уравнения Bodnar (1993) и Darling (1991). '
          'Совпадение подтверждает только то, что коэффициенты и форма уравнений перенесены в код без искажений.',
          ''] + _table(repro) + ['']

    L += ['## C. Контрольные искажения (способность допуска обнаружить ошибку)', '',
          'Для каждой независимой точки ядро вызывается с намеренно искажёнными входами. Обязательные искажения '
          '(грубые ошибки: ошибочная ветвь насыщения, температура в кельвинах) должны обнаруживаться — иначе '
          'проверка считается неуспешной. Информационные (сдвиг температуры) показывают разрешающую способность '
          'допуска и критерием PASS не являются.', '',
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
                  + ', '.join(f'{r.checkpoint.id} ({", ".join(r.undetected_informative)})' for r in coarse)
                  + '. Значит, эти точки подтверждают отсутствие грубых ошибок (ветвь, шкала температуры, единицы), '
                    'но не исключают систематической ошибки такого масштаба.']

    L += ['', '## D. Согласованность приложения с ядром', '',
          'Те же входные данные пропущены через `fluid_app.calc` (путь, которым считает графический интерфейс).', '']
    cons = [r for r in results if r.app_consistent is not None]
    bad = [r.checkpoint.id for r in cons if not r.app_consistent]
    L.append(f'Проверено точек: {len(cons)}; расхождений: {len(bad)}' + (f' ({", ".join(bad)})' if bad else '') + '.')

    L += ['', '## E. Замечания о моделях', '']
    L += [f'- **{m}.** {t}' for m, t in MODEL_NOTES]
    L += ['', '## F. Открытые вопросы научной валидации', '']
    L += [f'{i}. {q}' for i, q in enumerate(OPEN_QUESTIONS, 1)]
    L += ['', '## Источники', '',
          '- Bodnar R.J. (1993) Revised equation and table for determining the freezing point depression of '
          'H₂O–NaCl solutions. GCA 57, 683–684. DOI 10.1016/0016-7037(93)90378-A',
          '- Darling R.S. (1991) An extended equation to calculate NaCl contents from final clathrate melting '
          'temperatures in H₂O–CO₂–NaCl fluid inclusions. GCA 55, 3869–3871. DOI 10.1016/0016-7037(91)90079-K',
          '- Span R., Wagner W. (1996) J. Phys. Chem. Ref. Data 25, 1509–1596. DOI 10.1063/1.555991 '
          '(реализация: CoolProp, Bell et al. 2014, DOI 10.1021/ie4033999)',
          '- Université de Lille, Fluid inclusions teaching resource: '
          'https://fluid-inclusions.univ-lille.fr/co/004_ice_melting_H2O-NaCl_inclusion.html',
          '- ASHRAE Handbook — Refrigeration, Ch. 3 Carbon Dioxide Refrigeration Systems: '
          'https://handbook.ashrae.org/Handbooks/R26/SI/r26_ch03/r26_ch03_si.aspx',
          '- Научный аудит 2026-11-06: `validation/sources/FluidCalc_scientific_audit_2026-11-06.md`', '']
    path.write_text('\n'.join(L), encoding='utf-8')
    return path
