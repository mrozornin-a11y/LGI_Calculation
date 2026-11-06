"""Запуск: python -m validation [--strict] [--no-write]

Проверяет контрольные точки validation/checkpoints.csv, пишет validation/VALIDATION_REPORT.md
и validation/validation_results.csv. Код возврата 1 при FAIL/ERROR (и при SKIPPED с --strict).
"""
from __future__ import annotations

import argparse
import sys

from .checkpoints import evaluate_all
from .report import REPORT_MD, RESULTS_CSV, write_report, write_results_csv


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='validation', description='Научная валидация ядра FluidCalc')
    ap.add_argument('--strict', action='store_true', help='SKIPPED считается неуспехом')
    ap.add_argument('--no-write', action='store_true', help='не перезаписывать отчёт и CSV')
    args = ap.parse_args(argv)
    results = evaluate_all()
    for r in results:
        c = r.checkpoint
        kind = 'независимая' if c.independent else 'пересчёт уравнения'
        dev = '' if r.deviation is None else f'отклонение {r.deviation:+.3g}, допуск {c.tolerance():.3g}'
        ctrl = ''
        if r.controls:
            ctrl = '; грубые ошибки обнаруживаются' if r.required_controls_detected else '; ГРУБАЯ ОШИБКА НЕ ОБНАРУЖЕНА'
            if r.undetected_informative:
                ctrl += f' (не разрешает: {", ".join(r.undetected_informative)})'
        print(f'{r.status:7s} {c.id:13s} [{kind}] {dev}{ctrl} {r.message}')
    if not args.no_write:
        write_report(results)
        write_results_csv(results)
        print(f'Отчёт: {REPORT_MD}\nТаблица: {RESULTS_CSV}')
    bad = [r for r in results if r.status in ('FAIL', 'ERROR')]
    skipped = [r for r in results if r.status == 'SKIPPED']
    undetected = [r for r in results if not r.required_controls_detected]
    coarse = [r for r in results if r.undetected_informative]
    print(f'Итого: {len(results)} точек; FAIL/ERROR {len(bad)}; SKIPPED {len(skipped)}; '
          f'не обнаружено грубых искажений {len(undetected)}; '
          f'допусков, не разрешающих информационные искажения, {len(coarse)}')
    print('Напоминание: пересчёт того же уравнения не является независимой экспериментальной проверкой.')
    return 1 if bad or undetected or (args.strict and skipped) else 0


if __name__ == '__main__':
    sys.exit(main())
