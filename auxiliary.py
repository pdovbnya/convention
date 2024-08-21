# -*- coding: utf8 -*-

# ---------------------------------------------------------------------------------------------------------------------------------------- #
# ----- КОНВЕНЦИЯ ДЛЯ ИПОТЕЧНЫХ ЦЕННЫХ БУМАГ: ВСПОМОГАТЕЛЬНЫЕ ПЕРЕМЕННЫЕ, КЛАССЫ, ФУНКЦИИ ------------------------------------------------ #
# ---------------------------------------------------------------------------------------------------------------------------------------- #

import math
import numpy as np
import pandas as pd
import time
import asyncio
import threading
import openpyxl
from openpyxl.utils.dataframe import dataframe_to_rows
from ESB.ESBClient import client
from ESB.PercentsNotificationMessage import PercentsNotificationMessage
from globals import definitions
from requests import post

import warnings
warnings.filterwarnings('ignore')
np.seterr(all='ignore')

s_type = 'datetime64[s]'
d_type = 'datetime64[D]'
m_type = 'datetime64[M]'
y_type = 'datetime64[Y]'
second = np.timedelta64(1, 's')
hour = np.timedelta64(1, 'h')
day = np.timedelta64(1, 'D')
month = np.timedelta64(1, 'M')
year = np.timedelta64(1, 'Y')
d_nat = np.datetime64('NaT')


# ----- МЕТОДЫ API ----------------------------------------------------------------------------------------------------------------------- #
class API(object):

    """ Методы API """

    SERVER = u'https://калькулятор.дом.рф'
    PORT = 8193

    DATA_FOR_CALC = SERVER + ':' + str(PORT) + u'/DataSource/v2/GetDataForCalculation?bondID={}'
    GET_ZCYC_COEF = SERVER + ':' + str(PORT) + u'/DataSource/v2/GetZCYCCoefficients?zcycDate={}'
    GET_POOL_DATA = SERVER + ':' + str(PORT) + u'/DataSource/v2/GetPoolsData?bondID={}&date={}&full=false&ifrs={}'
    GET_MACR_DATA = SERVER + ':' + str(PORT) + u'/DataSource/v2/GetMacroData?date={}'
    UPDATE_STATUS = SERVER + ':' + str(PORT) + u'/Convention2/v2/UpdateConventionStatus'


# ----- ОПОВЕЩЕНИЯ ОБ ОШИБКАХ ------------------------------------------------------------------------------------------------------------ #
class EXCEPTIONS(object):

    """ Сообщения, возникающие при ошибках """

    _1 = ('Пожалуйста, укажите ISIN (например, RU000A0ZYJT2) или регистрационный номер (например, 4-02-00307-R-002P) выпуска ИЦБ ДОМ.РФ, '
          'для которого Вы хотите провести расчет ценовых метрик')

    _2 = ('Вы выбрали для оценки ИЦБ ДОМ.РФ с фиксированной ставкой купона (размер выплаченного купона определяется начислением на '
          'непогашенный номинал облигации ставки купона, зафиксированной на весь срок обращения выпуска облигаций). Пожалуйста, задайте '
          'значение одного (и только одного) из следующих полей: zSpread (Z-спред в б.п.), gSpread (G-спред в б.п.), dirtyPrice (грязная '
          'цена в % от номинала), cleanPrice (чистая цена в % от номинала)')

    _3 = ('Вы выбрали для оценки ИЦБ ДОМ.РФ с плавающей ставкой купона (размер выплаченного купона определяется начислением на '
          'непогашенный номинал облигации суммы Ключевой ставки ЦБ РФ на начало расчетного периода и фиксированной надбавки). Пожалуйста, '
          'задайте значение одного (и только одного) из следующих полей: requiredKeyRatePremium (требуемая надбавка к Ключевой ставке в '
          'б.п.), dirtyPrice (грязная цена в % от номинала), cleanPrice (чистая цена в % от номинала)')

    _4 = ('Вы выбрали для оценки ИЦБ ДОМ.РФ с переменной ставкой купона (размер выплаченного купона равен процентным поступлениям по пулу '
          'закладных за расчетный период за вычетом всех расходов Ипотечного агента, относящихся к купонной выплате). Ипотечное покрытие '
          'данного выпуска на 100% процентов состоит из кредитов с фиксированной процентной ставкой без субсидий. Пожалуйста, задайте '
          'значение одного (и только одного) из следующих полей: zSpread (Z-спред в б.п.), gSpread (G-спред в б.п.), dirtyPrice (грязная '
          'цена в % от номинала), cleanPrice (чистая цена в % от номинала)')

    _5 = ('Вы выбрали для оценки ИЦБ ДОМ.РФ с переменной ставкой купона (размер выплаченного купона равен процентным поступлениям по пулу '
          'закладных за расчетный период за вычетом всех расходов Ипотечного агента, относящихся к купонной выплате). Ипотечное покрытие '
          'данного выпуска на 100% процентов состоит из субсидируемых кредитов (размер субсидии привязан к значению Ключевой ставки). '
          'Пожалуйста, задайте значение одного (и только одного) из следующих полей: requiredKeyRatePremium (требуемая надбавка к Ключевой '
          'ставке в б.п.), dirtyPrice (грязная цена в % от номинала), cleanPrice (чистая цена в % от номинала)')

    _6 = ('Вы выбрали для оценки ИЦБ ДОМ.РФ с переменной ставкой купона (размер выплаченного купона равен процентным поступлениям по пулу '
          'закладных за расчетный период за вычетом всех расходов Ипотечного агента, относящихся к купонной выплате). Ипотечное покрытие '
          'данного выпуска на {}% состоит из субсидируемых кредитов (размер субсидии привязан к значению Ключевой ставки). Пожалуйста, '
          'задайте значение двух (и только двух) полей: zSpread (Z-спред в б.п.), requiredKeyRatePremium (требуемая надбавка к Ключевой '
          'ставке в б.п.). ИЦБ в части кредитов без субсидий будет оценена по текущей КБД с указанным Z-спредом, а ИЦБ в части кредитов с '
          'субсидиями будет оценена путем соотнесения указанной требуемой надбавки с оцененным значением спреда, который генерируют над '
          'Ключевой ставкой кредиты с субсидиями')

    _7 = ('Дата оценки не валидна, расчет не проводится. Причина: Дата оценки выходит за рамки юридического/фактического срока обращения '
          'выпуска облигаций')

    _8 = ('Дата оценки не валидна, расчет не проводится. Причина: на Дату оценки нет актуального отчета для инвесторов. Обратитетсь в тех. '
          'поддержку по адресу calculator.service@domrf.ru')

    _9 = 'CDR нельзя задавать выше 30% годовых'

    _10 = 'Произвести расчет по требованиям МСФО на {} невозможно, т.к. на {} отсутствует отчет сервисного агента'

    _11 = ('С помощью имеющихся исторических данных сервисных отчетов не удалось восстановить денежный поток в один из прошедших месяцев. '
           'Обратитетсь в тех. поддержку по адресу calculator.service@domrf.ru')


# ----- ПРЕДУПРЕЖДЕНИЯ ------------------------------------------------------------------------------------------------------------------- #
class WARNINGS(object):

    """ Сообщения, возникающие при предупреждениях """

    _1 = 'По выпуску {} на отчетную дату {} нет среза ипотечного покрытия. Выгружены данные на {}'


# ----- ОГРАНИЧЕНИЯ НА ПАРАМЕТРЫ ОЦЕНКИ -------------------------------------------------------------------------------------------------- #
class CONSTRAINTS(object):

    """ Ограничения на ввод параметров оценки """

    ZSPRD_MIN, ZSPRD_MAX = -300, 500
    GSPRD_MIN, GSPRD_MAX = -300, 500
    DIRTY_MIN, DIRTY_MAX = 10, 150
    CLEAN_MIN, CLEAN_MAX = 10, 150
    PREMI_MIN, PREMI_MAX = -300, 500
    COUPN_MIN, COUPN_MAX = 0, 20

    ZSPRD_EXCEP = 'Z-спред может быть задан в диапазоне от {} до {} б.п.'.format(int(ZSPRD_MIN), int(ZSPRD_MAX))
    GSPRD_EXCEP = 'G-спред может быть задан в диапазоне от {} до {} б.п.'.format(int(GSPRD_MIN), int(GSPRD_MAX))
    DIRTY_EXCEP = 'Грязная цена может быть задана в диапазоне от {}% до {}% от номинала'.format(int(DIRTY_MIN), int(DIRTY_MAX))
    CLEAN_EXCEP = 'Чистая цена может быть задана в диапазоне от {}% до {}% от номинала'.format(int(CLEAN_MIN), int(CLEAN_MAX))
    COUPN_EXCEP = 'Ставка купона может быть задана в диапазоне от {} до {}% годовых'.format(int(COUPN_MIN), int(COUPN_MAX))
    PREMI_EXCEP = ('Требуемая фиксированная надбавка к Ключевой ставке может быть задана в диапазоне от {} до {} б.п.'
                   .format(int(PREMI_MIN), int(PREMI_MAX)))


# ----- ТИПЫ РАСЧЕТА --------------------------------------------------------------------------------------------------------------------- #
class CALCULATION_TYPE(object):

    """ Категориальный параметр, определяющий алгоритм расчета ценовых параметров ИЦБ ДОМ.РФ """

    SET_ZSPRD = 1  # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 1: ЗАДАТЬ Z-СПРЕД
    SET_GSPRD = 2  # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 2: ЗАДАТЬ G-СПРЕД
    SET_DIRTY = 3  # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 3: ЗАДАТЬ ГРЯЗНУЮ ЦЕНУ
    SET_CLEAN = 4  # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 4: ЗАДАТЬ ЧИСТУЮ ЦЕНУ
    SET_PREMI = 5  # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 5: ЗАДАТЬ ТРЕБУЕМУЮ НАДБАВКУ
    SET_COUPN = 6  # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 6: ЗАДАТЬ СТАВКУ КУПОНА
    SET_Z_PRM = 7  # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 7: ЗАДАТЬ Z-СПРЕД И ТРЕБУЕМУЮ НАДБАВКУ


# ----- ТИПЫ КУПОННОЙ ВЫПЛАТЫ ------------------------------------------------------------------------------------------------------------ #
class COUPON_TYPE(object):

    """ Категориальный признак, определяющий один из трех вариантов расчета купонной выплаты по ИЦБ ДОМ.РФ:

            1. Фиксированная ставка купона: размер выплаченного купона определяется начислением на непогашенный номинал облигации
               ставки купона, зафиксированной на весь срок обращения выпуска облигаций

            2. Переменная ставка купона: размер выплаченных купонов по выпуску равен процентным поступлениям по пулу закладных за
               расчетный период за вычетом всех расходов Ипотечного агента, относящихся к купонной выплате

            3. Плавающая ставка купона: размер выплаченного купона определяется начислением на непогашенный номинал облигации суммы
               Ключевой ставки ЦБ РФ на начало расчетного периода и фиксированной надбавки
    """

    FXD = 1  # ТИП РАСЧЕТА КУПОННОЙ ВЫПЛАТЫ 1: ФИКСИРОВАННАЯ СТАВКА КУПОНА
    CHG = 2  # ТИП РАСЧЕТА КУПОННОЙ ВЫПЛАТЫ 2: ПЕРЕМЕННАЯ СТАВКА КУПОНА
    FLT = 3  # ТИП РАСЧЕТА КУПОННОЙ ВЫПЛАТЫ 3: ПЛАВАЮЩАЯ СТАВКА КУПОНА


# ----- ТИПЫ ИПОТЕЧНОГО ПОКРЫТИЯ --------------------------------------------------------------------------------------------------------- #
class POOL_TYPE(object):

    """ Категориальный признак, определяющий один из трех вариантов ипотечного покрытия выпуска ИЦБ ДОМ.РФ:

            1.	Стандартное ипотечное покрытие полностью состоит из кредитов с фиксированной процентной ставкой

            2.	Субсидируемое ипотечное покрытие полностью состоит из субсидируемых кредитов с плавающей процентной ставкой (текущая
                Ключевая ставка + фиксированная для кредита надбавка)

            3.	В смешанном ипотечном покрытии есть кредиты как с фиксированной, так и с плавающей процентной став-кой
     """

    FXD = 1  # ТИП ИПОТЕЧНОГО ПОКРЫТИЯ 1: СТАНДАРТНОЕ
    FLT = 2  # ТИП ИПОТЕЧНОГО ПОКРЫТИЯ 2: СУБСИДИРУЕМОЕ
    MIX = 3  # ТИП ИПОТЕЧНОГО ПОКРЫТИЯ 3: СМЕШАННОЕ


# ----- ДАННЫЕ ПО ВЫПЛАТЕ СУБСИДИЙ ------------------------------------------------------------------------------------------------------- #
# День месяца, в который приходит субсидия:
subsidy_payment_day = 15

# Таблица соответствия месяца начисления субсидии и количества месяцев, через которое она придет:
subsidy_months = pd.DataFrame(
    [
        {'accrualMonth': 1,  'addMonths': 2},  # субсидия за янв приходит в мрт
        {'accrualMonth': 2,  'addMonths': 2},  # субсидия за фев приходит в апр
        {'accrualMonth': 3,  'addMonths': 2},  # субсидия за мрт приходит в май
        {'accrualMonth': 4,  'addMonths': 2},  # субсидия за апр приходит в июн
        {'accrualMonth': 5,  'addMonths': 2},  # субсидия за май приходит в июл
        {'accrualMonth': 6,  'addMonths': 2},  # субсидия за июн приходит в авг
        {'accrualMonth': 7,  'addMonths': 2},  # субсидия за июл приходит в сен
        {'accrualMonth': 8,  'addMonths': 4},  # субсидия за авг приходит в дек
        {'accrualMonth': 9,  'addMonths': 3},  # субсидия за сен приходит в дек
        {'accrualMonth': 10, 'addMonths': 2},  # субсидия за окт приходит в дек
        {'accrualMonth': 11, 'addMonths': 4},  # субсидия за ноя приходит в мрт
        {'accrualMonth': 12, 'addMonths': 3},  # субсидия за дек приходит в мрт
    ]
)


# ----- ВЫПУСКИ ИЦБ ДОМ.РФ С ФИКСИРОВАННОЙ АМОРТИЗАЦИЕЙ ---------------------------------------------------------------------------------- #
fixed_amt_bonds = ['RU000A100DQ4', '4-09-00307-R-002P']


# ----- ФУНКЦИИ ОКРУГЛЕНИЙ --------------------------------------------------------------------------------------------------------------- #
@np.vectorize
def round_floor(x, decimals):

    """ Функция, округляющая заданное число до заданного разряда вниз """

    return (math.floor(x * 10.0 ** float(decimals))) / 10.0 ** float(decimals)


@np.vectorize
def round_ceil(x, decimals):

    """ Функция, округляющая заданное число до заданного разряда вверх """

    return (math.ceil(x * 10.0 ** float(decimals))) / 10.0 ** float(decimals)


# ----- РАСЧЕТ КБД ----------------------------------------------------------------------------------------------------------------------- #
@np.vectorize
def Y(params, t):

    """ Фукнция Y(•), определенная для любого строго положительного срока поступления денежного потока, выраженного в годах,
    и возвращающая спот-доходность КБД с годовой капитализацией процентов в указанной точке по указанным Параметрам КБД """

    k = 1.6
    a1 = 0
    a2 = 0.6
    b1 = 0.6

    for i in range(2, 9):
        locals()['a' + str(i + 1)] = locals()['a' + str(i)] + a2 * (k ** (i - 1))

    for i in range(1, 9):
        locals()['b' + str(i + 1)] = locals()['b' + str(i)] * k

    g_array = np.array([params['g1'], params['g2'], params['g3'], params['g4'],
                        params['g5'], params['g6'], params['g7'], params['g8'], params['g9']])

    exp_list = []
    for i in range(1, 10):
        exp_list.append(np.exp(-(((t - locals()['a' + str(i)]) ** 2) / (locals()['b' + str(i)] ** 2))))

    exp_list = np.array(exp_list)
    sum = float(np.sum(g_array * exp_list))

    g_t = (params['b0'] + (params['b1'] + params['b2']) * (params['tau'] / t) *
           (1 - np.exp(-t / params['tau'])) - params['b2'] * np.exp(-t / params['tau']) + sum)

    return 10000.0 * (np.exp(g_t / 10000.0) - 1)


# ----- ЗАПРОС НА ОБНОВЛЕНИЕ ДОЛИ ГОТОВНОСТИ РАСЧЕТА НА САЙТЕ КАЛЬКУЛЯТОРА --------------------------------------------------------------- #
def update(connection_id, percent, progress_bar=None):

    percent = np.round(percent, 0)

    if connection_id is None and progress_bar is not None:
        progress_delta = int(percent) - int(progress_bar.n)
        progress_bar.update(int(progress_delta))

    if connection_id is None:
        return

    message = PercentsNotificationMessage(connection_id, percent)

    client.sendNotification(message)


# ----- ТЕХНИЧЕСКИЕ ПЕРЕМЕННЫЕ ДЛЯ СОХРАНЕНИЯ РЕЗУЛЬТАТА РАСЧЕТА В EXCEL-ФАЙЛ ------------------------------------------------------------ #
rslt_cf = pd.DataFrame([])
pool_cf_total = pd.DataFrame([])
pool_cf_fixed = pd.DataFrame([])
pool_cf_float = pd.DataFrame([])
subs_cf = pd.DataFrame([])
bond_cf = pd.DataFrame([])
swap_cf = pd.DataFrame([])

rslt_cols = ['name', 'isin', 'pricingDate', 'poolReportDate', 'zcycDateTime', 'dirtyPrice', 'cleanPrice', 'poolModelCPR']

rslt_cols_ifrs = ['name', 'isin', 'pricingDate', 'poolReportDate', 'zcycDateTime',
                  'dirtyPrice', 'cleanPrice', 'swapPrice', 'swapPriceRub', 'poolModelCPR']

pool_cols = ['name', 'isin', 'pricingDate', 'reportDate', 'paymentMonth', 'debt', 'amortization', 'yield', 'subsidyPaid', 'cpr']

pool_cols_ifrs = ['name', 'isin', 'pricingDate', 'reportDate', 'paymentMonth', 'debt',
                  'amortization', 'amortizationIFRS', 'yield', 'yieldIFRS', 'subsidyPaid', 'expensePart1', 'expensePart2', 'cpr']

subs_cols = ['name', 'isin', 'pricingDate', 'reportDate', 'paymentMonth', 'debt', 'keyRateStartDate', 'keyRate',
             'waKeyRateDeduction', 'floatFraction', 'subsidyAccrued', 'subsidyPaymentDate', 'subsidyCouponDate', 'subsidyPaid']

bond_cols = ['name', 'isin', 'pricingDate', 'couponDate', 'bondPrincipalStartPeriod', 'bondAmortization',
             'bondCouponPayments', 'issuePrincipalStartPeriod', 'issueAmortization', 'issueCouponPayments']

swap_cols = ['name', 'isin', 'pricingDate', 'nettingDate', 'fixedSum', 'yield', 'subsidy',
             'reinvestment', 'expense', 'accruedYield', 'floatSum']

date_cols = ['pricingDate', 'zcycDateTime', 'poolReportDate', 'reportDate', 'paymentMonth', 'keyRateStartDate',
             'subsidyPaymentDate', 'subsidyCouponDate', 'couponDate', 'nettingDate']

def export_table(sheet: openpyxl.Workbook, df: pd.DataFrame, start_row: int = 0, start_col: int = 0):
    rows = dataframe_to_rows(df, index=False, header=False)
    for r_idx, row in enumerate(rows, start_row + 1):
        for c_idx, value in enumerate(row, start_col + 1):
            cell = sheet.cell(row=r_idx, column=c_idx)
            if isinstance(value, pd.Timestamp):
                cell.number_format = 'dd.MM.YYYY'
            elif isinstance(value, float):
                cell.number_format = '#,##0.00'
            cell.value = value