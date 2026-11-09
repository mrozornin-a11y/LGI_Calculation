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
