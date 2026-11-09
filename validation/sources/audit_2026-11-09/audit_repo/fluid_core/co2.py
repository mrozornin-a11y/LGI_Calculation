"""Pure CO2 saturation-state calculations for fluid-inclusion microthermometry.

CoolProp is an OPTIONAL dependency. This module calculates saturated *pure CO2*
properties based on an observed homogenization branch, NOT a bulk H2O-CO2-NaCl
inclusion density, total pressure of trapping, or total inclusion isochore.
"""
from dataclasses import dataclass
from math import isfinite

TRIPLE_POINT_C = 216.592 - 273.15
CRITICAL_POINT_C = 304.1282 - 273.15
# This conservative guard protects users against ambiguous observations extremely
# close to the critical region; it is a provisional project rule, NOT an EOS limit.
DEFAULT_CRITICAL_GUARD_C = 0.10


@dataclass(frozen=True)
class Co2SaturationResult:
    temperature_c: float
    homogenization_to: str
    density_g_cm3: float
    saturation_pressure_bar: float
    molar_volume_cm3_mol: float
    critical_proximity_c: float
    backend: str
    backend_version: str
    model_reference: str
    note: str


def pure_co2_saturation(temperature_c: float, homogenization_to: str,
                        *, co2_purity_confirmed: bool,
                        critical_guard_c: float = DEFAULT_CRITICAL_GUARD_C) -> Co2SaturationResult:
    """Saturated phase density and CO2 vapor pressure at Th_CO2 (°C).

    homogenization_to is 'liquid' or 'vapor'. Observing disappearance of a
    bubble into liquid requires Q=0; disappearance of liquid into gas Q=1.
    Density is pure CO2 density at the CO2 L-V saturation boundary; pressure
    is the saturation pressure there, NOT pressure of mineral formation.
    """
    if isinstance(temperature_c, bool):
        raise TypeError('Temperature must be numeric')
    t = float(temperature_c)
    if not isfinite(t):
        raise ValueError('Temperature must be finite')
    if homogenization_to not in ('liquid', 'vapor'):
        raise ValueError("Homogenization branch must be explicitly 'liquid' or 'vapor'")
    if co2_purity_confirmed is not True:
        raise ValueError('Pure CO2 approximation must be explicitly accepted; contaminants require a mixture model')
    guard = float(critical_guard_c)
    if not isfinite(guard) or guard < 0:
        raise ValueError('Critical guard must be a finite nonnegative value')
    if t <= TRIPLE_POINT_C:
        raise ValueError('CO2 liquid-vapor saturation is not defined at/below its triple point')
    if t >= CRITICAL_POINT_C:
        raise ValueError('CO2 liquid-vapor branches merge at the critical point')
    if (CRITICAL_POINT_C-t) <= guard:
        raise ValueError('Too near critical point for routine branch identification: confirm data and use specialist analysis')
    try:
        import CoolProp
        from CoolProp.CoolProp import PropsSI
    except ImportError as exc:
        raise RuntimeError('Optional dependency CoolProp is required: python -m pip install CoolProp') from exc
    kelvin = t + 273.15
    quality = 0 if homogenization_to == 'liquid' else 1
    rho_kg_m3 = PropsSI('Dmass', 'T', kelvin, 'Q', quality, 'CO2')
    pressure_pa = PropsSI('P', 'T', kelvin, 'Q', quality, 'CO2')
    molar_mass_kg_mol = PropsSI('M', 'T', kelvin, 'Q', quality, 'CO2')
    if not all(isfinite(x) and x > 0 for x in (rho_kg_m3, pressure_pa, molar_mass_kg_mol)):
        raise ArithmeticError('Thermodynamic backend returned invalid results')
    molar_volume_cm3_mol = molar_mass_kg_mol / rho_kg_m3 * 1e6
    return Co2SaturationResult(
        temperature_c=t, homogenization_to=homogenization_to,
        density_g_cm3=rho_kg_m3/1000.0, saturation_pressure_bar=pressure_pa/1e5,
        molar_volume_cm3_mol=molar_volume_cm3_mol,
        critical_proximity_c=CRITICAL_POINT_C-t, backend='CoolProp HEOS / CO2',
        backend_version=CoolProp.__version__,
        model_reference='Span & Wagner (1996), DOI:10.1063/1.555991; implementation via CoolProp',
        note='Only the pure-CO2 saturation state; not trapping P or bulk inclusion density.'
    )

