"""Чистая CO₂ для модели H₂O–CO₂–NaCl (этап 2б, часть 1): молярный объём, давление, коэффициент фугитивности.

Уравнение состояния — Duan, Møller & Weare (1992a), Geochim. Cosmochim. Acta 56, 2605–2617 («An equation of
state for the CH4-CO2-H2O system: I. Pure systems from 0 to 1000 °C and 0 to 8000 bar»), в приведённых
переменных:

    Z = P·V/(R·T) = Pr·Vr/Tr = 1 + B/Vr + C/Vr² + D/Vr⁴ + E/Vr⁵ + F/Vr²·(β + γ/Vr²)·exp(−γ/Vr²),
    B = a1 + a2/Tr² + a3/Tr³,  C = a4 + a5/Tr² + a6/Tr³,  D = a7 + a8/Tr² + a9/Tr³,
    E = a10 + a11/Tr² + a12/Tr³,  F = α/Tr³,  Tr = T/Tc,  Pr = P/Pc,  Vr = V·Pc/(R·Tc);

    ln φ = Z − 1 − ln Z + B/Vr + C/(2Vr²) + D/(4Vr⁴) + E/(5Vr⁵)
           + F/(2γ)·[β + 1 − (β + 1 + γ/Vr²)·exp(−γ/Vr²)].

Коэффициенты, критические константы (Tc = 304,2 K, Pc = 73,825 бар) и газовая постоянная перенесены из программы
H2O-NaCl-CO2 (Steele-MacInnis, 2018, Chem. Geol. 498, 31–44) — процедуры Volume_CO2, CO2_isochore, lnPhiCO2.
Линия насыщения жидкость–пар — корреляции Span & Wagner (1996), ур. 3.13–3.15, в том виде, в каком они записаны
в программе автора (ур. 13–15 статьи 2018 г.: округлённые Tc = 304,2 K, Pc = 73,9 бар, ρc = 0,466 г/см³).

Модуль описывает ТОЛЬКО чистую CO₂. Это не давление захвата и не свойства включения в целом; в интерфейс
программы модуль не подключён (до сверки всей модели 2б с эталоном). Корреляции `fluid_core/co2.py`
(Span & Wagner через CoolProp) этим модулем не заменяются.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import exp, isfinite, log

MODEL_REFERENCE = ('Duan Z., Møller N., Weare J.H. (1992) Geochim. Cosmochim. Acta 56, 2605–2617 (уравнение состояния '
                   'CO₂); Span R., Wagner W. (1996) J. Phys. Chem. Ref. Data 25, 1509–1596, ур. 3.13–3.15 (линия '
                   'насыщения); в записи программы H2O-NaCl-CO2: Steele-MacInnis M. (2018) Chem. Geol. 498, 31–44')

TC_K = 304.2                    # критическая температура CO₂ в уравнении Duan et al. (1992a)
PC_BAR = 73.825                 # критическое давление там же
R_CM3_BAR = 83.14467            # газовая постоянная программы автора, см³·бар/(моль·K)
M_CO2 = 44.01                   # молярная масса CO₂ в программе автора, г/моль
TC_C = 31.05                    # граница «T < 31.05» в программе автора (= TC_K − 273,15)
TRIPLE_POINT_C = 216.592 - 273.15

T_PUBLISHED_MIN_C = 0.0         # заявленная область уравнения: 0–1000 °C, 0–8000 бар
T_MAX_C = 1000.0
P_MAX_BAR = 8000.0

_A = (0.0899288497, -0.494783127, 0.0477922245, 0.0103808883, -0.0282516861, 0.0949887563, 0.00052060088,
      -0.000293540971, -0.00177265112, -2.51101973E-05, 8.93353441E-05, 7.88998563E-05)
_ALPHA = -0.0166727022
_BETA = 1.398
_GAMMA = 0.0296

# Линия насыщения (программа автора, ур. 13–15): Tc = 304,2 K, Pc = 73,9 бар, ρc = 0,466 г/см³.
_SAT_PC_BAR = 73.9
_SAT_RHOC = 0.466


def _num(x, name):
    if isinstance(x, bool):
        raise TypeError(f'{name}: требуется число')
    x = float(x)
    if not isfinite(x):
        raise ValueError(f'{name}: требуется конечное число')
    return x


def _check_t(t_c):
    t = _num(t_c, 'Температура')
    if not TRIPLE_POINT_C < t <= T_MAX_C:
        raise ValueError(f'Температура вне области модели CO₂ ({TRIPLE_POINT_C:.2f} … {T_MAX_C:g} °C)')
    return t


def _coef(tr):
    a = _A
    return (a[0] + a[1] / tr ** 2 + a[2] / tr ** 3, a[3] + a[4] / tr ** 2 + a[5] / tr ** 3,
            a[6] + a[7] / tr ** 2 + a[8] / tr ** 3, a[9] + a[10] / tr ** 2 + a[11] / tr ** 3, _ALPHA / tr ** 3)


def _z(tr, vr):
    b, c, d, e, f = _coef(tr)
    return (1 + b / vr + c / vr ** 2 + d / vr ** 4 + e / vr ** 5
            + f / vr ** 2 * (_BETA + _GAMMA / vr ** 2) * exp(-_GAMMA / vr ** 2))


def _lnphi(tr, vr, z):
    b, c, d, e, f = _coef(tr)
    return (z - 1 - log(z) + b / vr + c / 2 / vr ** 2 + d / 4 / vr ** 4 + e / 5 / vr ** 5
            + f / 2 / _GAMMA * (_BETA + 1 - (_BETA + 1 + _GAMMA / vr ** 2) * exp(-_GAMMA / vr ** 2)))


def _vr(v):
    return v * PC_BAR / (R_CM3_BAR * TC_K)


# --- линия насыщения жидкость–пар ---------------------------------------------------------------------------
def _tau(t_c):
    t = _num(t_c, 'Температура')
    if not TRIPLE_POINT_C < t <= TC_C:
        raise ValueError(f'Линия насыщения CO₂ определена от {TRIPLE_POINT_C:.2f} до {TC_C:g} °C')
    return t, max(0.0, 1 - (t + 273.15) / TC_K)


def saturation_pressure_bar(t_c: float) -> float:
    """Давление насыщенного пара CO₂, бар (Span & Wagner, 1996, ур. 3.13; запись программы автора)."""
    t, x = _tau(t_c)
    return _SAT_PC_BAR * exp(TC_K / (t + 273.15) * (-7.0602087 * x + 1.9391218 * x ** 1.5 - 1.6463597 * x ** 2
                                                   - 3.2995634 * x ** 4))


def saturated_liquid_volume(t_c: float) -> float:
    """Молярный объём насыщенной жидкой CO₂, см³/моль (Span & Wagner, 1996, ур. 3.14)."""
    _, x = _tau(t_c)
    rho = _SAT_RHOC * exp(1.9245108 * x ** 0.34 - 0.62385555 * x ** 0.5 - 0.32731127 * x ** (10 / 6)
                          + 0.39245142 * x ** (11 / 6))
    return M_CO2 / rho


def saturated_vapor_volume(t_c: float) -> float:
    """Молярный объём насыщенного пара CO₂, см³/моль (Span & Wagner, 1996, ур. 3.15)."""
    _, x = _tau(t_c)
    rho = _SAT_RHOC * exp(-1.7074879 * x ** 0.34 - 0.8227467 * x ** 0.5 - 4.6008549 * x - 10.111178 * x ** (7 / 3)
                          - 29.742252 * x ** (14 / 3))
    return M_CO2 / rho


# --- уравнение состояния ------------------------------------------------------------------------------------
def compressibility(t_c: float, v_cm3_mol: float) -> float:
    """Коэффициент сжимаемости Z(T, V) по Duan et al. (1992a)."""
    t = _check_t(t_c)
    v = _num(v_cm3_mol, 'Молярный объём')
    if v <= 0:
        raise ValueError('Молярный объём должен быть положительным')
    return _z((t + 273.15) / TC_K, _vr(v))


def pressure_bar(t_c: float, v_cm3_mol: float) -> float:
    """Давление CO₂ при заданных T и молярном объёме, бар (изохора чистой CO₂; CO2_isochore программы автора)."""
    z = compressibility(t_c, v_cm3_mol)
    return z * R_CM3_BAR * (float(t_c) + 273.15) / float(v_cm3_mol)


def ln_fugacity_coefficient(t_c: float, p_bar: float, v_cm3_mol: float) -> float:
    """ln φ при заданных T, P и V, где Z = P·V/(R·T) (функция lnPhiCO2 программы автора).

    Используется, когда объём взят с линии насыщения (ур. 14–15), а не из решения уравнения состояния:
    тройка (T, P, V) тогда не обязана точно удовлетворять уравнению Duan — так поступает программа автора.
    """
    t = _check_t(t_c)
    p = _num(p_bar, 'Давление')
    v = _num(v_cm3_mol, 'Молярный объём')
    if p <= 0 or v <= 0:
        raise ValueError('Давление и молярный объём должны быть положительными')
    return _lnphi((t + 273.15) / TC_K, _vr(v), p * v / (R_CM3_BAR * (t + 273.15)))


@dataclass(frozen=True)
class Co2State:
    temperature_c: float
    pressure_bar: float
    molar_volume_cm3_mol: float
    density_g_cm3: float
    compressibility: float
    ln_fugacity_coefficient: float
    fugacity_bar: float
    phase: str                      # 'liquid' | 'vapor' | 'supercritical'
    in_published_range: bool        # False ниже 0 °C: экстраполяция уравнения (как в программе автора)
    multiple_roots: bool            # уравнение имеет несколько корней при этих T и P (выбор ветви — см. `state`)
    model_reference: str = MODEL_REFERENCE


def _roots(tr, pr):
    """Все корни Pr·Vr/Tr = Z(Tr, Vr) по возрастанию Vr (перебор по логарифмической сетке + деление пополам)."""
    b, c, d, e, f_ = _coef(tr)
    k = pr / tr

    def f(vr):
        w = 1 / (vr * vr)
        return k * vr - (1 + b / vr + c * w + d * w * w + e * w * w / vr + f_ * w * (_BETA + _GAMMA * w) * exp(-_GAMMA * w))

    lo, hi, n = 0.05, max(10.0, 20 * tr / pr), 1200
    step = (hi / lo) ** (1 / n)
    out, x0, f0 = [], lo, f(lo)
    for i in range(1, n + 1):
        x1 = lo * step ** i
        f1 = f(x1)
        if f0 == 0:
            out.append(x0)
        elif f0 * f1 < 0:
            a, bb, fa = x0, x1, f0
            for _ in range(200):
                m = 0.5 * (a + bb)
                fm = f(m)
                if fa * fm <= 0:
                    bb = m
                else:
                    a, fa = m, fm
                if bb - a <= 1e-15 * bb:
                    break
            out.append(0.5 * (a + bb))
        x0, f0 = x1, f1
    return out


@lru_cache(maxsize=8192)
def state(t_c: float, p_bar: float) -> Co2State:
    """Молярный объём и фугитивность чистой CO₂ при заданных T (°C) и P (бар).

    Ниже 31,05 °C уравнение имеет жидкий и газовый корни. Ветвь выбирается, как в программе автора (Volume_CO2):
    при P выше давления насыщения (ур. 13) — жидкость, иначе — пар. Собственная критическая точка уравнения лежит
    немного выше 31,05 °C, поэтому в узкой области (примерно 31–34 °C, 72–78 бар) корней тоже несколько; там
    берётся термодинамически устойчивый корень (наименьшая фугитивность) и выставляется `multiple_roots`.
    """
    t = _check_t(t_c)
    p = _num(p_bar, 'Давление')
    if not 0 < p <= P_MAX_BAR:
        raise ValueError(f'Давление вне области модели CO₂ (0 … {P_MAX_BAR:g} бар)')
    tr, pr = (t + 273.15) / TC_K, p / PC_BAR
    roots = _roots(tr, pr)
    if not roots:
        raise ArithmeticError('Уравнение состояния CO₂: корень не найден')
    if t < TC_C:
        liquid = p > saturation_pressure_bar(t)
        vr, phase = (roots[0], 'liquid') if liquid else (roots[-1], 'vapor')
    else:
        # устойчивый корень — с наименьшей фугитивностью (наименьшей энергией Гиббса)
        vr, phase = min(roots, key=lambda x: _lnphi(tr, x, pr * x / tr)), 'supercritical'
    z = pr * vr / tr
    v = vr * R_CM3_BAR * TC_K / PC_BAR
    lnphi = _lnphi(tr, vr, z)
    return Co2State(t, p, v, M_CO2 / v, z, lnphi, p * exp(lnphi), phase, t >= T_PUBLISHED_MIN_C,
                    len(roots) > 1)


def author_volume_and_lnphi(t_c: float, p_bar: float, max_iter: int = 10000) -> tuple[float, float]:
    """(V, ln φ) в точности по вычислительной схеме процедуры Volume_CO2 программы автора.

    Нужна только для сверки с эталонным прогоном (части 2–5 этапа 2б). Отличия от `state`:
    метод Ньютона с конечной разностью (шаг 1·10⁻⁴ по Vr) и теми же начальными приближениями; слагаемое
    Z − 1 − ln Z в ln φ берётся из правой части уравнения в точке, смещённой на этот шаг от корня. Из-за этого
    ln φ программы автора отличается от точного значения уравнения (заметно для жидкой CO₂; см. отчёт, разд. 12).
    """
    t = _check_t(t_c)
    p = _num(p_bar, 'Давление')
    if p <= 0:
        raise ValueError('Давление должно быть положительным')
    gas_con, pcrit = 8.314467, 7382500.0
    tr, pr = (t + 273.15) / TC_K, p * 100000.0 / pcrit
    if t < TC_C:
        v0 = 40.0 if p > saturation_pressure_bar(t) else 1000.0
    else:
        v0 = 200.0
    vr = v0 / gas_con / TC_K * pcrit / 100 ** 3
    increment, f, zrhs = 0.0001, [1.0, 1.0], 1.0
    for _ in range(max_iter):
        if abs(f[0]) <= 1e-10:
            break
        for i in (0, 1):
            vr = vr + i * increment
            zrhs = _z(tr, vr)
            f[i] = pr * vr / tr - zrhs
        vr = vr - f[1] / ((f[1] - f[0]) / increment)
        if vr < 0:
            vr = -vr + p / 100
    else:
        raise ArithmeticError('Схема Volume_CO2 программы автора не сошлась')
    v = vr * gas_con * TC_K / pcrit * 100 ** 3
    return v, _lnphi(tr, vr, zrhs)
