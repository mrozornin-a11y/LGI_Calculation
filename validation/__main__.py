"""Запуск: python -m validation [--strict] [--no-write]

Проверяет:
  * контрольные точки validation/checkpoints.csv (аудит 2026-11-06);
  * калибровочные экспериментальные данные Hall (1988) и Chen (1972) — два раздельных критерия;
  * выгрузку NIST WebBook для насыщения CO₂.
Пишет validation/VALIDATION_REPORT.md и validation/results/*.csv.

Код возврата 1, если: есть FAIL/ERROR в контрольных точках или NIST; не обнаружено обязательное
контрольное искажение; появилось незарегистрированное расхождение; известное расхождение из
validation/known_discrepancies.csv больше не воспроизводится (требует пересмотра); SKIPPED при --strict.
Зарегистрированные открытые расхождения (FAIL/несовместимо) показываются, но код возврата не меняют.
"""
from __future__ import annotations

import argparse
import sys

from . import datasets as D
from .checkpoints import evaluate_all
from .report import (REPORT_MD, RESULTS_DIR, write_nist_csv, write_report, write_results_csv,
                     write_salinity_csv)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='validation', description='Научная валидация ядра FluidCalc')
    ap.add_argument('--strict', action='store_true', help='SKIPPED считается неуспехом')
    ap.add_argument('--no-write', action='store_true', help='не перезаписывать отчёт и CSV')
    args = ap.parse_args(argv)

    results = evaluate_all()
    hall, chen, nist = D.evaluate_hall(), D.evaluate_chen(), D.evaluate_nist()
    rec = D.reconcile(hall + chen, nist)

    print('— Контрольные точки (аудит 2026-11-06)')
    for r in results:
        c = r.checkpoint
        kind = 'независимая' if c.independent else 'пересчёт уравнения'
        dev = '' if r.deviation is None else f'отклонение {r.deviation:+.3g}, допуск {c.tolerance():.3g}'
        ctrl = ''
        if r.controls:
            ctrl = '; грубые ошибки обнаруживаются' if r.required_controls_detected else '; ГРУБАЯ ОШИБКА НЕ ОБНАРУЖЕНА'
            if r.undetected_informative:
                ctrl += f' (не разрешает: {", ".join(r.undetected_informative)})'
        print(f'  {r.status:7s} {c.id:13s} [{kind}] {dev}{ctrl} {r.message}')

    known = {(k.id, k.criterion) for k in rec.known_reproduced}
    for name, rows in (('Hall 1988 → Bodnar 1993 (калибровочные данные)', hall),
                       ('Chen 1972 → Darling 1991 (калибровочные данные)', chen)):
        print(f'— {name}')
        for crit, attr in (('регрессия', 'regression'), ('эксп. совместимость', 'experimental')):
            counts = {}
            for r in rows:
                counts[getattr(r, attr)] = counts.get(getattr(r, attr), 0) + 1
            print(f'  {crit}: ' + ', '.join(f'{k} {v}' for k, v in sorted(counts.items())))
        for r in rows:
            flags = [f'{c}={getattr(r, a)}' for c, a in (('regression', 'regression'), ('experimental', 'experimental'))
                     if getattr(r, a) in ('FAIL', 'INCOMPATIBLE')]
            if flags:
                tag = 'известное открытое' if all((r.id, f.split('=')[0]) in known for f in flags) else 'НОВОЕ'
                print(f'  {r.id:9s} T={r.temperature_c:+g} Δ={r.deviation:+.4f}: {", ".join(flags)} [{tag}]')
            if r.regression == 'OUTSIDE_DOMAIN':
                print(f'  {r.id:9s} T={r.temperature_c:+g}: SKIPPED — вне области ядра, без экстраполяции')
    st = D.chen_statistics(chen)
    print(f'  Chen: max |Δ| {st["max_abs"]:.5f}; max отн. {st["max_rel_pct"]:.4f} % при {st["max_rel_at_c"]:+g} °C; '
          f'среднее отн. {st["mean_abs_rel_pct"]:.4f} %')

    print('— NIST WebBook, насыщение CO₂')
    nc = {}
    for r in nist:
        nc[r.status] = nc.get(r.status, 0) + 1
        if r.status != 'PASS':
            print(f'  {r.status} {r.id} {r.reason}')
    print('  ' + ', '.join(f'{k} {v}' for k, v in sorted(nc.items())))

    from . import models as Mo
    hokie = Mo.evaluate_hokieflincs()
    print('— Перенос H₂O–NaCl против HokieFlincs: ' + ', '.join(
        f'{k} {sum(r.status == k for r in hokie)}' for k in ('PASS', 'FAIL', 'SKIPPED')))
    st = Mo.stage1_statistics(Mo.evaluate_stage1_vs_sm2018())
    print(f'— Этап 1 против Steele-MacInnis (2018): n={st["n"]}, отклонение {st["min"]:+.2f}…{st["max"]:+.2f} %, '
          f'среднее {st["mean"]:+.2f} %')
    bad_models = [r for r in hokie if r.status == 'FAIL']

    if not args.no_write:
        write_report(results, hall, chen, nist, rec)
        write_results_csv(results)
        write_salinity_csv(hall, RESULTS_DIR / 'hall1988_bodnar.csv')
        write_salinity_csv(chen, RESULTS_DIR / 'chen1972_darling.csv')
        write_nist_csv(nist, RESULTS_DIR / 'nist_co2.csv')
        print(f'Отчёт: {REPORT_MD}\nТаблицы: {RESULTS_DIR}')

    bad = [r for r in results if r.status in ('FAIL', 'ERROR')] + [r for r in nist if r.status in ('FAIL', 'ERROR')]
    skipped = [r for r in results if r.status == 'SKIPPED'] + [r for r in nist if r.status == 'SKIPPED']
    undetected = [r for r in results if not r.required_controls_detected]
    print(f'Итого: известных открытых расхождений {len(rec.known_reproduced)}; '
          f'новых {len(rec.new_discrepancies)}; не воспроизведённых известных {len(rec.known_not_reproduced)}; '
          f'FAIL/ERROR вне реестра {len(bad)}; SKIPPED {len(skipped)}; '
          f'не обнаружено обязательных искажений {len(undetected)}')
    print('Напоминание: калибровочные данные и пересчёт тех же уравнений не являются независимой '
          'валидацией прогностической точности моделей.')
    return 1 if bad or bad_models or undetected or not rec.ok or (args.strict and skipped) else 0


if __name__ == '__main__':
    sys.exit(main())
