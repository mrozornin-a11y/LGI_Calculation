"""Сверка лабораторной сводной таблицы (формат «Таблица 1/2/3») с расчётом FluidCalc.

Запуск:
    ~/miniforge3/envs/fluidcalc/bin/python tools/compare_lab_table.py ТАБЛИЦА.xlsx СВЕРКА.xlsx
Исходный файл только читается.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fluid_app.lab_compare import compare, salinity_verdict, write_comparison_xlsx  # noqa: E402
from fluid_app.lab_table import read_lab_table  # noqa: E402


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    table = read_lab_table(argv[1])
    for w in table.warnings:
        print('Предупреждение:', w)
    checks, incons = compare(table)
    write_comparison_xlsx(table, argv[2])
    from collections import Counter
    print(f'Включений: {len(table.rows)}')
    print('Солёность:', dict(Counter(salinity_verdict(c) for c in checks)))
    bad = [c for c in checks if c.density_status.startswith(('физически', 'невозможно', 'нечисл'))]
    print(f'Плотность: невозможных/нечисловых значений {bad and len(bad) or 0} из '
          f'{sum(bool(c.density_status) for c in checks)}')
    for c in checks:
        if salinity_verdict(c) == 'существенное расхождение':
            print(f'  {c.row.sample} {c.row.inclusion}: {c.method} T={c.input_t:g} → расчёт {c.calc_salinity:.2f}, '
                  f'в таблице {c.lab_salinity:g}')
    for x in incons:
        print('  Несогласованность:', x)
    print('Сверка сохранена:', argv[2])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
