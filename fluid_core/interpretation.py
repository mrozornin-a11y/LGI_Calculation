"""Диагностическая интерпретация наблюдений, по которым количественный расчёт невозможен.

Здесь НЕТ расчёта состава. Функции возвращают структурированное заключение одного из трёх видов:
диагностическая интерпретация (перечень кандидатов), указание на достаточность данных для будущей модели или
указание на недостаточность данных. Отсутствующие измерения не подставляются.

Te (температура первого плавления) — источники:
  Davis D.W., Lowenstein T.K., Spencer R.J. (1990) Geochim. Cosmochim. Acta 54, 591–601,
      DOI 10.1016/0016-7037(90)90355-O;
  Oakes C.S., Bodnar R.J., Simonson J.M. (1990) Geochim. Cosmochim. Acta 54, 603–610,
      DOI 10.1016/0016-7037(90)90356-P;
  Steele-MacInnis M., Ridley J., Lecumberri-Sanchez P., Schlegel T.U., Heinrich C.A. (2016) Earth-Sci. Rev. 159,
      14–35, DOI 10.1016/j.earscirev.2016.04.011;
  Lecumberri-Sanchez P., Steele-MacInnis M., Bodnar R.J. (2015) Geochim. Cosmochim. Acta 148, 34–49,
      DOI 10.1016/j.gca.2014.08.015.
Ограничения, которые обязаны сопровождать любую интерпретацию Te:
  * первое плавление может быть метастабильным;
  * в системах H₂O–NaCl и H₂O–KCl первое плавление наблюдалось до ~15 °C ниже равновесной эвтектики;
  * метастабильность гидратов Ca и Mg может давать крайне низкие Te;
  * сообщавшаяся эвтектика ~−37 °C системы H₂O–NaCl–FeCl₂ не является надёжным однозначным признаком:
    Baldassaro (1998) не смог её подтвердить из-за метастабильной жидкости до ~−196 °C.

Tm CO₂ — источники:
  Thiéry R., Van den Kerkhof A.M., Dubessy J. (1994) Eur. J. Mineral. 6, 753–771, DOI 10.1127/ejm/6/6/0753;
  Thiéry R., Vidal J., Dubessy J. (1994) Geochim. Cosmochim. Acta 58, 1073–1082,
      DOI 10.1016/0016-7037(94)90573-8.
VX-диаграммы этих работ не оцифрованы, коэффициенты по рисункам не восстанавливались: количественного состава
CO₂–CH₄–N₂ модуль не выдаёт.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite

TE_SOURCES = ('Davis, Lowenstein & Spencer (1990), DOI 10.1016/0016-7037(90)90355-O; Oakes, Bodnar & Simonson (1990), '
              'DOI 10.1016/0016-7037(90)90356-P; Steele-MacInnis et al. (2016), DOI 10.1016/j.earscirev.2016.04.011; '
              'Lecumberri-Sanchez et al. (2015), DOI 10.1016/j.gca.2014.08.015')
TM_CO2_SOURCES = ('Thiéry, Van den Kerkhof & Dubessy (1994), DOI 10.1127/ejm/6/6/0753; Thiéry, Vidal & Dubessy (1994), '
                  'DOI 10.1016/0016-7037(94)90573-8')

NACL_EUTECTIC_C = -21.20            # равновесная эвтектика H₂O–NaCl
NACL_KCL_EUTECTIC_C = -22.9         # H₂O–NaCl–KCl (приблизительно)
TE_COMPLEX_BELOW_C = -55.0          # ниже — соль автоматически не назначается
TE_METASTABLE_DEPRESSION_C = 15.0   # наблюдавшееся занижение первого плавления в H₂O–NaCl / H₂O–KCl
CO2_TRIPLE_POINT_C = -56.558        # то же значение, что в fluid_core/co2.py (Span & Wagner, 1996)

TE_COMPOSITION_WARNING = 'Одна Te не определяет количественный солевой состав.'
TE_LIMITATIONS = (
    'Первое плавление может быть метастабильным: наблюдаемая Te не обязана совпадать с равновесной эвтектикой.',
    'В системах H₂O–NaCl и H₂O–KCl первое плавление наблюдалось до ~15 °C ниже равновесной эвтектики.',
    'Метастабильность гидратов Ca и Mg может давать крайне низкие Te.',
    'Сообщавшаяся эвтектика около −37 °C системы H₂O–NaCl–FeCl₂ не является надёжным однозначным признаком: '
    'Baldassaro (1998) не смог её подтвердить из-за метастабильной жидкости до ~−196 °C.',
)
TE_RECOMMENDED = (('Tm_ice', 'Tm льда'), ('Tm_hydrohalite', 'Tm гидрогалита'),
                  ('phase_sequence', 'порядок исчезновения фаз при нагревании'),
                  ('freeze_thaw_repeat', 'повторные циклы замораживания–оттаивания'),
                  ('cryo_raman', 'криогенная КР-спектроскопия'),
                  ('cation_ratios', 'отношения катионов (LA-ICP-MS)'))


@dataclass(frozen=True)
class TeCandidate:
    key: str
    label: str
    window_c: tuple                  # диагностическое окно (мин., макс.), °C
    note: str
    multicomponent: bool             # кандидат указывает на заметную роль CaCl₂ / MgCl₂ / FeCl₂


# Диагностические окна; они намеренно перекрываются и не являются границами фазовых полей.
_TE_WINDOWS = (
    TeCandidate('nacl_dominant', 'преобладание NaCl (H₂O–NaCl)', (-22.2, -20.2),
                f'Около равновесной эвтектики H₂O–NaCl ({NACL_EUTECTIC_C:.2f} °C). Окно перекрывается с эвтектикой '
                f'H₂O–NaCl–KCl (≈ {NACL_KCL_EUTECTIC_C} °C): по Te эти системы не различаются.', False),
    TeCandidate('nacl_kcl', 'NaCl–KCl (H₂O–NaCl–KCl)', (-23.9, -21.9),
                f'Около эвтектики H₂O–NaCl–KCl (≈ {NACL_KCL_EUTECTIC_C} °C); перекрывается с окном H₂O–NaCl.', False),
    TeCandidate('mgcl2_bearing', 'присутствие MgCl₂', (-38.0, -33.0),
                'Область эвтектик MgCl₂-содержащих систем. По Te не отличается от FeCl₂-содержащих систем.', True),
    TeCandidate('fecl2_bearing', 'присутствие FeCl₂', (-38.0, -33.0),
                'Область эвтектик FeCl₂-содержащих систем. По Te не отличается от MgCl₂-содержащих систем; '
                'эвтектика ~−37 °C системы H₂O–NaCl–FeCl₂ не подтверждена (Baldassaro, 1998).', True),
    TeCandidate('cacl2_bearing', 'присутствие CaCl₂ (H₂O–CaCl₂ / H₂O–NaCl–CaCl₂)', (-52.5, -49.5),
                'Около эвтектик H₂O–CaCl₂ и H₂O–NaCl–CaCl₂ (≈ −50…−52 °C).', True),
)


@dataclass(frozen=True)
class TeInterpretation:
    te_c: float
    uncertainty_c: float | None
    interval_c: tuple                # интервал измерения (Te − u, Te + u)
    status: str                      # candidates_identified | metastable_or_complex_system | no_matching_window
    candidates: tuple                # все подходящие кандидаты (TeCandidate); выбор одного не делается
    indicates_multicomponent: bool   # есть указание на CaCl₂/MgCl₂/FeCl₂ или сложную/метастабильную систему
    summary: str
    warnings: tuple
    limitations: tuple = TE_LIMITATIONS
    recommended_data: tuple = ()
    quantitative_composition_available: bool = False
    kind: str = 'diagnostic_interpretation'
    sources: str = TE_SOURCES


def _number(x, name, allow_none=False):
    if x is None and allow_none:
        return None
    if isinstance(x, bool):
        raise TypeError(f'{name}: требуется число')
    x = float(x)
    if not isfinite(x):
        raise ValueError(f'{name}: требуется конечное число')
    return x


def interpret_te(te_c: float, uncertainty_c: float | None = None, observations=None) -> TeInterpretation:
    """Диагностическая интерпретация температуры первого плавления (Te). Это НЕ определение состава.

    uncertainty_c — погрешность измерения: окна сравниваются с интервалом Te ± u. observations — перечень уже
    имеющихся данных по включению (ключи вида 'Tm_ice', 'Tm_hydrohalite', 'cryo_raman', 'cation_ratios', …):
    они исключаются из списка рекомендуемых дополнительных данных. Возвращаются ВСЕ подходящие кандидаты.
    """
    te = _number(te_c, 'Te')
    u = _number(uncertainty_c, 'Погрешность', allow_none=True)
    if u is not None and u < 0:
        raise ValueError('Погрешность не может быть отрицательной')
    lo, hi = te - (u or 0.0), te + (u or 0.0)
    have = set(observations or ())
    recommended = tuple(label for key, label in TE_RECOMMENDED if key not in have)
    warnings = [TE_COMPOSITION_WARNING]
    if u is None:
        warnings.append('Погрешность Te не указана: сравнение с диагностическими окнами выполнено без запаса.')

    if te < TE_COMPLEX_BELOW_C:
        return TeInterpretation(
            te, u, (lo, hi), 'metastable_or_complex_system', (), True,
            f'Te ниже {TE_COMPLEX_BELOW_C:g} °C: метастабильное первое плавление или сложная многокомпонентная '
            'система. CaCl₂ или MgCl₂ автоматически не назначаются.',
            tuple(warnings + ['Крайне низкая Te может быть следствием метастабильности гидратов Ca и Mg, а не '
                              'признаком определённой соли.']),
            recommended_data=recommended)

    candidates = tuple(c for c in _TE_WINDOWS if lo <= c.window_c[1] and hi >= c.window_c[0])
    if any(c.key == 'nacl_dominant' for c in candidates):
        warnings.append(f'Окно H₂O–NaCl перекрывается с эвтектикой H₂O–NaCl–KCl (≈ {NACL_KCL_EUTECTIC_C} °C): '
                        'присутствие KCl по Te не исключается.')
    if {'mgcl2_bearing', 'fecl2_bearing'} <= {c.key for c in candidates}:
        warnings.append('MgCl₂- и FeCl₂-содержащие системы по Te не различаются: оба кандидата равноправны.')
    if NACL_EUTECTIC_C - TE_METASTABLE_DEPRESSION_C <= hi and lo < NACL_EUTECTIC_C - 1.0:
        warnings.append('Te ниже равновесной эвтектики H₂O–NaCl не более чем на ~15 °C: возможно метастабильное '
                        'первое плавление в системе H₂O–NaCl(–KCl) без дополнительных солей.')
    if candidates:
        status = 'candidates_identified'
        summary = 'Кандидаты (выбор одного не делается): ' + '; '.join(c.label for c in candidates) + '.'
    else:
        status = 'no_matching_window'
        if lo > _TE_WINDOWS[0].window_c[1]:
            summary = ('Te выше эвтектики H₂O–NaCl: с хлоридно-натриевой эвтектикой не согласуется. Возможно, первое '
                       'плавление замечено с опозданием либо система иная.')
        else:
            summary = 'Te не попадает ни в одно диагностическое окно: по одной Te система не определяется.'
    multi = any(c.multicomponent for c in candidates)
    if hi < NACL_EUTECTIC_C - TE_METASTABLE_DEPRESSION_C:
        # ниже того, что наблюдалось как метастабильное первое плавление H₂O–NaCl / H₂O–KCl
        multi = True
        if not candidates:
            summary += (' Te более чем на 15 °C ниже эвтектики H₂O–NaCl: чисто хлоридно-натриевой системой не '
                        'объясняется; вероятны дополнительные соли, но какие — по Te не определяется.')
    return TeInterpretation(te, u, (lo, hi), status, candidates, multi, summary, tuple(warnings),
                            recommended_data=recommended)


# --- Tm CO₂ ------------------------------------------------------------------------------------------------------
RAMAN_SPECIES = ('CO2', 'CH4', 'N2')


@dataclass(frozen=True)
class TmCo2Interpretation:
    tm_c: float
    uncertainty_c: float | None
    reference_c: float
    difference_c: float              # Tm − тройная точка чистой CO₂
    temperature_status: str          # consistent_with_pure_CO2_within_measurement | volatile_impurity_suspected |
    #                                  calibration_or_transition_check_required | uncertainty_not_specified
    status: str                      # итог: temperature_status либо одно из указаний на достаточность данных
    raman_species: tuple | None      # что выявила КР-спектроскопия (None — не выполнялась / не указана)
    summary: str
    warnings: tuple
    quantitative_result_available: bool = False
    mole_percent: None = None        # количественный состав не выдаётся
    kind: str = 'diagnostic_interpretation'
    sources: str = TM_CO2_SOURCES
    notes: tuple = field(default_factory=tuple)


def interpret_tm_co2(tm_c: float, uncertainty_c: float | None = None, raman_species=None,
                     th_co2_c: float | None = None, homogenization_direction: str | None = None
                     ) -> TmCo2Interpretation:
    """Диагностическая интерпретация температуры плавления твёрдой CO₂. Состав (мол. %) НЕ рассчитывается.

    raman_species — перечень компонентов, выявленных КР-спектроскопией, из 'CO2', 'CH4', 'N2' (None — данных нет).
    th_co2_c и homogenization_direction ('liquid' | 'vapor') нужны только для вывода о достаточности данных для
    будущей бинарной VX-модели Thiéry et al. (1994).
    """
    tm = _number(tm_c, 'Tm CO₂')
    u = _number(uncertainty_c, 'Погрешность', allow_none=True)
    if u is not None and u < 0:
        raise ValueError('Погрешность не может быть отрицательной')
    th = _number(th_co2_c, 'Th CO₂', allow_none=True)
    if homogenization_direction not in (None, '', 'liquid', 'vapor', 'critical'):
        raise ValueError("Направление гомогенизации: 'liquid', 'vapor', 'critical' или не указано")
    species = None
    if raman_species is not None:
        species = tuple(s for s in RAMAN_SPECIES if s in set(raman_species))
        unknown = set(raman_species) - set(RAMAN_SPECIES)
        if unknown:
            raise ValueError(f'Неизвестные компоненты КР-спектроскопии: {sorted(unknown)}')
    diff = tm - CO2_TRIPLE_POINT_C
    warnings, notes = [], []
    if u is None:
        t_status = 'uncertainty_not_specified'
        summary = (f'Tm CO₂ отличается от тройной точки чистой CO₂ ({CO2_TRIPLE_POINT_C} °C) на {diff:+.2f} °C; '
                   'погрешность измерения не указана, поэтому вывод о чистоте CO₂ не делается.')
    elif abs(diff) <= u:
        t_status = 'consistent_with_pure_CO2_within_measurement'
        summary = (f'Tm CO₂ согласуется с тройной точкой чистой CO₂ ({CO2_TRIPLE_POINT_C} °C) в пределах погрешности '
                   'измерения. Это не доказательство отсутствия примесей.')
    elif diff < 0:
        t_status = 'volatile_impurity_suspected'
        summary = (f'Tm CO₂ ниже тройной точки чистой CO₂ на {-diff:.2f} °C (больше погрешности): вероятна летучая '
                   'примесь. Возможны CH₄ и/или N₂, но одна Tm CO₂ их не различает.')
    else:
        t_status = 'calibration_or_transition_check_required'
        summary = (f'Tm CO₂ выше тройной точки чистой CO₂ на {diff:.2f} °C (больше погрешности): проверьте калибровку '
                   'термостолика и то, какой фазовый переход наблюдался. Как «отрицательная примесь» не трактуется.')
    status = t_status
    has_ch4, has_n2 = bool(species) and 'CH4' in species, bool(species) and 'N2' in species
    if species is None:
        warnings.append('Данных КР-спектроскопии нет: CH₄ и N₂ не различаются, мольные доли не выдаются.')
    elif has_ch4 and has_n2:
        status = 'ternary_requires_quantitative_Raman_and_mixture_EOS'
        summary += (' КР-спектроскопия показывает CO₂ + CH₄ + N₂: тройная система требует количественной '
                    'КР-спектроскопии и смесевого уравнения состояния (не реализовано).')
    elif has_ch4 or has_n2:
        gas = 'CH₄' if has_ch4 else 'N₂'
        if th is not None and homogenization_direction in ('liquid', 'vapor'):
            status = 'data_sufficient_for_future_Thiery_binary_VX_model'
            summary += (f' КР-спектроскопия подтверждает только {gas}; Tm CO₂, Th CO₂ и направление гомогенизации '
                        f'заданы: данных достаточно для будущей бинарной VX-модели CO₂–{gas} (Thiéry et al., 1994). '
                        'Количественный результат пока не рассчитывается.')
        else:
            lacking = [name for name, ok in (('Th CO₂', th is not None),
                                             ('направление гомогенизации CO₂ (в жидкость или в газ)',
                                              homogenization_direction in ('liquid', 'vapor'))) if not ok]
            notes.append(f'Для бинарной VX-модели CO₂–{gas} не хватает: ' + '; '.join(lacking) + '.')
    else:
        notes.append('КР-спектроскопия не выявила CH₄ и N₂.')
        if t_status == 'volatile_impurity_suspected':
            warnings.append('Tm CO₂ понижена, хотя КР-спектроскопия CH₄ и N₂ не выявила: проверьте калибровку, предел '
                            'обнаружения и возможность других летучих компонентов.')
    warnings.append('Мольные доли CH₄ и N₂ по Tm CO₂ не оцениваются.')
    return TmCo2Interpretation(tm, u, CO2_TRIPLE_POINT_C, diff, t_status, status, species, summary, tuple(warnings),
                               notes=tuple(notes))
