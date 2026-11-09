"""Создаёт validation/oracle/Эталонные_расчёты.xlsx — входные данные для прогона программ авторов в Excel.

Раскладка столбцов повторяет листы «Main» программ H2O-NaCl-CO2 (Steele-MacInnis, 2018) и
HOKIEFLINCS_H2O-NACL (Steele-MacInnis et al., 2012), чтобы блоки можно было копировать без перестановки.
"""
import csv
import os
import sys

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'validation', 'oracle', 'Эталонные_расчёты.xlsx')
IN_FILL = PatternFill('solid', fgColor='E2F0D9')
OUT_FILL = PatternFill('solid', fgColor='FFF2CC')


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return v if v != '' else None


def main():
    wb = Workbook()
    ws = wb.active
    ws.title = 'SM2018'
    sm_in = ['Mode', 'Tm,ice', 'Tm,clath', 'PCO2', '← @T', 'Th,CO2', '(V,L)', 'PhiVap', '← @T', 'Th,tot']
    sm_out = ['сообщение (M)', 'XNaCl', 'XCO2', 'XH2O', 'wt% NaCl', 'mol% CO2', 'V', 'rho', '(U)', 'P@350',
              'P@400', 'P@450', 'P@500', '(Z)', 'dP/dT', 'intercept', '(AC)', 'P@Th,tot']
    ws.append(['case'] + sm_in + sm_out)
    for c in ws[1]:
        c.font = Font(bold=True)
    for c in ws[1][1:11]:
        c.fill = IN_FILL
    for c in ws[1][11:]:
        c.fill = OUT_FILL
    with open(os.path.join(ROOT, 'validation', 'oracle', 'sm2018_inputs.csv'), encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            ws.append([r['case'], r['mode'], num(r['Tm_ice']), num(r['Tm_clath']), num(r['PCO2']), num(r['PCO2_T']),
                       num(r['Th_CO2']), r['homog_to'] or None, num(r['PhiVap']), num(r['PhiVap_T']), num(r['Th_tot'])])
    n_sm = ws.max_row - 1
    hf = wb.create_sheet('HokieFlincs')
    hf.append(['case', 'Tm', 'phase', 'ThL-V', 'S (wt%) — не заполнять', '(G)', 'wt% NaCl', 'T @ homog.',
               'P @ homog.', 'rBULK', 'dP/dT', '(M)', 'Based on', 'T or P', 'unit', 'T trap', 'P trap', '(S)', 'Messages'])
    for c in hf[1]:
        c.font = Font(bold=True)
    for i in (1, 2, 3, 12, 13, 14):
        hf[1][i].fill = IN_FILL
    for i in (6, 7, 8, 9, 10, 15, 16, 18):
        hf[1][i].fill = OUT_FILL
    with open(os.path.join(ROOT, 'validation', 'oracle', 'hokieflincs_inputs.csv'), encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            row = [r['case'], num(r['Tm']), r['phase'], num(r['Th'])] + [None] * 8
            if r['trap_mode']:
                row += [r['trap_mode'], num(r['trap_value']), '°C' if r['trap_mode'].startswith('temperature') else 'bar']
            hf.append(row)
    n_hf = hf.max_row - 1
    ins = wb.create_sheet('Инструкция', 0)
    for line in (
            'Эталонные расчёты для проверки FluidCalc (этап 2). Нужен Excel с включёнными макросами.',
            'Зелёные столбцы — входные данные (заполнены). Жёлтые — результаты, которые нужно перенести обратно.',
            '',
            'A. Программа H2O-NaCl-CO2_Steele-MacInnis.xlsm (Steele-MacInnis, 2018), лист «Main»:',
            f'  1) скопируйте блок SM2018!B2:K{n_sm + 1} и вставьте «только значения» в Main!C12;',
            '  2) нажмите кнопку расчёта на листе Main (макрос Selector) и дождитесь окончания;',
            f'  3) скопируйте Main!M12:AD{n_sm + 11} и вставьте «только значения» в SM2018!L2.',
            '',
            'B. Программа HOKIEFLINCS_H2O-NACL.xls (Steele-MacInnis et al., 2012), лист «Main»:',
            f'  1) скопируйте HokieFlincs!B2:D{n_hf + 1} → «только значения» в Main!C28 (столбцы Tm, phase, ThL-V);',
            f'  2) скопируйте HokieFlincs!M2:N{n_hf + 1} → «только значения» в Main!N28 (способ и значение поправки на',
            '     давление; единицы программа ставит сама); не вставляйте ничего в столбцы с формулами (H–L, P–R);',
            f'  3) скопируйте Main!H28:L{n_hf + 27} → HokieFlincs!G2 и Main!Q28:R{n_hf + 27} → HokieFlincs!P2,',
            f'     Main!T28:T{n_hf + 27} → HokieFlincs!S2 (сообщения).',
            '',
            'Сохраните этот файл и пришлите обратно. Исходные программы авторов не сохраняйте с изменениями.',
            'Входные значения — синтетические (сетка условий), а не данные лаборатории.'):
        ins.append([line])
    ins.column_dimensions['A'].width = 120
    wb.save(OUT)
    print('saved', OUT, n_sm, n_hf)


if __name__ == '__main__':
    sys.exit(main())
