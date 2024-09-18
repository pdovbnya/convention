# -*- coding: utf8 -*-

# ---------------------------------------------------------------------------------------------------------------------------------------- #
# ----- КОНВЕНЦИЯ ДЛЯ ИПОТЕЧНЫХ ЦЕННЫХ БУМАГ: ЗАПУСК РАСЧЕТА НА ЛОКАЛЬНОМ КОМПЬЮТЕРЕ ----------------------------------------------------- #
# ---------------------------------------------------------------------------------------------------------------------------------------- #

import os
import time
import json
import pymssql
import warnings
import pandas as pd
import numpy as np
from convention import Convention
from auxiliary import *
warnings.filterwarnings('ignore')

# Расчет с учетом требований МСФО (актуально только для бухгалтерской отчетности):
ifrs = False
# ifrs = True

# Путь для сохранения эксель-файла с результатом расчета (изменить на пользовательский!):
save_path = r"C:\Users\pavel.dovbnya\Desktop\calculation_result.xlsx"

# Параметры расчетов. С помощью комментирования строк можно оставить только интересуемые выпуски ИЦБ ДОМ.РФ:
calculations = [
            {'bondID': 'RU000A1074A5', 'zSpread': 100.0},
            {'bondID': 'RU000A105NP4', 'zSpread': 100.0},
]

# Последовательный запуск расчетов в calculations:
for calculation in calculations:

    # Расчет с учетом требований МСФО (актуально только для бухгалтерской отчетности):
    calculation['ifrs'] = ifrs

    # Включаем progressBar:
    calculation['progressBar'] = True

    # Запуск расчета:
    res = Convention(calculation).calculate()

    # Подготовка результата расчета к сохранению в Excel:
    # — результат оценки:
    rslt = pd.DataFrame(res['pricingResult'], index=[0])
    rslt['poolReportDate'] = None
    if res['poolStatistics'] is not None:
        rslt['poolReportDate'] = res['poolStatistics']['reportDate']
    rslt['zcycDateTime'] = res['pricingParameters']['zcycDateTime']
    rslt['poolModelCPR'] = res['calculationParameters']['poolModelCPR']
    # — ожидаемый денежный поток по ипотечному покрытию:
    empty = pd.DataFrame([])
    pool_total = pd.DataFrame(res['poolCashflowTable']['total']) if res['poolCashflowTable']['total'] is not None else empty
    pool_fixed = pd.DataFrame(res['poolCashflowTable']['fixed']) if res['poolCashflowTable']['fixed'] is not None else empty
    pool_float = pd.DataFrame(res['poolCashflowTable']['float']) if res['poolCashflowTable']['float'] is not None else empty
    # — таблица, демонстрирующая расчет субсидий (при наличии):
    subs = pd.DataFrame(res['subsidyCashflowTable']) if res['subsidyCashflowTable'] is not None else empty
    # — ожидаемый денежный поток по ИЦБ ДОМ.РФ:
    bond = pd.DataFrame(res['mbsCashflowTable']) if res['mbsCashflowTable'] is not None else empty
    # — ожидаемый денежный поток по свопу между ДОМ.РФ и Ипотечным агентом (при наличии):
    swap = pd.DataFrame(res['swapCashflowTable']) if res['swapCashflowTable'] is not None else empty

    for table in [rslt, pool_total, pool_fixed, pool_float, subs, bond, swap]:
        if not table.empty:
            table['isin'] = calculation['bondID']
            table['pricingDate'] = res['pricingParameters']['pricingDate']

    if not pool_total.empty:
        pool_total = pool_total[pool_total['model'] == 1]
        pool_total.reset_index(inplace=True, drop=True)

    if not pool_fixed.empty:
        pool_fixed = pool_fixed[pool_fixed['model'] == 1]
        pool_fixed.reset_index(inplace=True, drop=True)

    if not pool_float.empty:
        pool_float = pool_float[pool_float['model'] == 1]
        pool_float.reset_index(inplace=True, drop=True)

    bond = bond[(bond['cashflowType'] == 1) | (bond['cashflowType'] == 0)]
    bond.reset_index(inplace=True, drop=True)

    rslt = rslt[rslt_cols_ifrs if ifrs else rslt_cols]
    pool_total = pool_total[pool_cols_ifrs if ifrs else pool_cols] if res['poolCashflowTable']['total'] is not None else empty
    pool_fixed = pool_fixed[pool_cols_ifrs if ifrs else pool_cols] if res['poolCashflowTable']['fixed'] is not None else empty
    pool_float = pool_float[pool_cols_ifrs if ifrs else pool_cols] if res['poolCashflowTable']['float'] is not None else empty
    subs = subs[subs_cols] if res['subsidyCashflowTable'] is not None else empty
    bond = bond[bond_cols] if res['mbsCashflowTable'] is not None else empty
    swap = swap[swap_cols] if res['swapCashflowTable'] is not None else empty

    for table in [rslt, pool_total, pool_fixed, pool_float, subs, bond, swap]:
        for c in date_cols:
            if c in table.columns:
                table[c] = pd.to_datetime(table[c])

    rslt_cf = pd.concat([rslt_cf, rslt])
    pool_cf_total = pd.concat([pool_cf_total, pool_total])
    pool_cf_fixed = pd.concat([pool_cf_fixed, pool_fixed])
    pool_cf_float = pd.concat([pool_cf_float, pool_float])
    subs_cf = pd.concat([subs_cf, subs])
    bond_cf = pd.concat([bond_cf, bond])
    swap_cf = pd.concat([swap_cf, swap])

    del res

# Сохранение результата расчета в Excel-файл:
name = r'\TEMPLATE_IFRS.xlsx' if ifrs else r'\TEMPLATE.xlsx'
wb = openpyxl.load_workbook(os.getcwd() + name)
export_table(wb["Оценка"], rslt_cf, 2)
export_table(wb["Все кредиты"], pool_cf_total, 2)
export_table(wb["Кредиты без субсидий"], pool_cf_fixed, 2)
export_table(wb["Кредиты с субсидиями"], pool_cf_float, 2)
export_table(wb["Формирование субсидий"], subs_cf, 2)
export_table(wb["ИЦБ"], bond_cf, 2)
if ifrs:
    export_table(wb["Своп"], swap_cf, 2)
wb.save(save_path)
