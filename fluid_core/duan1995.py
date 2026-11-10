"""Давление однофазного флюида H₂O–CO₂–NaCl при высоких температурах и изохора включения (этап 2б, часть 5).

Уравнение состояния Duan, Møller & Weare (1995), Geochim. Cosmochim. Acta 59, 2869–2882 («Equation of state for
the NaCl-H2O-CO2 system: Prediction of phase equilibria and volumetric properties»), развитие модели
Anderko & Pitzer (1993): Z = 1 + Z(твёрдые сферы) + Z(диполи) + Z(возмущение). Перенесено из процедуры
Duan_H2O_NaCl_CO2 программы H2O-NaCl-CO2 (Steele-MacInnis, 2018, Chem. Geol. 498, 31–44, разд. 4.8), включая её
физические константы.

Изохора включения в программе автора (процедура Isochore): давление вычисляется при 623, 673, 723 и 773 K
(в таблице они подписаны как 350, 400, 450 и 500 °C), по четырём точкам методом наименьших квадратов строится
прямая P = a + b·T(°C) с подписями 350…500; давление при Th общ. — значение этой прямой. Здесь то же самое
воспроизводит `author_isochore`; функция `pressure_bar` даёт давление уравнения при любой температуре области.

Область: в программе автора уравнение применяется при 350–500 °C. Ниже 573,15 K (300 °C) формулы параметров
не определены (дробные степени отрицательных чисел). Модуль в интерфейс программы не подключён.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, pi

MODEL_REFERENCE = ('Duan Z., Møller N., Weare J.H. (1995) Geochim. Cosmochim. Acta 59, 2869–2882; в записи программы '
                   'H2O-NaCl-CO2: Steele-MacInnis M. (2018) Chem. Geol. 498, 31–44')

T_MIN_K = 573.15                # ниже параметры уравнения не определены
T_MAX_K = 1273.15               # верхняя граница модели по статье (1000 °C)

_NA = 6.0221415E+23             # константы программы автора
_KB = 1.3807E+20
_R = 83.14472
_MU = (1.85, 6.4, 0.0)          # дипольные моменты: H₂O, NaCl, CO₂
_B = (28.4959, 60.0124, 49.52)  # объёмные параметры, см³/моль
_SIGMA = tuple((b / (2 / 3) / pi / _NA) ** (1 / 3) for b in _B)
_B13 = tuple(b ** (1 / 3) for b in _B)
_BIJ = tuple(tuple(((_B13[i] + _B13[j]) / 2) ** 3 for j in range(3)) for i in range(3))
_IDX = (1, 2, 3)                # номера компонентов программы автора: произведения номеров задают параметры смешения
_EPS_CO2 = frozenset((3, 9, 27, 81, 48, 72, 108, 162, 6, 12, 24, 18, 54, 36))


def _parameters(t):
    """Температурно-зависимые параметры (T в K)."""
    tw, tc, h = t / 647.067, t / 304.2, t / 100
    a = ((1.718248 + 1.828379 / tw + 1.546648 / tw ** 2 + 0.107189 / tw ** 4) * 1000000,
         (14.412 + 5.644 * exp(-0.4817 * (h - 8.959) ** 2) - 10 * exp(-0.6154 * (h - 5.403) ** 3.26)) * 1000000,
         (3.86491553 - 2.36222839 / tc + 3.51977858 / tc ** 2 - 1.01456034 / tc ** 4) * 1000000)
    c1 = 2.953548 - 8.874823 / tw + 3.179334 / tw ** 2 - 0.168698 / tw ** 4
    d1 = 2.139339 + 9.442203 / tw - 3.144017 / tw ** 2 + 0.149539 / tw ** 4
    ac = (a[0] * c1, a[1] * -2.7501, -4185084.6 + 518786.559 / tc)
    ad = (a[0] * d1, a[1] * 8.0969, 14954846.2 + 1402327.39 / tc)
    ae = (a[0] * -9.0, a[1] * -9.0, -30473228.4)
    x = h - 5.7315
    tau = ((0.10119 + 6.4313 * exp(-0.9961 * x ** 0.79026))
           * (1 + 6.1005 * x / 10 - 27.15 * (x / 10) ** 2 + 141.3 * (x / 10) ** 3 - 136.43 * (x / 10) ** 4))
    alpha = {2: (-3.0873 + 1.2688 * h - 0.1185 * h ** 2 + 0.0036853 * h ** 3
                 + 0.4213 * exp(-1.3614 * (h - 5.491) ** 2)) * tau,
             3: 0.88868 - 0.00017347 * t + 4.038E-07 * t ** 2,
             6: -1.73355444 + 0.00560408826 * t - 2.70381422E-06 * t ** 2}
    g_co2 = 1.03463 - 0.0002 * t if t > 773 else 1.41683554 - 0.000702857143 * t
    gamma = {2: (0.7865 + 0.1487 * h + 0.2537 * exp(-1.162E-06 * (h - 0.57315) ** 8)) * tau,
             3: g_co2, 9: g_co2, 12: g_co2, 18: g_co2,
             4: (1.4194 + 0.06552 * h + 0.2058 * exp(-1.604 * (h - 5.667) ** 2)) * tau,
             6: -0.207 + 0.00227 * t - 1.051E-06 * t ** 2}
    delta = {2: 1.293 * tau, 4: 1.389 * tau, 8: (1.306 + 0.091 * exp(-1.72 * x ** 2)) * tau}
    e_co2 = 1.28262 - 0.000732919762 * t + 3.51190476E-07 * t ** 2
    epsilon = {k: tau for k in (2, 4, 8, 16)}
    epsilon.update({k: e_co2 for k in _EPS_CO2})
    return a, ac, ad, ae, alpha, gamma, delta, epsilon


def _check(t_k, v, x_h2o, x_nacl, x_co2):
    vals = []
    for val, name in ((t_k, 'Температура'), (v, 'Молярный объём'), (x_h2o, 'Доля H₂O'), (x_nacl, 'Доля NaCl'),
                      (x_co2, 'Доля CO₂')):
        if isinstance(val, bool):
            raise TypeError(f'{name}: требуется число')
        val = float(val)
        if not isfinite(val):
            raise ValueError(f'{name}: требуется конечное число')
        vals.append(val)
    t_k, v, xw, xn, xc = vals
    if not T_MIN_K <= t_k <= T_MAX_K:
        raise ValueError(f'Температура вне области уравнения Duan et al. (1995): {T_MIN_K - 273.15:g} … '
                         f'{T_MAX_K - 273.15:g} °C')
    if v <= 0:
        raise ValueError('Молярный объём должен быть положительным')
    if min(xw, xn, xc) < 0 or xw <= 0 or abs(xw + xn + xc - 1) > 1e-9:
        raise ValueError('Мольные доли должны быть неотрицательными (воды — положительной) и давать в сумме 1')
    return t_k, v, (xw, xn, xc)


def pressure_at_kelvin_bar(t_k: float, v_cm3_mol: float, x_h2o: float, x_nacl: float, x_co2: float) -> float:
    """Давление флюида H₂O–NaCl–CO₂ при температуре T (K) и молярном объёме V, бар (Duan et al., 1995)."""
    t, v, x = _check(t_k, v_cm3_mol, x_h2o, x_nacl, x_co2)
    a, ac, ad, ae, alpha, gamma, delta, epsilon = _parameters(t)
    r3 = range(3)

    # твёрдые сферы
    dhs = sum(x[i] * _SIGMA[i] for i in r3)
    ehs = sum(x[i] * _SIGMA[i] ** 2 for i in r3)
    fhs = sum(x[i] * _SIGMA[i] ** 3 for i in r3)
    y = (2 / 3) * pi * _NA * fhs / 4 / v
    zhs = ((1 + 3 * dhs * ehs / fhs) * y - (2 + 3 * dhs * ehs / fhs - 3 * ehs ** 3 / fhs ** 2) * y ** 2
           - (ehs ** 3 / fhs ** 2 - 1) * y ** 3) / (1 - y) ** 3

    # диполи
    mu2 = tuple(_MU[i] ** 2 / _SIGMA[i] ** 3 / _KB / t for i in r3)        # квадраты приведённых моментов
    bdip = sum(x[i] * x[j] * _BIJ[i][j] for i in r3 for j in r3)
    n = bdip / 4 / v
    i2 = 1 + 1.6054 * n - 4.4521 * n ** 2 + 10.0368 * n ** 3
    poly = 1 + 0.35147 * n - 1.83943 * n ** 2 + 5.95676 * n ** 3
    i3 = i2 * poly
    di2 = 1.6054 - 2 * 4.4521 * n + 3 * 10.0368 * n ** 2
    di3 = i2 * (0.35147 - 2 * 1.83943 * n + 3 * 5.95676 * n ** 2) + di2 * poly
    a2 = da2 = a3 = da3 = 0.0
    for i in r3:
        for j in r3:
            w = x[i] * x[j] * _B[i] * _B[j] * mu2[i] * mu2[j]
            a2 += (-4 / 3) * w / _BIJ[i][j] ** 2 * (_BIJ[i][j] / 4 / v) * i2
            da2 += (-4 / 3) * w / _BIJ[i][j] / bdip * (i2 + n * di2)
            for k in r3:
                b3 = _BIJ[i][j] * _BIJ[i][k] * _BIJ[j][k]
                w3 = x[i] * x[j] * x[k] * _B[i] * _B[j] * _B[k] / b3 * mu2[i] * mu2[j] * mu2[k]
                a3 += (10 / 9) * w3 * (b3 ** (1 / 3) / 4 / v) ** 2 * i3
                da3 += (10 / 9) * w3 * b3 ** (2 / 3) / bdip ** 2 * (2 * n * i3 + n ** 2 * di3)
    zdip = n * ((1 - 2 * a3 / a2) * da2 + da3) / (1 - a3 / a2) ** 2 if a2 != 0 else 0.0

    # возмущение
    aper = acb = adb2 = aeb3 = 0.0
    for i in r3:
        if x[i] == 0:
            continue
        for j in r3:
            if x[j] == 0:
                continue
            pij = _IDX[i] * _IDX[j]
            aper += x[i] * x[j] * (a[i] * a[j]) ** 0.5 * alpha.get(pij, 1.0)
            for k in r3:
                if x[k] == 0:
                    continue
                pijk = pij * _IDX[k]
                bijk = ((_B13[i] + _B13[j] + _B13[k]) / 3) ** 3
                acb += (x[i] * x[j] * x[k] * -(abs(ac[i] * ac[j] * ac[k]) ** (1 / 3)) * gamma.get(pijk, 1.0) * bijk)
                for m in r3:
                    if x[m] == 0:
                        continue
                    pijkm = pijk * _IDX[m]
                    b4 = ((_B13[i] + _B13[j] + _B13[k] + _B13[m]) / 4) ** 3
                    adb2 += (x[i] * x[j] * x[k] * x[m] * (ad[i] * ad[j] * ad[k] * ad[m]) ** (1 / 4)
                             * delta.get(pijkm, 1.0) * b4 ** 2)
                    for q in r3:
                        if x[q] == 0:
                            continue
                        b5 = ((_B13[i] + _B13[j] + _B13[k] + _B13[m] + _B13[q]) / 5) ** 3
                        aeb3 += (x[i] * x[j] * x[k] * x[m] * x[q]
                                 * -(abs(ae[i] * ae[j] * ae[k] * ae[m] * ae[q]) ** (1 / 5))
                                 * epsilon.get(pijkm * _IDX[q], 1.0) * b5 ** 3)
    zper = (-1 / _R / t) * (aper / v + acb / 2 / v ** 2 + 3 * adb2 / 16 / v ** 3 + aeb3 / 16 / v ** 4)
    return (1 + zhs + zdip + zper) * _R * t / v


def pressure_bar(t_c: float, v_cm3_mol: float, x_h2o: float, x_nacl: float, x_co2: float) -> float:
    """Давление флюида H₂O–NaCl–CO₂ при температуре t (°C) и молярном объёме V, бар (Duan et al., 1995)."""
    if isinstance(t_c, bool):
        raise TypeError('Температура: требуется число')
    return pressure_at_kelvin_bar(float(t_c) + 273.15, v_cm3_mol, x_h2o, x_nacl, x_co2)


AUTHOR_ISOCHORE_T_K = (623.0, 673.0, 723.0, 773.0)       # температуры расчёта в программе автора
AUTHOR_ISOCHORE_LABELS_C = (350.0, 400.0, 450.0, 500.0)  # их подписи в таблице и в регрессии


@dataclass(frozen=True)
class LinearIsochore:
    pressures_bar: tuple            # давления в точках AUTHOR_ISOCHORE_T_K (подписаны как 350…500 °C)
    slope_bar_per_c: float          # dP/dT прямой
    intercept_bar: float            # свободный член прямой P = intercept + slope·T(°C)
    model_reference: str = MODEL_REFERENCE

    def pressure_at(self, t_c: float) -> float:
        """Давление по прямой при температуре t (°C); вне 350–500 °C — линейная экстраполяция, как у автора."""
        return self.intercept_bar + self.slope_bar_per_c * float(t_c)


def author_isochore(v_cm3_mol: float, x_h2o: float, x_nacl: float, x_co2: float) -> LinearIsochore:
    """Линейная изохора включения в точности по процедуре Isochore программы автора.

    Особенность программы: расчёт ведётся при 623…773 K (349,85…499,85 °C), а в регрессии и в таблице эти точки
    считаются равными 350…500 °C; давление при Th общ. получается подстановкой Th общ. в прямую.
    """
    p = tuple(pressure_at_kelvin_bar(t, v_cm3_mol, x_h2o, x_nacl, x_co2) for t in AUTHOR_ISOCHORE_T_K)
    mean = sum(p) / 4
    slope = sum((pi_ - mean) * (t - 425) for pi_, t in zip(p, AUTHOR_ISOCHORE_LABELS_C)) / 12500
    return LinearIsochore(p, slope, mean - slope * 425)
