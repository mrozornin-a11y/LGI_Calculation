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
                      FLAG_FIELDS, HOMOGENIZATION, translate_core_message, kind_label, kind_title)

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
    if kind == 'bulk_density':
        rows.append(('Результат по включению', f'{kind_label(kind)} — {kind_title(kind)}'))
        phi, phi_u = inputs.get('carbonic_fraction'), inputs.get('carbonic_fraction_unc')
        rows.append(('φ углекислотной фазы, %', 'не указана' if phi is None else format_value(100 * phi, 1)
                     + ('' if not phi_u else f' ± {format_value(100 * phi_u, 1)}')))
        rows.append(('Способ оценки φ', inputs.get('carbonic_fraction_method') or 'не указан'))
        tphi = inputs.get('carbonic_fraction_temp_c')
        rows.append(('Температура оценки φ, °C', 'не указана' if tphi is None else format_value(tphi, 1)))
        for key, label, digits in (('Th_CO2', 'Th CO₂, °C', 2), ('rho_co2_g_cm3', 'Плотность CO₂, г/см³', 4),
                                   ('Tm_clath', 'Tm клатрата, °C', 2), ('salinity_wt_pct', 'Солёность, мас. % NaCl-экв.', 2),
                                   ('rho_brine_20c_g_cm3', 'Плотность раствора при 20 °C, г/см³', 4)):
            if inputs.get(key) is not None:
                rows.append((label, format_value(inputs[key], digits)))
        if inputs.get('homogenization_to'):
            rows.append(('Направление гомогенизации CO₂', HOMOGENIZATION.get(inputs['homogenization_to'], '')))
    elif kind == 'co2_pvtx':
        rows.append(('Результат по включению', f'{kind_label(kind)} — {kind_title(kind)}'))
        mode = inputs.get('mode')
        rows.append(('Режим модели', PVTX_MODES.get(mode, 'не определён — см. причину')))
        for key, label, digits in (('Tm_ice', 'Tm льда, °C', 2), ('Tm_clath', 'Tm клатрата, °C', 2),
                                   ('Th_CO2', 'Th CO₂, °C', 2), ('Th_total', 'Th общ., °C', 1)):
            if inputs.get(key) is not None:
                rows.append((label, format_value(inputs[key], digits)))
        if inputs.get('homogenization_to'):
            rows.append(('Направление гомогенизации CO₂', HOMOGENIZATION.get(inputs['homogenization_to'], '')))
        if inputs.get('Th_total') is not None:
            rows.append(('Направление общей гомогенизации', HOMOGENIZATION.get(inputs.get('Th_total_to'), 'не указано')))
        phi, phi_u = inputs.get('carbonic_fraction'), inputs.get('carbonic_fraction_unc')
        rows.append(('φ углекислотных фаз, %', 'не указана' if phi is None else format_value(100 * phi, 1)
                     + ('' if not phi_u else f' ± {format_value(100 * phi_u, 1)}')))
        tphi = inputs.get('carbonic_fraction_temp_c')
        rows.append(('Температура оценки φ, °C', 'не указана' if tphi is None else format_value(tphi, 1)))
        rows.append(('Способ оценки φ', inputs.get('carbonic_fraction_method') or 'не указан'))
    elif kind == 'aq_pvt':
        rows.append(('Результат по включению', f'{kind_label(kind)} — {kind_title(kind)}'))
        for key, label, digits in (('Tm_ice', 'Tm льда, °C', 2), ('salinity_wt_pct', 'Солёность, мас. % NaCl-экв.', 2),
                                   ('Th_total', 'Th общ., °C', 1)):
            if inputs.get(key) is not None:
                rows.append((label, format_value(inputs[key], digits)))
        rows.append(('Направление гомогенизации', HOMOGENIZATION.get(inputs.get('homogenization_to'), 'не указано')))
    else:
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
        if 'Ph_bar' in ex:
            rows.append(('Давление при Th (Ph), бар', format_value(ex['Ph_bar'], 2) + ' — минимальное давление захвата'))
            rows.append(('Наклон изохоры dP/dT, бар/°C', format_value(ex['dPdT_bar_per_C'], 3)))
            rows.append(('Критическая температура раствора, °C', format_value(ex['Tc_C'], 1)))
            if ex.get('isochore'):
                rows.append(('Изохора (T, °C → P, бар)', '; '.join(f'{t:.0f} → {p:.0f}' for t, p in ex['isochore'])))
        if 'x_co2' in ex:
            rows.append(('Чем задано количество CO₂-фазы', ex.get('fraction_source', '')))
            rows.append(('Валовый состав, мол. доли', f'H₂O {format_value(ex["x_h2o"], 5)}; CO₂ '
                         f'{format_value(ex["x_co2"], 5)}; NaCl {format_value(ex["x_nacl"], 5)}'))
            rows.append(('CO₂ / (CO₂ + H₂O), мол. %', format_value(ex['co2_mol_pct_salt_free'], 3)))
            rows.append(('Солёность валовая, мас. % NaCl', format_value(ex['salinity_bulk_wt_pct'], 3)))
            rows.append(('Молярный объём включения, см³/моль', format_value(ex['molar_volume_cm3_mol'], 4)))
            rows.append(('Солёность раствора при Tm клатрата, мас. %', format_value(ex['salinity_at_tm_clath_wt_pct'], 3)))
            rows.append(('Давление при Tm клатрата, бар', format_value(ex['pressure_at_tm_clath_bar'], 2)
                         + ' — внутри включения, не давление захвата'))
            if ex.get('pressure_at_th_co2_bar') is not None:
                rows.append(('Давление при Th CO₂, бар', format_value(ex['pressure_at_th_co2_bar'], 2)
                             + ' — давление насыщения CO₂, не давление захвата'))
                rows.append(('Солёность раствора при Th CO₂, мас. %', format_value(ex['salinity_at_th_co2_wt_pct'], 3)))
            if ex.get('pressure_at_tm_ice_bar') is not None:
                rows.append(('Давление при Tm льда (Q1), бар', format_value(ex['pressure_at_tm_ice_bar'], 2)))
                rows.append(('Солёность раствора при Tm льда (Q1), мас. %', format_value(ex['salinity_at_tm_ice_wt_pct'], 3)))
            for key, label in (('carbonic_fraction_at_th_co2', 'φ при Th CO₂ (расчётная), %'),
                               ('carbonic_fraction_at_tm_clath', 'φ при Tm клатрата (расчётная), %')):
                if ex.get(key) is not None:
                    rows.append((label, format_value(100 * ex[key], 2)))
            if ex.get('isochore'):
                rows.append(('Изохора: уравнение состояния Duan et al. (1995), T °C → P бар',
                             '; '.join(f'{t:.0f} → {p:.0f}' for t, p in ex['isochore'])))
                rows.append(('Прямая по точкам 350–500 °C', f'P = {format_value(ex["isochore_intercept_bar"], 1)} + '
                             f'{format_value(ex["isochore_slope_bar_per_c"], 3)}·T(°C), бар'))
            if ex.get('pressure_solvus_th_total_bar') is not None:
                rows.append(('Давление на линии расслоения при Th общ., бар',
                             format_value(ex['pressure_solvus_th_total_bar'], 1) + ' — растворимость CO₂ по Mao et al. '
                             '(2013) равна валовой доле CO₂'))
            if ex.get('pressure_isochore_th_total_bar') is not None:
                rows.append(('Давление по изохоре при Th общ., бар',
                             format_value(ex['pressure_isochore_th_total_bar'], 1) + ' — '
                             + ex.get('pressure_isochore_th_total_method', '')))
            if ex.get('pressure_th_total_difference_bar') is not None:
                rows.append(('Расхождение двух давлений при Th общ.',
                             f'{format_value(ex["pressure_th_total_difference_bar"], 1)} бар '
                             f'({format_value(ex["pressure_th_total_difference_pct"], 1)} %) — значения не '
                             'взаимозаменяемы'))
            res = ex.get('residuals') or {}
            rows.append(('Решение', ('сошедшееся; ' if ex.get('converged') else 'НЕ сошедшееся; ')
                         + 'невязки уравнений: ' + '; '.join(f'{RESIDUAL_LABELS.get(k, k)} = {v:.1e}'
                                                             for k, v in res.items())))
            for where, fr in (ex.get('phase_fractions') or {}).items():
                rows.append((f'Объёмные доли фаз при {where}',
                             '; '.join(f'{name} {format_value(100 * val, 2)} %' for name, val in fr.items())))
        if 'rho_at_phi_plus_u' in ex:
            rows.append(('Плотность при φ + u / φ − u', f'{format_value(ex["rho_at_phi_plus_u"], 4)} / '
                         f'{format_value(ex["rho_at_phi_minus_u"], 4)} г/см³ (чувствительность к оценке φ)'))
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


# --- Производные расчёты по включению ----------------------------------------------------
PHI_TEMPERATURE_WARN_C = 5.0      # предупреждать, если φ оценена дальше 5 °C от 20 °C
CO2_IMPURITY_WARN_C = 0.4         # Tm CO₂ ниже тройной точки более чем на 0,4 °C


def _bulk_density_outcome(group: list[tuple[dict, Outcome]]) -> tuple[dict, Outcome] | None:
    """Плотность включения по объёмному балансу фаз (этап 1). None — расчёт к включению не относится."""
    from fluid_core.brine import nacl_solution_density_20c, REFERENCE as BRINE_REF
    from fluid_core.salinity import mixture_density_simple

    obs0 = group[0][0]
    co2 = [(o, r) for o, r in group if o.get('kind') == 'Th_CO2']
    if not co2:
        return None                                   # нет Th CO₂ — не углекислотное включение
    phi = obs0.get('carbonic_fraction')
    phi_u = obs0.get('carbonic_fraction_unc')
    phi_t = obs0.get('carbonic_fraction_temp_c')
    ctx = {k: obs0.get(k) for k in ('project_name', 'sample_name', 'mineral_name', 'fia_name', 'inclusion_name',
                                    'project_id', 'inclusion_id')}
    pseudo = dict(ctx, id=None, kind='bulk_density', temperature_c=None, uncertainty_c=None,
                  homogenization_to=None, source='производный расчёт по включению')
    meta = METHODS['volume_balance_density']
    base = dict(kind='bulk_density', method_key='volume_balance_density', model=meta['title'], doi=meta['doi'],
                citation=meta['citation'])

    def fail(msg, extra=None):
        pseudo['extra_inputs'] = extra or {}
        return pseudo, Outcome('error', message=msg, **base)

    ok_co2 = [(o, r) for o, r in co2 if r.status == 'ok']
    sal = [(o, r) for o, r in group if o.get('kind') == 'Tm_clath' and r.status == 'ok']
    extra = {'carbonic_fraction': phi, 'carbonic_fraction_unc': phi_u,
             'carbonic_fraction_method': obs0.get('carbonic_fraction_method'), 'carbonic_fraction_temp_c': phi_t}
    if phi is None:
        return fail('Не указана объёмная доля углекислотной фазы φ включения (контекстное меню включения → '
                    '«Доля углекислотной фазы…»).', extra)
    if not ok_co2:
        return fail('Нет рассчитанной плотности CO₂: расчёт по Th CO₂ заблокирован (см. причину в строке Th CO₂).',
                    extra)
    if len(ok_co2) > 1:
        return fail('У включения несколько рассчитанных Th CO₂; оставьте одно наблюдение — автоматический выбор '
                    'или усреднение не выполняются.', extra)
    if not sal:
        return fail('Нет солёности водной фазы по Tm клатрата (Darling, 1991). Солёность по Tm льда в '
                    'углекислотных включениях не используется (влияние клатрата).', extra)
    if len(sal) > 1:
        return fail('У включения несколько рассчитанных значений Tm клатрата; оставьте одно наблюдение.', extra)
    o_co2, r_co2 = ok_co2[0]
    o_sal, r_sal = sal[0]
    rho_c = r_co2.extras['density_g_cm3']
    s = r_sal.value
    extra.update({'Th_CO2': o_co2.get('temperature_c'), 'homogenization_to': o_co2.get('homogenization_to'),
                  'rho_co2_g_cm3': rho_c, 'Tm_clath': o_sal.get('temperature_c'), 'salinity_wt_pct': s})
    try:
        rho_aq = nacl_solution_density_20c(s)
        rho = mixture_density_simple(rho_c, rho_aq, phi, same_temperature_pressure=True)
    except (ValueError, TypeError) as exc:
        return fail(f'Расчёт невозможен: {exc}', extra)
    extra['rho_brine_20c_g_cm3'] = rho_aq
    out = Outcome('ok', value=rho, unit='г/см³', result_kind=KIND_RESULT_LABEL['volume_balance_density'], **base)
    out.assumptions = ' '.join(meta['assumptions'])
    out.scope = meta['range']
    out.extras.update({'rho_co2_g_cm3': rho_c, 'rho_brine_20c_g_cm3': rho_aq, 'salinity_wt_pct': s,
                       'carbonic_fraction': phi, 'brine_reference': BRINE_REF})
    if phi_u:
        lo = mixture_density_simple(rho_c, rho_aq, min(1.0, phi + phi_u), same_temperature_pressure=True)
        hi = mixture_density_simple(rho_c, rho_aq, max(0.0, phi - phi_u), same_temperature_pressure=True)
        out.extras['rho_at_phi_plus_u'] = lo
        out.extras['rho_at_phi_minus_u'] = hi
    else:
        out.warnings.append('Погрешность φ не указана — диапазон плотности не оценивается, а именно φ обычно '
                            'вносит основную неопределённость.')
    if phi_t is not None and abs(phi_t - 20.0) > PHI_TEMPERATURE_WARN_C:
        out.warnings.append(f'φ оценена при {phi_t:g} °C; плотность раствора взята при 20 °C.')
    tm_co2 = [o.get('temperature_c') for o, _ in group if o.get('kind') == 'Tm_CO2']
    if any(t is not None and t < -56.558 - CO2_IMPURITY_WARN_C for t in tm_co2):
        out.warnings.append('Tm CO₂ ниже тройной точки чистой CO₂: вероятны примеси; плотность углекислотной фазы '
                            'для чистой CO₂ — приближение.')
    out.warnings.append('Плотность — не давление и не изохора: давление по этой величине программа не рассчитывает.')
    pseudo['extra_inputs'] = extra
    return pseudo, out


AQ_NEAR_CRITICAL_C = 30.0         # предупреждать о плотности, если Th ближе 30 °C к Tc (см. сравнение с IAPWS-95)
AQ_TE_OTHER_SALTS_C = -23.0       # Te ниже эвтектики H₂O–NaCl (−21,2 °C) с запасом → другие соли


def _aqueous_outcome(group: list[tuple[dict, Outcome]]) -> tuple[dict, Outcome] | None:
    """Этап 2a: включение H₂O–NaCl (без CO₂) — плотность, Ph при Th, изохора (HokieFlincs)."""
    from fluid_core.h2o_nacl import homogenization_to_liquid
    kinds = {o.get('kind') for o, _ in group}
    if kinds & {'Th_CO2', 'Tm_clath', 'Tm_CO2'}:
        return None                                   # углекислотное включение — не H₂O–NaCl
    th_obs = [(o, r) for o, r in group if o.get('kind') == 'Th_total']
    if not th_obs:
        return None
    obs0 = group[0][0]
    ctx = {k: obs0.get(k) for k in ('project_name', 'sample_name', 'mineral_name', 'fia_name', 'inclusion_name',
                                    'project_id', 'inclusion_id')}
    pseudo = dict(ctx, id=None, kind='aq_pvt', temperature_c=None, uncertainty_c=None, homogenization_to=None,
                  source='производный расчёт по включению')
    meta = METHODS['h2o_nacl_hokieflincs']
    base = dict(kind='aq_pvt', method_key='h2o_nacl_hokieflincs', model=meta['title'], doi=meta['doi'],
                citation=meta['citation'])
    extra: dict = {}

    def fail(msg):
        pseudo['extra_inputs'] = extra
        return pseudo, Outcome('error', message=msg, **base)

    if len(th_obs) > 1:
        return fail('У включения несколько Th общ.; оставьте одно наблюдение — усреднение не выполняется.')
    o_th = th_obs[0][0]
    extra.update({'Th_total': o_th.get('temperature_c'), 'homogenization_to': o_th.get('homogenization_to')})
    ice = [(o, r) for o, r in group if o.get('kind') == 'Tm_ice']
    ice_ok = [(o, r) for o, r in ice if r.status == 'ok']
    if not ice:
        return fail('Нет Tm льда: солёность водно-солевого включения не определена.')
    if not ice_ok:
        return fail('Солёность по Tm льда не рассчитана (см. причину в строке Tm лёд).')
    if len(ice_ok) > 1:
        return fail('У включения несколько Tm льда; оставьте одно наблюдение.')
    o_ice, r_ice = ice_ok[0]
    s = r_ice.value
    extra.update({'Tm_ice': o_ice.get('temperature_c'), 'salinity_wt_pct': s})
    h = o_th.get('homogenization_to')
    if h is None:
        return fail('Не указано направление гомогенизации Th общ. Модель применима только к гомогенизации в '
                    'жидкость; автоматически это не предполагается.')
    if h != 'liquid':
        return fail('Гомогенизация в газ или критическая: корреляции HokieFlincs (жидкая ветвь) неприменимы.')
    try:
        res = homogenization_to_liquid(o_th.get('temperature_c'), s, homogenization_to='liquid')
    except (ValueError, TypeError) as exc:
        return fail(translate_core_message(str(exc)))
    out = Outcome('ok', value=res.density_g_cm3, unit='г/см³', result_kind=KIND_RESULT_LABEL['h2o_nacl_hokieflincs'],
                  **base)
    out.assumptions = ' '.join(meta['assumptions'])
    out.scope = meta['range']
    out.extras.update({'Ph_bar': res.pressure_bar, 'dPdT_bar_per_C': res.slope_bar_per_c,
                       'Tc_C': res.critical_temperature_c, 'salinity_wt_pct': s, 'density_g_cm3': res.density_g_cm3,
                       'isochore': [list(p) for p in res.isochore]})
    out.warnings.append('Ph — давление при гомогенизации (минимальное давление захвата), а не давление захвата.')
    if res.critical_temperature_c - res.th_c < AQ_NEAR_CRITICAL_C:
        out.warnings.append(f'Th в {res.critical_temperature_c - res.th_c:.0f} °C от критической температуры: '
                            'плотность по Bodnar (1983) здесь ненадёжна (для чистой воды до 18 % от IAPWS-95).')
    te = [o.get('temperature_c') for o, _ in group if o.get('kind') == 'Te']
    if any(t is not None and t < AQ_TE_OTHER_SALTS_C for t in te):
        out.warnings.append('Te ниже эвтектики H₂O–NaCl: в растворе есть другие соли; свойства H₂O–NaCl — '
                            'приближение NaCl-эквивалента.')
    pseudo['extra_inputs'] = extra
    return pseudo, out


# --- Этап 2б: строгая модель H₂O–CO₂–NaCl (Steele-MacInnis, 2018), режимы 1–3 ---------------------------------
PVTX_MODES = {1: 'режим 1 — клатрат плавится раньше гомогенизации CO₂ (Tm клатрата ≤ Th CO₂)',
              2: 'режим 2 — CO₂ гомогенизируется раньше плавления клатрата (Th CO₂ < Tm клатрата)',
              3: 'режим 3 — жидкой CO₂ нет: Tm льда и Tm клатрата в присутствии пара'}
RESIDUAL_LABELS = {'volume_cm3_mol': 'равенство объёмов, см³/моль', 'fraction': 'заданная доля φ',
                   'fraction:h2o': 'баланс H₂O (доля фаз)', 'fraction:volume': 'баланс объёма (доля фаз)',
                   'boundary_pressure_bar': 'граница клатрата, бар',
                   'volume_cm3_mol:th_total': 'объём при Th общ., см³/моль', 'fraction:solvus': 'линия расслоения'}
PVTX_SALINITY_WARN_WT = 20.08     # 4,3 моль/кг NaCl — граница модели растворимости Duan & Sun (2003)
PVTX_CLATHRATE_P_WARN_BAR = 1000.0   # выше — прямые изоплеты ур. 22–23 расходятся с Bakker et al. (1996), Q25
PVTX_SOLVUS_P_MAX_BAR = 1500.0    # заявленная область модели Mao et al. (2013)


def _flag_state(obs, key, want, missing, wrong):
    """Сравнить записанный наблюдателем признак фазы с требуемым режимом; ничего не подставляет."""
    v = obs.get(key)
    if v is None:
        missing.append(f'{FLAG_FIELDS[key]} при плавлении клатрата — не указано (нужно: {"да" if want else "нет"})')
    elif bool(v) != want:
        wrong.append(f'{FLAG_FIELDS[key]} при плавлении клатрата: записано «{"да" if v else "нет"}», '
                     f'а режим требует «{"да" if want else "нет"}»')


def _pvtx_outcome(group: list[tuple[dict, Outcome]]) -> tuple[dict, Outcome] | None:
    """Состав, плотность и давления включения H₂O–CO₂–NaCl по строгой модели (режимы 1–3)."""
    from fluid_core import duan1995, h2o_co2_nacl as model

    def of(kind):
        return [o for o, _ in group if o.get('kind') == kind and o.get('temperature_c') is not None]
    clath, co2, ice, th_tot = of('Tm_clath'), of('Th_CO2'), of('Tm_ice'), of('Th_total')
    if not clath and not co2:
        return None                                   # не углекислотное включение
    obs0 = group[0][0]
    ctx = {k: obs0.get(k) for k in ('project_name', 'sample_name', 'mineral_name', 'fia_name', 'inclusion_name',
                                    'project_id', 'inclusion_id')}
    pseudo = dict(ctx, id=None, kind='co2_pvtx', temperature_c=None, uncertainty_c=None, homogenization_to=None,
                  source='производный расчёт по включению')
    meta = METHODS['h2o_co2_nacl_sm2018']
    base = dict(kind='co2_pvtx', method_key='h2o_co2_nacl_sm2018', model=meta['title'], doi=meta['doi'],
                citation=meta['citation'])
    phi, phi_u, phi_t = (obs0.get(k) for k in ('carbonic_fraction', 'carbonic_fraction_unc',
                                               'carbonic_fraction_temp_c'))
    extra: dict = {'carbonic_fraction': phi, 'carbonic_fraction_unc': phi_u,
                   'carbonic_fraction_method': obs0.get('carbonic_fraction_method'),
                   'carbonic_fraction_temp_c': phi_t}

    def fail(msg):
        pseudo['extra_inputs'] = extra
        return pseudo, Outcome('error', message=msg, **base)

    for name, lst in (('Tm клатрата', clath), ('Th CO₂', co2), ('Tm льда', ice), ('Th общ.', th_tot)):
        if len(lst) > 1:
            return fail(f'У включения несколько наблюдений «{name}»; оставьте одно — автоматический выбор или '
                        'усреднение не выполняются.')
    missing: list[str] = []
    wrong: list[str] = []
    mode = None
    if not clath:
        missing.append('Tm клатрата (температура окончательного плавления клатрата CO₂)')
    o_cl = clath[0] if clath else {}
    tm = o_cl.get('temperature_c')
    branch = None
    if co2:
        o_co2 = co2[0]
        th = o_co2['temperature_c']
        extra.update({'Th_CO2': th, 'homogenization_to': o_co2.get('homogenization_to')})
        branch = o_co2.get('homogenization_to')
        if branch in (None, ''):
            missing.append('направление гомогенизации CO₂ (в жидкость или в газ) — автоматически не выбирается')
        elif branch == 'critical':
            return fail('Критическая гомогенизация CO₂: модель определена только для гомогенизации в жидкость '
                        'или в газ.')
        if o_co2.get('co2_purity_confirmed') is not True:
            missing.append('приближение чистой CO₂ не принято явно (флажок у наблюдения Th CO₂)')
        if clath:
            mode = 1 if tm <= th else 2
            _flag_state(o_cl, 'aqueous_brine_present', True, missing, wrong)
            if mode == 1:
                _flag_state(o_cl, 'liquid_co2_present', True, missing, wrong)
                _flag_state(o_cl, 'vapor_co2_present', True, missing, wrong)
            elif branch in ('liquid', 'vapor'):
                _flag_state(o_cl, 'liquid_co2_present', branch == 'liquid', missing, wrong)
                _flag_state(o_cl, 'vapor_co2_present', branch == 'vapor', missing, wrong)
    elif clath:
        mode = 3
        if not ice:
            missing.append('Th CO₂ с направлением гомогенизации (режимы 1–2) либо Tm льда (режим 3, если жидкой CO₂ '
                           'во включении нет)')
        else:
            extra['Tm_ice'] = ice[0]['temperature_c']
        _flag_state(o_cl, 'aqueous_brine_present', True, missing, wrong)
        _flag_state(o_cl, 'liquid_co2_present', False, missing, wrong)
        _flag_state(o_cl, 'vapor_co2_present', True, missing, wrong)
        if o_cl.get('co2_purity_confirmed') is not True:
            missing.append('приближение чистой CO₂ не принято явно (флажок у наблюдения Tm клатрата)')
    if clath:
        extra['Tm_clath'] = tm
    extra['mode'] = mode

    # чем задаётся количество углекислотной фазы: измеренной долей (основной путь) или Th общ.
    o_tot = th_tot[0] if th_tot else None
    tot_liquid = o_tot is not None and o_tot.get('homogenization_to') == 'liquid'
    if o_tot is not None:
        extra.update({'Th_total': o_tot['temperature_c'], 'Th_total_to': o_tot.get('homogenization_to')})
    by_fraction = phi is not None
    if by_fraction:
        if phi_t is None:
            missing.append('температура, при которой оценена доля φ (контекстное меню включения → «Доля '
                           'углекислотной фазы…»)')
    elif o_tot is None:
        missing.append('объёмная доля углекислотных фаз φ с температурой оценки (контекстное меню включения → '
                       '«Доля углекислотной фазы…»); при её отсутствии — Th общ. с гомогенизацией в жидкость')
    elif o_tot.get('homogenization_to') is None:
        missing.append('доля φ не указана, а у Th общ. не указано направление гомогенизации (расчёт по Th общ. '
                       'возможен только при гомогенизации в жидкость)')
    elif not tot_liquid:
        return fail('Доля углекислотных фаз φ не указана, а Th общ. — не в жидкость: расчёт по Th общ. определён '
                    'только для гомогенизации в водную жидкость. Укажите φ.')
    head = 'Строгая модель H₂O–CO₂–NaCl' + (f' ({PVTX_MODES[mode]})' if mode else '')
    if wrong:
        return fail(f'{head}: записанные фазы не соответствуют режиму — ' + '; '.join(wrong) + '. Проверьте '
                    'наблюдения: режим определяется порядком Tm клатрата и Th CO₂ и фазами при плавлении клатрата.')
    if missing:
        return fail(f'{head}. Не хватает данных: ' + '; '.join(missing) + '.')

    def run(fraction):
        kw = (dict(carbonic_fraction=fraction, fraction_temperature_c=phi_t) if by_fraction else
              dict(total_homogenization_c=o_tot['temperature_c'], total_homogenization_to='liquid'))
        if mode == 1:
            return model.mode1(tm, th, branch, **kw)
        if mode == 2:
            return model.mode2(tm, th, branch, **kw)
        return model.mode3(ice[0]['temperature_c'], tm, **kw)

    try:
        r = run(phi)
    except model.ConvergenceError as exc:
        return fail(f'{head}: СХОДИМОСТЬ НЕ ДОСТИГНУТА, результат не выдаётся. {exc}')
    except model.NonPhysicalSolutionError as exc:
        return fail(f'{head}: решение физически недопустимо для этих наблюдений, результат не выдаётся. {exc}')
    except (ValueError, TypeError, ArithmeticError) as exc:
        return fail(f'{head}: {exc}')

    out = Outcome('ok', value=r.density_g_cm3, unit='г/см³', result_kind=KIND_RESULT_LABEL['h2o_co2_nacl_sm2018'],
                  **base)
    out.assumptions = ' '.join(meta['assumptions'])
    out.scope = meta['range']
    ex = out.extras
    ex.update({'mode': mode, 'mode_title': PVTX_MODES[mode],
               'fraction_source': 'измеренная доля φ' if by_fraction else 'Th общ. (доля φ не измерена)',
               'x_h2o': r.x_h2o, 'x_nacl': r.x_nacl, 'x_co2': r.x_co2,
               'salinity_bulk_wt_pct': r.salinity_wt_pct, 'co2_mol_pct_salt_free': r.co2_mol_pct_salt_free,
               'molar_volume_cm3_mol': r.molar_volume_cm3_mol, 'density_g_cm3': r.density_g_cm3,
               'salinity_at_tm_clath_wt_pct': r.salinity_at_tm_clath_wt_pct,
               'pressure_at_tm_clath_bar': r.pressure_at_tm_clath_bar,
               'salinity_at_th_co2_wt_pct': r.salinity_at_th_co2_wt_pct,
               'pressure_at_th_co2_bar': r.pressure_at_th_co2_bar,
               'salinity_at_tm_ice_wt_pct': r.salinity_at_tm_ice_wt_pct,
               'pressure_at_tm_ice_bar': r.pressure_at_tm_ice_bar,
               'carbonic_fraction_at_th_co2': r.carbonic_fraction_at_th_co2,
               'carbonic_fraction_at_tm_clath': r.carbonic_fraction_at_tm_clath,
               'converged': r.converged, 'residuals': dict(r.residuals),
               'phase_fractions': {k: dict(v) for k, v in r.phase_fractions.items()}})
    w = out.warnings
    w.append('Давления при Tm клатрата, Th CO₂ и Tm льда — давления внутри включения при этих фазовых переходах; '
             'это не давление захвата.')
    if not by_fraction:
        w.append('Доля углекислотных фаз не измерена: она найдена из условия гомогенизации в водную жидкость при '
                 f'Th общ. (φ при {"Th CO₂" if mode == 1 else "Tm клатрата"} = '
                 f'{format_value(100 * (r.carbonic_fraction_at_th_co2 if mode == 1 else r.carbonic_fraction_at_tm_clath), 1)} %).')
        if o_tot['temperature_c'] > model.TH_TOTAL_APPROXIMATE_ABOVE_C:
            w.append(f'ОРИЕНТИРОВОЧНО: расчёт по Th общ. выше {model.TH_TOTAL_APPROXIMATE_ABOVE_C:g} °C использует '
                     'объёмные корреляции раствора за пределами их области (потеря точности выше 150–200 °C); состав '
                     'и плотность — ориентировочные. Надёжнее задать измеренную долю φ.')
    elif phi_u:
        sens = []
        for f in (min(0.999, phi + phi_u), max(0.001, phi - phi_u)):
            try:
                sens.append(run(f).density_g_cm3)
            except (ValueError, ArithmeticError):
                sens.append(None)
        ex['rho_at_phi_plus_u'], ex['rho_at_phi_minus_u'] = sens
        if None in sens:
            w.append('При φ ± погрешность одна из границ не имеет допустимого решения — диапазон плотности неполный.')
    else:
        w.append('Погрешность φ не указана — диапазон плотности не оценивается, а именно φ обычно вносит основную '
                 'неопределённость.')
    if mode == 3:
        w.append('Принято, что лёд окончательно плавился в присутствии клатрата и пара (точка Q1); если клатрата при '
                 'плавлении льда не было, режим неприменим.')
    if tm < 0:
        w.append('Tm клатрата ниже 0 °C: растворимость CO₂ (Duan & Sun, 2003) используется ниже заявленной области '
                 '(экстраполяция).')
    if max(r.salinity_at_tm_clath_wt_pct, r.salinity_at_tm_ice_wt_pct or 0) > PVTX_SALINITY_WARN_WT:
        w.append('Солёность раствора выше 4,3 моль/кг (≈ 20 мас. %): вне заявленной области модели растворимости '
                 'CO₂ (Duan & Sun, 2003).')
    if r.pressure_at_tm_clath_bar > PVTX_CLATHRATE_P_WARN_BAR:
        w.append('Давление плавления клатрата выше 1 кбар: граница устойчивости клатрата с жидкой CO₂ в модели — '
                 'прямые линии, расходящиеся с расчётами Bakker et al. (1996) на 2–6 °C.')
    tm_co2 = [o.get('temperature_c') for o, _ in group if o.get('kind') == 'Tm_CO2']
    if any(t is not None and t < -56.558 - CO2_IMPURITY_WARN_C for t in tm_co2):
        w.append('Tm CO₂ ниже тройной точки чистой CO₂: вероятны примеси (CH₄, N₂); модель рассчитана для чистой CO₂.')

    # изохора: давление однофазного флюида того же состава и объёма (правильный перевод °C → K)
    try:
        iso = duan1995.isochore(r.molar_volume_cm3_mol, r.x_h2o, r.x_nacl, r.x_co2)
        ex.update({'isochore': [list(pt) for pt in iso.points], 'isochore_slope_bar_per_c': iso.slope_bar_per_c,
                   'isochore_intercept_bar': iso.intercept_bar})
        if iso.points:
            w.append('Изохора — давление однофазного флюида того же состава и объёма (Duan et al., 1995; 300 °C и '
                     'выше). Давление захвата по ней определяется только при независимой оценке температуры захвата.')
        else:
            w.append('Изохора не выведена: давление уравнения состояния при 300–600 °C вне области 0–6000 бар.')
    except (ValueError, ArithmeticError, ZeroDivisionError) as exc:
        iso = None
        w.append(f'Изохора не рассчитана: {exc}')

    # давления при Th общ.: линия расслоения и изохора — раздельно
    if o_tot is not None:
        t_tot = o_tot['temperature_c']
        if not tot_liquid:
            w.append('Th общ. записана не как гомогенизация в жидкость: давление на линии расслоения не рассчитывается '
                     '(модель определена для гомогенизации в водную жидкость).')
        else:
            p_solv = r.pressure_at_th_total_bar
            if p_solv is None:
                try:
                    p_solv = model.solvus_pressure_bar(t_tot, r.x_h2o, r.x_nacl, r.x_co2)
                except (ValueError, ArithmeticError) as exc:
                    w.append(f'Давление на линии расслоения при Th общ. не рассчитано: {exc}')
            ex['pressure_solvus_th_total_bar'] = p_solv
            if p_solv is not None and p_solv > PVTX_SOLVUS_P_MAX_BAR:
                w.append('Давление на линии расслоения выше 1500 бар — вне заявленной области модели Mao et al. (2013).')
            if r.x_nacl == 0 and t_tot + 273.15 > 523:
                w.append('Солёность строго нулевая: для линии расслоения применён низкотемпературный набор параметров '
                         'Mao et al. (2013) до 647 K (примечание к табл. 4 статьи). При малой ненулевой солёности '
                         'модель переключается на другой набор, поэтому результат может измениться скачком.')
            p_iso = None
            if iso is not None:
                if t_tot >= duan1995.ISOCHORE_T_MIN_C:
                    try:
                        p_iso = duan1995.pressure_bar(t_tot, r.molar_volume_cm3_mol, r.x_h2o, r.x_nacl, r.x_co2)
                        ex['pressure_isochore_th_total_method'] = 'уравнение состояния Duan et al. (1995) при Th общ.'
                    except (ValueError, ArithmeticError):
                        p_iso = None
                else:
                    p_iso = iso.linear_pressure_at(t_tot)
                    ex['pressure_isochore_th_total_method'] = ('ЭКСТРАПОЛЯЦИЯ прямой изохоры из интервала 350–500 °C '
                                                               '(уравнение состояния ниже 300 °C не определено)')
                    w.append('Давление по изохоре при Th общ. ниже 300 °C получено линейной экстраполяцией из интервала '
                             '350–500 °C, а не расчётом по уравнению состояния.')
            ex['pressure_isochore_th_total_bar'] = p_iso
            if p_solv is not None and p_iso is not None:
                ex['pressure_th_total_difference_bar'] = p_iso - p_solv
                ex['pressure_th_total_difference_pct'] = 100 * (p_iso / p_solv - 1)
                w.append('При Th общ. рассчитаны ДВА разных давления: на линии расслоения (Mao et al., 2013) — '
                         f'{format_value(p_solv, 0)} бар и по изохоре (Duan et al., 1995) — {format_value(p_iso, 0)} бар; '
                         f'расхождение {format_value(p_iso - p_solv, 0)} бар ({format_value(100 * (p_iso / p_solv - 1), 0)} %). '
                         'Они получены разными моделями, не взаимозаменяемы и не являются давлением захвата.')
    pseudo['extra_inputs'] = extra
    return pseudo, out


def derive_inclusion_results(items: list[tuple[dict, Outcome]]) -> list[tuple[dict, Outcome]]:
    """Производные результаты по включениям на основе уже рассчитанных наблюдений того же расчёта."""
    groups: dict = {}
    for obs, out in items:
        key = obs.get('inclusion_id')
        if key is not None:
            groups.setdefault(key, []).append((obs, out))
    derived = []
    for group in groups.values():
        for fn in (_bulk_density_outcome, _pvtx_outcome, _aqueous_outcome):
            r = fn(group)
            if r is not None:
                derived.append(r)
    return derived


def calculate_all(observations: list[dict]) -> list[tuple[dict, Outcome]]:
    items = [(o, calculate_observation(o)) for o in observations]
    return items + derive_inclusion_results(items)
