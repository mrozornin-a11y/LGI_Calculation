"""Пересечение готовой изохоры включения с независимым ограничением по температуре или давлению.

Новых уравнений состояния здесь нет: используются уже реализованные изохоры —
  * H₂O–NaCl: линейная изохора HokieFlincs, P = Ph + (dP/dT)·(T − Th) (`fluid_core.h2o_nacl`);
  * H₂O–CO₂–NaCl: давление по уравнению Duan et al. (1995) в форме Gottschalk (2007) (`fluid_core.duan1995`).

Результат — «условия захвата включения при независимом ограничении». Это не давление и не температура
минералообразования: такая трактовка допустима только если одновременность захвата включения и роста минерала
документирована отдельно (параметр coeval_with_mineral_growth_documented), и никогда не выводится из Th или
типа включения.

Задаётся ровно одно ограничение: температура, давление, диапазон температур или диапазон давлений. Для диапазона
вычисляются значения на его концах и упорядочиваются; это НЕ статистический доверительный интервал.
Экстраполяция за пределы области изохоры не выполняется.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from . import duan1995

WORDING = 'условия захвата включения при независимом ограничении'
COEVAL_WORDING = 'может интерпретироваться как условие соответствующего этапа минералообразования'
RANGE_NOTE = 'Диапазон — значения на концах заданного интервала; это не статистический доверительный интервал.'


@dataclass(frozen=True)
class LinearIsochore:
    """Линейная изохора H₂O–NaCl (HokieFlincs): P = Ph + slope·(T − Th), от Th до p_max_bar."""
    th_c: float
    ph_bar: float
    slope_bar_per_c: float
    p_max_bar: float = 6000.0
    system: str = 'H₂O–NaCl'
    method: str = 'линейная изохора HokieFlincs: P = Ph + (dP/dT)·(T − Th)'

    @classmethod
    def from_h2o_nacl(cls, result) -> 'LinearIsochore':
        """Из результата `fluid_core.h2o_nacl.homogenization_to_liquid`."""
        from .h2o_nacl import P_MAX_BAR
        return cls(result.th_c, result.pressure_bar, result.slope_bar_per_c, P_MAX_BAR)

    @property
    def t_min_c(self):
        return self.th_c

    @property
    def t_max_c(self):
        return self.th_c + (self.p_max_bar - self.ph_bar) / self.slope_bar_per_c

    def pressure_at(self, t_c):
        return self.ph_bar + self.slope_bar_per_c * (t_c - self.th_c)

    def temperatures_at(self, p_bar):
        """Все температуры, при которых изохора даёт давление p (для прямой — не более одной)."""
        if self.slope_bar_per_c <= 0:
            return []
        t = self.th_c + (p_bar - self.ph_bar) / self.slope_bar_per_c
        return [t] if self.t_min_c <= t <= self.t_max_c else []


@dataclass(frozen=True)
class CompositionIsochore:
    """Изохора H₂O–CO₂–NaCl: давление уравнения Duan et al. (1995) при постоянных составе и молярном объёме."""
    molar_volume_cm3_mol: float
    x_h2o: float
    x_nacl: float
    x_co2: float
    t_min_c: float = duan1995.T_MIN_K - 273.15       # 300 °C
    t_max_c: float = duan1995.T_MAX_K - 273.15       # 1000 °C
    p_max_bar: float = duan1995.P_MAX_BAR            # 6000 бар
    system: str = 'H₂O–CO₂–NaCl'
    method: str = 'уравнение состояния Duan et al. (1995) в форме Gottschalk (2007)'
    scan_step_c: float = 5.0

    def pressure_at(self, t_c):
        return duan1995.pressure_bar(t_c, self.molar_volume_cm3_mol, self.x_h2o, self.x_nacl, self.x_co2)

    def temperatures_at(self, p_bar):
        """Все корни P(T) = p в области изохоры: перебор по сетке и деление пополам (детерминированно)."""
        n = max(2, int(round((self.t_max_c - self.t_min_c) / self.scan_step_c)))
        grid = [self.t_min_c + (self.t_max_c - self.t_min_c) * i / n for i in range(n + 1)]
        vals = [self.pressure_at(t) - p_bar for t in grid]
        roots = []
        for (a, fa), (b, fb) in zip(zip(grid, vals), zip(grid[1:], vals[1:])):
            if fa == 0:
                roots.append(a)
            elif fa * fb < 0:
                lo, hi, flo = a, b, fa
                for _ in range(200):
                    mid = 0.5 * (lo + hi)
                    fm = self.pressure_at(mid) - p_bar
                    if flo * fm <= 0:
                        hi = mid
                    else:
                        lo, flo = mid, fm
                    if hi - lo <= 1e-12 * max(1.0, abs(hi)):
                        break
                roots.append(0.5 * (lo + hi))
        if vals[-1] == 0:
            roots.append(grid[-1])
        return roots


@dataclass(frozen=True)
class TrappingConstraintResult:
    status: str                      # ok | no_valid_intersection | ambiguous_intersections | out_of_range
    constraint: str                  # temperature | pressure | temperature_range | pressure_range
    temperature_c: float | None = None            # для одиночного ограничения
    pressure_bar: float | None = None
    temperature_range_c: tuple | None = None      # (мин., макс.) для диапазона
    pressure_range_bar: tuple | None = None
    system: str = ''
    method: str = ''
    message: str = ''
    notes: tuple = ()
    wording: str = WORDING
    coeval_with_mineral_growth_documented: bool = False

    @property
    def interpretation(self) -> str:
        """Формулировка результата; расширенная — только при документированной одновременности с ростом минерала."""
        if self.coeval_with_mineral_growth_documented:
            return f'{self.wording}; {COEVAL_WORDING}'
        return self.wording


def _num(x, name):
    if isinstance(x, bool):
        raise TypeError(f'{name}: требуется число')
    x = float(x)
    if not isfinite(x):
        raise ValueError(f'{name}: требуется конечное число')
    return x


def _pair(rng, name):
    try:
        a, b = rng
    except (TypeError, ValueError):
        raise ValueError(f'{name}: требуется пара значений (от, до)') from None
    a, b = _num(a, name), _num(b, name)
    return (a, b) if a <= b else (b, a)


def _pressure_at(isochore, t):
    """(статус, давление, сообщение) при температуре t."""
    if not isochore.t_min_c <= t <= isochore.t_max_c:
        return ('out_of_range', None, f'Температура {t:g} °C вне области изохоры ({isochore.t_min_c:.1f} … '
                                      f'{isochore.t_max_c:.1f} °C); экстраполяция не выполняется.')
    p = isochore.pressure_at(t)
    if not 0 < p <= isochore.p_max_bar:
        return ('out_of_range', None, f'Давление на изохоре при {t:g} °C ({p:.0f} бар) вне области модели '
                                      f'(до {isochore.p_max_bar:g} бар); экстраполяция не выполняется.')
    return 'ok', p, ''


def _temperature_at(isochore, p):
    """(статус, температура, сообщение) при давлении p."""
    if not 0 < p <= isochore.p_max_bar:
        return ('out_of_range', None, f'Давление {p:g} бар вне области изохоры (до {isochore.p_max_bar:g} бар); '
                                      'экстраполяция не выполняется.')
    roots = isochore.temperatures_at(p)
    if not roots:
        return ('no_valid_intersection', None,
                f'В области изохоры ({isochore.t_min_c:.1f} … {isochore.t_max_c:.1f} °C) давление {p:g} бар не '
                'достигается: допустимого пересечения нет.')
    if len(roots) > 1:
        return ('ambiguous_intersections', None,
                f'Изохора достигает давления {p:g} бар при нескольких температурах ('
                + '; '.join(f'{t:.1f}' for t in roots) + ' °C): пересечение неоднозначно, выбор не делается.')
    return 'ok', roots[0], ''


def solve_trapping_constraint(isochore, independent_temperature=None, independent_pressure=None,
                              temperature_range=None, pressure_range=None, *,
                              coeval_with_mineral_growth_documented: bool = False) -> TrappingConstraintResult:
    """Условия захвата включения при независимом ограничении: точка (или отрезок) на готовой изохоре.

    isochore — `LinearIsochore` (H₂O–NaCl) или `CompositionIsochore` (H₂O–CO₂–NaCl).
    Должно быть задано ровно одно из: independent_temperature (°C), independent_pressure (бар),
    temperature_range (°C, пара), pressure_range (бар, пара).
    """
    given = [(k, v) for k, v in (('temperature', independent_temperature), ('pressure', independent_pressure),
                                 ('temperature_range', temperature_range), ('pressure_range', pressure_range))
             if v is not None]
    if len(given) != 1:
        raise ValueError('Нужно задать ровно одно независимое ограничение: температуру, давление, диапазон '
                         'температур или диапазон давлений')
    if not isinstance(coeval_with_mineral_growth_documented, bool):
        raise TypeError('coeval_with_mineral_growth_documented: True или False')
    kind, value = given[0]
    base = dict(constraint=kind, system=isochore.system, method=isochore.method,
                coeval_with_mineral_growth_documented=coeval_with_mineral_growth_documented)
    if kind == 'temperature':
        t = _num(value, 'Температура')
        status, p, msg = _pressure_at(isochore, t)
        return TrappingConstraintResult(status, temperature_c=t, pressure_bar=p, message=msg, **base)
    if kind == 'pressure':
        p = _num(value, 'Давление')
        status, t, msg = _temperature_at(isochore, p)
        return TrappingConstraintResult(status, temperature_c=t, pressure_bar=p, message=msg, **base)
    if kind == 'temperature_range':
        lo, hi = _pair(value, 'Диапазон температур')
        ends = [_pressure_at(isochore, t) for t in (lo, hi)]
        bad = next((e for e in ends if e[0] != 'ok'), None)
        if bad:
            return TrappingConstraintResult(bad[0], temperature_range_c=(lo, hi), message=bad[2], **base)
        ps = sorted(e[1] for e in ends)
        return TrappingConstraintResult('ok', temperature_range_c=(lo, hi), pressure_range_bar=(ps[0], ps[1]),
                                        notes=(RANGE_NOTE,), **base)
    lo, hi = _pair(value, 'Диапазон давлений')
    ends = [_temperature_at(isochore, p) for p in (lo, hi)]
    bad = next((e for e in ends if e[0] != 'ok'), None)
    if bad:
        return TrappingConstraintResult(bad[0], pressure_range_bar=(lo, hi), message=bad[2], **base)
    ts = sorted(e[1] for e in ends)
    return TrappingConstraintResult('ok', pressure_range_bar=(lo, hi), temperature_range_c=(ts[0], ts[1]),
                                    notes=(RANGE_NOTE,), **base)
