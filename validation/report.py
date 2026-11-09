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
