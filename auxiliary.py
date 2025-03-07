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
from requests import post

import warnings
warnings.filterwarnings('ignore')
np.seterr(all='ignore')

import logging
logger = logging.getLogger('logger')

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

governProgramsFractionLowerBound = 0.5
governProgramsFractionUpperBound = 99.5

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

    _8 = ('Дата оценки не валидна, расчет не проводится. Причина: на Дату оценки нет актуального отчета для инвесторов. Поажлуйста, '
          'обратитетсь в тех. поддержку по адресу calculator.service@domrf.ru')

    _9 = 'Значение CPR может быть задано от 0 до 80% годовых'

    _10 = 'Значение CDR может быть задано от 0 до 20% годовых'

    _11 = ('Произвести расчет по требованиям МСФО на {} невозможно, т.к. на {} отсутствует отчет сервисного агента. Пожалуйста, обратитесь в '
           'тех. поддержку по адресу calculator.service@domrf.ru')

    _12 = ('С помощью имеющихся исторических данных сервисных отчетов не удалось восстановить денежный поток в один из прошедших месяцев. '
           'Пожалуйста, обратитетсь в тех. поддержку по адресу calculator.service@domrf.ru')

    _13 = ('Модель не может рассчитать погашение в первую купонную выплату. Объем выпуска облигаций на {} млн руб. меньше, чем сумма '
           'остатков основного долга в ипотечном покрытии на дату передачи. При этом в первом расчетном периоде моделируется погашение '
           'ипотечного покрытия только на {} млн руб. Это значит, что у Ипотечного агента в первом расчетном периоде недостаточно средств, '
           'чтобы вернуть оригинатору разницу между суммой основного долга в ипотечном покрытии на дату передачи и объемом выпуска. '
           'В Калькулятор заданы неверные параметры. Пожалуйста, обратитесь в тех. поддержку по адресу calculator.service@domrf.ru')

    _14 = ('Оценка по требованиям МФСО/РСБУ может проводиться либо на Дату размещения, либо на последний день отчетного месяца. '
           'Укажите корректную дату оценки в параметре pricingDate')

    _15 = ('По состоянию на {} не были обновлены параметры модели ставки рефинансирования ипотеки. Расчет по требованиям МСФО на {} не '
           'может быть проведен. Пожалуйста, обратитесь в тех. поддержку по адресу calculator.service@domrf.ru')

    _16 = ('Дата рыночной траектории ключевой ставки по котировкам свопов ({}) не равна дате КБД ({}). Расчет по требованиям МСФО на {} не '
           'может быть проведен. Пожалуйста, обратитесь в тех. поддержку по адресу calculator.service@domrf.ru')

    _17 = ('По состоянию на {} не были обновлены параметры S-кривых. Расчет по требованиям МСФО на {} не может быть проведен. '
           'Пожалуйста, обратитесь в тех. поддержку по адресу calculator.service@domrf.ru')


# ----- ПРЕДУПРЕЖДЕНИЯ ------------------------------------------------------------------------------------------------------------------- #
class WARNINGS(object):

    """ Сообщения, возникающие при предупреждениях """

    _1 = 'По выпуску {} на отчетную дату {} нет среза ипотечного покрытия. Выгружены данные на {}'


# ----- ОГРАНИЧЕНИЯ НА ПАРАМЕТРЫ ОЦЕНКИ -------------------------------------------------------------------------------------------------- #
class CONSTRAINTS(object):

    """ Ограничения на ввод параметров оценки """

    ZSPRD_MIN, ZSPRD_MAX = -300, 1000
    GSPRD_MIN, GSPRD_MAX = -300, 1000
    DIRTY_MIN, DIRTY_MAX = 10, 150
    CLEAN_MIN, CLEAN_MAX = 10, 150
    PREMI_MIN, PREMI_MAX = -300, 1000
    COUPN_MIN, COUPN_MAX = 0, 20
    FXPRM_MIN, FXPRM_MAX = 0, 300

    ZSPRD_EXCEP = 'Z-спред может быть задан в диапазоне от {} до {} б.п.'.format(int(ZSPRD_MIN), int(ZSPRD_MAX))
    GSPRD_EXCEP = 'G-спред может быть задан в диапазоне от {} до {} б.п.'.format(int(GSPRD_MIN), int(GSPRD_MAX))
    DIRTY_EXCEP = 'Грязная цена может быть задана в диапазоне от {}% до {}% от номинала'.format(int(DIRTY_MIN), int(DIRTY_MAX))
    CLEAN_EXCEP = 'Чистая цена может быть задана в диапазоне от {}% до {}% от номинала'.format(int(CLEAN_MIN), int(CLEAN_MAX))
    COUPN_EXCEP = 'Ставка купона может быть задана в диапазоне от {} до {}% годовых'.format(int(COUPN_MIN), int(COUPN_MAX))
    PREMI_EXCEP = ('Требуемая фиксированная надбавка к Ключевой ставке может быть задана в диапазоне от {} до {} б.п.'
                   .format(int(PREMI_MIN), int(PREMI_MAX)))
    FXPRM_EXCEP = ('Фактичесекая фиксированная надбавка к Ключевой ставке может быть задана в диапазоне от {} до {} б.п.'
                   .format(int(FXPRM_MIN), int(FXPRM_MAX)))


# ----- ТИПЫ РАСЧЕТА --------------------------------------------------------------------------------------------------------------------- #
class CALCULATION_TYPE(object):

    """ Категориальный параметр, определяющий алгоритм расчета ценовых параметров ИЦБ ДОМ.РФ """

    SET_ZSPRD = 1  # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 1: ЗАДАТЬ Z-СПРЕД
    SET_GSPRD = 2  # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 2: ЗАДАТЬ G-СПРЕД
    SET_DIRTY = 3  # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 3: ЗАДАТЬ ГРЯЗНУЮ ЦЕНУ
    SET_CLEAN = 4  # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 4: ЗАДАТЬ ЧИСТУЮ ЦЕНУ
    SET_PREMI = 5  # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 5: ЗАДАТЬ ТРЕБУЕМУЮ НАДБАВКУ
    SET_COUPN = 6  # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 6: ЗАДАТЬ ФИКСИРОВАННУЮ СТАВКУ КУПОНА
    SET_Z_PRM = 7  # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 7: ЗАДАТЬ Z-СПРЕД И ТРЕБУЕМУЮ НАДБАВКУ
    SET_FXPRM = 8  # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 8: ЗАДАТЬ ФАКТИЧЕСКУЮ НАДБАВКУ


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

    """ Категориальный признак, определяющий один из трех вариантов ипотечного покрытия выпуска ИЦБ ДОМ.РФ.
        С точки зрения формирования процентных поступлений кредиты в ипотечном покрытии могут быть трех типов:
            1. Кредиты без субсидий — стандартные кредиты с фиксированной процентной ставкой
            2. Полностью субсидируемые кредиты — субсидируемые в рамках какой-либо гос. программы кредиты, у которых плавающая ставка
               субсидии начисляется на весь остаток основного долга
            3. Частично субсидируемые кредиты — субсидируемые в рамках какой-либо гос. программы кредиты, у которых плавающая ставка
               субсидии начисляется на фиксированную долю остатка основного долга

        Ипотечное покрытие может быть сформировано из двух разных с финансовой точки зрения частей — фиксированной и плавающей.
        В фиксированную часть входят кредиты без субсидий, а также несубсидируемые доли частично субсидируемых кредитов.
        В плавающую входят полностью субсидируемые кредиты, а также субсидируемые доли частично субсидируемых кредитов

        В рамках методики выделяется три типа ипотечного покрытия:
            1. Стандартное (состоит только из фиксированной части)
            2. Субсидируемое (состоит только из плавающей части)
            3. Смешанное (есть как фиксированная, так и плавающая часть)
    """

    FXD = 1  # ТИП ИПОТЕЧНОГО ПОКРЫТИЯ 1: СТАНДАРТНОЕ (ТОЛЬКО ФИКСИРОВАННАЯ ЧАСТЬ)
    FLT = 2  # ТИП ИПОТЕЧНОГО ПОКРЫТИЯ 2: СУБСИДИРУЕМОЕ (ТОЛЬКО ПЛАВАЮЩАЯ ЧАСТЬ)
    MIX = 3  # ТИП ИПОТЕЧНОГО ПОКРЫТИЯ 3: СМЕШАННОЕ (ЕСТЬ КАК ФИКСИРОВАННАЯ, ТАК И ПЛАВАЮЩАЯ ЧАСТЬ)


# ----- ДАННЫЕ ПО ВЫПЛАТЕ СУБСИДИЙ ----------------------------------------------------------------------------------------------------------- #
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

# ----- ТЕХНИЧЕСКИЕ ПЕРЕМЕННЫЕ ДЛЯ СОХРАНЕНИЯ РЕЗУЛЬТАТА РАСЧЕТА В EXCEL-ФАЙЛ ------------------------------------------------------------ #
rslt_cf = pd.DataFrame([])
pool_cf_total = pd.DataFrame([])
pool_cf_fixed = pd.DataFrame([])
pool_cf_float = pd.DataFrame([])
subs_cf = pd.DataFrame([])
bond_cf = pd.DataFrame([])

rslt_cols = ['isin', 'pricingDate', 'poolReportDate', 'zcycDateTime', 'zSpread',
             'requiredKeyRatePremium', 'dirtyPrice', 'cleanPrice', 'modelCPR']

pool_cols = ['isin', 'pricingDate', 'reportDate', 'paymentMonth', 'debt', 'amortization', 'yield', 'subsidyPaid', 'cpr']

subs_cols = ['isin', 'pricingDate', 'reportDate', 'paymentMonth', 'debt', 'keyRateStartDate', 'keyRate',
             'waKeyRateDeduction', 'floatFraction', 'subsidyAccrued', 'subsidyPaymentDate', 'subsidyCouponDate', 'subsidyPaid']

bond_cols = ['isin', 'pricingDate', 'couponDate', 'bondPrincipalStartPeriod', 'bondAmortization',
             'bondCouponPayments', 'issuePrincipalStartPeriod', 'issueAmortization', 'issueCouponPayments']

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