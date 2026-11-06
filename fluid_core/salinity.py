"""Validated preliminary microthermometric salinity converters.

Pure Python, no third-party dependencies. Not a complete EOS or chemical assay.
"""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class Calculation:
    method: str
    temperature_c: float
    salinity_wt_pct_nacl_eq: float
    doi: str
    assumption: str
    scope: str


def _temperature(value: float) -> float:
    if isinstance(value, bool):
        raise TypeError('Temperature must be numeric, not boolean')
    v = float(value)
    if not isfinite(v):
        raise ValueError('Temperature must be finite')
    return v


def bodnar_1993(ice_melting_c: float) -> Calculation:
    """NaCl-equivalent salinity from final ice melting temperature (°C).

    Binary H2O–NaCl approximation, ice-liquid branch up to about -21.1 °C.
    No chemical speciation is inferred.
    """
    t = _temperature(ice_melting_c)
    if not -21.1 <= t <= 0.0:
        raise ValueError('Bodnar ice-melting conversion requires -21.1 <= Tm_ice <= 0 °C; consider other phase equilibria outside this interval')
    dt = -t
    w = 1.78 * dt - 0.0442 * dt**2 + 0.000557 * dt**3
    return Calculation('Bodnar (1993)', t, w,
        '10.1016/0016-7037(93)90378-A',
        'Final ice melting is assigned to the H2O-NaCl ice-liquid branch.',
        'NaCl-equivalent wt% of aqueous solution, not identification of dissolved ions.')


def darling_1991(clathrate_melting_c: float, *,
                 liquid_co2_present: bool,
                 vapor_co2_present: bool,
                 aqueous_brine_present: bool) -> Calculation:
    """NaCl-equivalent salinity of aqueous part from final CO2-clathrate melting.

    Requires coexistence of liquid CO2, vapor CO2, and brine at melting.
    Validated empirical range: -10 through +10 °C.
    """
    t = _temperature(clathrate_melting_c)
    if not -10.0 <= t <= 10.0:
        raise ValueError('Darling clathrate conversion requires -10 <= Tm_clath <= 10 °C')
    if not all((liquid_co2_present, vapor_co2_present, aqueous_brine_present)):
        raise ValueError('Darling requires liquid CO2 + vapor CO2 + aqueous brine present during final clathrate melting')
    w = 0.00098241 * (10.0 - t) * (t**2 + 45.385*t + 1588.75)
    return Calculation('Darling (1991)', t, w,
        '10.1016/0016-7037(91)90079-K',
        'CO2-clathrate melts in the presence of liquid CO2, CO2 vapor, and brine.',
        'NaCl-equivalent wt% relative to aqueous-salt portion only; not bulk inclusion salinity.')


def mixture_density_simple(co2_density_g_cm3: float, brine_density_g_cm3: float,
                            co2_volume_fraction: float, *,
                            same_temperature_pressure: bool) -> float:
    """Arithmetic volume-weighted balance, not an EOS.

    Volumes/densities MUST all refer to the same T,P; not suitable for
    casually mixing bubble area fractions measured at room temperature
    with phase densities at homogenization temperature.
    """
    a, b, phi = map(_temperature, (co2_density_g_cm3, brine_density_g_cm3, co2_volume_fraction))
    if not same_temperature_pressure:
        raise ValueError('All densities and volume fractions must refer to the same temperature and pressure')
    if a <= 0 or b <= 0 or not 0 <= phi <= 1:
        raise ValueError('Densities must be positive and phase volume fraction in [0,1]')
    return phi*a+(1-phi)*b
