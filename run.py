# -*- coding: utf8 -*-
import os
import time
import json
import pymssql
import warnings
import pandas as pd
import numpy as np
from convention_2.convention import Convention
from convention_2.auxiliary import *
warnings.filterwarnings('ignore')

# Расчет с учетом требований МСФО:
# ifrs = True
ifrs = False

# Индикатор использования только доступной на Дату оценки информации (имеет значение, только если ifrs = False):
usePricingDateDataOnly = True
# usePricingDateDataOnly = False

# Значения даты оценки, Z-спреда и требуемой надбавки в расчетах:
report_data = [
               {'pricingDate': '2024-04-30', 'zSpread': 150.0, 'requiredKeyRatePremium': 150.0},
              ]

# Путь для сохранения эксель-файла с результатом расчета (изменить на пользовательский!):
save_path = r"C:\Users\pavel.dovbnya\Desktop\calculation_result.xlsx"

# С помощью комментирования строк можно оставить только интересуемые выпуски ИЦБ ДОМ.РФ:
calculations = [
            # ### Выпуски ИЦБ ДОМ.РФ с фиксированной ставкой купона:                                            # ВЫПУСК        ДАТА РАЗМЕЩ.
            {'bondID': 'RU000A0ZYJT2', 'zSpread': None},                                                      # ВТБ-1           2017-12-07
            # {'bondID': 'RU000A0ZZCH9', 'zSpread': None},                                                      # Дельта-1        2018-07-11
            # {'bondID': 'RU000A0ZZNW5', 'zSpread': None},                                                      # ДОМ.РФ-1        2018-10-08
            # {'bondID': 'RU000A0ZZV86', 'zSpread': None},                                                      # ВТБ-2           2018-11-26
            # {'bondID': 'RU000A0ZZZ09', 'zSpread': None},                                                      # ДОМ.РФ-2        2018-12-20
            # {'bondID': 'RU000A100DQ4', 'zSpread': None},                                                      # ВТБ-3           2019-05-29
            # {'bondID': 'RU000A100YY4', 'zSpread': None},                                                      # МИБ-1           2019-10-25
            # {'bondID': 'RU000A1019A0', 'zSpread': None},                                                      # НФИ-1           2019-12-27
            # {'bondID': 'RU000A101JD7', 'zSpread': None},                                                      # Росбанк-1       2020-03-18
            # {'bondID': 'RU000A101TD6', 'zSpread': None},                                                      # ДОМ.РФ-3        2020-06-18
            # {'bondID': 'RU000A101U95', 'zSpread': None},                                                      # ДОМ.РФ-4        2020-06-26
            # {'bondID': 'RU000A102AP8', 'zSpread': None},                                                      # Газпромбанк-1   2020-10-30
            # {'bondID': 'RU000A102D46', 'zSpread': None},                                                      # Банк ДОМ.РФ-1   2020-11-19
            # {'bondID': 'RU000A102GD1', 'zSpread': None},                                                      # ДОМ.РФ-5        2020-12-10
            # {'bondID': 'RU000A102GV3', 'zSpread': None},                                                      # Росбанк-2       2020-12-11
            # {'bondID': 'RU000A102JB9', 'zSpread': None},                                                      # Банк ДОМ.РФ-2   2020-12-18
            # {'bondID': 'RU000A102K13', 'zSpread': None},                                                      # ВТБ-6           2020-12-21
            # {'bondID': 'RU000A102L87', 'zSpread': None},                                                      # Газпромбанк-2   2020-12-25
            # {'bondID': 'RU000A103125', 'zSpread': None},                                                      # ДОМ.РФ-6        2021-04-22
            # {'bondID': 'RU000A1031K4', 'zSpread': None},                                                      # МИБ-2           2021-04-23
            # {'bondID': 'RU000A103N43', 'zSpread': None},                                                      # Банк ДОМ.РФ-3   2021-09-07
            # {'bondID': 'RU000A103W42', 'zSpread': None},                                                      # МИБ-3           2021-10-18
            # {'bondID': 'RU000A103YG5', 'zSpread': None},                                                      # Газпромбанк-3   2021-10-28
            # {'bondID': 'RU000A103YK7', 'zSpread': None},                                                      # Банк ДОМ.РФ-5   2021-10-29
            # {'bondID': 'RU000A104AM1', 'zSpread': None},                                                      # Банк ДОМ.РФ-6   2021-12-21
            # {'bondID': 'RU000A104B79', 'zSpread': None},                                                      # ВТБ-7           2021-12-23
            # {'bondID': 'RU000A104C45', 'zSpread': None},                                                      # Абсолют-1       2021-12-24
            # {'bondID': 'RU000A105898', 'zSpread': None},                                                      # Совкомбанк-1    2022-09-22
            # {'bondID': 'RU000A105AV9', 'zSpread': None},                                                      # МИБ-4           2022-10-18
            # {'bondID': 'RU000A105CB7', 'zSpread': None},                                                      # Абсолют-2       2022-10-28
            # {'bondID': 'RU000A105H23', 'zSpread': None},                                                      # НФИ-2           2022-11-23
            # {'bondID': 'RU000A105LN3', 'zSpread': None},                                                      # Банк ДОМ.РФ-10  2022-12-12
            # {'bondID': 'RU000A105NP4', 'zSpread': None},                                                      # Совкомбанк-2    2022-12-22
            # {'bondID': 'RU000A105P72', 'zSpread': None},                                                      # Газпромбанк-4   2022-12-26
            # {'bondID': 'RU000A1065R7', 'zSpread': None},                                                      # Банк ДОМ.РФ-13  2023-04-26
            # {'bondID': 'RU000A1074A5', 'zSpread': None},                                                      # МИБ-5           2023-10-23
            # {'bondID': 'RU000A107GM1', 'zSpread': None},                                                      # Газпромбанк-6   2023-12-25
            # {'bondID': 'RU000A107GL3', 'zSpread': None},                                                      # ВТБ-10          2023-12-25
            #
            # ### Выпуски ИЦБ ДОМ.РФ с плавающей ставкой купона (Ключевая ставка + фиксированная надбавка):
            # {'bondID': 'RU000A1041Q0', 'requiredKeyRatePremium': None},                                       # Банк ДОМ.РФ-4   2021-11-17
            # {'bondID': 'RU000A104UV0', 'requiredKeyRatePremium': None},                                       # Банк ДОМ.РФ-7   2022-06-03
            # {'bondID': 'RU000A104X32', 'requiredKeyRatePremium': None},                                       # Банк ДОМ.РФ-8   2022-07-01
            # {'bondID': 'RU000A1058R2', 'requiredKeyRatePremium': None},                                       # Банк ДОМ.РФ-9   2022-09-29
            # {'bondID': 'RU000A105JF3', 'requiredKeyRatePremium': None},                                       # Банк ДОМ.РФ-11  2022-11-30
            # {'bondID': 'RU000A105NN9', 'requiredKeyRatePremium': None},                                       # ВТБ-8           2022-12-22
            # {'bondID': 'RU000A105NZ3', 'requiredKeyRatePremium': None},                                       # Банк ДОМ.РФ-12  2022-12-23
            # {'bondID': 'RU000A106FM5', 'requiredKeyRatePremium': None},                                       # Банк ДОМ.РФ-14  2023-06-29
            # {'bondID': 'RU000A107G55', 'requiredKeyRatePremium': None},                                       # ВТБ-9           2023-12-22
            #
            # ### Выпуски ИЦБ ДОМ.РФ с переменной ставкой купона (ипотечное покрытие без субсидируемых кредитов):
            # {'bondID': 'RU000A0JX3M0', 'zSpread': None},                                                      # БЖФ-1           2016-12-28
            # {'bondID': 'RU000A0JXRM6', 'zSpread': None},                                                      # Сбербанк-1      2017-05-26
            # {'bondID': 'RU000A0ZYL89', 'zSpread': None},                                                      # Райф-1          2017-12-20
            # {'bondID': 'RU000A0ZYLX0', 'zSpread': None},                                                      # БЖФ-3           2017-12-26
            # {'bondID': 'RU000A0ZZZ58', 'zSpread': None},                                                      # Сбербанк-2      2018-12-21
            # {'bondID': 'RU000A100ZB9', 'zSpread': None},                                                      # ВТБ-4           2019-10-30
            # {'bondID': 'RU000A1016B4', 'zSpread': None},                                                      # Сбербанк-3      2019-12-13
            # {'bondID': 'RU000A1018T2', 'zSpread': None},                                                      # ВТБ-5           2019-12-25
            # {'bondID': 'RU000A101X01', 'zSpread': None},                                                      # Сбербанк-4      2020-07-17
            # {'bondID': 'RU000A102L53', 'zSpread': None},                                                      # Сбербанк-5      2020-12-24
            # {'bondID': 'RU000A104511', 'zSpread': None},                                                      # Сбербанк-6      2021-11-26
            # {'bondID': 'RU000A105344', 'zSpread': None},                                                      # Сбербанк-7      2022-08-12
            # {'bondID': 'RU000A106HE8', 'zSpread': None},                                                      # Сбербанк-9      2023-07-07
            # {'bondID': 'RU000A107EQ7', 'zSpread': None},                                                      # Сбербанк-10     2023-12-19
            # {'bondID': 'RU000A1093G2', 'zSpread': None},                                                      # Сбербанк-12     2024-07-26
            #
            # ### Выпуски ИЦБ ДОМ.РФ с переменной ставкой купона (ипотечное покрытие частично состоит из субсидируемых кредитов):
            # {'bondID': 'RU000A105NY6', 'zSpread': None, 'requiredKeyRatePremium': None},                      # Сбербанк-8      2022-12-23
            # {'bondID': 'RU000A106YR5', 'zSpread': None, 'requiredKeyRatePremium': None},                      # Газпромбанк-5   2023-09-29
            # {'bondID': 'RU000A108GC0', 'zSpread': None, 'requiredKeyRatePremium': None},                      # Газпромбанк-7   2024-05-22
            #
            # ### Выпуски ИЦБ ДОМ.РФ с переменной ставкой купона (ипотечное покрытие полностью состоит из субсидируемых кредитов):
            # {'bondID': 'RU000A107SY1', 'requiredKeyRatePremium': None},                                       # Сбербанк-11     2024-02-16
]

query = '''
        SELECT ISIN, Name
        FROM [Calculator].[dbo].[Bonds]
        WHERE IsDomRF = 1
        ORDER BY ISIN
        '''
conn = pymssql.connect(host='matlab-db01', user='CalculatorService', password='!2345Qwert', database='Calculator')
names = pd.read_sql(query, conn)
conn.close()

# Последовательный запуск расчетов в calculations:
for parameters in calculations:

    for report in report_data:

        # Расчет с учетом требований МСФО:
        parameters['ifrs'] = ifrs

        # Индикатор использования только доступной на Дату оценки информации:
        parameters['usePricingDateDataOnly'] = usePricingDateDataOnly

        # Включаем progressBar:
        parameters['progressBar'] = True

        # Дата оценки (отчетная дата МСФО):
        if 'pricingDate' in report.keys() is not None:
            parameters['pricingDate'] = report['pricingDate']

        if 'zSpread' in parameters.keys():
            parameters['zSpread'] = report['zSpread']

        if 'requiredKeyRatePremium' in parameters.keys():
            parameters['requiredKeyRatePremium'] = report['requiredKeyRatePremium']

        # Запуск расчета:
        res = Convention(parameters).calculate()

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
                table['name'] = names[names['ISIN']==parameters['bondID']]['Name'].values[0]
                table['isin'] = parameters['bondID']
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