# -*- coding: utf8 -*-
# ----------------------------------------------------------------------------------- #
# ------------------- ВСПОМОГАТЕЛЬНЫЕ ПЕРЕМЕННЫЕ, КЛАССЫ, ФУНКЦИИ ------------------- #
# ----------------------------------------------------------------------------------- #

import math
import numpy as np

d_type = 'datetime64[D]'
m_type = 'datetime64[M]'
s_type = 'datetime64[s]'


class API(object):

    """ Методы API """

    DATA_FOR_CALCULATION = u'https://калькулятор.дом.рф:8193/DataSource/v1/GetDataForCalculation?isin={}'
    GET_ZCYC_COEFFICIENTS = u'https://калькулятор.дом.рф:8193/DataSource/v1/GetZCYCCoefficients?ZCYCDate={}'
    GET_SCURVE_EMPIRICAL_DATA = u'https://калькулятор.дом.рф:8193/DataSource/v1/GetSCurveEmpiricalData'


class EXCEPTIONS(object):

    """ Сообщения, возникающие при ошибках """

    ISIN_NOT_SET = 'Пожалуйста, укажите ISIN ИЦБ ДОМ.РФ, для которой Вы хотите провести расчет ценовых метрик'

    CPR_CDR_SUM_CHECK = 'Указанные CPR и CDR в сумме не должны превышать 100%'

    CALCULATION_TYPE_NOT_SPECIFIED = 'Пожалуйста, задайте значение одного из следующих полей: zSpread, gSpread, dirtyPrice, cleanPrice, requiredKeyRatePremium, couponRate (см. раздел 5 в Методике)'
    SEVERAL_CALCULATION_TYPES = 'Должно быть указано значение тольго одного из следующих полей: zSpread, gSpread, dirtyPrice, cleanPrice, requiredKeyRatePremium, couponRate (см. раздел 5 в Методике)'
    CALCULATION_TYPE_INCORRECT_CPN = 'Тип расчета ценовых параметров не соответствует Типу расчета купонной выплаты (см. раздел 5 в Методике)'

    PRICING_DATE_NOT_VALID_REASON_1 = 'Дата оценки не валидна, расчет не проводится. Причина: Дата оценки выходит за рамки юридического/фактического срока обращения выпуска облигаций'
    PRICING_DATE_NOT_VALID_REASON_2 = 'Дата оценки не валидна, расчет не проводится. Причина: на Дату оценки нет актуального отчета для инвесторов. Обратитетсь в тех. поддержку'

    NO_KEY_RATE_VALUE = 'В Данных по Ключевой ставке ЦБ РФ нет значения Ключевой ставки на {}. Обратитетсь в тех. поддержку'


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
    PREMI_EXCEP = 'Требуемая фиксированная надбавка к Ключевой ставке может быть задана в диапазоне от {} до {} б.п.'.format(int(PREMI_MIN), int(PREMI_MAX))
    COUPN_EXCEP = 'Ставка купона может быть задана в диапазоне от {} до {}% годовых'.format(int(COUPN_MIN), int(COUPN_MAX))


class CALCULATION_TYPE(object):

    """ Категориальный параметр, определяющий алгоритм расчета ценовых параметров ИЦБ ДОМ.РФ """

    SET_ZSPRD = 1   # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 1: ЗАДАТЬ Z-СПРЕД
    SET_GSPRD = 2   # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 2: ЗАДАТЬ G-СПРЕД
    SET_DIRTY = 3   # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 3: ЗАДАТЬ ГРЯЗНУЮ ЦЕНУ
    SET_CLEAN = 4   # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 4: ЗАДАТЬ ЧИСТУЮ ЦЕНУ
    SET_PREMI = 5   # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 5: ЗАДАТЬ ТРЕБУЕМУЮ НАДБАВКУ
    SET_COUPN = 6   # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 6: ЗАДАТЬ СТАВКУ КУПОНА


class COUPON_TYPE(object):

    """ Категориальный признак, определяющий один из трех вариантов расчета купонной выплаты по ИЦБ ДОМ.РФ """

    FXD = 1   # ТИП РАСЧЕТА КУПОННОЙ ВЫПЛАТЫ 1: ФИКСИРОВАННАЯ СТАВКА КУПОНА
    CHG = 2   # ТИП РАСЧЕТА КУПОННОЙ ВЫПЛАТЫ 2: ПЕРЕМЕННАЯ СТАВКА КУПОНА
    FLT = 3   # ТИП РАСЧЕТА КУПОННОЙ ВЫПЛАТЫ 3: ПЛАВАЮЩАЯ СТАВКА КУПОНА

def round_floor(x, decimals):

    """ Функция, округляющая заданное число до ближайшей сотой вниз """

    return (math.floor(x * 10.0 ** float(decimals))) / 10.0 ** float(decimals)


@np.vectorize
def Y(params, t):

    """ Фукнция Y(∙), определенная для любого строго положительного срока поступления денежного потока, выраженного в годах,
    и возвращающая спот-доходность КБД с годовой капитализацией процентов в указанной точке по указанным Параметрам КБД """

    k = 1.6
    a1 = 0
    a2 = 0.6
    b1 = 0.6

    for i in range(2, 9):
        locals()['a' + str(i + 1)] = locals()['a' + str(i)] + a2 * (k ** (i - 1))

    for i in range(1, 9):
        locals()['b' + str(i + 1)] = locals()['b' + str(i)] * k

    g_array = np.array([params['g1'], params['g2'], params['g3'], params['g4'], params['g5'], params['g6'], params['g7'], params['g8'], params['g9']])

    exp_list = []
    for i in range(1, 10):
        exp_list.append(np.exp(-(((t - locals()['a' + str(i)]) ** 2) / (locals()['b' + str(i)] ** 2))))

    exp_list = np.array(exp_list)
    sum = float(np.sum(g_array * exp_list))

    g_t = params['b0'] + (params['b1'] + params['b2']) * (params['tau'] / t) * (1 - np.exp(-t / params['tau'])) - params['b2'] * np.exp(-t / params['tau']) + sum

    return 10000.0 * (np.exp(g_t / 10000.0) - 1)
