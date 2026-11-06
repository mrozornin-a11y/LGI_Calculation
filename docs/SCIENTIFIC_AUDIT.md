# Scientific scope and validation dossier — 0.2

## Inputs: evidence chain

Original source set: Prokofyev & Samsonov (2022) textbook; laboratory method narrative (`Текст.doc`); calculation workbook (`Методика расчетов.xlsx`); research memo (`Научно-техническое исследование концепции современной программы термобарогеохимических расчётов.pdf`). Do not mistake the memo for primary thermodynamic data.

### Current methods

| Operation | Inputs | Output | Status | Mandatory conditions |
|---|---|---|---|---|
| Bodnar 1993 | Final ice melting T °C | aqueous wt% NaCl-equivalent | Implemented, equation substitution tested | Approximate binary H₂O–NaCl ice-liquid field; -21.1 to 0 °C |
| Darling 1991 | Final CO₂ clathrate melting T °C | aqueous wt% NaCl-equivalent | Implemented, equation substitution tested | aqueous solution + liquid CO₂ + CO₂ vapor coexist at transition; -10 to 10 °C |
| Pure CO₂ saturation | partial CO₂ homogenization T °C and liquid/vapor branch | pure CO₂ density, saturation pressure, molar volume | Implemented adapter; backend numerical tests only when CoolProp installed | pure-CO₂ assumption; above CO₂ triple point and below critical point; validated branch |
| Simple phase density balance | densities and volume fractions at identical T/P | mean density | Implemented as conditional sanity check | NOT a PVT solver or measurement-based bulk density |

## Conditional and unavailable outputs

- No NaCl, CaCl₂, MgCl₂ or FeCl₂ concentrations can be uniquely inferred from a single eutectic temperature.
- In particular, the laboratory narrative's Mg–Na–Fe chloride lists are **hypotheses** inferred from phase behavior, not quantitative compositional measurements.
- For true H₂O–NaCl–CO₂ bulk density or trapping P one needs a constrained phase-equilibrium/mass-balance model and enough independent measured quantities (typically with phase relationships, and sometimes Raman or composition measurements).
- No default conversion of Th to formation T, and no default additive P_CO2 + P_H2O trapping pressure.
- Pending: origin of numerical lookups marked 9.1–9.3, 9.5, 9.12 and 9.13 in the historical sheet.

## Independent validation before scientific release (NOT completed)

1. Obtain source tabulated pure CO₂ saturation densities and pressures at 0, 10, 20, 25, 30 °C from NIST/REFPROP/primary EOS, and check both branches with numerical tolerances and exact CoolProp version. At the critical region verify expected branch convergence and uncertainty behavior.
2. Benchmark Bodnar and Darling against source tabulated experimental points, not just formula substitution.
3. Validate instrument uncertainty at measured temperatures against documented Linkam calibration standard and replicate measurements. Propagate uncertainty through both formula and CO₂ EOS.
4. Verify the true meaning of CO₂ phase percentage in the lab examples (volume vs area; temperature of observation); check original tables and historical pressures.
5. Later: implement H₂O–NaCl Driesner 2007 and compare with AqSo_NaCl; implement H₂O–CO₂–NaCl only after obtaining full model description and independent reference calculations. No invented fit coefficients.
6. Validate data provenance (sample, inclusion, assemblage, instrument, calibration, source model, model version, calculation timestamp).

## Sources to retrieve/verify in next research phase

- Driesner & Heinrich (2007), Part I DOI 10.1016/j.gca.2006.01.033; Driesner (2007), Part II DOI 10.1016/j.gca.2007.05.026.
- Steele-MacInnis (2018), DOI 10.1016/j.chemgeo.2018.08.022.
- Mao et al. (2015), DOI 10.1016/j.apgeochem.2015.01.003.
- Steele-MacInnis et al. (2011), DOI 10.1016/j.gca.2010.10.002 — система H₂O–NaCl–CaCl₂ (уточнение аудита 2026-11-06).
- Liu et al. (2024) PyPitzer DOI 10.1016/j.chemgeo.2023.121863.

## A caution about changing CO₂ standards

A 2026 NIST report describes an updated CO₂ equation of state. Its existence does **not** automatically invalidate Span–Wagner (1996), nor does it justify switching formulae without benchmarking. Version-pin the thermodynamic backend and retain reproducible records.
