# Fluid Inclusion Core — pre-release 0.2

**Research/development prototype. NOT validated software for publication-ready fluid inclusion pressure or composition estimates.**

## What's included

- `fluid_core/salinity.py`: Bodnar (1993) ice-melting NaCl-equivalent salinity, Darling (1991) CO₂-clathrate-melting NaCl-equivalent salinity, conditional mass-volume balance check.
- `fluid_core/co2.py`: **pure CO₂** density and saturation pressure at a measured CO₂ partial homogenization temperature for **explicit liquid/vapor homogenization branch**. Uses CoolProp (`HEOS`/CO₂) as an optional back-end; no copied EOS coefficients.
- `fluid_core/batch.py`: UTF-8 CSV processing that records measurement and method, and flags invalid inputs per row.
- `tests/`: formula substitution tests, applicability checks, and **conditional** backend consistency check.
- `docs/`: scientific assumptions, staged development brief for Claude Code, and outstanding validation.

## Running on modern Windows with Python

```bat
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-optional.txt
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m fluid_core examples\example_input.csv examples\results.csv
```

Without installing CoolProp, the salinity operations work; CO₂ numerical calculations will return a clear per-row error. Tests can still run, but the CO₂-backend test will be **skipped**. This is not a passing CO₂ validation.

Do not run this development environment on the Linkam Windows XP acquisition computer. Use a modern research PC for thermodynamic calculations.

## Input

`method`: `bodnar`, `darling`, `co2`. `temperature_c` is °C with decimal point or comma (within a quoted CSV field). For Darling, confirm coexistence of liquid CO₂, CO₂ vapor, and aqueous phase **at the clathrate disappearance**. For pure CO₂ density, `homogenization_to` is `liquid` or `vapor` and `co2_purity_confirmed=true` means the operator explicitly accepts the pure-CO₂ approximation (it is **not proof** of composition).

## Important limitations

1. These salinities are NaCl equivalents, **not** chemical analyses.
2. CO₂ partial homogenization is not complete inclusion homogenization. CO₂ saturated phase pressure at Th_CO2 is **not** trapping pressure.
3. The two CO₂ saturation densities are distinct for temperatures below the critical point; choosing the wrong branch produces a different density. If CO₂ has significant CH₄, N₂ etc., this model does not apply.
4. `mixture_density_simple` assumes densities and volume proportions all refer to the same T/P. It does not infer bulk density from a room-temperature image.
5. The critical temperature guard of 0.10 °C is a **conservative software policy**, not a published fixed uncertainty threshold. A validated release needs instrument-specific calibration and uncertainty propagation.
6. Current test values for salinity derive from equation substitution. They are **not** independent experimental reference points.
7. **No** H₂O–NaCl EOS, H₂O–CO₂–NaCl PVT, trapping pressures, isochore solver, Raman composition, or multi-salt speciation is claimed to be implemented.

## Scientific sources

- Bodnar R.J. (1993). DOI: https://doi.org/10.1016/0016-7037(93)90378-A
- Darling R.S. (1991). DOI: https://doi.org/10.1016/0016-7037(91)90079-K
- Span & Wagner (1996). DOI: https://doi.org/10.1063/1.555991
- CoolProp API: https://coolprop.org/coolprop/HighLevelAPI.html
- CoolProp CO₂: https://coolprop.org/fluid_properties/fluids/CarbonDioxide.html

See `docs/` for planned scientific verification and instructions for Claude Code.
