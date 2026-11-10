"""Состав и плотность включений H₂O–CO₂–NaCl по микротермометрии (этап 2б, часть 4; режимы 1–3).

Алгоритм статьи Steele-MacInnis (2018), Chem. Geol. 498, 31–44, разд. 3.1–3.3, перенесённый из процедур MODE1,
MODE2, MODE3 и Phi_at_T программы автора.

* Режим 1 (`mode1`): клатрат плавится раньше гомогенизации углекислотных фаз (Tm клатрата ≤ Th CO₂), то есть
  в присутствии водного раствора, жидкой CO₂ и пара (точка Q2).
* Режим 2 (`mode2`): углекислотные фазы гомогенизируются раньше плавления клатрата (Th CO₂ ≤ Tm клатрата);
  клатрат плавится в присутствии раствора и одной углекислотной фазы, давление при этом заранее не известно.
* Режим 3 (`mode3`): жидкой CO₂ нет; измерены Tm льда (точка Q1) и Tm клатрата в присутствии раствора и пара.

Входные данные: температуры фазовых переходов, объёмная доля углекислотных фаз φ и температура, при которой она
оценена. Результат: валовый состав (мольные доли), солёность, молярный объём и плотность включения.

Режим 1 — условия, из которых находится решение (ур. 2–9 статьи):
  1. при Th CO₂ включение состоит из водного раствора и одной углекислотной фазы с объёмом насыщенной жидкости
     (гомогенизация в жидкость) или насыщенного пара (в пар); давление — давление насыщения CO₂;
  2. при Tm клатрата раствор имеет солёность точки Q2, сосуществуют раствор, жидкая CO₂ и пар; балансы NaCl и H₂O
     задают доли фаз;
  3. объём включения при Th CO₂ и при Tm клатрата одинаков — отсюда солёность раствора при Th CO₂;
  4. если φ оценена не при Th CO₂, доля при Th CO₂ подбирается так, чтобы рассчитанная доля при температуре
     оценки совпала с заданной.

Составные модели — модули `co2_duan1992`, `clathrate`, `co2_brine`.

Параметр numerics. 'exact' — уравнения решаются до сходимости, коэффициент фугитивности CO₂ — точное решение
уравнения Duan. 'author' — для сверки с эталоном: коэффициент фугитивности по вычислительной схеме программы автора,
а в режимах 2 и 3 дополнительно повторяются её итерации с её критериями остановки (в режиме 2 результат берётся
в предпоследней точке метода Ньютона при невязке доли фаз до 0,001; в режиме 3 деление пополам останавливается
при расхождении объёмов 0,02 см³/моль). В режиме 1 критерии автора достаточно жёсткие, поэтому там оба варианта
решаются до сходимости и совпадение с программой автора — до 5–6 значащих цифр.

Модуль в интерфейс программы не подключён (до завершения сверки всей модели 2б с эталоном).
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from . import clathrate as C
from . import co2_brine as B
from . import co2_duan1992 as D

MODEL_REFERENCE = 'Steele-MacInnis M. (2018) Chem. Geol. 498, 31–44, DOI 10.1016/j.chemgeo.2018.08.022'

ROOM_TEMPERATURE_C = 23.5        # «комнатная температура» в программе автора
TH_CO2_MAX_C = D.TC_C            # 31,05 °C
TM_CLATH_MIN_C = -9.92           # границы режима 1 в программе автора
TM_CLATH_MAX_C = 10.0


@dataclass(frozen=True)
class InclusionComposition:
    x_nacl: float                    # валовые мольные доли
    x_co2: float
    x_h2o: float
    salinity_wt_pct: float           # NaCl/(NaCl + H₂O), мас. % (валовая)
    co2_mol_pct_salt_free: float     # CO₂/(CO₂ + H₂O), мол. %
    molar_volume_cm3_mol: float
    density_g_cm3: float
    carbonic_fraction_at_th_co2: float | None   # объёмная доля углекислотной фазы при Th CO₂ (режимы 1, 2)
    salinity_at_tm_clath_wt_pct: float      # солёность раствора при плавлении клатрата
    salinity_at_th_co2_wt_pct: float | None  # солёность раствора при Th CO₂ (режимы 1, 2)
    pressure_at_tm_clath_bar: float
    pressure_at_th_co2_bar: float | None
    numerics: str
    mode: int = 1
    carbonic_fraction_at_tm_clath: float | None = None   # режимы 2, 3
    salinity_at_tm_ice_wt_pct: float | None = None       # режим 3 (точка Q1)
    pressure_at_tm_ice_bar: float | None = None
    model_reference: str = MODEL_REFERENCE


def _num(x, name):
    if isinstance(x, bool):
        raise TypeError(f'{name}: требуется число')
    x = float(x)
    if not isfinite(x):
        raise ValueError(f'{name}: требуется конечное число')
    return x


def _secant(f, x0, x1, tol, what, max_iter=100):
    f0, f1 = f(x0), f(x1)
    for _ in range(max_iter):
        if f1 == f0:
            if abs(f1) < 1e-12:
                return x1
            break
        x2 = x1 - f1 * (x1 - x0) / (f1 - f0)
        if not isfinite(x2):
            break
        x0, f0, x1 = x1, f1, x2
        f1 = f(x1)
        if abs(x1 - x0) <= tol * max(1.0, abs(x1)):
            return x1
    raise ArithmeticError(f'Решение не найдено: {what}')


def _co2_volume_and_lnphi(t, p, numerics):
    if numerics == 'author':
        return D.author_volume_and_lnphi(t, p)
    s = D.state(t, p)
    return s.molar_volume_cm3_mol, s.ln_fugacity_coefficient


class _Q2State:
    """Фазы при плавлении клатрата в точке Q2: раствор + жидкая CO₂ + пар при давлении насыщения CO₂."""
    def __init__(self, t, salinity=None):
        self.t = t
        self.p = D.saturation_pressure_bar(t)
        self.v_liq = D.saturated_liquid_volume(t)
        self.v_vap = D.saturated_vapor_volume(t)
        self.lnphi = D.ln_fugacity_coefficient(t, self.p, self.v_vap)
        self.set_salinity(C.q2_salinity(t) if salinity is None else salinity)

    def set_salinity(self, s):
        self.salinity = s
        aq = B.co2_solubility(self.t, self.p, s, self.lnphi)
        self.x_co2, self.x_nacl, self.x_h2o = aq.x_co2, aq.x_nacl, aq.x_h2o
        self.v_aq = B.aqueous_molar_volume(self.t, self.p, aq.x_co2, aq.x_nacl)
        self.y_vap = B.water_fraction_in_co2(self.t, self.p, aq.x_co2, aq.x_nacl, self.v_vap)
        self.y_liq = B.water_fraction_in_co2(self.t, self.p, aq.x_co2, aq.x_nacl, self.v_liq)

    def phase_fractions(self, mol_nacl, mol_h2o):
        """Объёмные доли (раствор, пар, жидкая CO₂) по балансам NaCl и H₂O (ур. 6–8)."""
        phi_aq = mol_nacl * self.v_aq / self.x_nacl
        phi_vap = ((mol_h2o - phi_aq * self.x_h2o / self.v_aq - (1 - phi_aq) * self.y_liq / self.v_liq)
                   / (self.y_vap / self.v_vap - self.y_liq / self.v_liq))
        return phi_aq, phi_vap, 1 - phi_aq - phi_vap

    def bulk_volume(self, mol_nacl, mol_h2o):
        phi_aq, phi_vap, phi_liq = self.phase_fractions(mol_nacl, mol_h2o)
        return 1 / (phi_aq / self.v_aq + phi_vap / self.v_vap + phi_liq / self.v_liq)      # ур. 9


def _two_phase(t, p, salinity, v_carb, lnphi, phi):
    """Раствор + одна углекислотная фаза: моли компонентов на см³ и молярный объём включения (ур. 2–5)."""
    aq = B.co2_solubility(t, p, salinity, lnphi)
    v_aq = B.aqueous_molar_volume(t, p, aq.x_co2, aq.x_nacl)
    y = B.water_fraction_in_co2(t, p, aq.x_co2, aq.x_nacl, v_carb)
    mol_nacl = (1 - phi) / v_aq * aq.x_nacl
    mol_co2 = phi / v_carb * (1 - y) + (1 - phi) / v_aq * aq.x_co2
    mol_h2o = phi / v_carb * y + (1 - phi) / v_aq * aq.x_h2o
    return mol_nacl, mol_co2, mol_h2o, 1 / (phi / v_carb + (1 - phi) / v_aq), v_aq


def _solve_at_th_co2(q2, th, v_carb, phi):
    """Солёность раствора при Th CO₂ из равенства объёмов включения при Th CO₂ и Tm клатрата."""
    p = D.saturation_pressure_bar(th)
    lnphi = D.ln_fugacity_coefficient(th, p, v_carb)

    def moles(s):
        return _two_phase(th, p, s, v_carb, lnphi, phi)

    if q2.x_nacl == 0:                       # раствор без соли: условие на солёность отсутствует
        s = 0.0
    else:
        def mismatch(s):
            n_nacl, _, n_h2o, v, _ = moles(s)
            return v - q2.bulk_volume(n_nacl, n_h2o)
        s = _secant(mismatch, q2.salinity, q2.salinity * (1 - 1e-4) - 1e-6, 1e-13, 'солёность раствора при Th CO₂')
    n_nacl, n_co2, n_h2o, v, _ = moles(s)
    return s, p, n_nacl, n_co2, n_h2o, v


def _fraction_above_th(t, th, v, n_nacl, n_co2, n_h2o, numerics):
    """Объёмная доля углекислотной фазы при T > Th CO₂ (раствор + одна углекислотная фаза) для заданного состава."""
    total = n_nacl + n_co2 + n_h2o
    x_nacl_tot, x_co2_tot = n_nacl / total, n_co2 / total
    s0 = 100 * n_nacl * B.M_NACL / (n_nacl * B.M_NACL + n_h2o * B.M_H2O)
    state = {'s': s0}

    def at(p, s):
        v_c, lnphi = _co2_volume_and_lnphi(t, p, numerics)
        aq = B.co2_solubility(t, p, s, lnphi)
        v_aq = B.aqueous_molar_volume(t, p, aq.x_co2, aq.x_nacl)
        y = B.water_fraction_in_co2(t, p, aq.x_co2, aq.x_nacl, v_c)
        phi = (v_aq / v - 1) / (v_aq / v_c - 1)
        a = (1 - phi) / v_aq * aq.x_nacl
        b = phi / v_c * (1 - y) + (1 - phi) / v_aq * aq.x_co2
        c = phi / v_c * y + (1 - phi) / v_aq * aq.x_h2o
        return phi, a / (a + b + c), b / (a + b + c)

    def co2_mismatch(p):
        if x_nacl_tot > 0:
            state['s'] = _secant(lambda s: at(p, s)[1] - x_nacl_tot, state['s'], state['s'] * (1 + 1e-4) + 1e-6,
                                 1e-13, 'солёность раствора при температуре оценки φ')
        else:
            state['s'] = 0.0
        state['phi'], _, x_co2 = at(p, state['s'])
        return x_co2 - x_co2_tot

    p0 = D.saturation_pressure_bar(th)
    _secant(co2_mismatch, p0, p0 + 0.01, 1e-12, 'давление при температуре оценки φ')
    return state['phi']


def _fraction_below_th(t, v, n_nacl, n_h2o):
    """Суммарная объёмная доля углекислотных фаз (жидкость + пар) при T ≤ Th CO₂ для заданного состава."""
    st = _Q2State(t, 100 * n_nacl * B.M_NACL / (n_nacl * B.M_NACL + n_h2o * B.M_H2O))
    if n_nacl > 0:
        def mismatch(s):
            st.set_salinity(s)
            return st.bulk_volume(n_nacl, n_h2o) - v
        s = _secant(mismatch, st.salinity, st.salinity * (1 + 1e-4) + 1e-6, 1e-13,
                    'солёность раствора при температуре оценки φ')
        st.set_salinity(s)
        phi_aq, _, _ = st.phase_fractions(n_nacl, n_h2o)
    else:                                    # без соли доля раствора — из баланса воды и объёма
        raise ValueError('Оценка φ ниже Th CO₂ для включения без соли этим алгоритмом не определена')
    return 1 - phi_aq


def mode1(tm_clath_c: float, th_co2_c: float, homogenization_to: str, carbonic_fraction: float,
          fraction_temperature_c: float | None = None, *, numerics: str = 'author') -> InclusionComposition:
    """Режим 1: Tm клатрата ≤ Th CO₂ (клатрат плавится в присутствии жидкой CO₂ и пара).

    homogenization_to — 'liquid' или 'vapor' (направление гомогенизации углекислотных фаз, только явно).
    carbonic_fraction — объёмная доля углекислотных фаз (0…1) при температуре fraction_temperature_c;
    если температура не задана, доля относится к Th CO₂ (как в программе автора).
    numerics: 'author' — коэффициент фугитивности CO₂ вне линии насыщения по вычислительной схеме программы автора
    (для сверки с эталоном); 'exact' — точное решение уравнения Duan.
    """
    tm = _num(tm_clath_c, 'Tm клатрата')
    th = _num(th_co2_c, 'Th CO₂')
    phi_in = _num(carbonic_fraction, 'Доля углекислотных фаз')
    if homogenization_to not in ('liquid', 'vapor'):
        raise ValueError("Направление гомогенизации CO₂ должно быть задано явно: 'liquid' или 'vapor'")
    if numerics not in ('author', 'exact'):
        raise ValueError("numerics: 'author' или 'exact'")
    if not TM_CLATH_MIN_C <= tm <= TM_CLATH_MAX_C:
        raise ValueError(f'Режим 1: Tm клатрата должна быть в пределах {TM_CLATH_MIN_C:g} … {TM_CLATH_MAX_C:g} °C '
                         '(плавление в присутствии жидкой CO₂ и пара)')
    if th > TH_CO2_MAX_C:
        raise ValueError(f'Th CO₂ не может превышать {TH_CO2_MAX_C:g} °C')
    if tm > th:
        raise ValueError('Режим 1 требует Tm клатрата ≤ Th CO₂; иначе это режим 2')
    if not 0 < phi_in < 1:
        raise ValueError('Доля углекислотных фаз должна быть больше 0 и меньше 1')
    t_phi = th if fraction_temperature_c is None else _num(fraction_temperature_c, 'Температура оценки φ')
    if t_phi < tm:
        raise ValueError('Температура оценки φ должна быть не ниже Tm клатрата')

    q2 = _Q2State(tm)
    v_carb = D.saturated_vapor_volume(th) if homogenization_to == 'vapor' else D.saturated_liquid_volume(th)

    def solve(phi_th):
        return _solve_at_th_co2(q2, th, v_carb, phi_th)

    if t_phi == th:
        phi_th = phi_in
    else:
        def mismatch(phi_th):
            _, _, n_nacl, n_co2, n_h2o, v = solve(phi_th)
            if t_phi > th:
                return _fraction_above_th(t_phi, th, v, n_nacl, n_co2, n_h2o, numerics) - phi_in
            return _fraction_below_th(t_phi, v, n_nacl, n_h2o) - phi_in
        first = mismatch(phi_in)
        phi_th = _secant(mismatch, phi_in, phi_in - first, 1e-12, 'доля углекислотной фазы при Th CO₂')
        if not 0 < phi_th < 1:
            raise ArithmeticError('Доля углекислотной фазы при Th CO₂ вышла за пределы 0…1')

    s_th, p_th, n_nacl, n_co2, n_h2o, v = solve(phi_th)
    total = n_nacl + n_co2 + n_h2o
    x_nacl, x_co2, x_h2o = n_nacl / total, n_co2 / total, n_h2o / total
    return InclusionComposition(
        x_nacl=x_nacl, x_co2=x_co2, x_h2o=x_h2o,
        salinity_wt_pct=100 * n_nacl * B.M_NACL / (n_nacl * B.M_NACL + n_h2o * B.M_H2O),
        co2_mol_pct_salt_free=100 * n_co2 / (n_co2 + n_h2o),
        molar_volume_cm3_mol=v,
        density_g_cm3=(x_nacl * B.M_NACL + x_co2 * B.M_CO2 + x_h2o * B.M_H2O) / v,
        carbonic_fraction_at_th_co2=phi_th, salinity_at_tm_clath_wt_pct=q2.salinity,
        salinity_at_th_co2_wt_pct=s_th, pressure_at_tm_clath_bar=q2.p, pressure_at_th_co2_bar=p_th,
        numerics=numerics)


# ====================================================================================================================
# Общие части режимов 2 и 3
# ====================================================================================================================
TM_CLATH_VAPOR_MIN_C = -24.7     # границы программы автора для плавления клатрата в присутствии пара
TM_ICE_MAX_C = C.Q1_T0_C         # −1,48 °C


def _bisect(f, lo, hi, what, tol=1e-13):
    flo, fhi = f(lo), f(hi)
    if flo == 0:
        return lo
    if fhi == 0:
        return hi
    if flo * fhi > 0:
        raise ValueError(f'Решение вне области модели: {what}')
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if flo * fm <= 0:
            hi = mid
        else:
            lo, flo = mid, fm
        if hi - lo <= tol * max(1.0, abs(hi)):
            break
    return 0.5 * (lo + hi)


def _vapor_boundary_salinity_range(tm):
    lo = 0.0 if tm >= C.Q1_T0_C else C.q1_salinity(tm)
    hi = C.q2_salinity(tm) if tm >= C.Q2_T_MIN_C else C.S_MAX_WT_PCT
    return lo, min(hi, C.S_MAX_WT_PCT)


def _boundary_salinity(tm, p, branch):
    """Солёность раствора на границе плавления клатрата при Tm и давлении p (обращение ур. 19–23)."""
    if branch == 'vapor':
        lo, hi = _vapor_boundary_salinity_range(tm)
        return _bisect(lambda x: C.laq_v_c_pressure_bar(tm, x) - p, lo, hi,
                       'давление плавления клатрата вне поверхности «раствор – пар – клатрат»')
    lo = C.q2_salinity(tm) if C.Q2_T_MIN_C <= tm <= C.Q2_T0_C else 0.0
    return _bisect(lambda x: C.laq_lcarb_c_pressure_bar(tm, x) - p, lo, C.S_MAX_WT_PCT,
                   'давление плавления клатрата вне поверхности «раствор – жидкая CO₂ – клатрат»')


def _composition(n_nacl, n_co2, n_h2o, v, numerics, **extra):
    total = n_nacl + n_co2 + n_h2o
    x_nacl, x_co2, x_h2o = n_nacl / total, n_co2 / total, n_h2o / total
    return InclusionComposition(
        x_nacl=x_nacl, x_co2=x_co2, x_h2o=x_h2o,
        salinity_wt_pct=100 * n_nacl * B.M_NACL / (n_nacl * B.M_NACL + n_h2o * B.M_H2O),
        co2_mol_pct_salt_free=100 * n_co2 / (n_co2 + n_h2o), molar_volume_cm3_mol=v,
        density_g_cm3=(x_nacl * B.M_NACL + x_co2 * B.M_CO2 + x_h2o * B.M_H2O) / v, numerics=numerics, **extra)


def _solve_fraction(evaluate, phi_in, tm, t_phi, numerics):
    """Доля углекислотной фазы при Tm клатрата, дающая заданную долю при температуре оценки (режимы 2, 3).

    evaluate(phi) -> (n_nacl, n_co2, n_h2o, v, сведения). 'author' — простая итерация программы автора
    (φ ← φ − (φ расч. − φ задан.), остановка при расхождении 1·10⁻⁷); 'exact' — метод секущих.
    """
    if t_phi == tm:
        return phi_in, evaluate(phi_in)

    def mismatch(phi):
        n_nacl, n_co2, n_h2o, v, _ = evaluate(phi)
        return _fraction_above_th(t_phi, tm, v, n_nacl, n_co2, n_h2o, numerics) - phi_in

    if numerics == 'author':
        phi = phi_in
        for _ in range(60):
            result = evaluate(phi)
            n_nacl, n_co2, n_h2o, v, _ = result
            d = _fraction_above_th(t_phi, tm, v, n_nacl, n_co2, n_h2o, numerics) - phi_in
            if abs(d) < 1e-07:
                return phi, result
            phi -= d
            if not 0 < phi < 1:
                break
        raise ArithmeticError('Итерация программы автора по доле углекислотной фазы не сошлась')
    first = mismatch(phi_in)
    phi = _secant(mismatch, phi_in, phi_in - first, 1e-12, 'доля углекислотной фазы при Tm клатрата')
    if not 0 < phi < 1:
        raise ArithmeticError('Доля углекислотной фазы при Tm клатрата вышла за пределы 0…1')
    return phi, evaluate(phi)


def _check_common(tm, phi_in, t_phi, numerics):
    if numerics not in ('author', 'exact'):
        raise ValueError("numerics: 'author' или 'exact'")
    if not 0 < phi_in < 1:
        raise ValueError('Доля углекислотных фаз должна быть больше 0 и меньше 1')
    if t_phi < tm:
        raise ValueError('Температура оценки φ должна быть не ниже Tm клатрата')


# ====================================================================================================================
# Режим 2
# ====================================================================================================================
def mode2(tm_clath_c: float, th_co2_c: float, homogenization_to: str, carbonic_fraction: float,
          fraction_temperature_c: float | None = None, *, numerics: str = 'author') -> InclusionComposition:
    """Режим 2: Th CO₂ ≤ Tm клатрата (клатрат плавится в присутствии раствора и одной углекислотной фазы).

    Th CO₂ здесь — гомогенизация углекислотных фаз в присутствии клатрата (метастабильно продолженная линия
    насыщения CO₂). carbonic_fraction — объёмная доля углекислотной фазы при температуре fraction_temperature_c;
    если она не задана, доля относится к Tm клатрата (как в программе автора).

    Неизвестное давление плавления клатрата находится из условий (ур. 1, 4, 6 статьи): при Tm клатрата солёность
    раствора лежит на границе устойчивости клатрата при этом давлении; при Th CO₂ балансы NaCl и H₂O дают одну и ту
    же долю углекислотной фазы, и она согласуется с объёмом включения.
    """
    tm = _num(tm_clath_c, 'Tm клатрата')
    th = _num(th_co2_c, 'Th CO₂')
    phi_in = _num(carbonic_fraction, 'Доля углекислотных фаз')
    if homogenization_to not in ('liquid', 'vapor'):
        raise ValueError("Направление гомогенизации CO₂ должно быть задано явно: 'liquid' или 'vapor'")
    t_phi = tm if fraction_temperature_c is None else _num(fraction_temperature_c, 'Температура оценки φ')
    _check_common(tm, phi_in, t_phi, numerics)
    if th > TH_CO2_MAX_C:
        raise ValueError(f'Th CO₂ не может превышать {TH_CO2_MAX_C:g} °C')
    if tm < th:
        raise ValueError('Режим 2 требует Tm клатрата ≥ Th CO₂; иначе это режим 1')
    if homogenization_to == 'vapor' and not TM_CLATH_VAPOR_MIN_C <= tm <= TM_CLATH_MAX_C:
        raise ValueError(f'Режим 2, гомогенизация в пар: Tm клатрата {TM_CLATH_VAPOR_MIN_C:g} … {TM_CLATH_MAX_C:g} °C')
    if homogenization_to == 'liquid' and tm < TM_CLATH_MIN_C:
        raise ValueError(f'Режим 2, гомогенизация в жидкость: Tm клатрата не ниже {TM_CLATH_MIN_C:g} °C')

    vapor = homogenization_to == 'vapor'
    p_th = D.saturation_pressure_bar(th)
    v_th = D.saturated_vapor_volume(th) if vapor else D.saturated_liquid_volume(th)
    lnphi_th = D.ln_fugacity_coefficient(th, p_th, v_th)
    p_sat_tm = D.saturation_pressure_bar(tm) if tm <= D.TC_C else None
    v_sat_vap_tm = D.saturated_vapor_volume(tm) if tm <= D.TC_C else None
    s_guess = [None]

    def clamp(p):
        if p_sat_tm is not None:
            p = min(p, p_sat_tm) if vapor else max(p, p_sat_tm)
        return max(p, p_th)

    def at_pressure(p, phi):
        """Невязка доли углекислотной фазы при Th CO₂ (ур. 6 против ур. 1) и состав при давлении плавления p."""
        s_tm = _boundary_salinity(tm, p, homogenization_to)
        v_c, lnphi = _co2_volume_and_lnphi(tm, p, numerics)
        if v_sat_vap_tm is not None:                         # ограничения программы автора
            v_c = max(v_c, v_sat_vap_tm) if vapor else min(v_c, v_sat_vap_tm)
        n_nacl, n_co2, n_h2o, v, _ = _two_phase(tm, p, s_tm, v_c, lnphi, phi)
        if n_nacl <= 0:
            raise ValueError('Режим 2 для раствора без соли этим алгоритмом не определён')

        def th_state(sal):
            aq = B.co2_solubility(th, p_th, sal, lnphi_th)
            v_aq = B.aqueous_molar_volume(th, p_th, aq.x_co2, aq.x_nacl)
            y = B.water_fraction_in_co2(th, p_th, aq.x_co2, aq.x_nacl, v_th)
            by_nacl = 1 - n_nacl * v_aq / aq.x_nacl                                        # ур. 6
            by_h2o = (n_h2o - aq.x_h2o / v_aq) / (y / v_th - aq.x_h2o / v_aq)              # ур. 4
            return by_nacl, by_h2o, v_aq

        start = s_guess[0] if s_guess[0] is not None else s_tm
        s_th = _secant(lambda x: th_state(x)[0] - th_state(x)[1], start, start * (1 + 1e-4) + 1e-6, 1e-13,
                       'солёность раствора при Th CO₂')
        s_guess[0] = s_th
        by_nacl, _, v_aq = th_state(s_th)
        by_volume = (v_aq / v - 1) / (v_aq / v_th - 1)                                     # ур. 1
        return by_nacl - by_volume, (n_nacl, n_co2, n_h2o, v, (p, s_tm, s_th, by_nacl))

    def evaluate(phi):
        p = clamp(D.pressure_bar(tm, v_th))                  # начальное приближение: изохора CO₂ от Th CO₂
        if numerics == 'author':
            # метод Ньютона программы автора: шаг 1·10⁻⁴ бар, остановка при невязке ≤ 0,001; результат —
            # в последней вычисленной точке (до заключительного уточнения давления)
            for _ in range(200):
                f0, _ = at_pressure(p, phi)
                p = p + 0.0001
                f1, result = at_pressure(p, phi)
                p = clamp(p - f1 / ((f1 - f0) / 0.0001))
                if abs(f1) <= 0.001:
                    return result
            raise ArithmeticError('Итерация программы автора по давлению плавления клатрата не сошлась')
        p = _secant(lambda x: at_pressure(x, phi)[0], p, p + 0.01, 1e-12, 'давление плавления клатрата')
        if clamp(p) != p:
            raise ValueError('Давление плавления клатрата вышло за границу режима 2 (проверьте, не режим ли это 1)')
        return at_pressure(p, phi)[1]

    phi_tm, (n_nacl, n_co2, n_h2o, v, (p_tm, s_tm, s_th, phi_th)) = _solve_fraction(evaluate, phi_in, tm, t_phi,
                                                                                    numerics)
    return _composition(n_nacl, n_co2, n_h2o, v, numerics, mode=2, carbonic_fraction_at_th_co2=phi_th,
                        salinity_at_tm_clath_wt_pct=s_tm, salinity_at_th_co2_wt_pct=s_th,
                        pressure_at_tm_clath_bar=p_tm, pressure_at_th_co2_bar=p_th,
                        carbonic_fraction_at_tm_clath=phi_tm)


# ====================================================================================================================
# Режим 3
# ====================================================================================================================
def mode3(tm_ice_c: float, tm_clath_c: float, carbonic_fraction: float,
          fraction_temperature_c: float | None = None, *, numerics: str = 'author') -> InclusionComposition:
    """Режим 3: жидкой CO₂ нет; Tm льда (в присутствии клатрата, раствора и пара — точка Q1) ≤ Tm клатрата.

    carbonic_fraction — объёмная доля пара при температуре fraction_temperature_c; если она не задана, доля
    относится к Tm клатрата. Солёность раствора при Tm клатрата находится из равенства объёмов включения при
    Tm клатрата (раствор + пар) и при Tm льда (раствор + пар + клатрат; ур. 6, 10–12 статьи).
    """
    t_ice = _num(tm_ice_c, 'Tm льда')
    tm = _num(tm_clath_c, 'Tm клатрата')
    phi_in = _num(carbonic_fraction, 'Доля углекислотных фаз')
    t_phi = tm if fraction_temperature_c is None else _num(fraction_temperature_c, 'Температура оценки φ')
    _check_common(tm, phi_in, t_phi, numerics)
    if not TM_CLATH_VAPOR_MIN_C <= t_ice <= TM_ICE_MAX_C:
        raise ValueError(f'Режим 3: Tm льда должна быть в пределах {TM_CLATH_VAPOR_MIN_C:g} … {TM_ICE_MAX_C:g} °C')
    if not TM_CLATH_VAPOR_MIN_C <= tm <= TM_CLATH_MAX_C:
        raise ValueError(f'Режим 3: Tm клатрата должна быть в пределах {TM_CLATH_VAPOR_MIN_C:g} … {TM_CLATH_MAX_C:g} °C')
    if tm < t_ice:
        raise ValueError('Режим 3 требует Tm клатрата ≥ Tm льда')

    # фазы в точке Q1 (Tm льда): раствор, пар, клатрат
    s_ice, p_ice = C.q1_salinity(t_ice), C.q1_pressure_bar(t_ice)
    v_vap_ice, lnphi_ice = _co2_volume_and_lnphi(t_ice, p_ice, numerics)
    aq_ice = B.co2_solubility(t_ice, p_ice, s_ice, lnphi_ice)
    v_aq_ice = B.aqueous_molar_volume(t_ice, p_ice, aq_ice.x_co2, aq_ice.x_nacl)
    y_ice = B.water_fraction_in_co2(t_ice, p_ice, aq_ice.x_co2, aq_ice.x_nacl, v_vap_ice)
    clath = C.clathrate_composition(t_ice, p_ice, lnphi_ice, 1 - y_ice)
    v_clath = C.clathrate_molar_volume(t_ice, p_ice, clath.x_h2o)
    lo0, hi0 = _vapor_boundary_salinity_range(tm)

    def at_salinity(sal, phi):
        p = C.laq_v_c_pressure_bar(tm, sal)
        v_c, lnphi = _co2_volume_and_lnphi(tm, p, numerics)
        n_nacl, n_co2, n_h2o, v, _ = _two_phase(tm, p, sal, v_c, lnphi, phi)
        if n_nacl < 1e-10:
            return 0.0, 1.0, (n_nacl, n_co2, n_h2o, v, (p, sal))
        phi_liq = n_nacl * v_aq_ice / aq_ice.x_nacl                                            # ур. 6
        phi_vap = ((n_h2o - phi_liq * aq_ice.x_h2o / v_aq_ice - (1 - phi_liq) * clath.x_h2o / v_clath)
                   / (y_ice / v_vap_ice - clath.x_h2o / v_clath))                              # ур. 10
        v_at_ice = 1 / (phi_liq / v_aq_ice + phi_vap / v_vap_ice + (1 - phi_liq - phi_vap) / v_clath)   # ур. 12
        return v - v_at_ice, phi_vap, (n_nacl, n_co2, n_h2o, v, (p, sal))

    def evaluate(phi):
        lo, hi = lo0, hi0
        tol = 0.02 if numerics == 'author' else 1e-10          # 0,02 см³/моль — критерий программы автора
        result = None
        for _ in range(200):
            sal = 0.5 * (lo + hi)
            dv, phi_vap, result = at_salinity(sal, phi)
            if abs(dv) <= tol:
                return result
            if phi_vap < 0 or dv > 0:
                lo = sal
            else:
                hi = sal
            if hi - lo < 1e-13:
                if numerics == 'exact' and abs(dv) < 1e-6:
                    return result
                break
        raise ValueError('Режим 3: решение не найдено — сочетание Tm льда, Tm клатрата и φ вне области модели')

    phi_tm, (n_nacl, n_co2, n_h2o, v, (p_tm, s_tm)) = _solve_fraction(evaluate, phi_in, tm, t_phi, numerics)
    if p_tm > D.saturation_pressure_bar(tm):
        raise ValueError('Режим 3: давление плавления клатрата выше давления насыщения CO₂ (вне области режима)')
    return _composition(n_nacl, n_co2, n_h2o, v, numerics, mode=3, carbonic_fraction_at_th_co2=None,
                        salinity_at_tm_clath_wt_pct=s_tm, salinity_at_th_co2_wt_pct=None,
                        pressure_at_tm_clath_bar=p_tm, pressure_at_th_co2_bar=None,
                        carbonic_fraction_at_tm_clath=phi_tm, salinity_at_tm_ice_wt_pct=s_ice,
                        pressure_at_tm_ice_bar=p_ice)
