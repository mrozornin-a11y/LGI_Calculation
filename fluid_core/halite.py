"""Солёность по температурам растворения галита и плавления гидрогалита в системе H₂O–NaCl.

1. Растворение галита (галит + жидкость + пар → жидкость + пар).
   Sterner S.M., Hall D.L., Bodnar R.J. (1988) Geochim. Cosmochim. Acta 52, 989–1005,
   DOI 10.1016/0016-7037(88)90254-2; кривая галит + жидкость + пар, 0,1 ≤ T ≤ 801 °C:

       wt = 26,242 + 0,4928·ψ + 1,42·ψ² − 0,223·ψ³ + 0,04129·ψ⁴ + 0,006295·ψ⁵ − 0,001967·ψ⁶ + 0,0001112·ψ⁷,
       ψ = T/100.

   Используется именно эта запись (коэффициент при ψ² равен +1,42, член +0,006295·ψ⁵ присутствует, старший
   коэффициент 0,0001112); вторичные перепечатки с другими значениями не применяются.
   Полином описывает растворение В ПРИСУТСТВИИ ПАРА. Если пар к моменту растворения галита уже исчез,
   растворимость зависит от давления и нужна другая модель — количественный результат не выдаётся.

2. Плавление гидрогалита, бинарный предел H₂O–NaCl.
   Steele-MacInnis M., Bodnar R.J., Naden J. (2011) Geochim. Cosmochim. Acta 75, 21–40,
   DOI 10.1016/j.gca.2010.10.002, ур. 2 (рукопись, с. 14), коэффициенты — табл. 2 (рукопись, с. 51).
   Общая структура ур. 2 для поля гидрогалита (Ψ — массовое отношение NaCl/(NaCl + CaCl₂), x = T + 52):

       S = a0 + a1·x + a2·x² + a3·Ψ + a4·Ψ² + a5·Ψ³ + a6·Ψ·x² + a7·Ψ·x³ + a8·Ψ²·x,

   S — мольная доля соли. Здесь реализован ТОЛЬКО предел Ψ = 1 (соль — чистый NaCl); Ψ пользователем не
   задаётся. Полная инверсия H₂O–NaCl–CaCl₂ не реализована. Область: от эвтектики (−21,2 °C) до перитектики
   (+0,1 °C); экстраполяция не выполняется.

Функции чистые и ничего не округляют; округление — дело интерфейса.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

HALITE_REFERENCE = ('Sterner S.M., Hall D.L., Bodnar R.J. (1988) Geochim. Cosmochim. Acta 52, 989–1005, '
                    'DOI 10.1016/0016-7037(88)90254-2')
HYDROHALITE_REFERENCE = ('Steele-MacInnis M., Bodnar R.J., Naden J. (2011) Geochim. Cosmochim. Acta 75, 21–40, '
                         'DOI 10.1016/j.gca.2010.10.002, ур. 2, табл. 2 (предел Ψ = 1)')

HALITE_T_MIN_C = 0.1
HALITE_T_MAX_C = 801.0
_HALITE = (26.242, 0.4928, 1.42, -0.223, 0.04129, 0.006295, -0.001967, 0.0001112)

HYDROHALITE_T_MIN_C = -21.2      # эвтектика H₂O–NaCl
HYDROHALITE_T_MAX_C = 0.1        # перитектика гидрогалит → галит + жидкость
_HH = (0.06039097042, -2.967800E-5, 7.0463278E-6, 1.237133E-3, -1.290978E-3, -5.219129E-3, -3.178747E-6,
       -1.408898E-7, 1.0353807E-3)
M_NACL = 58.44277                # молярные массы, принятые в проекте (как в fluid_core/co2_brine.py)
M_H2O = 18.0152

NO_VAPOR_MESSAGE = ('Опубликованный полином описывает растворение галита в присутствии пара (галит + жидкость + пар). '
                    'Если пар к моменту растворения уже отсутствует, растворимость зависит от давления и требуется '
                    'другая модель; количественный результат не выдаётся.')
MULTICOMPONENT_MESSAGE = ('Одной Tm гидрогалита недостаточно для определения состава многокомпонентной системы; '
                          'бинарная солёность H₂O–NaCl не рассчитывается.')


@dataclass(frozen=True)
class SalinityResult:
    status: str                      # ok | no_quantitative_result
    temperature_c: float
    salinity_wt_pct_nacl: float | None
    mole_fraction_nacl: float | None
    reason: str                      # причина отсутствия количественного результата
    method: str
    reference: str


def _temperature(value, name):
    if isinstance(value, bool):
        raise TypeError(f'{name}: требуется число')
    t = float(value)
    if not isfinite(t):
        raise ValueError(f'{name}: требуется конечное число')
    return t


def _tri(value, name):
    if value not in (True, False, None):
        raise TypeError(f'{name}: True (да), False (нет) или None (не указано)')
    return value


def halite_liquidus_wt_pct(t_c: float) -> float:
    """Мас. % NaCl на кривой галит + жидкость + пар при температуре t (°C), Sterner et al. (1988)."""
    t = _temperature(t_c, 'T раств. галита')
    if not HALITE_T_MIN_C <= t <= HALITE_T_MAX_C:
        raise ValueError(f'Уравнение Sterner et al. (1988) применимо при {HALITE_T_MIN_C:g} ≤ T ≤ '
                         f'{HALITE_T_MAX_C:g} °C')
    psi = t / 100
    return sum(c * psi ** i for i, c in enumerate(_HALITE))


def halite_dissolution_salinity(t_diss_halite_c: float, vapor_present_at_transition: bool | None) -> SalinityResult:
    """Солёность по температуре растворения галита. Количественный результат — только если пар присутствует.

    vapor_present_at_transition: True — при растворении галита во включении есть пар; False — пара уже нет;
    None — не указано. При False и None возвращается status = 'no_quantitative_result' с объяснением.
    """
    t = _temperature(t_diss_halite_c, 'T раств. галита')
    vapor = _tri(vapor_present_at_transition, 'Присутствие пара')
    method = 'галит + жидкость + пар → жидкость + пар'
    if vapor is not True:
        why = ('Пар при растворении галита отсутствует. ' if vapor is False else
               'Не указано, присутствует ли пар при растворении галита. ') + NO_VAPOR_MESSAGE
        return SalinityResult('no_quantitative_result', t, None, None, why, method, HALITE_REFERENCE)
    wt = halite_liquidus_wt_pct(t)
    x = (wt / M_NACL) / (wt / M_NACL + (100 - wt) / M_H2O)
    return SalinityResult('ok', t, wt, x, '', method, HALITE_REFERENCE)


def hydrohalite_liquidus_mole_fraction(t_c: float) -> float:
    """Мольная доля NaCl в растворе на ликвидусе гидрогалита, бинарный предел (Ψ = 1) ур. 2."""
    t = _temperature(t_c, 'Tm гидрогалита')
    if not HYDROHALITE_T_MIN_C <= t <= HYDROHALITE_T_MAX_C:
        raise ValueError(f'Бинарная ветвь плавления гидрогалита: {HYDROHALITE_T_MIN_C:g} ≤ Tm ≤ '
                         f'+{HYDROHALITE_T_MAX_C:g} °C; экстраполяция не выполняется')
    a0, a1, a2, a3, a4, a5, a6, a7, a8 = _HH
    x = t + 52
    # ур. 2 при Ψ = 1: a3·Ψ + a4·Ψ² + a5·Ψ³ → a3 + a4 + a5; a6·Ψ·x² → a6·x²; a7·Ψ·x³ → a7·x³; a8·Ψ²·x → a8·x
    return a0 + a1 * x + a2 * x ** 2 + a3 + a4 + a5 + a6 * x ** 2 + a7 * x ** 3 + a8 * x


def hydrohalite_melting_salinity(tm_hydrohalite_c: float, phase_identified: bool | None,
                                 multicomponent_salts_indicated: bool = False) -> SalinityResult:
    """Солёность по температуре окончательного плавления гидрогалита (только бинарная система H₂O–NaCl).

    phase_identified: True — плавящаяся фаза уверенно определена как гидрогалит; False / None — нет / не указано.
    multicomponent_salts_indicated: True, если есть признак или подтверждение заметной роли CaCl₂, MgCl₂ или
    FeCl₂ (например, по интерпретации Te или внешним данным) — тогда бинарный расчёт не выполняется.
    """
    t = _temperature(tm_hydrohalite_c, 'Tm гидрогалита')
    identified = _tri(phase_identified, 'Определение фазы')
    if not isinstance(multicomponent_salts_indicated, bool):
        raise TypeError('multicomponent_salts_indicated: True или False')
    method = 'плавление гидрогалита, бинарный предел H₂O–NaCl (Ψ = 1)'

    def no(reason):
        return SalinityResult('no_quantitative_result', t, None, None, reason, method, HYDROHALITE_REFERENCE)
    if identified is not True:
        return no(('Плавящаяся фаза не определена как гидрогалит. ' if identified is False else
                   'Не указано, определена ли плавящаяся фаза как гидрогалит. ')
                  + 'Без уверенного определения фазы солёность по этой температуре не рассчитывается.')
    if multicomponent_salts_indicated:
        return no(MULTICOMPONENT_MESSAGE)
    s = hydrohalite_liquidus_mole_fraction(t)
    wt = 100 * (s * M_NACL) / (s * M_NACL + (1 - s) * M_H2O)
    return SalinityResult('ok', t, wt, s, '', method, HYDROHALITE_REFERENCE)
