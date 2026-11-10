"""Границы устойчивости клатрата CO₂ в системе H₂O–CO₂–NaCl и свойства клатрата (этап 2б, часть 2).

Корреляции статьи Steele-MacInnis (2018), Chem. Geol. 498, 31–44, разд. 4.2–4.4 и 4.7, перенесённые из программы
автора (функции Q1X, Q1P, Q2X, Q1Q2P, Q2plusP, ClathrateComp, ClathrateVol):

* четверная точка Q1 (лёд + клатрат + водный раствор + пар): солёность раствора и давление — ур. 16, 17;
* четверная точка Q2 (клатрат + водный раствор + жидкая CO₂ + пар): солёность — ур. 18 (Chen, 1972; Darling, 1991),
  давление — давление насыщения CO₂ (ур. 13);
* трёхфазная поверхность «раствор – пар – клатрат» между Q1 и Q2 — ур. 19–21;
* трёхфазная поверхность «раствор – жидкая CO₂ – клатрат» выше Q2 — ур. 22–23;
* состав клатрата — модель van der Waals & Platteeuw (1959) с константами Ленгмюра Parrish & Prausnitz (1972);
* молярный объём клатрата — ур. 24 (тепловое расширение по Tse, 1987; сжимаемость 1·10⁻⁵ бар⁻¹ по Bakker et al.,
  1996).

Корреляции 16–17 и 19–23 автор подобрал по данным Larson (1955), Chen (1972) и расчётам Bakker et al. (1996).
Обозначения фаз в функциях: Laq — водный раствор, Lcarb — жидкая CO₂, V — пар, C — клатрат.

Солёность везде — мас. % NaCl в водном растворе (без учёта растворённой CO₂), температура — °C, давление — бар.
Модуль в интерфейс программы не подключён (до сверки всей модели 2б с эталоном); `fluid_core/salinity.py` он не
заменяет и не изменяет.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite

from .co2_duan1992 import saturation_pressure_bar

MODEL_REFERENCE = ('Steele-MacInnis M. (2018) Chem. Geol. 498, 31–44, ур. 16–24; Darling R.S. (1991) GCA 55, 3869–3871; '
                   'Bakker R.J., Dubessy J., Cathelineau M. (1996) GCA 60, 1657–1681; van der Waals J.H., '
                   'Platteeuw J.C. (1959) Adv. Chem. Phys. 2, 1–57; Parrish W.R., Prausnitz J.M. (1972) Ind. Eng. '
                   'Chem. Process Des. Dev. 11, 26–35; Tse J.S. (1987) J. Phys. Colloques 48, C1-543')

Q1_T0_C = -1.48                 # Q1 при нулевой солёности (Larson, 1955)
Q1_P0_BAR = 10.34
Q2_T0_C = 10.0                  # Q2 при нулевой солёности
S_MAX_WT_PCT = 24.2             # наибольшая солёность изоплет в данных Bakker et al. (1996), табл. 4
Q1_T_MIN_C = -25.0              # ниже Q1 для 24,2 мас. % (−24,7 °C); корреляции дальше не определены
Q2_T_MIN_C = -10.0              # нижняя граница уравнения Darling, как в fluid_core/salinity.py
LCARB_P_FITTED_MAX_BAR = 2000.0  # ур. 23 подобрано до ~2 кбар; выше — экстраполяция (по статье, допустимая)

M_H2O = 18.0152                 # молярные массы программы автора, г/моль
M_CO2 = 44.01


def _num(x, name):
    if isinstance(x, bool):
        raise TypeError(f'{name}: требуется число')
    x = float(x)
    if not isfinite(x):
        raise ValueError(f'{name}: требуется конечное число')
    return x


def _salinity(s):
    s = _num(s, 'Солёность')
    if not 0 <= s <= S_MAX_WT_PCT:
        raise ValueError(f'Солёность раствора вне области корреляций (0 … {S_MAX_WT_PCT:g} мас. % NaCl)')
    return s


# --- четверные точки -----------------------------------------------------------------------------------------
def _q1x(t):
    x = t + 1.48
    return -0.000396376732 * x ** 3 - 0.042882835239 * x ** 2 - 1.824116649925 * x


def _q2x(t):
    return 0.00098241 * (10 - t) * (t ** 2 + 45.385 * t + 1588.75)


def _check_q1_t(t_c):
    t = _num(t_c, 'Температура')
    if not Q1_T_MIN_C <= t <= Q1_T0_C:
        raise ValueError(f'Температура Q1 вне области корреляции ({Q1_T_MIN_C:g} … {Q1_T0_C:g} °C)')
    return t


def q1_salinity(t_c: float) -> float:
    """Солёность раствора в точке Q1 при заданной температуре, мас. % NaCl (ур. 16)."""
    return _q1x(_check_q1_t(t_c))


def q1_pressure_bar(t_c: float) -> float:
    """Давление в точке Q1 при заданной температуре, бар (ур. 17)."""
    x = _check_q1_t(t_c) + 1.48
    return 2.1624216E-05 * x ** 3 + 0.004757798464 * x ** 2 + 0.360621996598 * x + 10.34


def q2_salinity(t_c: float) -> float:
    """Солёность раствора в точке Q2 при заданной температуре, мас. % NaCl (ур. 18; Darling, 1991)."""
    t = _num(t_c, 'Температура')
    if not Q2_T_MIN_C <= t <= Q2_T0_C:
        raise ValueError(f'Температура Q2 вне области уравнения Darling ({Q2_T_MIN_C:g} … {Q2_T0_C:g} °C)')
    return _q2x(t)


def q2_pressure_bar(t_c: float) -> float:
    """Давление в точке Q2, бар: давление насыщения CO₂ при этой температуре (ур. 13)."""
    t = _num(t_c, 'Температура')
    if not Q2_T_MIN_C <= t <= Q2_T0_C:
        raise ValueError(f'Температура Q2 вне области уравнения Darling ({Q2_T_MIN_C:g} … {Q2_T0_C:g} °C)')
    return saturation_pressure_bar(t)


def _inverse(fun, s, lo, hi):
    """Температура, при которой убывающая функция fun(T) равна s (деление пополам)."""
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if fun(mid) > s:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-13:
            break
    return 0.5 * (lo + hi)


def q1_temperature_c(salinity_wt_pct: float) -> float:
    """Температура точки Q1 для раствора заданной солёности, °C (обращение ур. 16)."""
    s = _salinity(salinity_wt_pct)
    return Q1_T0_C if s == 0 else _inverse(_q1x, s, Q1_T_MIN_C, Q1_T0_C)


def q2_temperature_c(salinity_wt_pct: float) -> float:
    """Температура точки Q2 для раствора заданной солёности, °C (обращение ур. 18)."""
    s = _salinity(salinity_wt_pct)
    return Q2_T0_C if s == 0 else _inverse(_q2x, s, Q2_T_MIN_C, Q2_T0_C)


# --- трёхфазные поверхности плавления клатрата ---------------------------------------------------------------------
def laq_v_c_pressure_bar(t_c: float, salinity_wt_pct: float) -> float:
    """Давление равновесия «раствор – пар – клатрат» при T и солёности раствора, бар (ур. 19–21).

    Определено между точками Q1 и Q2 изоплеты данной солёности. В точке Q2 кривая приходит на 0,15–0,25 бар ниже
    давления Q2: сумма коэффициентов ур. 21 равна 0,9933, а не 1 (свойство корреляции автора, не исправляется).
    """
    t = _num(t_c, 'Температура')
    s = _salinity(salinity_wt_pct)
    tq1, tq2 = q1_temperature_c(s), q2_temperature_c(s)
    if not tq1 - 1e-9 <= t <= tq2 + 1e-9:
        raise ValueError(f'При солёности {s:g} мас. % равновесие «раствор – пар – клатрат» существует от '
                         f'{tq1:.2f} (Q1) до {tq2:.2f} °C (Q2)')
    pq1, pq2 = q1_pressure_bar(tq1), saturation_pressure_bar(tq2)
    ft = (t - tq1) / (tq2 - tq1)
    fp = (7.9709 * ft ** 6 - 21.055 * ft ** 5 + 20.948 * ft ** 4 - 9.2243 * ft ** 3 + 2.1122 * ft ** 2
          + 0.2415 * ft)
    return fp * (pq2 - pq1) + pq1


def laq_lcarb_c_slope_bar_per_c(salinity_wt_pct: float) -> float:
    """Наклон dP/dT изоплеты равновесия «раствор – жидкая CO₂ – клатрат», бар/°C (ур. 22)."""
    s = _salinity(salinity_wt_pct)
    return 116.2846 + (-0.00357355 * s ** 2 + 0.182396 * s) ** 4


def laq_lcarb_c_pressure_bar(t_c: float, salinity_wt_pct: float) -> float:
    """Давление равновесия «раствор – жидкая CO₂ – клатрат» при T и солёности раствора, бар (ур. 22–23).

    Определено при T не ниже Q2 данной солёности. Ур. 23 подобрано примерно до 2 кбар.
    В программе автора (Q2plusP) при T ниже Q2 возвращается наклон·(T − T(Q2)) без давления Q2, то есть
    отрицательное число; здесь такой вызов считается ошибкой.
    """
    t = _num(t_c, 'Температура')
    s = _salinity(salinity_wt_pct)
    tq2 = q2_temperature_c(s)
    if t < tq2 - 1e-9:
        raise ValueError(f'При солёности {s:g} мас. % равновесие «раствор – жидкая CO₂ – клатрат» существует '
                         f'выше {tq2:.2f} °C (Q2)')
    return saturation_pressure_bar(tq2) + laq_lcarb_c_slope_bar_per_c(s) * (t - tq2)


# --- клатрат ---------------------------------------------------------------------------------------------------
_LANGMUIR_SMALL = (0.0011978, 2860.5)       # A (K/атм), B (K): малые полости, CO₂ (Parrish & Prausnitz, 1972)
_LANGMUIR_LARGE = (0.008507, 3277.9)        # большие полости
_BAR_TO_ATM = 0.987                         # множитель программы автора
_COMPRESSIBILITY_PER_BAR = 1e-05
_AVOGADRO = 6.022E+23                       # как в программе автора


@dataclass(frozen=True)
class ClathrateComposition:
    hydration_number: float         # n в формуле CO₂·nH₂O
    x_h2o: float                    # мольная доля H₂O в клатрате, n/(1 + n) («ZH2O» программы автора)
    occupancy_small: float          # заполнение малых полостей (2 на ячейку)
    occupancy_large: float          # заполнение больших полостей (6 на ячейку)

    @property
    def molar_mass_g_mol(self) -> float:
        return self.x_h2o * M_H2O + (1 - self.x_h2o) * M_CO2


def clathrate_composition(t_c: float, p_bar: float, ln_phi_co2: float, y_co2: float = 1.0) -> ClathrateComposition:
    """Состав клатрата CO₂ (структура I: 46 H₂O, 2 малые и 6 больших полостей на ячейку).

    ln_phi_co2 — ln коэффициента фугитивности CO₂ в сосуществующей углекислотной фазе, y_co2 — мольная доля CO₂
    в ней. Фугитивность, как в программе автора: f = y·φ·P·0,987 (атм).
    """
    t = _num(t_c, 'Температура') + 273.15
    p = _num(p_bar, 'Давление')
    lnphi = _num(ln_phi_co2, 'ln φ')
    y = _num(y_co2, 'Мольная доля CO₂')
    if t <= 0 or p <= 0:
        raise ValueError('Температура (K) и давление должны быть положительными')
    if not 0 < y <= 1:
        raise ValueError('Мольная доля CO₂ в углекислотной фазе должна быть в пределах (0; 1]')
    fug = y * exp(lnphi) * p * _BAR_TO_ATM
    theta = []
    for a, b in (_LANGMUIR_SMALL, _LANGMUIR_LARGE):
        c = a / t * exp(b / t)
        theta.append(c * fug / (1 + c * fug))
    n = 46 / (2 * theta[0] + 6 * theta[1])
    return ClathrateComposition(n, n / (1 + n), theta[0], theta[1])


def clathrate_volume_per_mol_h2o(t_c: float) -> float:
    """Объём клатрата на моль H₂O при 1 бар, см³/моль (ребро ячейки по Tse, 1987)."""
    t = _num(t_c, 'Температура') + 273.15
    if t <= 0:
        raise ValueError('Температура (K) должна быть положительной')
    cell = 11.835 + 2.2173E-05 * t + 2.2415E-06 * t ** 2          # Å
    return (cell * 1E-08) ** 3 * _AVOGADRO / 46


def clathrate_molar_volume(t_c: float, p_bar: float, x_h2o: float) -> float:
    """Молярный объём клатрата, см³ на моль смеси (H₂O + CO₂), ур. 24 в записи программы автора.

    x_h2o — мольная доля H₂O в клатрате (`ClathrateComposition.x_h2o`). В тексте статьи множитель «ZH2O» описан
    как число молей H₂O на моль клатрата; программа подставляет мольную долю n/(1 + n) — перенесено по программе.
    """
    p = _num(p_bar, 'Давление')
    x = _num(x_h2o, 'Мольная доля H₂O')
    if p <= 0:
        raise ValueError('Давление должно быть положительным')
    if not 0 < x < 1:
        raise ValueError('Мольная доля H₂O в клатрате должна быть в пределах (0; 1)')
    return x * clathrate_volume_per_mol_h2o(t_c) * exp(-_COMPRESSIBILITY_PER_BAR * (p - 1))


def clathrate_density_g_cm3(t_c: float, p_bar: float, composition: ClathrateComposition) -> float:
    """Плотность клатрата, г/см³."""
    return composition.molar_mass_g_mol / clathrate_molar_volume(t_c, p_bar, composition.x_h2o)
