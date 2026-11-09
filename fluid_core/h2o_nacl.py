"""PVTX-свойства водно-солевых включений H₂O–NaCl при гомогенизации жидкость–пар в жидкость (этап 2a).

Набор корреляций программы HOKIEFLINCS_H2O-NACL (Steele-MacInnis, Lecumberri-Sanchez & Bodnar, 2012,
Computers & Geosciences 49, 334–337, DOI 10.1016/j.cageo.2012.01.022):

* давление на кривой жидкость–пар при Th — Atkinson (2002, MSc thesis, Virginia Tech); коэффициенты перенесены
  из таблиц программы HOKIEFLINCS (опубликованное приложение к статье 2012 г.);
* плотность жидкости при Th (= плотность включения) — Bodnar (1983), Econ. Geol. 78, 535–542, в форме,
  используемой HOKIEFLINCS;
* наклон изохоры dP/dT в однофазной области — Bodnar & Vityk (1994), ур. 4–7 (коэффициенты совпадают в главе
  и в программе);
* критическая температура — Knight & Bodnar (1989), ур. 8 у Bodnar & Vityk (1994).

Изохора принимается линейной: P(T) = Ph + dP/dT·(T − Th) (так в HOKIEFLINCS; Bodnar & Vityk, 1994).
Солёность — NaCl-эквивалент; для растворов с другими солями это приближение.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite

MODEL_REFERENCE = ('Steele-MacInnis M., Lecumberri-Sanchez P., Bodnar R.J. (2012) HokieFlincs_H2O-NaCl. '
                   'Computers & Geosciences 49, 334–337, DOI 10.1016/j.cageo.2012.01.022; '
                   'Atkinson A.B. (2002) MSc thesis, Virginia Tech; Bodnar R.J. (1983) Econ. Geol. 78, 535–542; '
                   'Bodnar R.J., Vityk M.O. (1994) in: Fluid Inclusions in Minerals, Methods and Applications, '
                   'p. 117–130; Knight C.L., Bodnar R.J. (1989) GCA 53, 3–8')
TH_MIN_C = 50.0            # нижняя граница уравнения наклона изохоры (Bodnar & Vityk, 1994)
TH_MAX_C = 700.0           # верхняя граница плотности и наклона (Bodnar & Vityk, 1994; HOKIEFLINCS)
S_MAX_WT_PCT = 40.0        # уравнение наклона: 0–40 мас. % NaCl
P_MAX_BAR = 6000.0         # изохоры по экспериментальным данным до 6 кбар

# log10(P, бар) = Σ c[i][j]·Tᶦ·Xʲ, T = (Th + 273,15)/100, X = мас. % NaCl / 100.
# Три интервала по Th: [−21,2; 300), [300; 484), [484; 1500) °C. Строки — степени T (0…7), столбцы — X (0…7).
_ATKINSON = (
    (300.0, (
        (-27.2444260945847, -3.43823854919821, 0, 49.6470810423974, 284.920532084465, -671.468924936888,
         -306.420824097701, -476.391283161769),
        (19.6752698743832, 2.94599944070388, -5.05958726370657, -78.057932502234, 0, 272.541674619991,
         191.281847960897, 0),
        (-6.03987279418686, -1.02712250242286, 5.3605248349362, 18.9371135629599, -27.5731923339991,
         -43.6261697756668, 0, 0),
        (1.05318996126294, 0.132241696257544, -1.43460393380215, -0.517812895404853, 4.28981312806579, 0, 0, 0),
        (-0.107523830798341, 0, 0.115824432759682, -0.147543794540513, 0, 0, 0, 0),
        (0.0063216048751384, -0.000792743415349166, 0, 0, 0, 0, 0, 0),
        (-0.000201391014431089, 0, 0, 0, 0, 0, 0, 0),
        (2.9370853393422e-06, 0, 0, 0, 0, 0, 0, 0),
    )),
    (484.0, (
        (-7.25091694178014, 52.7356253268118, -95.139589091999, 237.00133358832, -270.853923550159, 0,
         -645.843502315573, 411.125432162485),
        (2.91847163119225, -30.0742277771278, 41.0055099275695, -82.6121950337547, 86.8864476861164,
         85.0303689746524, -24.1431916305905, 0),
        (-0.282727704099067, 5.98143068258883, -5.87588111777108, 7.89995198785004, -10.886118260654, 0, 0, 0),
        (0.00898343968706551, -0.436696998416016, 0.27654361988714, 0, 0, 0, 0, 0),
        (0, 0, 0, -0.0074586977134027, 0, 0, 0, 0),
        (0, 0.000828114542697018, 0, 0, 0, 0, 0, 0),
        (1.5228510009732e-06, 0, 0, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0, 0, 0),
    )),
    (1500.0, (
        (-10.1708289018151, 0, 11.2757426837744, -36.8724870227751, 194.961125252, -412.422321803683,
         386.510614816185, -139.824224670799),
        (4.7809083340614, -0.40967075242513, -4.54787095348135, 0, 7.95552629364737, -6.37018268058654,
         0.988511643702363, 0),
        (-0.739844995911952, 0.253297767997384, 0.47135407604605, -0.945923182349318, 0.546929925768266, 0, 0, 0),
        (0.0610381966266658, -0.0345961482768031, 0.0366507031096144, -0.0221690359176769, 0, 0, 0, 0),
        (-0.00273833143331212, 0.000309690020876693, 0, 0.000111317870749135, 0, 0, 0, 0),
        (8.04057534572992e-05, -5.651762407103e-06, 0, 0, 0, 0, 0, 0),
        (-1.277595020522e-06, 0, 0, 0, 0, 0, 0, 0),
        (8.9750622073e-09, 0, 0, 0, 0, 0, 0, 0),
    )),
)


def _check(value, name):
    if isinstance(value, bool):
        raise TypeError(f'{name} must be numeric')
    v = float(value)
    if not isfinite(v):
        raise ValueError(f'{name} must be finite')
    return v


def homogenization_pressure_bar(th_c: float, salinity_wt_pct: float) -> float:
    """Давление на кривой жидкость–пар раствора при Th, бар (Atkinson, 2002)."""
    th = _check(th_c, 'Th')
    s = _check(salinity_wt_pct, 'Salinity')
    if not -21.2 <= th < 1500.0:
        raise ValueError('Atkinson vapour-pressure equation covers -21.2 to 1500 °C')
    coeffs = next(c for upper, c in _ATKINSON if th < upper)
    t = (th + 273.15) / 100.0
    x = s / 100.0
    log_p = sum(c * t ** i * x ** j for i, row in enumerate(coeffs) for j, c in enumerate(row) if c)
    return 10.0 ** log_p


def liquid_density_g_cm3(th_c: float, salinity_wt_pct: float) -> float:
    """Плотность жидкости на кривой жидкость–пар при Th (= плотность включения), г/см³ (Bodnar, 1983)."""
    t = _check(th_c, 'Th') / 100.0
    s = _check(salinity_wt_pct, 'Salinity') / 10.0
    return (0.9923 - 0.030512 * t ** 2 - 0.00021977 * t ** 4 + 0.086241 * s - 0.041768 * t * s
            + 0.014825 * t ** 2 * s + 0.001446 * t ** 3 * s - 0.0000000030852 * t ** 8 * s + 0.013051 * t * s ** 2
            - 0.0061402 * t ** 2 * s ** 2 - 0.0012843 * s ** 3 + 0.00037604 * t ** 2 * s ** 3
            - 0.0000000099594 * t ** 2 * s ** 7)


def isochore_slope_bar_per_c(th_c: float, salinity_wt_pct: float) -> float:
    """dP/dT изохоры в однофазной (жидкой) области, бар/°C (Bodnar & Vityk, 1994, ур. 4–7)."""
    th = _check(th_c, 'Th')
    s = _check(salinity_wt_pct, 'Salinity')
    a = 18.28 + 1.4413 * s + 0.0047241 * s ** 2 - 0.0024213 * s ** 3 + 0.000038064 * s ** 4
    b = 0.019041 - 0.015268 * s + 0.000566012 * s ** 2 - 0.0000042329 * s ** 3 - 0.000000030354 * s ** 4
    c = -0.00015988 + 0.000036892 * s - 0.0000019473 * s ** 2 + 0.000000041674 * s ** 3 - 0.00000000033008 * s ** 4
    return a + b * th + c * th ** 2


def critical_temperature_c(salinity_wt_pct: float) -> float:
    """Критическая температура раствора NaCl, °C (Knight & Bodnar, 1989; ур. 8 у Bodnar & Vityk, 1994)."""
    s = _check(salinity_wt_pct, 'Salinity')
    return 374.1 + 8.8 * s + 0.1771 * s ** 2 - 0.0211 * s ** 3 + 0.0007334 * s ** 4


@dataclass(frozen=True)
class H2ONaClHomogenization:
    th_c: float
    salinity_wt_pct: float
    pressure_bar: float           # давление при Th на кривой L–V (минимальное давление захвата)
    density_g_cm3: float
    slope_bar_per_c: float
    critical_temperature_c: float
    reference: str = MODEL_REFERENCE
    note: str = ('Ph — давление при гомогенизации, т. е. минимальная оценка давления захвата, а не давление '
                 'захвата. Изохора линейна: P = Ph + dP/dT·(T − Th).')
    isochore: tuple = field(default_factory=tuple)

    def pressure_at(self, t_c: float) -> float:
        """Давление на изохоре при T ≥ Th, бар."""
        t = _check(t_c, 'T')
        if t < self.th_c:
            raise ValueError('Isochore is defined only for T >= Th (single-phase liquid field)')
        p = self.pressure_bar + self.slope_bar_per_c * (t - self.th_c)
        if p > P_MAX_BAR:
            raise ValueError('Isochore pressure exceeds 6 kbar, outside the experimental range')
        return p

    def temperature_at(self, p_bar: float) -> float:
        """Температура на изохоре при P ≥ Ph, °C."""
        p = _check(p_bar, 'P')
        if p < self.pressure_bar:
            raise ValueError('Pressure must be >= pressure at homogenization')
        if p > P_MAX_BAR:
            raise ValueError('Pressure exceeds 6 kbar, outside the experimental range')
        return self.th_c + (p - self.pressure_bar) / self.slope_bar_per_c


def homogenization_to_liquid(th_c: float, salinity_wt_pct: float, *, homogenization_to: str) -> H2ONaClHomogenization:
    """Свойства включения H₂O–NaCl, гомогенизирующегося в жидкость (L + V → L) при Th."""
    if homogenization_to != 'liquid':
        raise ValueError("Correlations apply only to liquid-vapour homogenization to the liquid ('liquid')")
    th = _check(th_c, 'Th')
    s = _check(salinity_wt_pct, 'Salinity')
    if not 0.0 <= s <= S_MAX_WT_PCT:
        raise ValueError('Salinity must be 0-40 wt% NaCl for the isochore-slope equation')
    tc = critical_temperature_c(s)
    if not TH_MIN_C <= th <= TH_MAX_C:
        raise ValueError('Th must be 50-700 °C (range of Bodnar & Vityk 1994 isochore slopes)')
    if th >= tc:
        raise ValueError('Th is at or above the critical temperature for this salinity')
    res = H2ONaClHomogenization(th, s, homogenization_pressure_bar(th, s), liquid_density_g_cm3(th, s),
                                isochore_slope_bar_per_c(th, s), tc)
    pts = []
    for dt in (0.0, 50.0, 100.0, 150.0, 200.0, 300.0):
        p = res.pressure_bar + res.slope_bar_per_c * dt
        if p <= P_MAX_BAR:
            pts.append((th + dt, p))
    return H2ONaClHomogenization(th, s, res.pressure_bar, res.density_g_cm3, res.slope_bar_per_c, tc,
                                 isochore=tuple(pts))
