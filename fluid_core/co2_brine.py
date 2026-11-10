"""Взаимная растворимость и объёмы фаз в системе H₂O–CO₂–NaCl (этап 2б, часть 3).

Составные модели программы H2O-NaCl-CO2 (Steele-MacInnis, 2018, Chem. Geol. 498, 31–44, разд. 4.5–4.6),
перенесённые из процедур CO2_Soly, Duan_H2O_Pres, H2O_NaCl_CO2_Volumes, NaCl_Partial_Molar_Volume, yH2O:

* растворимость CO₂ в водном растворе NaCl — Duan & Sun (2003), Chem. Geol. 193, 257–271 (273–533 K, 0–2000 бар,
  0–4,3 моль/кг NaCl); давление пара воды — там же, приложение B;
* молярный объём воды — Hu, Duan, Zhu & Chou (2007), Chem. Geol. 238, 249–267, ур. 2;
* кажущийся молярный объём NaCl — Rogers & Pitzer (1982), J. Phys. Chem. Ref. Data 11, 15–81; предельный объём
  V° и наклон Дебая–Хюккеля Av — регрессии автора программы по табл. A1 этой работы;
* кажущийся молярный объём растворённой CO₂ — Duan, Hu, Li & Mao (2008), Energy & Fuels 22, 1666–1674, ур. 3;
* доля воды в углекислотной фазе — Spycher, Pruess & Ennis-King (2003), GCA 67, 3015–3031, и Spycher & Pruess
  (2005), GCA 69, 3309–3320 (0,03–100 °C по статьям); молярный объём углекислотной фазы подаётся извне
  (в программе автора — объём чистой CO₂ по Duan или с линии насыщения).

Температура — °C, давление — бар, объёмы — см³/моль, солёность — мас. % NaCl в растворе без учёта CO₂.
Модуль в интерфейс программы не подключён (до сверки всей модели 2б с эталоном).
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, log, sqrt

MODEL_REFERENCE = ('Duan Z., Sun R. (2003) Chem. Geol. 193, 257–271; Hu J., Duan Z., Zhu C., Chou I.-M. (2007) Chem. '
                   'Geol. 238, 249–267; Rogers P.S.Z., Pitzer K.S. (1982) J. Phys. Chem. Ref. Data 11, 15–81; Duan Z., '
                   'Hu J., Li D., Mao S. (2008) Energy & Fuels 22, 1666–1674; Spycher N., Pruess K., Ennis-King J. '
                   '(2003) GCA 67, 3015–3031; Spycher N., Pruess K. (2005) GCA 69, 3309–3320; в записи программы '
                   'H2O-NaCl-CO2: Steele-MacInnis M. (2018) Chem. Geol. 498, 31–44')

M_H2O = 18.0152                 # молярные массы программы автора, г/моль
M_NACL = 58.44277
M_CO2 = 44.01
MOL_H2O_PER_KG = 1000 / M_H2O

SOLUBILITY_T_MIN_C = 0.0        # Duan & Sun (2003): 273–533 K, 0–2000 бар, до 4,3 моль/кг NaCl
SOLUBILITY_T_MAX_C = 260.0
SOLUBILITY_P_MAX_BAR = 2000.0
SOLUBILITY_M_MAX = 4.3


def _num(x, name):
    if isinstance(x, bool):
        raise TypeError(f'{name}: требуется число')
    x = float(x)
    if not isfinite(x):
        raise ValueError(f'{name}: требуется конечное число')
    return x


def _tk(t_c):
    t = _num(t_c, 'Температура') + 273.15
    if t <= 0:
        raise ValueError('Температура ниже абсолютного нуля')
    return t


def _pos(x, name):
    x = _num(x, name)
    if x <= 0:
        raise ValueError(f'{name}: требуется положительное число')
    return x


def nacl_molality(salinity_wt_pct: float) -> float:
    """Моляльность NaCl (моль на кг воды) по солёности в мас. %."""
    s = _num(salinity_wt_pct, 'Солёность')
    if not 0 <= s < 100:
        raise ValueError('Солёность должна быть в пределах 0 … 100 мас. %')
    return s / M_NACL / ((100 - s) / 1000)


# --- давление пара воды (Duan & Sun, 2003, приложение B) -----------------------------------------------------
_W_TC, _W_PC = 647.29, 220.85


def water_vapor_pressure_bar(t_c: float) -> float:
    """Давление насыщенного пара чистой воды, бар (Duan & Sun, 2003, ур. B1)."""
    tk = _tk(t_c)
    if tk > _W_TC:
        raise ValueError('Давление пара воды определено до критической температуры воды')
    x = (tk - _W_TC) / _W_TC
    return _W_PC * tk / _W_TC * (1 - 38.640844 * (-x) ** 1.9 + 5.894842 * x + 59.876516 * x ** 2
                                 + 26.654627 * x ** 3 + 10.637097 * x ** 4)


# --- растворимость CO₂ (Duan & Sun, 2003) ------------------------------------------------------------------------
@dataclass(frozen=True)
class AqueousComposition:
    m_co2: float                    # моль CO₂ на кг воды
    m_nacl: float                   # моль NaCl на кг воды
    x_co2: float                    # мольные доли в растворе (NaCl — как недиссоциированная соль)
    x_nacl: float
    x_h2o: float
    in_published_range: bool        # T, P и моляльность NaCl в заявленной области Duan & Sun (2003)

    @property
    def molar_mass_g_mol(self) -> float:
        return self.x_h2o * M_H2O + self.x_nacl * M_NACL + self.x_co2 * M_CO2


def co2_solubility(t_c: float, p_bar: float, salinity_wt_pct: float, ln_phi_co2: float) -> AqueousComposition:
    """Состав водного раствора, насыщенного CO₂, при T, P и солёности (Duan & Sun, 2003, ур. 6).

    ln_phi_co2 — ln коэффициента фугитивности CO₂ в углекислотной фазе (в статье и в программе автора — чистой CO₂
    по Duan et al., 1992a). Доля CO₂ в этой фазе принята, как в статье: y = (P − P пара воды)/P.
    Ниже 0 °C модель экстраполируется (в программе автора — без ограничений); это отмечается признаком.
    """
    tk = _tk(t_c)
    p = _pos(p_bar, 'Давление')
    lnphi = _num(ln_phi_co2, 'ln φ')
    m = nacl_molality(salinity_wt_pct)
    if tk >= 630:
        raise ValueError('Модель растворимости CO₂ не определена при 630 K и выше')
    ph2o = water_vapor_pressure_bar(t_c)
    if p <= ph2o:
        raise ValueError('Давление не выше давления пара воды: углекислотной фазы нет')
    lam = (-0.411370585 + 0.000607632013 * tk + 97.5347708 / tk - 0.0237622469 * p / tk
           + 0.0170656236 * p / (630 - tk) + 1.41335834E-05 * tk * log(p))
    xi = 0.000336389723 - 1.9829898E-05 * tk + 0.0021222083 * p / tk - 0.00524873303 * p / (630 - tk)
    mu = (28.9447706 - 0.0354581768 * tk - 4770.67077 / tk + 1.02782768E-05 * tk ** 2 + 33.8126098 / (630 - tk)
          + 0.0090403714 * p - 0.00114934031 * p * log(tk) - 0.307405726 * p / tk - 0.0907301486 * p / (630 - tk)
          + 0.000932713393 * p ** 2 / (630 - tk) ** 2)
    y_co2 = (p - ph2o) / p
    m_co2 = y_co2 * p / exp(mu - lnphi + 2 * lam * m + xi * m * m)
    total = m + m_co2 + MOL_H2O_PER_KG
    x_co2, x_nacl = m_co2 / total, m / total
    ok = (SOLUBILITY_T_MIN_C <= float(t_c) <= SOLUBILITY_T_MAX_C and p <= SOLUBILITY_P_MAX_BAR
          and m <= SOLUBILITY_M_MAX)
    return AqueousComposition(m_co2, m, x_co2, x_nacl, 1 - x_co2 - x_nacl, ok)


# --- объёмы -----------------------------------------------------------------------------------------------------
def water_molar_volume(t_c: float, p_bar: float) -> float:
    """Молярный объём жидкой воды, см³/моль (Hu et al., 2007, ур. 2)."""
    t = _tk(t_c)
    p = _pos(p_bar, 'Давление')
    return (3.27225E-07 * t ** 3 - 0.00042095 * t ** 2 + 0.232594 * t - 41.692 + 5712.92 / t
            + p * (-2.32306E-10 * t ** 3 + 2.91138E-07 * t ** 2 - 0.000149662 * t + 0.035986 - 3.55071 / t)
            + p ** 2 * (2.57241E-14 * t ** 3 - 1.24336E-11 * t ** 2 + 5.42707E-07)
            + p ** 3 * (-4.42028E-18 * t ** 3 + 2.10007E-15 * t ** 2 - 8.11491E-11))


# Rogers & Pitzer (1982), табл. 2: коэффициенты B (10–23) и C (24–28); два набора — до 50 °C и выше.
_RP_LOW = ((-2.1451068E-05, 0.0022324909, -6.4950599E-08, 2.450302E-10, 0.0, 1.0033371E-07, -1.2784026E-06,
            -4.6468063E-10, 5.7054131E-13, 0.0, 0.0, 1.3581172E-10, 0.0, 0.0),
           (-6.815243E-06, -0.00025382945, 6.2480692E-08, -1.0731284E-10, 0.0))
_RP_HIGH = ((5.3699517E-05, 0.0022020163, -2.6538013E-07, 8.6255554E-10, -0.02682931, -1.1173488E-07,
             -2.6249802E-07, 3.49265E-10, -8.3571924E-13, 3.066994E-05, 1.9767979E-11, -1.9144105E-10,
             3.1387857E-14, -9.6461948E-09),
            (2.2902837E-05, -0.00043314252, -9.0550901E-08, 8.69266E-11, 0.00051904777))
_RP_R = 83.144
_REG_T0, _REG_P0 = 72.0588235294118, 500.264705882353      # центры регрессий автора (°C, бар)


def _debye_huckel_slope(t_c, p):
    """Наклон Дебая–Хюккеля Av: регрессия автора программы по табл. A1 Rogers & Pitzer (1982)."""
    dt, dp = t_c - _REG_T0, p - _REG_P0
    return (1.17551943661751 + 0.0244082722185344 * t_c + dt * dt * 0.000151814888849409
            - 0.000717574993978318 * p + dp * dp * 1.158854071014E-07 + dt * dp * -1.11237235026788E-05
            + dt ** 3 * 8.488575543728E-07 + dt * dt * dp * -1.141523173118E-07 + dp * dp * dt * 4.1966905284E-09
            + dt ** 4 * 1.8124834764E-09 + dt ** 3 * dp * -9.335001529E-10 + dp * dp * dt * dt * 8.91890041311294E-11)


def _nacl_limiting_volume(t_c, p):
    """Предельный кажущийся объём NaCl V°: регрессия автора программы по табл. A1 Rogers & Pitzer (1982)."""
    dt, dp = t_c - _REG_T0, p - _REG_P0
    return (19.3070129434533 - 0.019011850525945 * t_c + 0.00276068666168927 * p
            + dt * dt * -0.000652332809444956 + dt * dp * 5.9099649164528E-06 + dp * dp * -6.199250918968E-07
            + dt ** 3 * 4.392651595269E-07 + dt * dt * dp * 4.564294343416E-07 + dt * dp * dp * 8.1522642772E-09
            + dt ** 4 * -2.40216101278E-08 + dt ** 5 * 1.61470571680867E-10)


def _pitzer_b_c(t, p):
    """Параметры B и 2C уравнения Rogers & Pitzer (1982), ур. 24–25 (T в K, P в бар)."""
    u, c = _RP_LOW if t <= 323.15 else _RP_HIGH
    dp = p - 1.01325
    bmx = (u[0] + u[1] / (t - 227) + u[2] * t + u[3] * t ** 2 + u[4] / (680 - t)
           + dp * (u[5] + u[6] / (t - 227) + u[7] * t + u[8] * t ** 2 + u[9] / (680 - t))
           + dp ** 2 * (u[10] + u[11] / (t - 227) + u[12] * t + u[13] / (680 - t)))
    cmx = c[0] + c[1] / (t - 227) + c[2] * t + c[3] * t ** 2 + c[4] / (680 - t)
    return bmx, cmx


def nacl_apparent_molar_volume(t_c: float, p_bar: float, molality: float) -> float:
    """Кажущийся молярный объём NaCl в растворе, см³/моль (Rogers & Pitzer, 1982, в записи программы автора).

    При нулевой моляльности программа автора возвращает 0 (вклад соли в объём отсутствует) — так же и здесь.
    Регрессии автора программы для V° и Av близки к табл. A-1 Rogers & Pitzer до ~150 °C и непригодны выше
    200 °C (V° при 300 °C: +18 вместо −45 см³/моль); сами параметры B и C совпадают с таблицей.
    """
    t = _tk(t_c)
    p = _pos(p_bar, 'Давление')
    m = _num(molality, 'Моляльность NaCl')
    if m < 0:
        raise ValueError('Моляльность NaCl не может быть отрицательной')
    if m == 0:
        return 0.0
    bmx, cmx = _pitzer_b_c(t, p)
    h = log(1 + 1.2 * sqrt(m)) / 2.4
    tc = t - 273.15
    return (_nacl_limiting_volume(tc, p) + 2 * _debye_huckel_slope(tc, p) * h
            + 2 * _RP_R * t * (m * bmx + m ** 2 * cmx / 2))


def co2_apparent_molar_volume(t_c: float, p_bar: float, x_co2_salt_free: float) -> float:
    """Кажущийся молярный объём растворённой CO₂, см³/моль (Duan et al., 2008, ур. 3).

    x_co2_salt_free — мольная доля CO₂ в пересчёте на раствор без соли: x(CO₂)/(x(CO₂) + x(H₂O)).
    По ур. 3 величина от этой доли не зависит (V = Vw·(1 + A1 + A2·P)); аргумент оставлен ради единообразия
    с программой автора и проверяется на допустимость.
    """
    t = _tk(t_c)
    p_mpa = _pos(p_bar, 'Давление') / 10
    x = _num(x_co2_salt_free, 'Мольная доля CO₂')
    if not 0 < x < 1:
        raise ValueError('Мольная доля CO₂ должна быть в пределах (0; 1)')
    a1 = 0.0003838402 * t ** 2 - 0.5595385 * t + 304.29268 - 72044.305 / t + 6300338.8 / t ** 2
    a2 = -5.7709332E-06 * t ** 2 + 0.0082764653 * t - 4.3813556 + 1014.4907 / t - 86777.045 / t ** 2
    vw = water_molar_volume(t_c, p_bar)
    vwc = vw * (1 + (a1 + a2 * p_mpa) * x)
    return (vwc - (1 - x) * vw) / x


def aqueous_molar_volume(t_c: float, p_bar: float, x_co2: float, x_nacl: float) -> float:
    """Молярный объём водного раствора H₂O–NaCl–CO₂, см³/моль (H2O_NaCl_CO2_Volumes программы автора).

    V = Vw·x(H₂O) + V(NaCl)·x(NaCl) + V(CO₂)·x(CO₂); мольные доли — как в `AqueousComposition`.
    """
    xc = _num(x_co2, 'Мольная доля CO₂')
    xn = _num(x_nacl, 'Мольная доля NaCl')
    xw = 1 - xc - xn
    if xc < 0 or xn < 0 or xw <= 0:
        raise ValueError('Мольные доли должны быть неотрицательными, доля воды — положительной')
    v = water_molar_volume(t_c, p_bar) * xw
    if xn > 0:
        v += nacl_apparent_molar_volume(t_c, p_bar, xn / (xw * M_H2O / 1000)) * xn
    if xc > 0:
        v += co2_apparent_molar_volume(t_c, p_bar, xc / (xc + xw)) * xc
    return v


def aqueous_density_g_cm3(t_c: float, p_bar: float, x_co2: float, x_nacl: float) -> float:
    """Плотность водного раствора H₂O–NaCl–CO₂, г/см³."""
    xw = 1 - x_co2 - x_nacl
    return (xw * M_H2O + x_nacl * M_NACL + x_co2 * M_CO2) / aqueous_molar_volume(t_c, p_bar, x_co2, x_nacl)


# --- вода в углекислотной фазе (Spycher et al., 2003; Spycher & Pruess, 2005) ---------------------------------------
_S_B_CO2, _S_B_H2O = 27.8, 18.18          # см³/моль
_S_A_H2O_CO2 = 78900000.0                 # бар·см⁶·K⁰·⁵/моль²
_S_R = 83.14462
_S_V_H2O = 18.1                           # парциальный молярный объём воды, см³/моль


def water_fraction_in_co2(t_c: float, p_bar: float, x_co2: float, x_nacl: float, v_co2_cm3_mol: float) -> float:
    """Мольная доля H₂O в углекислотной фазе, равновесной с водным раствором (процедура yH2O программы автора).

    y(H₂O) = K°/(φ·P)·exp[(P − 1)·V̄/(R·T)]·x(H₂O), где x(H₂O) = 1 − x(CO₂) − x(NaCl) — доля воды в растворе,
    φ — коэффициент фугитивности воды по уравнению Редлиха–Квонга (Spycher et al., 2003) при молярном объёме
    углекислотной фазы v_co2_cm3_mol.
    """
    t = _num(t_c, 'Температура')
    tk = _tk(t)
    p = _pos(p_bar, 'Давление')
    v = _pos(v_co2_cm3_mol, 'Молярный объём углекислотной фазы')
    xc = _num(x_co2, 'Мольная доля CO₂')
    xn = _num(x_nacl, 'Мольная доля NaCl')
    if xc < 0 or xn < 0 or xc + xn >= 1:
        raise ValueError('Мольные доли должны быть неотрицательными, доля воды — положительной')
    if v <= _S_B_CO2:
        raise ValueError('Молярный объём углекислотной фазы меньше параметра уравнения Редлиха–Квонга (27,8 см³/моль)')
    a_co2 = 75400000.0 - 41300.0 * tk
    log_k = -2.209 + 0.03097 * t - 0.0001098 * t ** 2 + 2.048E-07 * t ** 3
    ln_phi = (log(v / (v - _S_B_CO2)) + _S_B_H2O / (v - _S_B_CO2)
              - 2 * _S_A_H2O_CO2 / _S_R / tk ** 1.5 / _S_B_CO2 * log((v + _S_B_CO2) / v)
              + a_co2 * _S_B_H2O / _S_R / tk ** 1.5 / _S_B_CO2 ** 2 * (log((v + _S_B_CO2) / v) - _S_B_CO2 / (v + _S_B_CO2))
              - log(p * v / _S_R / tk))
    return 10 ** log_k / exp(ln_phi) / p * exp((p - 1) * _S_V_H2O / _S_R / tk) * (1 - xc - xn)
