"""Проверка моделей этапов 1–2a по эталонным расчётам программ авторов и независимым данным.

* HOKIEFLINCS_H2O-NACL (Steele-MacInnis et al., 2012), прогон в Excel пользователем → проверка ПЕРЕНОСА формул
  в fluid_core/h2o_nacl.py (класс reference_model_output; не независимая проверка модели).
* Предел чистой воды (S → 0) против IAPWS-95 (CoolProp) → независимая характеристика корреляций Atkinson (2002)
  и Bodnar (1983); отклонения фиксируются, а не «подгоняются».
* Упрощённая плотность этапа 1 (объёмный баланс) против строгой модели Steele-MacInnis (2018), прогон в Excel
  пользователем → характеристика систематической ошибки упрощения.
"""
from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass, field

from .checkpoints import HERE

HOKIE_CSV = HERE / 'data' / 'hokieflincs_oracle.csv'
SM2018_CSV = HERE / 'data' / 'sm2018_oracle.csv'
TRANSCRIPTION_REL_TOL = 1e-9     # те же формулы и коэффициенты: допускается только машинное округление
NEAR_CRITICAL_WARN_C = 30.0      # см. fluid_app.calc: предупреждение о плотности у критической точки


def _f(x):
    return None if x in ('', None) else float(x)


@dataclass
class OracleRow:
    case: str
    status: str                      # PASS | FAIL | SKIPPED
    deviations: dict = field(default_factory=dict)   # величина -> относительное отклонение
    reason: str = ''


def evaluate_hokieflincs() -> list[OracleRow]:
    from fluid_core.h2o_nacl import homogenization_to_liquid
    from fluid_core.salinity import bodnar_1993
    out = []
    with open(HOKIE_CSV, encoding='utf-8', newline='') as fh:
        for r in csv.DictReader(fh):
            if r['phase'] != 'ice':
                out.append(OracleRow(r['case'], 'SKIPPED', reason='гомогенизация с галитом в FluidCalc не реализована'))
                continue
            s = bodnar_1993(float(r['Tm'])).salinity_wt_pct_nacl_eq
            res = homogenization_to_liquid(float(r['Th']), s, homogenization_to='liquid')
            dev = {'salinity': s / float(r['wt_pct_NaCl']) - 1, 'Ph': res.pressure_bar / float(r['Ph_bar']) - 1,
                   'rho': res.density_g_cm3 / float(r['rho_g_cm3']) - 1,
                   'dPdT': res.slope_bar_per_c / float(r['dPdT_bar_C']) - 1}
            if r['trap_basis'].startswith('temperature'):
                dev['P_trap'] = res.pressure_at(float(r['trap_value'])) / float(r['P_trap_bar']) - 1
            elif r['trap_basis'].startswith('pressure'):
                dev['T_trap'] = res.temperature_at(float(r['trap_value'])) / float(r['T_trap_C']) - 1
            ok = all(abs(d) <= TRANSCRIPTION_REL_TOL for d in dev.values())
            out.append(OracleRow(r['case'], 'PASS' if ok else 'FAIL', dev))
    return out


@dataclass
class WaterRow:
    th_c: float
    p_model: float
    p_iapws: float
    rho_model: float
    rho_iapws: float

    @property
    def dp_pct(self):
        return 100 * (self.p_model / self.p_iapws - 1)

    @property
    def drho_pct(self):
        return 100 * (self.rho_model / self.rho_iapws - 1)

    @property
    def near_critical(self):
        return 373.946 - self.th_c < NEAR_CRITICAL_WARN_C


WATER_GRID_C = (50.0, 100.0, 150.0, 200.0, 250.0, 300.0, 320.0, 340.0, 350.0, 360.0, 370.0)


def evaluate_pure_water() -> list[WaterRow]:
    from CoolProp.CoolProp import PropsSI
    from fluid_core.h2o_nacl import homogenization_pressure_bar, liquid_density_g_cm3
    rows = []
    for th in WATER_GRID_C:
        t = th + 273.15
        rows.append(WaterRow(th, homogenization_pressure_bar(th, 0.0), PropsSI('P', 'T', t, 'Q', 0, 'Water') / 1e5,
                             liquid_density_g_cm3(th, 0.0), PropsSI('Dmass', 'T', t, 'Q', 0, 'Water') / 1000))
    return rows


@dataclass
class Stage1Row:
    case: str
    tm_clath: float
    th_co2: float
    branch: str
    phi_pct: float
    rho_stage1: float
    rho_sm2018: float
    s_darling: float
    s_sm2018: float

    @property
    def dev_pct(self):
        return 100 * (self.rho_stage1 / self.rho_sm2018 - 1)


def evaluate_stage1_vs_sm2018() -> list[Stage1Row]:
    """Режим 1 с φ при комнатной температуре: условия, при которых применим объёмный баланс этапа 1."""
    from fluid_app import calc
    rows = []
    with open(SM2018_CSV, encoding='utf-8', newline='') as fh:
        for r in csv.DictReader(fh):
            if not r['mode'].startswith('1)') or not r['PhiVap_pct']:
                continue
            phi = float(r['PhiVap_pct']) / 100
            props = dict(carbonic_fraction=phi, carbonic_fraction_unc=None, carbonic_fraction_method=None,
                         carbonic_fraction_temp_c=None, inclusion_id=1, inclusion_name='x', sample_name='s',
                         project_name='p', uncertainty_c=None, liquid_co2_present=None, vapor_co2_present=None,
                         aqueous_brine_present=None, co2_purity_confirmed=None, homogenization_to=None)
            obs = [dict(props, kind='Th_CO2', temperature_c=float(r['Th_CO2']), co2_purity_confirmed=True,
                        homogenization_to='liquid' if r['homog_to'] == 'L' else 'vapor'),
                   dict(props, kind='Tm_clath', temperature_c=float(r['Tm_clath']), liquid_co2_present=True,
                        vapor_co2_present=True, aqueous_brine_present=True)]
            items = calc.calculate_all(obs)
            o = next(o for _, o in items if o.kind == 'bulk_density')
            if o.status != 'ok':
                raise RuntimeError(f'{r["case"]}: {o.message}')
            rows.append(Stage1Row(r['case'], float(r['Tm_clath']), float(r['Th_CO2']), r['homog_to'],
                                  float(r['PhiVap_pct']), o.value, float(r['rho_g_cm3']), o.extras['salinity_wt_pct'],
                                  float(r['wt_pct_NaCl'])))
    return rows


def stage1_statistics(rows: list[Stage1Row]) -> dict:
    d = [r.dev_pct for r in rows]
    ds = [abs(r.s_darling - r.s_sm2018) for r in rows]
    return {'n': len(d), 'min': min(d), 'max': max(d), 'mean': statistics.mean(d), 'max_abs_dS': max(ds)}


# --- Этап 2б, часть 1: чистая CO₂ по Duan et al. (1992a) против Span & Wagner (1996) -------------------------------
CO2_GRID_T_C = (-20.0, -10.0, 0.0, 10.0, 20.0, 30.0, 50.0, 100.0, 200.0, 300.0, 400.0, 500.0, 700.0, 1000.0)
CO2_GRID_P_BAR = (10.0, 50.0, 100.0, 200.0, 500.0, 1000.0, 2000.0, 3000.0, 5000.0, 8000.0)
CO2_SAT_GRID_C = (-20.0, -10.0, 0.0, 10.0, 20.0, 25.0, 28.0, 30.0)


@dataclass
class Co2Row:
    t_c: float
    p_bar: float
    phase: str
    v_duan: float
    v_sw: float
    lnphi_duan: float
    lnphi_sw: float
    v_author: float | None           # None — схема программы автора не сошлась
    lnphi_author: float | None

    @property
    def dv_pct(self):
        return 100 * (self.v_duan / self.v_sw - 1)

    @property
    def dphi_pct(self):
        from math import exp
        return 100 * (exp(self.lnphi_duan - self.lnphi_sw) - 1)

    @property
    def author_dphi_pct(self):
        """Сдвиг φ в схеме программы автора относительно точного значения того же уравнения, %."""
        from math import exp
        return None if self.lnphi_author is None else 100 * (exp(self.lnphi_author - self.lnphi_duan) - 1)

    @property
    def author_same_root(self):
        return self.v_author is not None and abs(self.v_author / self.v_duan - 1) < 1e-8


def _span_wagner_state(t_c: float, p_bar: float):
    """(V, см³/моль; ln φ) чистой CO₂ по Span & Wagner (1996) через CoolProp; None ниже кривой плавления."""
    import CoolProp
    from math import log
    st = CoolProp.AbstractState('HEOS', 'CO2')
    try:
        st.update(CoolProp.PT_INPUTS, p_bar * 1e5, t_c + 273.15)
    except ValueError:
        return None
    z = st.compressibility_factor()
    return st.molar_mass() / st.rhomass() * 1e6, st.alphar() + z - 1 - log(z)


def evaluate_co2_duan1992() -> list[Co2Row]:
    from fluid_core import co2_duan1992 as D
    rows = []
    for t in CO2_GRID_T_C:
        for p in CO2_GRID_P_BAR:
            ref = _span_wagner_state(t, p)
            if ref is None:
                continue
            s = D.state(t, p)
            try:
                va, la = D.author_volume_and_lnphi(t, p)
            except ArithmeticError:
                va = la = None
            rows.append(Co2Row(t, p, s.phase, s.molar_volume_cm3_mol, ref[0], s.ln_fugacity_coefficient, ref[1],
                               va, la))
    return rows


def co2_statistics(rows: list[Co2Row]) -> dict:
    """Наибольшие отклонения по областям: заявленная (0–1000 °C) и экстраполяция (< 0 °C)."""
    def mx(sel, attr):
        vals = [abs(getattr(r, attr)) for r in rows if sel(r) and getattr(r, attr) is not None]
        return max(vals) if vals else None
    core = lambda r: 0 <= r.t_c <= 500 and r.p_bar <= 3000 and not (r.t_c == 30 and r.p_bar == 50)   # noqa: E731
    return {'n': len(rows),
            'core_dv': mx(core, 'dv_pct'), 'core_dphi': mx(core, 'dphi_pct'),
            'all_dv': mx(lambda r: r.t_c >= 0, 'dv_pct'), 'all_dphi': mx(lambda r: r.t_c >= 0, 'dphi_pct'),
            'cold_dv': mx(lambda r: r.t_c < 0, 'dv_pct'), 'cold_dphi': mx(lambda r: r.t_c < 0, 'dphi_pct'),
            'author_liquid_dphi': mx(lambda r: r.phase == 'liquid' and r.author_same_root, 'author_dphi_pct'),
            'author_other_root': [(r.t_c, r.p_bar) for r in rows if not r.author_same_root]}


@dataclass
class Co2SatRow:
    t_c: float
    p_eq: float
    p_sw: float
    vl_eq: float
    vl_sw: float
    vv_eq: float
    vv_sw: float
    p_duan_liquid: float            # давление уравнения Duan при объёме насыщенной жидкости (ур. 14)
    p_duan_vapor: float             # то же при объёме насыщенного пара (ур. 15)
    lnphi_liquid: float
    lnphi_vapor: float


def evaluate_co2_saturation() -> list[Co2SatRow]:
    from CoolProp.CoolProp import PropsSI
    from fluid_core import co2_duan1992 as D
    rows = []
    for t in CO2_SAT_GRID_C:
        k = t + 273.15
        m = PropsSI('M', 'CO2') * 1e3
        p, vl, vv = D.saturation_pressure_bar(t), D.saturated_liquid_volume(t), D.saturated_vapor_volume(t)
        rows.append(Co2SatRow(t, p, PropsSI('P', 'T', k, 'Q', 0, 'CO2') / 1e5,
                              vl, m / PropsSI('Dmass', 'T', k, 'Q', 0, 'CO2') * 1e3,
                              vv, m / PropsSI('Dmass', 'T', k, 'Q', 1, 'CO2') * 1e3,
                              D.pressure_bar(t, vl), D.pressure_bar(t, vv),
                              D.ln_fugacity_coefficient(t, p, vl), D.ln_fugacity_coefficient(t, p, vv)))
    return rows


DUAN_TABLE5_CSV = HERE / 'data' / 'duan1992_table5.csv'
BAKKER_TABLE4_CSV = HERE / 'data' / 'bakker1996_table4.csv'
PUBLISHED_TABLE_REL_TOL = 5e-4      # таблица Duan et al. (1992a) напечатана с 4 значащими цифрами


def _data_rows(path):
    with open(path, encoding='utf-8', newline='') as fh:
        return list(csv.reader(line for line in fh if not line.startswith('#')))


def evaluate_duan_table5() -> list[tuple[float, float, float, float]]:
    """(T, P, φ из табл. 5 статьи, φ модуля): проверка переноса коэффициентов по первоисточнику."""
    from math import exp
    from fluid_core import co2_duan1992 as D
    rows = _data_rows(DUAN_TABLE5_CSV)
    temps = [float(x) for x in rows[0][1:]]
    return [(t, float(r[0]), float(x), exp(D.state(t, float(r[0])).ln_fugacity_coefficient))
            for r in rows[1:] for t, x in zip(temps, r[1:])]


# --- Этап 2б, часть 2: границы устойчивости клатрата против Bakker et al. (1996) ----------------------------------
@dataclass
class ClathrateBoundaryRow:
    salinity: float
    element: str                     # Q1 | Q2 | HLwGc | HLwLc
    t_c: float                       # температура из таблицы Bakker
    p_bar: float                     # давление из таблицы Bakker
    t_chen_c: float | None           # Q2: температура по Chen (1972b)
    t_model_c: float | None          # Q1, Q2: температура точки; HLwLc: температура модели при давлении Bakker
    p_model_bar: float               # давление модели (Q1, Q2 — в точке модели; иначе при температуре Bakker)

    @property
    def dt(self):
        return None if self.t_model_c is None else self.t_model_c - self.t_c

    @property
    def dp_pct(self):
        return 100 * (self.p_model_bar / self.p_bar - 1)


def evaluate_clathrate_boundaries() -> list[ClathrateBoundaryRow]:
    from fluid_core import clathrate as C
    rows = _data_rows(BAKKER_TABLE4_CSV)
    out = []
    for r in (dict(zip(rows[0], x)) for x in rows[1:]):
        s, t, p, e = float(r['wt_pct_NaCl']), float(r['T_K']) - 273.15, float(r['P_MPa']) * 10, r['element']
        chen = float(r['T_chen_K']) - 273.15 if r['T_chen_K'] else None
        if e == 'Q1':
            tm = C.q1_temperature_c(s)
            pm = C.q1_pressure_bar(tm)
        elif e == 'Q2':
            tm = C.q2_temperature_c(s)
            pm = C.q2_pressure_bar(tm)
        elif e == 'HLwGc':
            tm, pm = None, C.laq_v_c_pressure_bar(t, s)
        else:
            tq2 = C.q2_temperature_c(s)
            tm = tq2 + (p - C.q2_pressure_bar(tq2)) / C.laq_lcarb_c_slope_bar_per_c(s)
            pm = C.laq_lcarb_c_pressure_bar(t, s)
        out.append(ClathrateBoundaryRow(s, e, t, p, chen, tm, pm))
    return out


def clathrate_boundary_statistics(rows: list[ClathrateBoundaryRow]) -> dict:
    def sel(e):
        return [r for r in rows if r.element == e]
    lc = sel('HLwLc')
    return {'q1_dt': max(abs(r.dt) for r in sel('Q1')), 'q1_dp_pct': max(abs(r.dp_pct) for r in sel('Q1')),
            'q2_dt_bakker': max(abs(r.dt) for r in sel('Q2')),
            'q2_dt_chen': max(abs(r.t_model_c - r.t_chen_c) for r in sel('Q2') if r.t_chen_c is not None),
            'q2_dp_pct': max(abs(r.dp_pct) for r in sel('Q2')),
            'gc_dp_pct': max(abs(r.dp_pct) for r in sel('HLwGc')),
            'lc_dt_to_1kbar': max(abs(r.dt) for r in lc if r.p_bar <= 1000),
            'lc_dt_above_1kbar': max(abs(r.dt) for r in lc if r.p_bar > 1000)}


def evaluate_clathrate_properties() -> list[tuple]:
    """Состав и плотность клатрата на кривой «раствор – пар – клатрат» без соли (характерные значения)."""
    from fluid_core import clathrate as C, co2_duan1992 as D
    out = []
    for t in (-1.48, 0.0, 2.0, 4.0, 6.0, 8.0, 9.9):
        p = C.laq_v_c_pressure_bar(t, 0.0)
        comp = C.clathrate_composition(t, p, D.state(t, p).ln_fugacity_coefficient)
        out.append((t, p, comp, C.clathrate_molar_volume(t, p, comp.x_h2o), C.clathrate_density_g_cm3(t, p, comp)))
    return out
