"""CSV in/out with explicit observations, methods and errors; standard library only."""
import csv
from pathlib import Path
from .salinity import bodnar_1993, darling_1991
from .co2 import pure_co2_saturation

HEADERS = ['sample_id','inclusion_id','method','temperature_c','homogenization_to',
           'liquid_co2_present','vapor_co2_present','aqueous_brine_present','co2_purity_confirmed']
OUT_HEADERS = HEADERS + ['status','result_kind','value','unit','model','doi','note']

def flag(raw: str) -> bool:
    s = raw.strip().lower()
    if s in ('true','yes','1','да'): return True
    if s in ('false','no','0','нет',''): return False
    raise ValueError('Expected boolean true/false, yes/no, 1/0, да/нет')

def calculate_row(row):
    method = row['method'].strip().lower()
    t = float(row['temperature_c'].replace(',', '.'))
    if method == 'bodnar':
        r = bodnar_1993(t)
        return ('NaCl-equivalent aqueous salinity', r.salinity_wt_pct_nacl_eq,
                'wt% NaCl eq', r.method, r.doi, r.assumption+' '+r.scope)
    if method == 'darling':
        r = darling_1991(t,
            liquid_co2_present=flag(row['liquid_co2_present']),
            vapor_co2_present=flag(row['vapor_co2_present']),
            aqueous_brine_present=flag(row['aqueous_brine_present']))
        return ('NaCl-equivalent aqueous salinity', r.salinity_wt_pct_nacl_eq,
                'wt% NaCl eq', r.method, r.doi, r.assumption+' '+r.scope)
    if method == 'co2':
        r = pure_co2_saturation(t,row['homogenization_to'].strip().lower(),
            co2_purity_confirmed=flag(row['co2_purity_confirmed']))
        return ('pure CO2 saturated phase density',r.density_g_cm3,
                'g/cm3',r.backend,'10.1063/1.555991',r.note + f' P_sat={r.saturation_pressure_bar:.5f} bar; molar volume={r.molar_volume_cm3_mol:.5f} cm3/mol; CoolProp={r.backend_version}')
    raise ValueError('Unknown method; use bodnar, darling or co2')

def run_csv(input_path, output_path):
    with Path(input_path).open('r',encoding='utf-8-sig',newline='') as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or any(h not in reader.fieldnames for h in HEADERS):
            raise ValueError('Input CSV must include every expected column from sample template')
        rows = list(reader)
    output=[]
    for row in rows:
        record={h:row.get(h,'') for h in HEADERS}
        try:
            kind,val,unit,model,doi,note=calculate_row(row)
            record.update(status='ok',result_kind=kind,value=f'{val:.9g}',unit=unit,
                          model=model,doi=doi,note=note)
        except (ValueError,TypeError,RuntimeError,ArithmeticError,KeyError) as exc:
            record.update(status='error',result_kind='',value='',unit='',model='',doi='',note=str(exc))
        output.append(record)
    with Path(output_path).open('w',encoding='utf-8-sig',newline='') as fh:
        writer=csv.DictWriter(fh, fieldnames=OUT_HEADERS)
        writer.writeheader();writer.writerows(output)
    return len(output),sum(r['status']=='ok' for r in output)
