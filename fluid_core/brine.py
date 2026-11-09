"""Плотность водного раствора NaCl при 20 °C и атмосферном давлении (справочные значения).

Источник: CRC Handbook of Chemistry and Physics, «Concentrative properties of aqueous solutions» (NaCl, 20 °C).
Те же значения приведены в табл. 9.9 лабораторной методики (совпадение проверено). Для чистой воды —
0,99821 г/см³ (IAPWS-95 при 20 °C, 0,101325 МПа) вместо округлённого 1,0 в табл. 9.9.
Между узлами — линейная интерполяция (погрешность интерполяции < 1·10⁻⁴ г/см³).

Применимость: раствор NaCl (для природных растворов — NaCl-эквивалент, т. е. приближение), 0–26 мас. %.
"""
from math import isfinite

REFERENCE = ('CRC Handbook of Chemistry and Physics, Concentrative properties of aqueous solutions: '
             'sodium chloride, 20 °C; чистая вода — IAPWS-95')
# мас. % NaCl → г/см³ при 20 °C
TABLE_20C = (
    (0.0, 0.99821), (1.0, 1.0053), (2.0, 1.0125), (3.0, 1.0196), (4.0, 1.0268), (5.0, 1.0340),
    (6.0, 1.0413), (7.0, 1.0486), (8.0, 1.0559), (9.0, 1.0633), (10.0, 1.0707), (12.0, 1.0857),
    (14.0, 1.1009), (16.0, 1.1162), (18.0, 1.1319), (20.0, 1.1478), (22.0, 1.1640), (24.0, 1.1804),
    (26.0, 1.1972),
)
MAX_WT_PCT = TABLE_20C[-1][0]


def nacl_solution_density_20c(wt_pct_nacl: float) -> float:
    """Плотность раствора NaCl, г/см³, при 20 °C по солёности, мас. %."""
    if isinstance(wt_pct_nacl, bool):
        raise TypeError('Salinity must be numeric')
    s = float(wt_pct_nacl)
    if not isfinite(s):
        raise ValueError('Salinity must be finite')
    if not 0.0 <= s <= MAX_WT_PCT:
        raise ValueError(f'NaCl solution density table covers 0-{MAX_WT_PCT:g} wt% NaCl')
    for (s0, d0), (s1, d1) in zip(TABLE_20C, TABLE_20C[1:]):
        if s0 <= s <= s1:
            return d0 + (d1 - d0) * (s - s0) / (s1 - s0)
    raise AssertionError('unreachable')
