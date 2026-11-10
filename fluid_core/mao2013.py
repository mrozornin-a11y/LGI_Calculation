"""Растворимость CO₂ в растворе NaCl до 450 °C — линия расслоения (сольвус) системы H₂O–CO₂–NaCl (этап 2б, часть 5).

Модель Mao, Zhang, Li & Liu (2013), Chem. Geol. 347, 43–58 (273–723 K, 1–1500 бар, 0–4,5 моль/кг NaCl),
перенесённая из процедуры CO2_Solvus программы H2O-NaCl-CO2 (Steele-MacInnis, 2018, Chem. Geol. 498, 31–44):

    ln m(CO₂) = ln[y·φ·P] − A(T, P, m),   A = μ/RT + 2λ·m(NaCl) + ξ·m(NaCl)²,

с двумя наборами параметров (до 503 K и от 523 K) и линейной интерполяцией A между 503 и 523 K. Как в программе
автора: коэффициент фугитивности CO₂ — по Duan et al. (1992a), давление пара раствора — по Atkinson (2002)
(функция этапа 2а), доля CO₂ в углекислотной фазе y = (P − P пара)/P.

Оговорка для чистой воды (решение пользователя от 2026-11-10, вопрос Q30). В примечании к табл. 4 статьи (с. 46)
сказано: при m(NaCl) = 0 низкотемпературный набор параметров можно применять до 647 K. В программе автора (VBA)
этого исключения нет: выше 523 K она всегда берёт высокотемпературный набор. По умолчанию ('exact') здесь
применяется оговорка статьи — только при строго нулевой солёности и T ≤ 647 K; на слабосолёные растворы она не
распространяется, сглаживание не вводится. Поэтому между нулевой и малой ненулевой солёностью при 523–647 K
возможен скачок растворимости CO₂ (при 573 K и 500 бар — около 30 %); это свойство опубликованной модели.
Схема программы автора ('author') сохранена только для сравнительных тестов.

Используется для определения давления на линии расслоения при полной гомогенизации включения (Th общ.).
"""
from __future__ import annotations

from math import exp, isfinite

from . import co2_duan1992 as D
from .co2_brine import MOL_H2O_PER_KG, nacl_molality
from .h2o_nacl import homogenization_pressure_bar

MODEL_REFERENCE = ('Mao S., Zhang D., Li Y., Liu N. (2013) Chem. Geol. 347, 43–58, DOI 10.1016/j.chemgeo.2013.03.010; '
                   'в записи программы H2O-NaCl-CO2: Steele-MacInnis M. (2018) Chem. Geol. 498, 31–44')

T_MAX_C = 450.0                 # 723,15 K
P_MAX_BAR = 1500.0              # заявленная область модели; выше — экстраполяция
M_NACL_MAX = 4.5
PURE_WATER_LOW_SET_MAX_K = 647.0   # примечание к табл. 4: низкотемпературный набор при m(NaCl) = 0


def _a_low(tk, p, m):
    mu = (23.018254 - 0.036540569 * tk - 1836.6895 / tk + 2.0330876E-05 * tk ** 2 - 390723.84 / tk ** 2
          - 0.058269326 * p + 0.00015061716 * p * tk + 7.8086969 * p / tk - 1.3013307E-07 * p * tk ** 2
          + 1.1145375E-09 * p ** 2 * tk - 1.3073985E-10 * p ** 3)
    lam = (-0.31312239 + 0.0005532647 * tk + 75.844401 / tk - 0.00018950519 * p + 7.1628762E-07 * p * tk
           - 1.458572E-10 * p ** 2 * tk)
    xi = 0.0034096802 - 2.7671084E-05 * tk - 8.3847525E-08 * p * tk + 3.4225403E-11 * p ** 2 * tk
    return mu + 2 * lam * m + xi * m * m


def _a_high(tk, p, m):
    mu = (1162.5439 - 1.3350381 * tk - 445228.15 / tk + 0.0005732654 * tk ** 2 + 64139318.0 / tk ** 2
          - 0.12735549 * p + 0.00021720184 * p * tk + 25.529557 * p / tk - 1.2542533E-07 * p * tk ** 2)
    lam = 0.38934171 - 0.00018177725 * tk - 65.214916 / tk - 0.00031200574 * p + 6.0052047E-07 * p * tk
    return mu + 2 * lam * m - 0.020867161 * m * m


def co2_solubility(t_c: float, p_bar: float, salinity_wt_pct: float, *, numerics: str = 'exact') -> tuple[float, float]:
    """(моляльность CO₂, мольная доля CO₂) в растворе, насыщенном CO₂, при T, P и солёности (Mao et al., 2013).

    numerics: 'exact' — коэффициент фугитивности CO₂ точно по уравнению Duan, для строго нулевой солёности
    до 647 K — низкотемпературный набор параметров (оговорка статьи); 'author' — вычислительная схема и выбор
    набора параметров программы автора (только для сравнительных тестов).
    """
    for val, name in ((t_c, 'Температура'), (p_bar, 'Давление'), (salinity_wt_pct, 'Солёность')):
        if isinstance(val, bool):
            raise TypeError(f'{name}: требуется число')
        if not isfinite(float(val)):
            raise ValueError(f'{name}: требуется конечное число')
    t, p = float(t_c), float(p_bar)
    if not 0.0 <= t <= T_MAX_C:
        raise ValueError(f'Модель растворимости Mao et al. (2013): 0 … {T_MAX_C:g} °C')
    if p <= 0:
        raise ValueError('Давление должно быть положительным')
    if numerics not in ('author', 'exact'):
        raise ValueError("numerics: 'author' или 'exact'")
    m = nacl_molality(salinity_wt_pct)
    tk = t + 273.15
    p_h2o = homogenization_pressure_bar(t, float(salinity_wt_pct))
    if p <= p_h2o:
        raise ValueError('Давление не выше давления пара раствора: расслоения на раствор и углекислотную фазу нет')
    lnphi = D.author_volume_and_lnphi(t, p)[1] if numerics == 'author' else D.state(t, p).ln_fugacity_coefficient
    if numerics == 'exact' and m == 0 and tk <= PURE_WATER_LOW_SET_MAX_K:
        a = _a_low(tk, p, 0.0)
    elif tk < 503:
        a = _a_low(tk, p, m)
    elif tk > 523:
        a = _a_high(tk, p, m)
    else:
        lo = _a_low(503.0, p, m)
        a = lo + (_a_high(523.0, p, m) - lo) * (tk - 503) / 20
    m_co2 = (p - p_h2o) / exp(a - lnphi)
    return m_co2, m_co2 / (m + m_co2 + MOL_H2O_PER_KG)
