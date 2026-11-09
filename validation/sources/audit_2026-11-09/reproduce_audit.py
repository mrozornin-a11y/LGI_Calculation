from pathlib import Path
import os
os.chdir(Path(__file__).resolve().parent)
import csv, json, sys, hashlib, shutil, platform
from decimal import Decimal
sys.path.insert(0, str(Path('audit_repo').resolve()))
from fluid_core.salinity import bodnar_1993, darling_1991
from fluid_core.co2 import pure_co2_saturation
import CoolProp

out=Path('.'); out.mkdir(exist_ok=True)
def write(name, rows):
    with (out/name).open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

hall=[(0,0),(-1.72,3),(-2.50,4.19),(-3.01,4.95),(-4,6.41),(-5,7.84),(-6,9.21),(-7,10.50),(-8,11.72),(-9,12.86),(-10.03,14),(-11,14.98),(-12,15.96),(-13.05,16.93),(-14,17.77),(-15,18.62),(-17.01,20.22),(-18.24,21.17),(-19,21.68),(-20,22.37),(-21,23.04),(-21.21,23.20)]
h=[]
for i,(t,s) in enumerate(hall,1):
    d=-t; derivative=abs(1.78-0.0884*d+0.001671*d*d)
    try: calc=bodnar_1993(t).salinity_wt_pct_nacl_eq
    except ValueError: calc=None
    tol=.05+.005+derivative*.005
    h.append(dict(id=f'HSB88-{i:02}',temperature_c=t,expected_wt_pct=s,calculated_wt_pct=calc,delta_wt_pct=None if calc is None else calc-s,regression_tolerance_abs=tol,experimental_envelope_abs=.02+.005+derivative*.055,status='OUTSIDE_CORE_DOMAIN' if calc is None else ('PASS' if abs(calc-s)<=tol else 'FAIL'),evidence_type='experiment_reproduced_in_compilation',independence='calibration_data',source='IUPAC SDS 47 p208 PDF237; Hall et al 1988',source_url='https://srdata.nist.gov/solubility/IUPAC/SDS-47/SDS-47.pdf',source_temperature_error_c=.05,source_composition_error_wt_pct=.02,comment='Pure-water anchor' if i==1 else ('Retain endpoint; do not bypass core guard' if calc is None else 'Experimental mass-percent column; not compiler mole fraction')))
write('hall1988_experiments.csv',h)

# Transcribed visually from Chen 1972b Table 5, p30 / PDF44.
# -1.34 is explicitly attested by Darling 1991 Table 1, p3870 / PDF2.
left='''8.94 635.8 2.28
8.79 633.5 2.35
7.52 613.5 5.05
7.31 610.2 5.23
7.08 606.8 5.38
5.78 587.9 8.00
5.53 583.4 8.20
5.36 580.3 8.14
5.00 576.4 8.90
4.75 571.8 9.98
4.13 563.4 10.25
4.00 561.9 10.37
3.84 559.0 10.53
3.44 553.6 11.09
0.66 514.1 14.94
0.64 514.3 14.94
0.52 512.3 15.20
0.48 512.7 15.16
0.20 508.4 15.34
0.20 508.6 15.28
0.03 506.0 15.56
-0.07 504.8 15.57
-0.23 501.7 15.94
-0.56 498.6 16.39
-0.56 498.1 16.38
-0.82 494.6 16.02
-0.92 493.7 16.20
-1.16 490.2 16.75'''
right='''1.34 486.9 16.94
-1.44 486.7 17.19
-1.49 485.7 17.21
-3.68 457.7 19.47
-3.75 456.9 19.48
-4.05 452.8 19.73
-4.44 448.2 20.07
-4.62 446.6 20.33
-4.87 443.9 20.42
-5.10 440.5 20.69
-5.32 437.6 21.02
-5.63 434.5 21.18
-5.80 432.6 21.28
-6.00 429.9 21.42
-6.27 426.4 21.64
-6.55 423.5 21.92
-6.60 423.1 21.47
-6.80 420.7 21.72
-8.60 399.2 23.45
-8.80 397.6 23.50
-8.90 396.6 23.58
-9.00 395.2 23.63
-9.28 391.9 23.83
-9.50 388.7 23.99
-9.73 387.1 23.74
-9.92 385.1 24.08
-9.97 384.6 23.89
-10.08 383.0 24.21
-10.40 381.1 24.11'''
c=[]
for i,line in enumerate((left+'\n'+right).splitlines(),1):
    raw,p,s=map(float,line.split()); t=-1.34 if i==29 else raw
    derivative=abs(.00098241*(-(t*t+45.385*t+1588.75)+(10-t)*(2*t+45.385)))
    try: calc=darling_1991(t,liquid_co2_present=True,vapor_co2_present=True,aqueous_brine_present=True).salinity_wt_pct_nacl_eq
    except ValueError: calc=None
    tol=.0561*s+.005+derivative*.005
    exp=.01*s+.005+derivative*.030
    c.append(dict(id=f'CH72-{i:02}',chen_printed_temperature_c=raw,temperature_c=t,pressure_psia=p,expected_wt_pct=s,calculated_wt_pct=calc,delta_wt_pct=None if calc is None else calc-s,relative_error_pct=None if calc is None else 100*(calc-s)/s,regression_tolerance_abs=tol,experimental_envelope_abs=exp,within_experimental_envelope=None if calc is None else abs(calc-s)<=exp,status='OUTSIDE_CORE_DOMAIN' if calc is None else ('PASS' if abs(calc-s)<=tol else 'FAIL'),evidence_type='experiment',independence='calibration_data',source='Chen 1972b Table5 p30 PDF44; Darling1991 Table1 p3870 PDF2',source_url='https://stacks.cdc.gov/view/cdc/236586/cdc_236586_DS1.pdf',source_temperature_error_c=.025,source_composition_error_relative=.01,comment='Chen prints +1.34; Darling prints -1.34; adopted latter with explicit provenance' if i==29 else ('Outside published -10..10 range; preserve without extrapolation' if calc is None else ('Near peritectic: source reports -9.6 and -10.0 alternatives' if t < -9.5 else 'Four-phase equilibrium; experimental salt concentration'))))
write('chen1972_experiments.csv',c)

n=[]
url='https://webbook.nist.gov/cgi/fluid.cgi?Action=Data&Wide=on&ID=C124389&Type=SatP&Digits=8&TLow=223.15&THigh=303.15&TInc=10&TUnit=K&PUnit=bar&DUnit=kg%2Fm3'
for r in csv.DictReader(open('nist_co2_mass.tsv'),delimiter='\t'):
    t=round(float(r['Temperature (K)'])-273.15,8)
    l=pure_co2_saturation(t,'liquid',co2_purity_confirmed=True)
    v=pure_co2_saturation(t,'vapor',co2_purity_confirmed=True)
    for q,col,calc,unit in [('pressure','Pressure (bar)',l.saturation_pressure_bar,'bar'),('liquid_density','Density (l, kg/m3)',l.density_g_cm3*1000,'kg_m3'),('vapor_density','Density (v, kg/m3)',v.density_g_cm3*1000,'kg_m3')]:
        raw=r[col]; e=float(raw); half=float(Decimal(10)**Decimal(Decimal(raw).as_tuple().exponent))/2
        tol=half+abs(e)*1e-8
        n.append(dict(id=f'NIST-{t:g}-{q}',temperature_c=t,quantity=q,expected=e,unit=unit,calculated=calc,delta=calc-e,rounding_half_unit=half,tolerance_abs=tol,status='PASS' if abs(calc-e)<=tol else 'FAIL',evidence_type='reference_table',independence='external_implementation_model_not_independently_verified',source='NIST WebBook SRD69 downloaded 2026-11-09',source_url=url,comment='Numerical agreement with NIST; not an independent experiment or proof of EOS accuracy'))
write('nist_co2_checkpoints.csv',n)
shutil.copyfile('nist_co2_mass.tsv',out/'nist_co2_raw.tsv')
summary={'date':'2026-11-09','python':platform.python_version(),'CoolProp':CoolProp.__version__,'hall':{'rows':len(h),'pass':sum(x['status']=='PASS' for x in h),'outside':sum(x['status']=='OUTSIDE_CORE_DOMAIN' for x in h),'max_abs_error':max(abs(x['delta_wt_pct']) for x in h if x['delta_wt_pct'] is not None)},'chen':{'rows':len(c),'pass':sum(x['status']=='PASS' for x in c),'outside':sum(x['status']=='OUTSIDE_CORE_DOMAIN' for x in c),'max_abs_error':max(abs(x['delta_wt_pct']) for x in c if x['delta_wt_pct'] is not None),'max_relative_pct':max(abs(x['relative_error_pct']) for x in c if x['relative_error_pct'] is not None),'mean_abs_relative_pct':sum(abs(x['relative_error_pct']) for x in c if x['relative_error_pct'] is not None)/sum(x['relative_error_pct'] is not None for x in c),'outside_experimental_envelope':sum(x['within_experimental_envelope'] is False for x in c)},'nist':{'rows':len(n),'pass':sum(x['status']=='PASS' for x in n)}}
(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
hashes=json.loads((out/'source_hashes.json').read_text()) if (out/'source_hashes.json').exists() else {}
hashes.update({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('audit_repo/fluid_core').glob('*.py')})
(out/'source_hashes.json').write_text(json.dumps(hashes,indent=2))
print(json.dumps(summary,indent=2))
