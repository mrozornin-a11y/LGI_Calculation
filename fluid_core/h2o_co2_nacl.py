"""Состав и плотность включений H₂O–CO₂–NaCl по микротермометрии (этап 2б, часть 4; пока только режим 1).

Алгоритм статьи Steele-MacInnis (2018), Chem. Geol. 498, 31–44, разд. 3.1, перенесённый из процедур MODE1 и
Phi_at_T программы автора. Режим 1: клатрат плавится раньше гомогенизации углекислотных фаз (Tm клатрата ≤ Th CO₂),
то есть в присутствии водного раствора, жидкой CO₂ и пара (точка Q2).

Входные данные: Tm клатрата, Th CO₂ с направлением гомогенизации, объёмная доля углекислотных фаз φ и температура,
при которой она оценена. Результат: валовый состав (мольные доли), солёность, молярный объём и плотность включения.

Условия, из которых находится решение (ур. 2–9 статьи):
  1. при Th CO₂ включение состоит из водного раствора и одной углекислотной фазы с объёмом насыщенной жидкости
     (гомогенизация в жидкость) или насыщенного пара (в пар); давление — давление насыщения CO₂;
  2. при Tm клатрата раствор имеет солёность точки Q2, сосуществуют раствор, жидкая CO₂ и пар; балансы NaCl и H₂O
     задают доли фаз;
  3. объём включения при Th CO₂ и при Tm клатрата одинаков — отсюда солёность раствора при Th CO₂;
  4. если φ оценена не при Th CO₂, доля при Th CO₂ подбирается так, чтобы рассчитанная доля при температуре
     оценки совпала с заданной.

Составные модели — модули `co2_duan1992`, `clathrate`, `co2_brine`. Уравнения решаются методом секущих до
сходимости; программа автора использует метод Ньютона с более грубыми критериями остановки, поэтому совпадение
с её результатами ожидается до 4–6 значащих цифр, а не до машинной точности.

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
    carbonic_fraction_at_th_co2: float      # объёмная доля углекислотной фазы при Th CO₂
    salinity_at_tm_clath_wt_pct: float      # солёность раствора при плавлении клатрата (точка Q2)
    salinity_at_th_co2_wt_pct: float        # солёность раствора при Th CO₂
    pressure_at_tm_clath_bar: float
    pressure_at_th_co2_bar: float
    numerics: str
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
