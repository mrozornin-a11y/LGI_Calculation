"""Проверка ядра по калибровочным экспериментальным данным (Hall 1988, Chen 1972) и по NIST WebBook.

Формулы ядра не дублируются: значения и производные (для переноса ошибки температуры) получаются
вызовами fluid_core. Для солевых уравнений применяются ДВА РАЗДЕЛЬНЫХ критерия, которые не сводятся
к одному общему PASS:

* регрессионный (regression) — соответствует ли расчёт заявленному авторами уравнения качеству
  аппроксимации своих калибровочных данных: PASS / FAIL / OUTSIDE_DOMAIN;
* экспериментальная совместимость (experimental) — укладывается ли отклонение в линейный конверт
  оценок ошибки, приведённых в источнике: COMPATIBLE / INCOMPATIBLE / OUTSIDE_DOMAIN.

Оценки ошибок со знаком «±» из источников не являются стандартными неопределённостями: уровень
доверия в источниках не задан. Критерии и допуски взяты из аудита 2026-11-09 без изменения.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .checkpoints import HERE, app_value

DATA = HERE / 'data'
AUDIT_DIR = HERE / 'sources' / 'audit_2026-11-09'
HALL_CSV = DATA / 'hall1988_bodnar.csv'
CHEN_CSV = DATA / 'chen1972_darling.csv'
NIST_TSV = AUDIT_DIR / 'nist_co2_raw.tsv'
KNOWN_CSV = HERE / 'known_discrepancies.csv'

NIST_URL = ('https://webbook.nist.gov/cgi/fluid.cgi?Action=Data&Wide=on&ID=C124389&Type=SatP&Digits=8'
            '&TLow=223.15&THigh=303.15&TInc=10&TUnit=K&PUnit=bar&DUnit=kg%2Fm3')
NIST_SOURCE = 'NIST Chemistry WebBook, SRD 69, насыщение CO₂; выгрузка 2026-11-09'
NIST_COLUMNS = (('pressure', 'Pressure (bar)', 'bar'),
                ('liquid_density', 'Density (l, kg/m3)', 'kg_m3'),
                ('vapor_density', 'Density (v, kg/m3)', 'kg_m3'))

EVIDENCE_RU = {
    'experiment_reproduced_in_compilation': 'эксперимент, воспроизведённый в авторитетной компиляции',
    'experiment': 'эксперимент первоисточника',
    'reference_table': 'точная справочная выгрузка',
}
INDEPENDENCE_RU = {
    'calibration_data': 'калибровочные данные модели: независимы от кода, но использованы при построении уравнения',
    'external_implementation_model_not_independently_verified':
        'внешняя реализация; независимость модели WebBook от CoolProp не установлена',
}

# Критерии аудита 2026-11-09 (validation/sources/audit_2026-11-09/README_RU.md), без изменений.
HALL_REGRESSION = dict(base=0.05, rounding=0.005, t_err=0.005)     # 0.05 + 0.005 + |dS/dT|·0.005
HALL_EXPERIMENT = dict(base=0.02, rounding=0.005, t_err=0.055)     # 0.02 + 0.005 + |dS/dT|·(0.05+0.005)
CHEN_REGRESSION = dict(rel=0.0561, rounding=0.005, t_err=0.005)    # 0.0561·S + 0.005 + |dS/dT|·0.005
CHEN_EXPERIMENT = dict(rel=0.01, rounding=0.005, t_err=0.030)      # 0.01·S + 0.005 + |dS/dT|·(0.025+0.005)


def _bodnar(t):
    from fluid_core.salinity import bodnar_1993
    return bodnar_1993(t).salinity_wt_pct_nacl_eq


def _darling(t):
    from fluid_core.salinity import darling_1991
    return darling_1991(t, liquid_co2_present=True, vapor_co2_present=True,
                        aqueous_brine_present=True).salinity_wt_pct_nacl_eq


def slope(fn, t: float, h: float = 1e-5) -> float:
    """|dS/dT| численно по функции ядра — только для переноса ошибки температуры в допуск.

    Если точка T ± h вне области ядра, используется односторонняя разность. Строки вне области
    ядра не оцениваются, производная для них не нужна.
    """
    try:
        return abs((fn(t + h) - fn(t - h)) / (2 * h))
    except ValueError:
        try:
            return abs((fn(t) - fn(t - h)) / h)
        except ValueError:
            return abs((fn(t + h) - fn(t)) / h)


@dataclass
class SalinityRow:
    dataset: str
    id: str
    temperature_c: float
    expected: float
    role: str
    meta: dict
    computed: float | None = None
    slope: float | None = None
    regression_tol: float | None = None
    experimental_tol: float | None = None
    regression: str = ''          # PASS | FAIL | OUTSIDE_DOMAIN
    experimental: str = ''        # COMPATIBLE | INCOMPATIBLE | OUTSIDE_DOMAIN
    reason: str = ''
    app_consistent: bool | None = None

    @property
    def deviation(self):
        return None if self.computed is None else self.computed - self.expected

    @property
    def rel_pct(self):
        if self.computed is None or self.expected == 0:
            return None
        return 100.0 * (self.computed - self.expected) / self.expected


def _ru(message: str) -> str:
    try:
        from fluid_app.methods import translate_core_message
    except ImportError:
        return message
    return translate_core_message(message)


def _read(path: Path) -> list[dict]:
    with open(path, encoding='utf-8', newline='') as fh:
        return list(csv.DictReader(fh))


def _evaluate_salinity(dataset, rows, fn, method, reg, exp):
    out = []
    for r in rows:
        t = float(r['temperature_c'])
        s = float(r['expected_wt_pct'])
        row = SalinityRow(dataset, r['id'], t, s, r.get('role', 'experiment'), r)
        try:
            row.computed = fn(t) + 0.0
        except ValueError as exc:
            row.regression = row.experimental = 'OUTSIDE_DOMAIN'
            row.reason = (f'Вне области применимости ядра: {_ru(str(exc))} (ядро: «{exc}»). '
                          'Строка сохранена без экстраполяции.')
            out.append(row)
            continue
        row.slope = slope(fn, t)
        if 'base' in reg:
            row.regression_tol = reg['base'] + reg['rounding'] + row.slope * reg['t_err']
            row.experimental_tol = exp['base'] + exp['rounding'] + row.slope * exp['t_err']
        else:
            row.regression_tol = reg['rel'] * s + reg['rounding'] + row.slope * reg['t_err']
            row.experimental_tol = exp['rel'] * s + exp['rounding'] + row.slope * exp['t_err']
        d = abs(row.deviation)
        row.regression = 'PASS' if d <= row.regression_tol else 'FAIL'
        row.experimental = 'COMPATIBLE' if d <= row.experimental_tol else 'INCOMPATIBLE'
        av = app_value(method, 'salinity', 'wt_pct_NaCl_eq', t)
        row.app_consistent = None if av is None else av == row.computed
        out.append(row)
    return out


def evaluate_hall(path: Path = HALL_CSV) -> list[SalinityRow]:
    return _evaluate_salinity('Hall1988', _read(path), _bodnar, 'Bodnar_1993', HALL_REGRESSION, HALL_EXPERIMENT)


def evaluate_chen(path: Path = CHEN_CSV) -> list[SalinityRow]:
    return _evaluate_salinity('Chen1972', _read(path), _darling, 'Darling_1991', CHEN_REGRESSION, CHEN_EXPERIMENT)


@dataclass
class NistRow:
    id: str
    temperature_k: str
    temperature_c: float
    quantity: str
    unit: str
    expected_text: str            # ровно как напечатано в выгрузке NIST
    expected: float
    rounding_half_unit: float
    tolerance: float
    computed: float | None = None
    status: str = ''              # PASS | FAIL | SKIPPED | ERROR
    reason: str = ''
    app_consistent: bool | None = None

    @property
    def deviation(self):
        return None if self.computed is None else self.computed - self.expected


def half_last_digit(text: str) -> float:
    """Половина единицы последнего напечатанного разряда (неопределённость округления)."""
    return float(Decimal(10) ** Decimal(text.strip()).as_tuple().exponent) / 2


def evaluate_nist(path: Path = NIST_TSV) -> list[NistRow]:
    with open(path, encoding='utf-8', newline='') as fh:
        table = list(csv.DictReader(fh, delimiter='\t'))
    try:
        from fluid_core.co2 import pure_co2_saturation
        import CoolProp  # noqa: F401
        have = True
    except ImportError:
        have = False
    out = []
    for r in table:
        tk = r['Temperature (K)'].strip()
        t = round(float(tk) - 273.15, 8)
        for q, col, unit in NIST_COLUMNS:
            text = r[col].strip()
            half = half_last_digit(text)
            e = float(text)
            row = NistRow(f'NIST-{t:g}-{q}', tk, t, q, unit, text, e, half, half + abs(e) * 1e-8)
            if not have:
                row.status, row.reason = 'SKIPPED', 'CoolProp не установлен — проверка не выполнена (это не PASS)'
                out.append(row)
                continue
            try:
                branch = 'vapor' if q == 'vapor_density' else 'liquid'
                res = pure_co2_saturation(t, branch, co2_purity_confirmed=True)
                row.computed = res.saturation_pressure_bar if q == 'pressure' else res.density_g_cm3 * 1000.0
            except Exception as exc:  # noqa: BLE001
                row.status, row.reason = 'ERROR', f'{type(exc).__name__}: {exc}'
                out.append(row)
                continue
            row.status = 'PASS' if abs(row.deviation) <= row.tolerance else 'FAIL'
            av = app_value('CO2_sat', q, unit, t)
            row.app_consistent = None if av is None else abs(av - row.computed) <= 1e-12 * max(1.0, abs(av))
            out.append(row)
    return out


# --- реестр известных открытых расхождений ----------------------------------------
@dataclass
class KnownDiscrepancy:
    id: str
    criterion: str        # regression | experimental | nist
    expected_status: str
    open_question: str
    note: str


def load_known(path: Path = KNOWN_CSV) -> list[KnownDiscrepancy]:
    return [KnownDiscrepancy(r['id'], r['criterion'], r['expected_status'], r['open_question'], r['note'])
            for r in _read(path)]


@dataclass
class Reconciliation:
    known_reproduced: list[KnownDiscrepancy] = field(default_factory=list)
    known_not_reproduced: list[KnownDiscrepancy] = field(default_factory=list)   # требует пересмотра
    new_discrepancies: list[tuple[str, str, str]] = field(default_factory=list)  # (id, criterion, status)

    @property
    def ok(self) -> bool:
        return not self.known_not_reproduced and not self.new_discrepancies


BAD = {'regression': {'FAIL'}, 'experimental': {'INCOMPATIBLE'}, 'nist': {'FAIL', 'ERROR'}}


def reconcile(salinity: list[SalinityRow], nist: list[NistRow],
              known: list[KnownDiscrepancy] | None = None) -> Reconciliation:
    """Сопоставить фактические расхождения с реестром.

    Зарегистрированное расхождение остаётся FAIL/INCOMPATIBLE и показывается как открытое; оно не
    превращается в PASS. Новое (незарегистрированное) расхождение или исчезновение известного
    требуют пересмотра и дают ненулевой код возврата.
    """
    known = load_known() if known is None else known
    actual: dict[tuple[str, str], str] = {}
    for r in salinity:
        actual[(r.id, 'regression')] = r.regression
        actual[(r.id, 'experimental')] = r.experimental
    for r in nist:
        actual[(r.id, 'nist')] = r.status
    rec = Reconciliation()
    registered = set()
    for k in known:
        registered.add((k.id, k.criterion))
        if actual.get((k.id, k.criterion)) == k.expected_status:
            rec.known_reproduced.append(k)
        else:
            rec.known_not_reproduced.append(k)
    for (rid, crit), status in actual.items():
        if status in BAD[crit] and (rid, crit) not in registered:
            rec.new_discrepancies.append((rid, crit, status))
    return rec


def chen_statistics(rows: list[SalinityRow]) -> dict:
    inside = [r for r in rows if r.computed is not None]
    rel = [abs(r.rel_pct) for r in inside]
    worst = max(inside, key=lambda r: abs(r.rel_pct))
    return {
        'n_inside': len(inside),
        'n_outside': len(rows) - len(inside),
        'max_abs': max(abs(r.deviation) for r in inside),
        'max_rel_pct': max(rel),
        'max_rel_at_c': worst.temperature_c,
        'mean_abs_rel_pct': sum(rel) / len(rel),
        'n_incompatible': sum(r.experimental == 'INCOMPATIBLE' for r in inside),
    }
