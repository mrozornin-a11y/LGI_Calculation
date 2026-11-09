"""Проверка контрольных точек расчётного ядра.

Модуль только ВЫЗЫВАЕТ функции fluid_core (формулы не дублируются и не изменяются) и
сравнивает результат с опорными значениями из validation/checkpoints.csv.

Классы свидетельств (evidence_type) и уровни независимости (independence) разделены
явно: совпадение с пересчётом того же уравнения (equation_reproduction, independence=none)
проверяет только перенос формулы в код и НЕ является независимой проверкой.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKPOINTS_CSV = HERE / 'checkpoints.csv'
SOURCE_CSV = HERE / 'sources' / 'FluidCalc_reference_checkpoints.csv'

EVIDENCE_TYPES = {
    'experiment': 'экспериментальные данные первоисточника',
    'reference_table': 'точная справочная таблица (напр. NIST/REFPROP)',
    'independent_rounded_reference': 'независимая округлённая справочная таблица',
    'independent_rounded_educational': 'независимый округлённый учебный пример',
    'equation_reproduction': 'пересчёт по проверяемому уравнению (не независимо)',
}
INDEPENDENCE = {
    'experimental': 'независимо от модели (эксперимент)',
    'external_reference': 'внешний источник, модель не указана',
    'implementation': 'независимая реализация той же модели',
    'none': 'нет: то же уравнение',
}
UNITS_RU = {'wt_pct_NaCl_eq': 'мас. % NaCl-экв.', 'bar': 'бар', 'kg_m3': 'кг/м³'}
QUANTITY_RU = {'salinity': 'солёность', 'pressure': 'P_sat', 'liquid_density': 'ρ жидкости',
               'vapor_density': 'ρ газа'}
REQUIRED_COLUMNS = ('id', 'method', 'temperature_c', 'quantity', 'expected', 'unit', 'evidence_type',
                    'independence', 'source', 'doi', 'url', 'reference_rounding_half_unit', 'tolerance_abs',
                    'tolerance_rel', 'tolerance_basis', 'comment')


@dataclass
class Checkpoint:
    id: str
    method: str
    temperature_c: float
    quantity: str
    expected: float
    unit: str
    evidence_type: str
    independence: str
    source: str
    doi: str
    url: str
    reference_rounding_half_unit: float | None
    tolerance_abs: float | None
    tolerance_rel: float | None
    tolerance_basis: str
    comment: str

    @property
    def independent(self) -> bool:
        return self.independence != 'none'

    def tolerance(self) -> float:
        """Допустимое абсолютное отклонение в единицах опорного значения."""
        tols = []
        if self.tolerance_abs is not None:
            tols.append(self.tolerance_abs)
        if self.tolerance_rel is not None:
            tols.append(self.tolerance_rel * abs(self.expected))
        return max(tols)


@dataclass
class Control:
    label: str
    required: bool
    deviation: float | None     # None — ядро отказало (искажение вывело за область применимости)
    detected: bool


@dataclass
class Result:
    checkpoint: Checkpoint
    status: str                     # PASS | FAIL | SKIPPED | ERROR
    computed: float | None = None
    deviation: float | None = None  # computed − expected
    app_consistent: bool | None = None
    message: str = ''
    controls: list[Control] = field(default_factory=list)

    @property
    def required_controls_detected(self) -> bool:
        return all(c.detected for c in self.controls if c.required)

    @property
    def undetected_informative(self) -> list[str]:
        return [c.label for c in self.controls if not c.required and not c.detected]

    @property
    def rel_deviation(self) -> float | None:
        if self.deviation is None or self.checkpoint.expected == 0:
            return None
        return self.deviation / abs(self.checkpoint.expected)

    @property
    def within_rounding(self) -> bool | None:
        u = self.checkpoint.reference_rounding_half_unit
        if self.deviation is None or u is None:
            return None
        return abs(self.deviation) <= u + 1e-12


def _opt(text: str) -> float | None:
    text = (text or '').strip()
    return float(text) if text else None


def load_checkpoints(path: Path = CHECKPOINTS_CSV) -> list[Checkpoint]:
    with open(path, encoding='utf-8', newline='') as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f'В {path.name} нет столбцов: {missing}')
        rows = list(reader)
    out = []
    ids = set()
    for r in rows:
        cp = Checkpoint(
            id=r['id'], method=r['method'], temperature_c=float(r['temperature_c']), quantity=r['quantity'],
            expected=float(r['expected']), unit=r['unit'], evidence_type=r['evidence_type'],
            independence=r['independence'], source=r['source'], doi=r['doi'], url=r['url'],
            reference_rounding_half_unit=_opt(r['reference_rounding_half_unit']), tolerance_abs=_opt(r['tolerance_abs']),
            tolerance_rel=_opt(r['tolerance_rel']), tolerance_basis=r['tolerance_basis'], comment=r['comment'])
        if cp.id in ids:
            raise ValueError(f'Повтор id {cp.id}')
        ids.add(cp.id)
        if cp.evidence_type not in EVIDENCE_TYPES:
            raise ValueError(f'{cp.id}: неизвестный evidence_type {cp.evidence_type}')
        if cp.independence not in INDEPENDENCE:
            raise ValueError(f'{cp.id}: неизвестный independence {cp.independence}')
        if (cp.evidence_type == 'equation_reproduction') != (cp.independence == 'none'):
            raise ValueError(f'{cp.id}: equation_reproduction должен иметь independence=none и наоборот')
        if cp.tolerance_abs is None and cp.tolerance_rel is None:
            raise ValueError(f'{cp.id}: не задан допуск')
        if not cp.tolerance_basis.strip():
            raise ValueError(f'{cp.id}: не обоснован допуск')
        if not (cp.doi or cp.url):
            raise ValueError(f'{cp.id}: нет ни DOI, ни URL источника')
        out.append(cp)
    return out


# --- вычисление через ядро ---------------------------------------------------
def core_value(method: str, quantity: str, unit: str, t: float, *, branch_swap: bool = False) -> float:
    """Значение функции fluid_core в единицах контрольной точки."""
    if method == 'Bodnar_1993' and quantity == 'salinity' and unit == 'wt_pct_NaCl_eq':
        from fluid_core.salinity import bodnar_1993
        return bodnar_1993(t).salinity_wt_pct_nacl_eq
    if method == 'Darling_1991' and quantity == 'salinity' and unit == 'wt_pct_NaCl_eq':
        from fluid_core.salinity import darling_1991
        return darling_1991(t, liquid_co2_present=True, vapor_co2_present=True,
                            aqueous_brine_present=True).salinity_wt_pct_nacl_eq
    if method == 'CO2_sat':
        from fluid_core.co2 import pure_co2_saturation
        branch = {'pressure': 'liquid', 'liquid_density': 'liquid', 'vapor_density': 'vapor'}[quantity]
        if branch_swap:
            branch = 'vapor' if branch == 'liquid' else 'liquid'
        r = pure_co2_saturation(t, branch, co2_purity_confirmed=True)
        if quantity == 'pressure' and unit == 'bar':
            return r.saturation_pressure_bar
        if quantity.endswith('density') and unit == 'kg_m3':
            return r.density_g_cm3 * 1000.0
    raise KeyError(f'Нет соответствия ядру: {method}/{quantity}/{unit}')


def app_value(method: str, quantity: str, unit: str, t: float) -> float | None:
    """То же значение через слой приложения fluid_app.calc (проверка, что GUI не искажает число)."""
    try:
        from fluid_app.calc import calculate_observation
    except ImportError:
        return None
    base = dict(uncertainty_c=None, homogenization_to=None, liquid_co2_present=None, vapor_co2_present=None,
                aqueous_brine_present=None, co2_purity_confirmed=None, temperature_c=t)
    if method == 'Bodnar_1993':
        o = calculate_observation(dict(base, kind='Tm_ice'))
        return o.value
    if method == 'Darling_1991':
        o = calculate_observation(dict(base, kind='Tm_clath', liquid_co2_present=True, vapor_co2_present=True,
                                       aqueous_brine_present=True))
        return o.value
    if method == 'CO2_sat':
        branch = 'vapor' if quantity == 'vapor_density' else 'liquid'
        o = calculate_observation(dict(base, kind='Th_CO2', homogenization_to=branch, co2_purity_confirmed=True))
        if o.status != 'ok':
            return None
        if quantity == 'pressure':
            return o.extras['saturation_pressure_bar']
        return o.value * 1000.0
    return None


# Контрольные искажения. required=True — грубые ошибки, которые допуск ОБЯЗАН обнаружить
# (ошибочная ветвь насыщения, путаница °C/K); required=False — информационные: показывают,
# какую ошибку температуры допуск способен разрешить, но не являются критерием PASS.
PERTURBATIONS = {
    'Bodnar_1993': [('T + 0,1 °C', 0.1, False, False), ('T в кельвинах вместо °C', 273.15, False, True)],
    'Darling_1991': [('T + 0,1 °C', 0.1, False, False), ('T в кельвинах вместо °C', 273.15, False, True)],
    'CO2_sat': [('T + 1 °C', 1.0, False, False), ('ошибочная ветвь насыщения', 0.0, True, True),
                ('T в кельвинах вместо °C', 273.15, False, True)],
}


def _coolprop_available() -> bool:
    try:
        import CoolProp  # noqa: F401
        return True
    except ImportError:
        return False


def evaluate(cp: Checkpoint) -> Result:
    if cp.method == 'CO2_sat' and not _coolprop_available():
        return Result(cp, 'SKIPPED', message='CoolProp не установлен — проверка не выполнена (это не PASS)')
    try:
        value = core_value(cp.method, cp.quantity, cp.unit, cp.temperature_c)
    except Exception as exc:  # noqa: BLE001 — любой отказ ядра фиксируется в отчёте
        return Result(cp, 'ERROR', message=f'{type(exc).__name__}: {exc}')
    dev = value - cp.expected
    tol = cp.tolerance()
    res = Result(cp, 'PASS' if abs(dev) <= tol else 'FAIL', computed=value, deviation=dev)
    av = app_value(cp.method, cp.quantity, cp.unit, cp.temperature_c)
    res.app_consistent = None if av is None else (av == value + 0.0 or math.isclose(av, value, rel_tol=0, abs_tol=1e-12))
    if res.app_consistent is False:
        res.status = 'FAIL'
        res.message = f'Слой приложения дал {av!r}, ядро {value!r}'
    if cp.independent:
        for label, shift, swap, required in PERTURBATIONS.get(cp.method, []):
            if swap and cp.quantity == 'pressure':
                continue        # давление насыщения одинаково на обеих ветвях
            try:
                v2 = core_value(cp.method, cp.quantity, cp.unit, cp.temperature_c + shift, branch_swap=swap)
                d2 = v2 - cp.expected
                res.controls.append(Control(label, required, d2, abs(d2) > tol))
            except Exception:  # noqa: BLE001 — ядро отказало (вне области): ошибка обнаружена
                res.controls.append(Control(label, required, None, True))
    return res


def evaluate_all(path: Path = CHECKPOINTS_CSV) -> list[Result]:
    return [evaluate(cp) for cp in load_checkpoints(path)]


def source_rows(path: Path = SOURCE_CSV) -> list[dict]:
    with open(path, encoding='utf-8', newline='') as fh:
        return list(csv.DictReader(fh))
