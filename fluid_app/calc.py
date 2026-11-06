"""Связь наблюдений с расчётным ядром ``fluid_core``.

Модуль не содержит формул: он только проверяет наличие обязательных данных,
вызывает функции ядра без изменения коэффициентов и формирует «паспорт» результата.
"""
from __future__ import annotations

import math
import platform
import sys
from dataclasses import dataclass, field
from typing import Any

import fluid_core
from fluid_core.co2 import pure_co2_saturation, CRITICAL_POINT_C, DEFAULT_CRITICAL_GUARD_C
from fluid_core.salinity import bodnar_1993, darling_1991

from . import __version__ as APP_VERSION
from .methods import (KIND_METHOD, KIND_NO_CALC_REASON, KINDS, METHODS, KIND_RESULT_LABEL,
                      FLAG_FIELDS, HOMOGENIZATION, translate_core_message, kind_label)

INPUT_FIELDS = ('kind', 'temperature_c', 'uncertainty_c', 'homogenization_to',
                'liquid_co2_present', 'vapor_co2_present', 'aqueous_brine_present',
                'co2_purity_confirmed')


class InputError(ValueError):
    """Недостаточно данных или нарушено фазовое условие (сообщение на русском)."""


@dataclass
class Outcome:
    status: str                      # ok | error | skipped
    kind: str
    method_key: str | None = None
    result_kind: str = ''
    value: float | None = None
    unit: str = ''
    extras: dict[str, Any] = field(default_factory=dict)
    model: str = ''
    doi: str = ''
    citation: str = ''
    assumptions: str = ''
    scope: str = ''
    warnings: list[str] = field(default_factory=list)
    message: str = ''                # пояснение / причина отказа (рус.)
    message_original: str = ''       # исходное сообщение ядра (англ.)


def backend_versions() -> dict[str, str]:
    try:
        import CoolProp
        coolprop = CoolProp.__version__
    except ImportError:
        coolprop = 'не установлен'
    return {
        'app_version': APP_VERSION,
        'core_version': getattr(fluid_core, '__version__', 'unknown'),
        'python_version': sys.version.split()[0],
        'coolprop_version': coolprop,
        'platform': f'{platform.system()} {platform.release()} {platform.machine()}',
    }


def _flag_or_missing(obs: dict, key: str, missing: list[str]) -> bool:
    v = obs.get(key)
    if v is None:
        missing.append(FLAG_FIELDS[key])
        return False
    return bool(v)


def _run_core(method_key: str, t: float, obs: dict):
    """Вызов функции ядра. Возвращает (значение, объект-результат ядра)."""
    if method_key == 'bodnar_1993':
        r = bodnar_1993(t)
        return r.salinity_wt_pct_nacl_eq, r
    if method_key == 'darling_1991':
        r = darling_1991(t, liquid_co2_present=obs['liquid_co2_present'] is True,
                         vapor_co2_present=obs['vapor_co2_present'] is True,
                         aqueous_brine_present=obs['aqueous_brine_present'] is True)
        return r.salinity_wt_pct_nacl_eq, r
    if method_key == 'pure_co2_saturation':
        r = pure_co2_saturation(t, obs.get('homogenization_to') or '',
                                co2_purity_confirmed=obs.get('co2_purity_confirmed') is True)
        return r.density_g_cm3, r
    raise KeyError(method_key)


def _precheck(method_key: str, obs: dict) -> None:
    """Проверка обязательных данных до вызова ядра; ничего не подставляет."""
    if method_key == 'darling_1991':
        missing: list[str] = []
        for key in ('liquid_co2_present', 'vapor_co2_present', 'aqueous_brine_present'):
            _flag_or_missing(obs, key, missing)
        if missing:
            raise InputError('Не указано: ' + '; '.join(missing) +
                             '. Для уравнения Darling наличие всех трёх фаз при плавлении клатрата '
                             'должно быть зафиксировано наблюдателем; предполагаемые значения не подставляются.')
    if method_key == 'pure_co2_saturation':
        h = obs.get('homogenization_to')
        if h is None or h == '':
            raise InputError('Направление гомогенизации CO₂ не указано. Автоматический выбор ветви '
                             '(жидкость/газ) не выполняется.')
        if h == 'critical':
            raise InputError('Критическая гомогенизация CO₂: ветви жидкость–газ неразличимы, '
                             'плотность насыщенной фазы не определяется рутинным расчётом.')
        if obs.get('co2_purity_confirmed') is not True:
            raise InputError('Приближение чистой CO₂ не принято явно. При возможных примесях '
                             '(CH₄, N₂ и др.) требуется смесевая модель, которая не реализована.')


def calculate_observation(obs: dict) -> Outcome:
    """Рассчитать одно наблюдение. ``obs`` — словарь с полями INPUT_FIELDS.

    Логические флаги: True / False / None (не указано).
    """
    kind = obs.get('kind')
    if kind not in KINDS:
        return Outcome('error', str(kind), message=f'Неизвестный тип наблюдения: {kind!r}')
    method_key = KIND_METHOD.get(kind)
    if method_key is None:
        return Outcome('skipped', kind, message=KIND_NO_CALC_REASON.get(kind, 'Расчёт не предусмотрен.'))
    meta = METHODS[method_key]
    base = dict(kind=kind, method_key=method_key, model=meta['title'], doi=meta['doi'],
                citation=meta['citation'])
    t = obs.get('temperature_c')
    try:
        if t is None or (isinstance(t, float) and math.isnan(t)):
            raise InputError('Температура не указана.')
        _precheck(method_key, obs)
        value, r = _run_core(method_key, float(t), obs)
    except InputError as exc:
        return Outcome('error', message=str(exc), **base)
    except (ValueError, TypeError, RuntimeError, ArithmeticError) as exc:
        return Outcome('error', message=translate_core_message(str(exc)),
                       message_original=str(exc), **base)

    out = Outcome('ok', value=float(value) + 0.0, result_kind=KIND_RESULT_LABEL[method_key], **base)
    out.assumptions = ' '.join(meta['assumptions'])
    out.scope = meta['range']
    if method_key in ('bodnar_1993', 'darling_1991'):
        out.unit = 'мас. % NaCl-экв.'
        out.extras['core_assumption'] = r.assumption
        out.extras['core_scope'] = r.scope
    else:
        out.unit = 'г/см³'
        branch = 'жидкой' if r.homogenization_to == 'liquid' else 'газовой'
        out.result_kind = f'Плотность насыщенной {branch} CO₂'
        out.extras.update({
            'branch': r.homogenization_to,
            'density_g_cm3': r.density_g_cm3,
            'saturation_pressure_bar': r.saturation_pressure_bar,
            'molar_volume_cm3_mol': r.molar_volume_cm3_mol,
            'critical_proximity_c': r.critical_proximity_c,
            'backend': r.backend,
            'backend_version': r.backend_version,
            'model_reference': r.model_reference,
            'core_note': r.note,
        })
        out.model = f'{meta["title"]}; {r.backend}, CoolProp {r.backend_version}'
        out.warnings.append('P_sat — давление насыщения чистой CO₂ при Th CO₂, а не давление '
                            'минералообразования или захвата.')
        out.warnings.append(f'До критической точки CO₂ ({CRITICAL_POINT_C:.3f} °C): '
                            f'{r.critical_proximity_c:.3f} °C (защитный интервал программы '
                            f'{DEFAULT_CRITICAL_GUARD_C:.2f} °C).')

    u = obs.get('uncertainty_c')
    if u is not None and u > 0:
        lo_hi = []
        for tt in (float(t) - u, float(t) + u):
            try:
                lo_hi.append(_run_core(method_key, tt, obs)[0])
            except (ValueError, TypeError, RuntimeError, ArithmeticError):
                lo_hi.append(None)
        out.extras['sensitivity_t_minus_u'] = lo_hi[0]
        out.extras['sensitivity_t_plus_u'] = lo_hi[1]
        if None in lo_hi:
            out.warnings.append(f'При T ± {u:g} °C одна из границ выходит за область применимости — '
                                'диапазон чувствительности неполный.')
    return out


def format_value(value: float | None, digits: int = 4) -> str:
    if value is None:
        return ''
    return f'{value:.{digits}f}'.replace('.', ',')


def _flag_text(v) -> str:
    return 'не указано' if v is None else ('да' if v else 'нет')


def passport_lines(inputs: dict, outcome: dict, run: dict | None = None,
                   context: dict | None = None) -> list[tuple[str, str]]:
    """Паспорт результата как список пар (поле, значение) — для GUI и экспорта."""
    kind = inputs.get('kind')
    rows: list[tuple[str, str]] = []
    if context:
        path = ' → '.join(x for x in (context.get('project_name'), context.get('sample_name'),
                                       context.get('mineral_name'), context.get('fia_name'),
                                       context.get('inclusion_name')) if x)
        rows.append(('Объект', path))
    rows.append(('Наблюдение', f'{kind_label(kind)} — {KINDS.get(kind, ("", ""))[1]}'))
    t = inputs.get('temperature_c')
    rows.append(('Температура, °C', '' if t is None else format_value(t, 2)))
    u = inputs.get('uncertainty_c')
    rows.append(('Погрешность ±, °C', 'не указана' if u is None else format_value(u, 2)))
    h = inputs.get('homogenization_to')
    if kind in ('Th_CO2', 'Th_total'):
        rows.append(('Направление гомогенизации', HOMOGENIZATION.get(h, 'не указано')))
    if kind == 'Tm_clath':
        for key in ('liquid_co2_present', 'vapor_co2_present', 'aqueous_brine_present'):
            rows.append((FLAG_FIELDS[key], _flag_text(inputs.get(key))))
    if kind == 'Th_CO2':
        rows.append((FLAG_FIELDS['co2_purity_confirmed'], _flag_text(inputs.get('co2_purity_confirmed'))))
    status = outcome.get('status')
    rows.append(('Статус', {'ok': 'рассчитано', 'error': 'расчёт заблокирован / ошибка',
                            'skipped': 'расчёт не выполняется'}.get(status, status)))
    if outcome.get('message'):
        rows.append(('Причина' if status != 'ok' else 'Примечание', outcome['message']))
    if outcome.get('message_original'):
        rows.append(('Сообщение ядра (исходное)', outcome['message_original']))
    if status == 'ok':
        rows.append(('Результат', f'{outcome.get("result_kind")}: {format_value(outcome.get("value"), 5)} {outcome.get("unit")}'))
        ex = outcome.get('extras') or {}
        if 'saturation_pressure_bar' in ex:
            rows.append(('Давление насыщения CO₂ P_sat, бар', format_value(ex['saturation_pressure_bar'], 4)))
            rows.append(('Мольный объём CO₂, см³/моль', format_value(ex['molar_volume_cm3_mol'], 4)))
            rows.append(('Ветвь насыщения', 'жидкость (Q = 0)' if ex.get('branch') == 'liquid' else 'газ (Q = 1)'))
        if 'sensitivity_t_minus_u' in ex:
            lo, hi = ex['sensitivity_t_minus_u'], ex['sensitivity_t_plus_u']
            rows.append(('Значение при T − u / T + u',
                         f'{format_value(lo, 5) or "вне области"} / {format_value(hi, 5) or "вне области"} '
                         '(чувствительность, не полный бюджет неопределённости)'))
    if outcome.get('method_key'):
        meta = METHODS[outcome['method_key']]
        rows.append(('Методика', outcome.get('model') or meta['title']))
        rows.append(('Уравнение / модель', meta['equation']))
        rows.append(('Область применимости', meta['range']))
        rows.append(('Источник', meta['citation']))
        rows.append(('DOI', f'https://doi.org/{meta["doi"]}'))
        rows.append(('Функция ядра', meta['core_function']))
        rows.append(('Допущения', ' '.join(meta['assumptions'])))
        rows.append(('Ограничения', ' '.join(meta['limitations'])))
    for w in outcome.get('warnings') or []:
        rows.append(('Предупреждение', w))
    if run:
        rows.append(('Расчёт №', str(run.get('id'))))
        rows.append(('Дата расчёта (UTC)', str(run.get('created_at'))))
        rows.append(('Версии', f'FluidCalc {run.get("app_version")}, ядро {run.get("core_version")}, '
                     f'Python {run.get("python_version")}, CoolProp {run.get("coolprop_version")}'))
    return rows
