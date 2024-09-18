# -*- coding: utf8 -*-

# ---------------------------------------------------------------------------------------------------------------------------------------- #
# ----- КОНВЕНЦИЯ ДЛЯ ИПОТЕЧНЫХ ЦЕННЫХ БУМАГ: ОСНОВНОЙ СКРИПТ ---------------------------------------------------------------------------- #
# ---------------------------------------------------------------------------------------------------------------------------------------- #

import logging

logger = logging.getLogger('logger')

import json
import time
import sys
import tqdm
import copy
import numpy as np
import pandas as pd
import datetime as dt

from requests import get
from scipy.optimize import minimize
from auxiliary import *
from pool_model import *
from macro_model import *

import warnings

warnings.filterwarnings('ignore')
np.seterr(all='ignore')


class Convention(object):
    """ Программная реализация Конвенции для ипотечных ценных бумаг """

    def __init__(self, input):

        # Заданные параметры оценки:
        self.pricingParameters = copy.deepcopy(input)

        # Идентификатор расчета (генерируется на стороне сайта калькулятора, необходим для идентификации расчета на сайте):
        self.connectionId = None
        if 'connectionId' in self.pricingParameters.keys() and self.pricingParameters['connectionId'] is not None:
            self.connectionId = self.pricingParameters['connectionId']

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ИДЕНТИФИКАТОР ВЫПУСКА ОБЛИГАЦИЙ ИЦБ ДОМ.РФ ------------------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        # Идентификатором может выступать либо ISIN (например, RU000A0ZYJT2), либо регистрационный номер (например, 4-02-00307-R-002P):
        self.bondID = None

        # Идентификатор можно задать либо через поле 'isin' (старый вариант), либо через 'bondID' (новый вариант).
        # Если заданы оба поля, будет использоваться поле 'bondID':
        condition_1 = 'isin' in self.pricingParameters.keys() and self.pricingParameters['isin'] is not None
        condition_2 = 'bondID' in self.pricingParameters.keys() and self.pricingParameters['bondID'] is not None

        if condition_1:
            self.bondID = self.pricingParameters['isin']

        if condition_2:
            self.bondID = self.pricingParameters['bondID']

        if not condition_1 and not condition_2:
            raise Exception(EXCEPTIONS._1)

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ИНИЦИАЛИЗАЦИЯ СТАТУСА РАСЧЕТА В КОНСОЛИ И НА САЙТЕ ----------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        # Время начала расчета (московское время):
        self.startTime = np.datetime64('now') + 3 * hour

        # Инициализация прогресс-бара в консоли:
        self.progressBar = tqdm.tqdm(total=100, file=sys.stdout, ncols=100, leave=False,
                                     desc=self.bondID, bar_format="{l_bar}|{bar}| {n_fmt}/{total_fmt}{postfix}")

        # [ОБНОВЛЕНИЕ СТАТУСА РАСЧЕТА]
        self.currentPercent = 1.0
        update(self.connectionId, self.currentPercent, self.progressBar)

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ДАННЫЕ, НЕОБХОДИМЫЕ ДЛЯ ПРОВЕДЕНИЯ РАСЧЕТА ------------------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        # Загрузка данных, необходимых для расчета, по API:
        self.dataForCalculation = get(API.DATA_FOR_CALC.format(self.bondID), timeout=15).json()

        # ----- ПАРАМЕТРЫ ВЫПУСКА ИЦБ ДОМ.РФ --------------------------------------------------------------------------------------------- #
        self.bondParameters = self.dataForCalculation['bondParameters']

        # --> Дата размещения <--
        # Дата размещения выпуска облигаций на Московской бирже:
        self.issueDate = np.datetime64(self.bondParameters['issueDate'], 'D')

        # --> Дата передачи <--
        # Дата перехода прав собственности на закладные в ипотечном покрытии Ипотечному агенту ДОМ.РФ). В том случае,
        # если расчет проводится до Даты размещения, и ипотечное покрытие еще не было передано Ипотечному агенту ДОМ.РФ, устанавливается
        # равной дате, предшествующей Дате размещения на 1 день:
        self.deliveryDate = None
        if self.bondParameters['deliveryDate'] is not None:
            self.deliveryDate = np.datetime64(self.bondParameters['deliveryDate'], 'D')
        else:
            self.deliveryDate = self.issueDate - day

        # --> Дата первой купонной выплаты <--
        # Дата, в которую, согласно эмиссионной документации, будет произведена выплата первого купона по облигациям:
        self.firstCouponDate = np.datetime64(self.bondParameters['firstCouponDate'], 'D')

        # --> Юридическая дата погашения <--
        # Дата, не позже которой, согласно эмиссионной документации, будет произведено погашение выпуска облигаций:
        self.legalRedemptionDate = np.datetime64(self.bondParameters['legalRedemptionDate'], 'D')

        # --> Фактическая дата погашения (если известна) <--
        self.actualRedemptionDate = None
        if self.bondParameters['actualRedemptionDate'] is not None:
            self.actualRedemptionDate = np.datetime64(self.bondParameters['actualRedemptionDate'], 'D')

        # --> Длина купонного периода, 1 или 3 (месяцы) <--
        # Количество месяцев во втором и последующих купонных периодах выпуска облигаций: 1 – ежемесячный ку-пон, 3 – квартальный купон:
        self.couponPeriod = int(self.bondParameters['couponPeriod'])

        # --> Тип расчета купонной выплаты, 1/2/3 <--
        # Категориальный признак, определяющий один из трех вариантов расчета купонной выплаты по ИЦБ ДОМ.РФ (см. auxiliary.COUPON_TYPE):
        self.couponType = int(self.bondParameters['couponType'])

        # --> Первоначальный номинал облигации (номинальная стоимость одной облигации выпуска ИЦБ ДОМ.РФ на Дату размещения), руб. <--
        self.startBondPrincipal = float(self.bondParameters['startBondPrincipal'])

        # --> Первоначальный объем выпуска (сумма номинальных стоимостей всех облигаций выпуска ИЦБ ДОМ.РФ на Дату размещения), руб. <--
        self.startIssuePrincipal = float(self.bondParameters['startIssuePrincipal'])

        # --> Порог условия clean-up в %, % <--
        # Cогласно эмиссионной документации, эмитент имеет право досрочного погашения выпуска облигаций в дату купонной выплаты, следующую
        # за датой купонной выплаты, в которую отношение непогашенного номинала облигации к первоначальному номиналу облигации стало меньше
        # порога clean-up (но не позднее Юридической даты погашения). В рамках модели предполагается, что в том случае, если порог условия
        # clean-up будет достигнут до наступления Юридической даты погашения, эмитент им воспользуется и погасит выпуск облигаций:
        self.cleanUpPercentage = float(self.bondParameters['cleanUpPercentage'])

        # --> Ожидаемый CDR на Дату передачи, % годовых <--
        # Темп выкупа дефолтных закладных (CDR) по ипотечному покрытию в обеспечении выпуска ИЦБ ДОМ.РФ, который устанавливается в расчете
        # в качестве модельного CDR до публикации данных четвертого ежемесячного отчета сервисного агента (т.к. при формировании ипотечного
        # покрытия в нем нет ни одного кредита с просроченной задолженностью, первый дефолт может возникнуть только на четвертый месяц
        # обращения выпуска облигаций). Значение определяется по внутренним моделям ДОМ.РФ на основе данных о кредитах в ипотечном покрытии:
        self.initialExpectedCDR = float(self.bondParameters['initialExpectedCDR'])

        # --> Оплата услуг Поручителя, Сервисного агента и Резервного сервисного агента
        # (первый купон, согласно эмисcионной документации), % годовых <--
        # Сумма регулярных расходов на оплату вознаграждения поручителя, услуг сервисного агента и услуг резервного сервисного агента на
        # дату утверждения условий выпуска облигаций в первом купонном периоде согласно решению о выпуске облигаций:
        self.firstCouponExpensesIssueDoc = float(self.bondParameters['firstCouponExpensesIssueDoc'])

        # --> Оплата услуг Поручителя, Сервисного агента и Резервного сервисного агента
        # (второй и последующие купоны, согласно эмисcионной документации), % годовых <--
        # Сумма регулярных расходов на оплату вознаграждения поручителя, услуг сервисного агента и услуг резервного сервисного агента,
        # начиная с даты начала второго купонного периода согласно решению о выпуске облигаций:
        self.otherCouponsExpensesIssueDoc = float(self.bondParameters['otherCouponsExpensesIssueDoc'])

        # --> Оплата услуг Специализированного депозитария, % годовых <--
        # Тариф вознаграждения специализированного депозитария за ведение реестра ипотечного покрытия и учет закладных согласно
        # решению о выпуске облигаций:
        self.specDepRateIssueDoc = float(self.bondParameters['specDepRateIssueDoc'])

        # --> Минимальная сумма оплаты услуг Специализированного депозитария, руб./мес. <--
        # Минимальная сумма вознаграждения специализированного депозитария за ведение реестра ипотечного покрытия и учет закладных
        # в месяц согласно решению о выпуске облигаций:
        self.specDepMinMonthIssueDoc = float(self.bondParameters['specDepMinMonthIssueDoc'])

        # --> Возмещение расходов Специализированного депозитария, руб./мес. <--
        # Максимальная сумма возмещаемых расходов специализированного депозитария в месяц согласно решению о выпуске облигаций:
        self.specDepCompensationMonthIssueDoc = float(self.bondParameters['specDepCompensationMonthIssueDoc'])

        # --> Оплата услуг управляющей и бухгалтерской организаций (тариф), % <--
        # Доля от непогашенной совокупной номинальной стоимости облигаций на начало квартала, составляющая ежеквартальное вознаграждение
        # управляющей и бухгалтерской организаций согласно решению о выпуске облигаций (в том случае, если вознаграждение считается по
        # тарифу, иначе не определяется):
        self.manAccQuartRateIssueDoc = 0.0
        if self.bondParameters['manAccQuartRateIssueDoc'] is not None:
            self.manAccQuartRateIssueDoc = float(self.bondParameters['manAccQuartRateIssueDoc'])

        # --> Оплата услуг управляющей и бухгалтерской организаций (фикс.), руб./кв. <--
        # Фиксированная сумма ежеквартального вознаграждения управляющей и бухгалтерской организаций согласно решению о выпуске облигаций
        # (в том случае, если вознаграждение фиксированное, иначе не определяется):
        self.manAccQuartFixIssueDoc = 0.0
        if self.bondParameters['manAccQuartFixIssueDoc'] is not None:
            self.manAccQuartFixIssueDoc = float(self.bondParameters['manAccQuartFixIssueDoc'])

        # --> Оплата услуг расчетного агента, руб./год <--
        # Фиксированная сумма годового вознаграждения расчетного агента согласно решению о выпуске облигаций:
        self.paymentAgentYearIssueDoc = float(self.bondParameters['paymentAgentYearIssueDoc'])

        # --> Индикатор начисления процентной ставки на остаток на счете Ипотечного агента, True/False <--
        # Бинарный параметр (да/нет, 1/0), определяющий наличие обязательства банка-держателя счетов Ипотечно-го агента выплачивать
        # проценты по остатку на счете:
        self.reinvestment = bool(self.bondParameters['reinvestment'])

        # --> Вычет из ставки RUONIA для расчета начисляемой процентной ставки, % годовых <--
        # Значение вычета из ставки RUONIA, которое указано в договоре о начислении на остаток на счете Ипотечного агента:
        self.deductionRUONIA = 0.0
        if self.bondParameters['deductionRUONIA'] is not None:
            self.deductionRUONIA = float(self.bondParameters['deductionRUONIA'])

        # --> Фиксированная ставка купона, % годовых <--
        # Дополнительный параметр выпуска ИЦБ ДОМ.РФ, если Тип расчета купонной выплаты = 1 (Плавающая ставка купона).
        # Значение фиксированной процентной ставки, установленной на весь срок обращения облигаций для расчета купонного дохода:
        self.fixedCouponRate = None
        if self.couponType == COUPON_TYPE.FXD:
            self.fixedCouponRate = float(self.bondParameters['fixedCouponRate'])

        # --> Фиксированная надбавка к Ключевой ставке, % годовых <--
        # Дополнительный параметр выпуска ИЦБ ДОМ.РФ, если Тип расчета купонной выплаты = 3 (Плавающая ставка купона).
        # Значение фиксированной надбавки к Ключевой ставке ЦБ РФ, установленной на весь срок обращения облигаций для расчета
        # купонного дохода:
        self.fixedKeyRatePremium = None
        if self.couponType == COUPON_TYPE.FLT:
            self.fixedKeyRatePremium = float(self.bondParameters['fixedKeyRatePremium'])

        # ----- ИСТОРИЧЕСКАЯ СТАТИСТИКА ИПОТЕЧНОГО ПОКРЫТИЯ ------------------------------------------------------------------------------ #
        # Таблица исторической статистики ипотечного покрытия:
        #   — reportDate    --> Дата отчета сервисного агента t
        #   — currentCPR    --> CPR за месяц t, % годовых
        #   — currentCDR    --> CDR за месяц t, % годовых
        #   — historicalCPR --> Исторический CPR (среднее с даты размещения) на дату t, % годовых
        #   — sixMonthsCPR  --> Исторический CPR (среднее за предыдущие 6 месяцев) на дату t, % годовых
        #   — historicalCDR --> Исторический CDR (среднее с даты размещения) на дату t, % годовых
        self.serviceReportsStatistics = pd.DataFrame(self.dataForCalculation['serviceReportsStatistics'])
        self.serviceReportsStatistics['reportDate'] = pd.to_datetime(self.serviceReportsStatistics['reportDate'])
        self.serviceReportsStatistics.sort_values(by='reportDate', inplace=True)
        c = ['currentCPR', 'currentCDR', 'historicalCPR', 'sixMonthsCPR', 'historicalCDR']
        self.serviceReportsStatistics.loc[:, c] = self.serviceReportsStatistics[c].astype(float)

        # ----- ДАННЫЕ ОТЧЕТОВ ДЛЯ ИНВЕСТОРОВ ИЦБ ДОМ.РФ --------------------------------------------------------------------------------- #
        # Таблица необходимых данных из отчетов для инвесторов ИЦБ ДОМ.РФ:
        #   — couponDate        --> Текущая дата перевода средств инвесторам
        #   — bondNextPrincipal --> Номинальная стоимость на конец периода по каждой облигации (т.е. номинал после couponDate), руб.
        #   — bondAmortization  --> Погашение номинальной стоимости по каждой облигации, руб.
        #   — bondCouponPayment --> Купонные выплаты по каждой облигации, руб.
        self.investorsReportsData = pd.DataFrame(self.dataForCalculation['investorsReportsData'])
        self.investorsReportsData['couponDate'] = pd.to_datetime(self.investorsReportsData['couponDate'])
        self.investorsReportsData.sort_values(by='couponDate', inplace=True)

        # ----- ПАРАМЕТРЫ S-КРИВЫХ ------------------------------------------------------------------------------------------------------- #
        # Таблица парамтеров всех доступных S-кривых:
        #   — reportDate         --> Дата отчетов сервисных агентов t
        #   — loanAge            --> Выдержка кредита h, целое число, годы
        #   — beta0, beta1, ...  --> Параметры S-кривых на дату t для выдержки кредита h, числа
        self.sCurvesParameters = pd.DataFrame(self.dataForCalculation['sCurvesParameters'])
        self.sCurvesParameters['reportDate'] = pd.to_datetime(self.sCurvesParameters['reportDate'])
        self.sCurvesParameters.sort_values(by=['reportDate', 'loanAge'], inplace=True)

        # ----- ДОСТУПНЫЕ ДЛЯ ЗАГРУЗКИ СРЕЗЫ ИПОТЕЧНОГО ПОКРЫТИЯ ------------------------------------------------------------------------- #
        # Список ипотечных покрытий по выпуску ИЦБ ДОМ.РФ, доступных для скачивания посредсвтом метода getPoolsData:
        #   — reportDate              --> Дата среза ипотечного покрытия
        #   — governProgramsFraction  --> Доля кредитов с субсидиями, % от суммы остатков основного долга в ипотечном покрытии
        self.pools = pd.DataFrame(self.dataForCalculation['pools'])
        self.pools['reportDate'] = pd.to_datetime(self.pools['reportDate'])
        self.pools.sort_values(by='reportDate', inplace=True)

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ПАРАМЕТРЫ ОЦЕНКИ --------------------------------------------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        # ----- ДАТА ОЦЕНКИ -------------------------------------------------------------------------------------------------------------- #
        # Дата, начиная с которой моделируются платежи по облигации и по отношению к которой производится их дисконтирование
        self.pricingDate = None
        if 'pricingDate' in self.pricingParameters.keys() and self.pricingParameters['pricingDate'] is not None:
            self.pricingDate = np.datetime64(self.pricingParameters['pricingDate'], 'D')
        else:
            # Может быть указана в промежутке от Даты размещения включительно до Юридической даты погашения не включительно
            # (до Фактического даты погашения не включительно, если та определена):
            maximum_possible_date = self.legalRedemptionDate if self.actualRedemptionDate is None else self.actualRedemptionDate
            if not self.issueDate <= np.datetime64('today') < maximum_possible_date:
                self.pricingDate = self.issueDate
            else:
                # Значение по умолчанию – дата фактического проведения расчета (сегодняшняя дата):
                self.pricingDate = np.datetime64('today')

        # Технически-смысловая проверка Даты оценки на валидность. Если Дата оценки не валидна, расчет останавливается:
        condition_1 = self.issueDate <= self.pricingDate < self.firstCouponDate
        condition_2_1 = self.firstCouponDate <= self.pricingDate < self.legalRedemptionDate
        condition_2_2 = True
        if self.actualRedemptionDate is not None:
            condition_2_2 = self.pricingDate < self.actualRedemptionDate
        condition_2 = condition_2_1 and condition_2_2

        if not condition_1 and not condition_2:
            raise Exception(EXCEPTIONS._7)

        # ----- ДАТА И ВРЕМЯ КБД (КРИВОЙ БЕСКУПОННОЙ ДОХОДНОСТИ) ------------------------------------------------------------------------- #
        # Торговый день и время, по состоянию на которые для дисконтирования платежей по облигации выгружаются параметры Кривой бескупонной
        # доходности Московской биржи (КБД). Значение по умолчанию – дата торгов, наиболее актуальная по отношению к Дате оценки (включи-
        # тельно), с максимально поздним временем обновления параметров КБД:
        self.zcycDateTime = self.pricingDate + np.timedelta64(1, 'D') - np.timedelta64(1, 's')
        if 'zcycDateTime' in self.pricingParameters.keys() and self.pricingParameters['zcycDateTime'] is not None:
            self.zcycDateTime = np.datetime64(self.pricingParameters['zcycDateTime'])

        # ----- ПАРАМЕТРЫ КБД (КРИВОЙ БЕСКУПОННОЙ ДОХОДНОСТИ) ---------------------------------------------------------------------------- #
        self.zcycParameters = get(API.GET_ZCYC_COEF.format(self.zcycDateTime), timeout=15).json()

        # ----- ИНДИКАТОР ИСПОЛЬЗОВАНИЯ ТОЛЬКО ДОСТУПНОЙ НА ДАТУ ОЦЕНКИ ИНФОРМАЦИИ ------------------------------------------------------- #
        # Бинарный параметр (1/0, да/нет), определяющий использование в расчете только той информации, которая доступна на Дату оценки.
        # Позволяет проводить оценку облигаций на определенный момент в прошлом без использования информации, доступной на сегодняшний день
        # (например, в целях расчета ожидаемой, а не реализуемой доходности на дату транзакции)
        #
        # Например, если 23.08.2024 проводится расчет с Датой оценки 10.06.2023 со значением индикатора, равным единице, то в расчете будут
        # использованы только те значения Исторической статистики ипотечного покрытия, Данных отчетов для инвесторов ИЦБ ДОМ.РФ, Параметров
        # S-кривых и Доступных для выгрузки срезов ипотечных покрытий, которые были доступны на 10.06.2023
        #
        # В том случае, если 23.08.2024 проводится расчет с Датой оценки 10.06.2023 со значением индикатора, равным нулю, то в расчете будут
        # использованы все доступные на 23.08.2024 данные (таким образом, денежные потоки по кредитам в ипотечном покрытии будут моделиро-
        # ваться, начиная с самого свежего по состоянию на 23.08.2024 среза ипотечного покрытия, а известные после 10.06.2023 денежные
        # выплаты по выпуску облигаций будут напрямую использованы при дисконтировании)
        #
        # Значение по умолчанию – 0 (нет), т.е. расчет проводится на данных, доступных на фактическую дату расче-та
        self.usePricingDateDataOnly = False
        if 'usePricingDateDataOnly' in self.pricingParameters.keys() and self.pricingParameters['usePricingDateDataOnly'] is not None:
            self.usePricingDateDataOnly = bool(self.pricingParameters['usePricingDateDataOnly'])

        # В том случае, если у выпуска ИЦБ ДОМ.РФ фиксированный график амортизации номинально стоимости, необходимо исключить возможность
        # оценки облигаций данного выпуска с индикатором, равным единице (в противном случае, расчет будет проведен с моделированием
        # амортизации выпуска):
        if self.bondID in fixed_amt_bonds:
            self.usePricingDateDataOnly = False

        # ----- ОЖИДАЕМЫЕ ЗНАЧЕНИЯ КЛЮЧЕВОЙ СТАВКИ --------------------------------------------------------------------------------------- #
        # Пользовательская траектория значений Ключевой ставки, которая будет использована для расчета Модельной траектории среднемесячной
        # рыночной ставки рефинансирования ипотеки. Задается в виде таблицы из двух колонок:
        #       · date — дата, с которой действует соответствующее ей значение Ключевой ставки
        #       · rate — значение Ключевой ставки в % годовых (например, 10.75, 7.00 и т.п.)
        # Траектория устанавливается с точностью до дня. Пример:
        #       [
        #           {'date': '2024-02-11', 'rate': 17.00},
        #           {'date': '2025-07-10', 'rate': 12.00},
        #           {'date': '2026-02-15', 'rate': 9.50},
        #           {'date': '2028-09-20', 'rate': 7.75},
        #       ]
        # Значения по умолчанию выставляются согласно базовой траектории Ключевой ставки (подробнее см. Модель Ключевой ставки в Методике)
        self.keyRateForecast = None
        if 'keyRateForecast' in self.pricingParameters.keys() and self.pricingParameters['keyRateForecast'] is not None:
            if len(self.pricingParameters['keyRateForecast']) > 0:
                keys = self.pricingParameters['keyRateForecast'][0].keys()
                condition_1 = 'date' in keys
                condition_2 = 'rate' in keys
                if condition_1 and condition_2:
                    self.keyRateForecast = pd.DataFrame(self.pricingParameters['keyRateForecast'])
                    self.keyRateForecast['date'] = pd.to_datetime(self.keyRateForecast['date']).values.astype(d_type)
                    self.keyRateForecast.sort_values(by='date', inplace=True)

        # ----- ЗАДАННЫЙ CPR ------------------------------------------------------------------------------------------------------------- #
        # Пользовательское значение CPR для каждого платежа по каждому кредиту (одно значение на все платежи). При заданном CPR S-кривые и
        # Модельная траектория среднемесячной рыночной ставки рефинансирования ипотеки не используются. Каждый платеж по каждому кредиту
        # рассчитывается исходя из заданного значения CPR:
        self.cpr = None
        if 'cpr' in self.pricingParameters.keys() and self.pricingParameters['cpr'] is not None:
            if 0.0 <= float(self.pricingParameters['cpr']) <= 80.0:
                self.cpr = float(self.pricingParameters['cpr'])
            else:
                raise Exception(EXCEPTIONS._9)

        # ----- ЗАДАННЫЙ CDR ------------------------------------------------------------------------------------------------------------- #
        # Пользовательское значение Модельного CDR (modelCDR).
        # Значение по умолчанию – Конвенциональный CDR (conventionalCDR, будет установлено далее):
        self.cdr = None
        if 'cdr' in self.pricingParameters.keys() and self.pricingParameters['cdr'] is not None:
            if 0.0 <= float(self.pricingParameters['cdr']) <= 20.0:
                self.cdr = float(self.pricingParameters['cdr'])
            else:
                raise Exception(EXCEPTIONS._10)

        # ----- ИНДИКАТОР ОКРУГЛЕНИЙ ----------------------------------------------------------------------------------------------------- #
        # В случае равенства индикатора единице значения ценовых метрик (pricingResult) будут указаны с точностью до соответствующего
        # ценовой метрике порядка (например, Z-спред будет округлен до целого б.п., чистая цена будет округлена до сотых и т.д.).
        # В случае равенства индикатора нулю значения ценовых метрик будут указаны с точностью до 15 знаков после запятой:
        self.rounding = False
        self.roundingPrecision = 15
        if 'rounding' in self.pricingParameters.keys() and self.pricingParameters['rounding'] is not None:
            self.rounding = bool(self.pricingParameters['rounding'])

        # ----- ИНДИКАТОР ПРОВЕДЕНИЯ РАСЧЕТА СОГЛАСНО ТРЕБОВАНИЯМ МСФО ------------------------------------------------------------------- #
        # В случае равенства индикатора единице расчет проводится в соответствии с требованиями стандартов МСФО
        self.ifrs = False
        self.poolDataDelay = np.timedelta64(15, 'D')
        self.fullPoolModel = False
        self.swapPricing = False
        if 'ifrs' in self.pricingParameters.keys() and self.pricingParameters['ifrs'] is True:

            self.ifrs = True

            # Оценка может проводиться либо на Дату размещения, либо на конец отчетного месяца. Следовательно, при равенстве индикатора
            # единице, если Дата оценки не равна Дате размещения, день Даты оценки будет автоматически перенесен на последний день месяца:
            if self.pricingDate != self.issueDate:
                self.pricingDate = (self.pricingDate.astype(m_type) + month).astype(d_type) - day

            # Индикатор использования только доступной на Дату оценки информации равен единице:
            self.usePricingDateDataOnly = True

            # Отчеты Сервисного агента ипотечного покрытия по выпуску ИЦБ ДОМ.РФ на 1 число месяца приходят на 7-10 рабочий день месяца.
            # Стандарты МСФО требуют игнорировать эту задержку (например, оценка на отчетную дату 31 мая должна быть рассчитана на сервисном
            # отчете на 1 июня):
            self.poolDataDelay = np.timedelta64(0, 'D')

            # В целях экономии расчетного времени денежный поток по ипотечному покрытию в рамках методики по умолчанию моделируется до
            # конца расчетного периода юридической даты погашения выпуска облигаций. Стандарты МСФО требуют моделировать ипотечное покрытие
            # до последней выплаты:
            self.fullPoolModel = True

            # В рамках методики по умолчанию свопы между Ипотечным агентом ДОМ.РФ и ДОМ.РФ (а также между ДОМ.РФ и Оригинаторами ипотечных
            # покрытий) не моделируются. Стандарты МСФО требуют проводить оценку свопов:
            if self.couponType in [COUPON_TYPE.FXD, COUPON_TYPE.FLT]:
                self.swapPricing = True

            # Согласно стандартам МСФО, Модельный CDR должен быть равен 0:
            self.cdr = 0.0

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ОПРЕДЕЛЕНИЕ ДАТЫ СРЕЗА И ТИПА ИПОТЕЧНОГО ПОКРЫТИЯ  ----------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        # ----- ДАТА ЗАГРУЗКИ ИПОТЕЧНОГО ПОКРЫТИЯ ДЛЯ РАСЧЕТА ---------------------------------------------------------------------------- #
        # Дата, по состоянию на которую (включительно) необходимо загрузить наиболее актуальное ипотечное покрытие:
        self.poolDownloadDate = None
        if self.usePricingDateDataOnly:
            self.poolDownloadDate = max(self.deliveryDate, self.pricingDate - self.poolDataDelay + self.ifrs * day)
            # ("self.ifrs * day" добавляется для того, чтобы в случае расчета по требованиям МСФО на Дату оценки, например, 31.03.2024
            # использовались данные на 01.04.2024)
        else:
            self.poolDownloadDate = np.datetime64('today')

        # В случае, если облигации готовятся к выпуску, и необходимо провести расчет до размещения выпуска облигаций, то дату загрузки
        # ипотечного покрытия необходимо перенести на дату передачи:
        if self.poolDownloadDate < self.deliveryDate:
            self.poolDownloadDate = self.deliveryDate

        # ----- ДАТА СРЕЗА ИПОТЕЧНОГО ПОКРЫТИЯ ДЛЯ РАСЧЕТА ------------------------------------------------------------------------------- #
        self.poolReportDate = None

        # Самое актуальное ипотечное покрытие из доступных по состоянию на poolDownloadDate:
        index = self.pools['reportDate'] <= self.poolDownloadDate
        self.poolReportDate = self.pools[index]['reportDate'].values[-1].astype(d_type)

        # Дата, которой, по логике, должна быть равна self.poolReportDate:
        date_to_be = max(self.deliveryDate, self.poolDownloadDate.astype(m_type).astype(d_type))
        if self.poolReportDate != date_to_be:
            warnings.warn(WARNINGS._1.format(self.bondID, str(date_to_be), str(self.poolReportDate)))

        # По требованиям МСФО необходимо использовать либо срез на Дату передачи (в случае оценки на дату признания), либо отчет сервисного
        # агента на дату, следующую за датой отчетности МСФО (например, на дату отчетности МСФО 31.03.2024 должны использоваться данные
        # на 01.04.2024). Если это не так, расчет не имеет смысла, должна выдаваться ошибка (может быть в том случае, если в базе данных
        # еще не появился отчет на нужную дату):
        if self.ifrs:
            condition_1 = self.pricingDate != self.issueDate
            condition_2 = self.poolReportDate != self.pricingDate + day
            if condition_1 and condition_2:
                raise Exception(EXCEPTIONS._11.format(str(self.pricingDate), str(self.poolReportDate)))

        # ----- ТИП ИПОТЕЧНОГО ПОКРЫТИЯ -------------------------------------------------------------------------------------------------- #
        # В рамках методики выделяются три типа ипотечного покрытия:
        #    1.	Стандартное ипотечное покрытие полностью состоит из кредитов с фиксированной процентной ставкой
        #    2.	Субсидируемое ипотечное покрытие полностью состоит из субсидируемых кредитов с плавающей процентной ставкой (текущая
        #       Ключевая ставка + фиксированная для кредита надбавка)
        #    3.	В смешанном ипотечном покрытии есть кредиты как с фиксированной, так и с плавающей процентной ставкой

        self.poolType = None
        self.governProgramsFraction = None
        self.governProgramsFractionLowerBound = 0.5
        self.governProgramsFractionUpperBound = 99.5

        # Тип ипотечного покрытия определяется исходя из значения Доли кредитов с субсидиями на Дату среза ипотечного покрытия для расчета
        # (согласно данным из таблицы Доступных для загрузки срезов ипотечного покрытия):
        index = self.pools['reportDate'] == self.poolReportDate
        self.governProgramsFraction = self.pools[index]['governProgramsFraction'].values[0]

        if self.governProgramsFraction <= self.governProgramsFractionLowerBound:
            self.poolType = POOL_TYPE.FXD
        elif self.governProgramsFraction >= self.governProgramsFractionUpperBound:
            self.poolType = POOL_TYPE.FLT
        else:
            self.poolType = POOL_TYPE.MIX

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ОПОРНЫЕ ЦЕНОВЫЕ МЕТРИКИ  ------------------------------------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        # Опорная ценовая метрика — ценовая метрика ИЦБ ДОМ.РФ, которая задается пользователем в явном виде и относительно которой
        # проводится расчет. В качестве опорной метрики, в зависимости от Типа расчета купонной выплаты и Типа ипотечного покрытия,
        # могут выступать:
        self.zSpread = None  # Z-СПРЕД
        self.gSpread = None  # G-СПРЕД
        self.dirtyPrice = None  # ГРЯЗНАЯ ЦЕНА
        self.cleanPrice = None  # ЧИСТАЯ ЦЕНА
        self.requiredKeyRatePremium = None  # ТРЕБУЕМАЯ НАДБАВКА

        # В зависимости от заданной опорной метрики определяется Тип расчета, в соответствии с котором далее будет выбран алгоритм расчета:
        self.calculationType = None

        # Однако для различных комбинаций типа ставки купона и типа ипотечного покрытия набор возможных для уставноки значения отличается.
        # Прежде чем проводить расчет, необходимо определиться, верно ли заданы параметры расчета. Для начала определим, что вообще задано:
        z = 'zSpread' in self.pricingParameters.keys() and self.pricingParameters['zSpread'] is not None
        g = 'gSpread' in self.pricingParameters.keys() and self.pricingParameters['gSpread'] is not None
        d = 'dirtyPrice' in self.pricingParameters.keys() and self.pricingParameters['dirtyPrice'] is not None
        c = 'cleanPrice' in self.pricingParameters.keys() and self.pricingParameters['cleanPrice'] is not None
        p = 'requiredKeyRatePremium' in self.pricingParameters.keys() and self.pricingParameters['requiredKeyRatePremium'] is not None
        r = 'fixedCouponRate' in self.pricingParameters.keys() and self.pricingParameters['fixedCouponRate'] is not None
        k = 'fixedKeyRatePremium' in self.pricingParameters.keys() and self.pricingParameters['fixedKeyRatePremium'] is not None

        # Если Тип расчета купонной выплаты — фиксированный:
        if self.couponType == COUPON_TYPE.FXD:

            # Необходимо задать одно из полей Z-СПРЕД, G-СПРЕД, ГРЯЗНАЯ ЦЕНА, ЧИСТАЯ ЦЕНА, СТАВКА КУПОНА:
            if z and not g and not d and not c and not p and not r and not k:
                self.calculationType = CALCULATION_TYPE.SET_ZSPRD
                self.zSpread = float(self.pricingParameters['zSpread'])
                if not CONSTRAINTS.ZSPRD_MIN <= self.zSpread <= CONSTRAINTS.ZSPRD_MAX:
                    raise Exception(CONSTRAINTS.ZSPRD_EXCEP)

            elif g and not z and not d and not c and not p and not r and not k:
                self.calculationType = CALCULATION_TYPE.SET_GSPRD
                self.gSpread = float(self.pricingParameters['gSpread'])
                if not CONSTRAINTS.GSPRD_MIN <= self.gSpread <= CONSTRAINTS.GSPRD_MAX:
                    raise Exception(CONSTRAINTS.GSPRD_EXCEP)

            elif d and not z and not g and not c and not p and not r and not k:
                self.calculationType = CALCULATION_TYPE.SET_DIRTY
                self.dirtyPrice = float(self.pricingParameters['dirtyPrice'])
                if not CONSTRAINTS.DIRTY_MIN <= self.dirtyPrice <= CONSTRAINTS.DIRTY_MAX:
                    raise Exception(CONSTRAINTS.DIRTY_EXCEP)

            elif c and not z and not g and not d and not p and not r and not k:
                self.calculationType = CALCULATION_TYPE.SET_CLEAN
                self.cleanPrice = float(self.pricingParameters['cleanPrice'])
                if not CONSTRAINTS.CLEAN_MIN <= self.cleanPrice <= CONSTRAINTS.CLEAN_MAX:
                    raise Exception(CONSTRAINTS.CLEAN_EXCEP)

            elif r and not z and not g and not d and not c and not p and not k:
                # В том случае, если задана ставка купона, дата оценки автоматически становится равной дате размещения, а индикатор
                # ипользования только доступной на дату оценки информации автоматически становится истинным:
                self.pricingDate = self.issueDate
                self.usePricingDateDataOnly = True
                self.poolReportDate = self.deliveryDate
                self.poolDownloadDate = self.deliveryDate
                self.calculationType = CALCULATION_TYPE.SET_COUPN
                self.fixedCouponRate = float(self.pricingParameters['fixedCouponRate'])
                if not CONSTRAINTS.COUPN_MIN <= self.fixedCouponRate <= CONSTRAINTS.COUPN_MAX:
                    raise Exception(CONSTRAINTS.COUPN_EXCEP)

            else:
                raise Exception(EXCEPTIONS._2)

        # Если Тип расчета купонной выплаты — плавающий:
        elif self.couponType == COUPON_TYPE.FLT:

            # Необходимо задать одно из полей ТРЕБУЕМАЯ НАДБАВКА, ГРЯЗНАЯ ЦЕНА, ЧИСТАЯ ЦЕНА, ФАКТИЧЕСКАЯ НАДБАВКА:
            if p and not z and not g and not d and not c and not r and not k:
                self.calculationType = CALCULATION_TYPE.SET_PREMI
                self.requiredKeyRatePremium = float(self.pricingParameters['requiredKeyRatePremium'])
                if not CONSTRAINTS.PREMI_MIN <= self.requiredKeyRatePremium <= CONSTRAINTS.PREMI_MAX:
                    raise Exception(CONSTRAINTS.PREMI_EXCEP)

            elif d and not z and not g and not c and not p and not r and not k:
                self.calculationType = CALCULATION_TYPE.SET_DIRTY
                self.dirtyPrice = float(self.pricingParameters['dirtyPrice'])
                if not CONSTRAINTS.DIRTY_MIN <= self.dirtyPrice <= CONSTRAINTS.DIRTY_MAX:
                    raise Exception(CONSTRAINTS.DIRTY_EXCEP)

            elif c and not z and not g and not d and not p and not r and not k:
                self.calculationType = CALCULATION_TYPE.SET_CLEAN
                self.cleanPrice = float(self.pricingParameters['cleanPrice'])
                if not CONSTRAINTS.CLEAN_MIN <= self.cleanPrice <= CONSTRAINTS.CLEAN_MAX:
                    raise Exception(CONSTRAINTS.CLEAN_EXCEP)

            elif k and not z and not g and not d and not c and not p and not r:
                # В том случае, если задана фактическая фиксированная надбавка к Ключевой ставке, дата оценки автоматически становится
                # равной дате размещения, а индикатор ипользования только доступной на дату оценки информации
                # автоматически становится истинным:
                self.pricingDate = self.issueDate
                self.usePricingDateDataOnly = True
                self.poolReportDate = self.deliveryDate
                self.poolDownloadDate = self.deliveryDate
                self.calculationType = CALCULATION_TYPE.SET_FXPRM
                self.fixedKeyRatePremium = float(self.pricingParameters['fixedKeyRatePremium'])
                if not CONSTRAINTS.FXPRM_MIN <= self.fixedKeyRatePremium <= CONSTRAINTS.FXPRM_MAX:
                    raise Exception(CONSTRAINTS.FXPRM_EXCEP)
                self.fixedKeyRatePremium /= 100.0

            else:
                raise Exception(EXCEPTIONS._3)

        # Если Тип расчета купонной выплаты — переменный:
        elif self.couponType == COUPON_TYPE.CHG:

            # Если в ипотечном покрытии нет кредитов с субсидиями, то необходимо задать одно из полей
            # Z-СПРЕД, G-СПРЕД, ГРЯЗНАЯ ЦЕНА, ЧИСТАЯ ЦЕНА:
            if self.poolType == POOL_TYPE.FXD:

                if z and not g and not d and not c and not p and not r and not k:
                    self.calculationType = CALCULATION_TYPE.SET_ZSPRD
                    self.zSpread = float(self.pricingParameters['zSpread'])
                    if not CONSTRAINTS.ZSPRD_MIN <= self.zSpread <= CONSTRAINTS.ZSPRD_MAX:
                        raise Exception(CONSTRAINTS.ZSPRD_EXCEP)

                elif g and not z and not d and not c and not p and not r and not k:
                    self.calculationType = CALCULATION_TYPE.SET_GSPRD
                    self.gSpread = float(self.pricingParameters['gSpread'])
                    if not CONSTRAINTS.GSPRD_MIN <= self.gSpread <= CONSTRAINTS.GSPRD_MAX:
                        raise Exception(CONSTRAINTS.GSPRD_EXCEP)

                elif d and not z and not g and not c and not p and not r and not k:
                    self.calculationType = CALCULATION_TYPE.SET_DIRTY
                    self.dirtyPrice = float(self.pricingParameters['dirtyPrice'])
                    if not CONSTRAINTS.DIRTY_MIN <= self.dirtyPrice <= CONSTRAINTS.DIRTY_MAX:
                        raise Exception(CONSTRAINTS.DIRTY_EXCEP)

                elif c and not z and not g and not d and not p and not r and not k:
                    self.calculationType = CALCULATION_TYPE.SET_CLEAN
                    self.cleanPrice = float(self.pricingParameters['cleanPrice'])
                    if not CONSTRAINTS.CLEAN_MIN <= self.cleanPrice <= CONSTRAINTS.CLEAN_MAX:
                        raise Exception(CONSTRAINTS.CLEAN_EXCEP)

                else:
                    raise Exception(EXCEPTIONS._4)

            # Если в ипотечном покрытии только кредиты с субсидиями, то необходимо задать одно из полей
            # ТРЕБУЕМАЯ НАДБАВКА, ГРЯЗНАЯ ЦЕНА, ЧИСТАЯ ЦЕНА:
            elif self.poolType == POOL_TYPE.FLT:

                if p and not z and not g and not d and not c and not r:
                    self.calculationType = CALCULATION_TYPE.SET_PREMI
                    self.requiredKeyRatePremium = float(self.pricingParameters['requiredKeyRatePremium'])
                    if not CONSTRAINTS.PREMI_MIN <= self.requiredKeyRatePremium <= CONSTRAINTS.PREMI_MAX:
                        raise Exception(CONSTRAINTS.PREMI_EXCEP)

                elif d and not z and not g and not c and not p and not r:
                    self.calculationType = CALCULATION_TYPE.SET_DIRTY
                    self.dirtyPrice = float(self.pricingParameters['dirtyPrice'])
                    if not CONSTRAINTS.DIRTY_MIN <= self.dirtyPrice <= CONSTRAINTS.DIRTY_MAX:
                        raise Exception(CONSTRAINTS.DIRTY_EXCEP)

                elif c and not z and not g and not d and not p and not r:
                    self.calculationType = CALCULATION_TYPE.SET_CLEAN
                    self.cleanPrice = float(self.pricingParameters['cleanPrice'])
                    if not CONSTRAINTS.CLEAN_MIN <= self.cleanPrice <= CONSTRAINTS.CLEAN_MAX:
                        raise Exception(CONSTRAINTS.CLEAN_EXCEP)

                else:
                    raise Exception(EXCEPTIONS._5)

            # Если в ипотечном покрытии и кредиты без субсидий, и кредиты с субсидиями, то необходимо задать два параметра одновременно:
            # Z-СПРЕД (для части выпуска облигаций, которая обеспечивается кредитами без субсидий) и ТРЕБУЕМАЯ НАДБАВКА (для части выпуска
            # облигаций, которая обеспечивается кредитами с субсидиями):
            else:

                if z & p and not g and not d and not c and not r:

                    self.calculationType = CALCULATION_TYPE.SET_Z_PRM

                    self.zSpread = float(self.pricingParameters['zSpread'])
                    if not CONSTRAINTS.ZSPRD_MIN <= self.zSpread <= CONSTRAINTS.ZSPRD_MAX:
                        raise Exception(CONSTRAINTS.ZSPRD_EXCEP)

                    self.requiredKeyRatePremium = float(self.pricingParameters['requiredKeyRatePremium'])
                    if not CONSTRAINTS.PREMI_MIN <= self.requiredKeyRatePremium <= CONSTRAINTS.PREMI_MAX:
                        raise Exception(CONSTRAINTS.PREMI_EXCEP)

                else:
                    raise Exception(EXCEPTIONS._6.format(np.round(self.governProgramsFraction, 2)))

        # [ОБНОВЛЕНИЕ СТАТУСА РАСЧЕТА]
        self.currentPercent = 3.0
        update(self.connectionId, self.currentPercent, self.progressBar)

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- РАСЧЕТНЫЕ ПАРАМЕТРЫ ------------------------------------------------------------------------------------------------------ #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        # ----- ЛАГ РАСЧЕТНОГО ПЕРИОДА --------------------------------------------------------------------------------------------------- #
        # Равенство Лага расчетного периода единице означает, что последним месяцем расчетного периода является не предыдущий от купонной
        # выплаты месяц, а предшествующий ему:
        self.paymentPeriodLag = 1 if self.firstCouponDate.astype(object).day < 16 else 0

        # ----- СТРУКТУРА ВЫПЛАТ ПО ОБЛИГАЦИЯМ ------------------------------------------------------------------------------------------- #
        # Таблица, содержащая информация обо всех датах купонных выплат по облигации и соответствующим им датам начала и конца
        # расчетных периодов:
        self.couponsStructure = pd.DataFrame({})

        # --> Даты купонных выплат <--
        # Даты купонных выплат по выпуску облигаций определяются от Даты первой купонной выплаты до Юридической даты погашения с шагом,
        # равным Длине купонного периода (праздники и выходные дни не учитываются, т.е. порядковый день месяца для каждой модельной купонной
        # выплаты равен порядковому дню месяца Даты первой купонной выплаты):
        start_range = self.firstCouponDate.astype(m_type)
        end_range = self.legalRedemptionDate.astype(m_type)
        step = np.timedelta64(self.couponPeriod, 'M')
        payment_day = np.timedelta64(self.firstCouponDate.astype(object).day - 1, 'D')
        self.couponDates = np.arange(start_range, end_range + month, step).astype(d_type) + payment_day
        self.couponsStructure['couponDate'] = self.couponDates

        # --> Количество дней в купонном периоде, предшествующем дате купонной выплаты <--
        # Рассчитывается для каждой из дат купонных выплат. Для первой купонной выплаты определяется как количество дней между Датой
        # размещения (включительно) и Датой выплаты первого купона (невключительно). В остальных случаях как количество дней между датой
        # купонной выплаты, для которой производится расчет (невключительно), и предшествующей ей датой купонной выплаты (включительно):
        self.couponsStructure['couponPeriodDays'] = self.couponsStructure['couponDate'].diff()
        self.couponsStructure.loc[0, 'couponPeriodDays'] = self.firstCouponDate - self.issueDate
        self.couponsStructure['couponPeriodDays'] /= np.timedelta64(1, 'D')

        # --> Дата конца расчетного периода, соответствующего дате купонной выплаты <--
        # Расчетный период – период, соответствующий купонной выплате, за который в эту купонную выплату направляются поступления по
        # ипотечному покрытию. Дата конца расчетного периода определяется как последний день месяца, предшествующего месяцу даты
        # купонной выплаты. В том случае, если Лаг расчетного периода равен единице, производится дополнительный сдвиг на месяц назад:
        pay_period_end = (self.couponDates.astype(m_type) - self.paymentPeriodLag * month).astype(d_type) - day
        self.couponsStructure['paymentPeriodEnd'] = pay_period_end

        # --> Дата начала расчетного периода, соответствующего дате купонной выплаты <--
        # Определяется как первый день месяца, отстающего от месяца Даты конца расчетного периода, соответствующего дате купонной выплаты,
        # на [Длина купонного периода - 1] месяцев. Например, если Дата конца расчетного периода 31 мая, а Длина купонного периода состав-
        # ляет 3 месяца, то Датой начала расчетного периода является 1 марта. Расчетный период первого купона начинается в Дату передачи:
        pay_period_start = ((pay_period_end + day).astype(m_type) - self.couponPeriod * month).astype(d_type)
        self.couponsStructure['paymentPeriodStart'] = pay_period_start
        self.couponsStructure.loc[0, 'paymentPeriodStart'] = self.deliveryDate

        # --> Количество дней в расчетном периоде, соответствующем дате купонной выплаты <--
        # Количество дней между Датой начала и Датой конца расчетного периода (обе даты включительно):
        pay_period_start = self.couponsStructure['paymentPeriodStart'].values
        self.couponsStructure['paymentPeriodDays'] = (pay_period_end - pay_period_start + day) / day

        # ----- ЮРИДИЧЕСКАЯ ДАТА ПОГАШЕНИЯ ВЫПУСКА ОБЛИГАЦИЙ ДЛЯ РАСЧЕТА ----------------------------------------------------------------- #
        # Дата, не позже которой в рамках расчета будет погашен выпуск облигаций. В качестве такой даты может выступать Юридическая дата
        # погашения или Фактическая дата погашения (если известна). В том случае, если Индикатор использования только доступной на Дату
        # оценки информации равен 1, необходимо учесть, что на момент Даты оценки Фактическая дата погашения еще могла быть не известна:

        self.calculationRedemptionDate = None
        if self.actualRedemptionDate is not None:
            if self.usePricingDateDataOnly:
                # Цитата из решений о выпуске ИЦБ ДОМ.РФ: "Эмитент должен принять решение об осуществлении досрочного погашения Облигаций и
                # осуществить раскрытие информации о досрочном погашении Облигаций по усмотрению Эмитента не позднее чем за 14 дней до даты
                # осуществления такого досрочного погашения":
                condition = (self.actualRedemptionDate - self.pricingDate) / day < 14
                self.calculationRedemptionDate = self.actualRedemptionDate if condition else self.legalRedemptionDate
            else:
                self.calculationRedemptionDate = self.actualRedemptionDate
        else:
            self.calculationRedemptionDate = self.legalRedemptionDate

        # ----- СООТВЕТСТВИЕ КУПОННЫХ ВЫПЛАТ И МЕСЯЦЕВ, ЗА КОТОРЫЕ ПРИХОДЯТ ПЛАТЕЖИ И СУБСИДИИ ------------------------------------------- #
        # Таблица, содержащая информацию о соответствии между месяцами платежей и субсидий по ипотечному покрытию датами купонных выплат:
        self.paymentsStructure = pd.DataFrame({})

        # --> Все возможные даты среза ипотечного покрытия <--
        # Все даты между Датой перадачи (включительно) и первым днем последнего месяца расчетного периода Юридической даты погашения
        # облигаций для расчета (включительно), на которые были/будут составлены срезы ипотечного покрытия:
        start_range = self.deliveryDate.astype(m_type)
        # end_range определяется как последний месяц расчетного периода юридической даты погашения выпуска облигаций:
        end_range = (self.calculationRedemptionDate.astype(m_type) - self.paymentPeriodLag * month)
        step = np.timedelta64(1, 'M')
        self.paymentsStructure['reportDate'] = np.arange(start_range, end_range, step).astype(d_type)
        self.paymentsStructure.loc[0, 'reportDate'] = self.deliveryDate

        # --> Месяц платежей по ипотечному покрытию и начисления субсидий <--
        # Определяется как месяц, на который приходится дата среза ипотечного покрытия. По содержанию является месяцем, за который приходят
        # платежи по ипотечному покрытию и за который начисляются субсидии (при наличии):
        self.paymentsStructure['paymentMonth'] = self.paymentsStructure['reportDate'].values.astype(m_type)

        # --> Соответствующая дата купонной выплаты (в части платежей по кредитам) <--
        # Расчетному периоду данной купонной выплаты относятся платежи по кредитам (погашения остатков основного долга и процентные
        # поступления), поступившим в Месяц платежей по ипотечному покрытию и начисления субсидий (paymentMonth):
        for i in range(len(self.paymentsStructure)):
            report_date = self.paymentsStructure['reportDate'].values[i].astype(d_type)
            index = (report_date >= pay_period_start) & (report_date <= pay_period_end)
            coupon_date = self.couponsStructure['couponDate'].values[index]
            if coupon_date.size == 1:
                self.paymentsStructure.loc[i, 'couponDate'] = coupon_date[0]

        # --> Дата поступления субсидии <--
        # Дата, в которую ожидается поступление субсидий за Месяц платежей по ипотечному покрытию и начисления субсидий (paymentMonth).
        # Определяется согласно таблице subsidy_months в модуле auxiliary:
        self.subsidyPaymentMonths = pd.DataFrame(self.paymentsStructure['reportDate'].dt.month.values, columns=['accrualMonth'])
        self.subsidyPaymentMonths = self.subsidyPaymentMonths.merge(subsidy_months, how='left', on='accrualMonth')
        self.subsidyPaymentDay = subsidy_payment_day  # день месяца, в который приходит субсидия
        paymentMonths = self.paymentsStructure['paymentMonth'].values.astype(m_type)
        self.paymentsStructure['subsidyPaymentDate'] = (paymentMonths + month * self.subsidyPaymentMonths['addMonths'].values).astype(
            d_type)
        self.paymentsStructure['subsidyPaymentDate'] += (self.subsidyPaymentDay - 1) * day

        # --> Соответствующая дата купонной выплаты (в части субсидий) <--`
        # Расчетному периоду данной купонной выплаты относятся субсидии, начисленные за Месяц платежей по ипотечному покрытию и начисления
        # субсидий (paymentMonth):
        for i in range(len(self.paymentsStructure)):
            subsidy_date = self.paymentsStructure['subsidyPaymentDate'].values[i].astype(d_type)
            index = (subsidy_date >= pay_period_start) & (subsidy_date <= pay_period_end)
            coupon_date = self.couponsStructure['couponDate'].values[index]
            if coupon_date.size == 1:
                self.paymentsStructure.loc[i, 'subsidyCouponDate'] = coupon_date[0]

        # ----- ПРЕДЫДУЩАЯ ОТ ДАТЫ ОЦЕНКИ ДАТА КУПОННОЙ ВЫПЛАТЫ -------------------------------------------------------------------------- #
        self.previousCouponDate = None
        if self.pricingDate >= self.firstCouponDate:
            self.previousCouponDate = self.couponDates[self.couponDates <= self.pricingDate][-1]

            # Технически-смысловая проверка Даты оценки на валидность (продолжение). Если Дата оценки не валидна, расчет останавливается:
            if not self.previousCouponDate in self.investorsReportsData['couponDate'].values:
                raise Exception(EXCEPTIONS._8)

        # ----- СЛЕДУЮЩАЯ ПОСЛЕ ДАТЫ ОЦЕНКИ ДАТА КУПОННОЙ ВЫПЛАТЫ ------------------------------------------------------------------------ #
        # Определяется как первая дата из Дат купонных выплат, наступающая строго после Даты оценки (в том случае, если Дата оценки равна
        # одной из Дат купонных выплат, берется следующая за Датой оценки дата купонной выплаты):
        self.nextCouponDate = self.couponDates[self.couponDates > self.pricingDate][0]

        # ----- КОЛИЧЕСТВО ПРОШЕДШИХ ДНЕЙ В ТЕКУЩЕМ КУПОННОМ ПЕРИОДЕ --------------------------------------------------------------------- #
        # Дата оценки не включается:
        self.daysPassedInCurrentCouponPeriod = None
        if self.nextCouponDate == self.firstCouponDate:
            self.daysPassedInCurrentCouponPeriod = float((self.pricingDate - self.issueDate) / np.timedelta64(1, 'D'))
        else:
            self.daysPassedInCurrentCouponPeriod = float((self.pricingDate - self.previousCouponDate) / np.timedelta64(1, 'D'))

        # ----- КОЛИЧЕСТВО ОБЛИГАЦИЙ В ВЫПУСКЕ ------------------------------------------------------------------------------------------- #
        self.numberOfBonds = self.startIssuePrincipal / self.startBondPrincipal

        # ----- НЕПОГАШЕННЫЙ НОМИНАЛ ОБЛИГАЦИИ НА ДАТУ ОЦЕНКИ ---------------------------------------------------------------------------- #
        self.currentBondPrincipal = None
        if self.issueDate <= self.pricingDate < self.firstCouponDate:
            self.currentBondPrincipal = self.startBondPrincipal
        else:
            index = self.investorsReportsData['couponDate'].values == self.previousCouponDate
            self.currentBondPrincipal = self.investorsReportsData['bondNextPrincipal'].values[index][0]

        # ----- МАКСИМАЛЬНАЯ ДАТА КУПОННОЙ ВЫПЛАТЫ С ИЗВЕСТНЫМ ПЛАТЕЖОМ ------------------------------------------------------------------ #
        self.maximumCouponDateWithKnownPayment = None
        if not self.investorsReportsData.empty:
            self.maximumCouponDateWithKnownPayment = self.investorsReportsData['couponDate'].values.max().astype(d_type)

        # ----- ПОРОГ УСЛОВИЯ CLEAN-UP В РУБЛЯХ (В ТЕРМИНАХ ВЫПУСКА ОБЛИГАЦИЙ) ----------------------------------------------------------- #
        self.cleanUpRubles = self.numberOfBonds * self.startBondPrincipal * self.cleanUpPercentage / 100.0

        # ----- СОВОКУПНЫЙ ТАРИФ ОСНОВНЫХ РАСХОДОВ ИПОТЕЧНОГО АГЕНТА (ЧАСТЬ 1) ----------------------------------------------------------- #
        self.mortgageAgentExpense1 = np.round(self.firstCouponExpensesIssueDoc - self.otherCouponsExpensesIssueDoc, 5)

        # ----- СОВОКУПНЫЙ ТАРИФ ОСНОВНЫХ РАСХОДОВ ИПОТЕЧНОГО АГЕНТА (ЧАСТЬ 2) --------------в--------------------------------------------- #
        self.mortgageAgentExpense2 = np.round(2.4 * self.otherCouponsExpensesIssueDoc - 1.2 * self.firstCouponExpensesIssueDoc, 5)

        # ----- ДАТА ПЕРВОЙ МОДЕЛЬНОЙ КУПОННОЙ ВЫПЛАТЫ ----------------------------------------------------------------------------------- #
        self.firstModelCouponDate = None
        if self.usePricingDateDataOnly:
            condition_1 = self.nextCouponDate in self.investorsReportsData['couponDate'].values
            condition_2 = float((self.nextCouponDate - self.pricingDate) / np.timedelta64(1, 'D')) <= 12
            condition_3 = self.nextCouponDate != self.legalRedemptionDate
            condition_4 = True
            if self.actualRedemptionDate is not None:
                condition_4 = self.nextCouponDate != self.actualRedemptionDate
            if condition_1 and condition_2 and condition_3 and condition_4:
                self.firstModelCouponDate = self.couponDates[self.couponDates > self.nextCouponDate][0]
            else:
                self.firstModelCouponDate = self.nextCouponDate
        else:
            if self.maximumCouponDateWithKnownPayment is not None:
                condition_1 = self.maximumCouponDateWithKnownPayment != self.legalRedemptionDate
                condition_2 = True
                if self.actualRedemptionDate is not None:
                    condition_2 = self.maximumCouponDateWithKnownPayment != self.actualRedemptionDate
                if condition_1 and condition_2:
                    self.firstModelCouponDate = self.couponDates[self.couponDates > self.maximumCouponDateWithKnownPayment][0]
                else:
                    self.firstModelCouponDate = None
            else:
                self.firstModelCouponDate = self.nextCouponDate

        # ----- ИНДИКАТОР МОДЕЛИРОВАНИЯ ДЕНЕЖНОГО ПОТОКА ПО ИПОТЕЧНОМУ ПОКРЫТИЮ ---------------------------------------------------------- #
        self.runCashflowModel = True
        if self.firstModelCouponDate is None and not self.ifrs:
            # Все будущие платежи по облигации известны, моделирование денежного потока по ипотечному покрытию не производится:
            self.runCashflowModel = False

        # ----- ПАРАМЕТРЫ, НЕОБХОДИМЫЕ В СЛУЧАЕ МОДЕЛИРОВАНИЯ ДЕНЕЖНОГО ПОТОКА ПО ИПОТЕЧНОМУ ПОКРЫТИЮ ------------------------------------ #
        self.startModelBondPrincipal = None
        self.poolCashflowEndDate = None
        self.keyRateModelDate = None
        self.keyRateModelData = None
        self.calculationSCurvesReportDate = None
        self.calculationSCurvesParameters = None
        self.historicalCDRDate = None
        self.historicalCDR = None
        self.conventionalCDR = None
        self.modelCDR = None
        self.deliveryMonths = None

        if self.runCashflowModel:

            # ----- НЕПОГАШЕННЫЙ НОМИНАЛ ОБЛИГАЦИИ ДО ДАТЫ ПЕРВОЙ МОДЕЛЬНОЙ КУПОННОЙ ВЫПЛАТЫ --------------------------------------------- #
            if self.firstModelCouponDate == self.firstCouponDate:
                self.startModelBondPrincipal = self.startBondPrincipal
            elif self.firstModelCouponDate == self.nextCouponDate:
                self.startModelBondPrincipal = self.currentBondPrincipal
            else:
                coupon_date = self.couponDates[self.couponDates < self.firstModelCouponDate][-1]
                index = self.investorsReportsData['couponDate'].values == coupon_date
                self.startModelBondPrincipal = self.investorsReportsData['bondNextPrincipal'].values[index][0]

            # ----- ДАТА, НА КОТОРОЙ ЗАКАНЧИВАЕТСЯ МОДЕЛИРОВАНИЕ ДЕНЕЖНОГО ПОТОКА ПО ИПОТЕЧНОМУ ПОКРЫТИЮ --------------------------------- #
            if not self.fullPoolModel:
                # Определяется как последний день расчетного периода юридической даты погашения выпуска облигаций для расчета:
                redemption_month = self.calculationRedemptionDate.astype(m_type)
                self.poolCashflowEndDate = (redemption_month - self.paymentPeriodLag * month).astype(d_type) - day

            # ----- ОПОРНАЯ ДАТА МОДЕЛИ КЛЮЧЕВОЙ СТАВКИ ---------------------------------------------------------------------------------- #
            # Дата, по состоянию на которую производится расчет ожидаемой траектории Ключевой ставки:
            if self.usePricingDateDataOnly:
                self.keyRateModelDate = min(self.pricingDate, np.datetime64('today'))
            else:
                self.keyRateModelDate = np.datetime64('today')

            # Загрузка данных для модели Ключевой ставки производится на Опорную дату модели макроэкономики:
            self.keyRateModelData = get(API.GET_MACR_DATA.format(self.keyRateModelDate), timeout=15).json()

            # ----- ДАТА ПАРАМЕТРОВ S-КРИВЫХ ДЛЯ РАСЧЕТА --------------------------------------------------------------------------------- #
            if self.usePricingDateDataOnly:
                date_a_1 = (self.pricingDate - self.poolDataDelay + self.ifrs * day).astype(m_type).astype(d_type)
                # ("self.ifrs * day" добавляется для того, чтобы в случае расчета по требованиям МСФО на Дату оценки, например, 31.03.2024
                # использовались данные на 01.04.2024)
                date_a_2 = self.sCurvesParameters['reportDate'].values.max().astype(d_type)
                date_a = min(date_a_1, date_a_2)
                date_b = self.sCurvesParameters['reportDate'].values.min().astype(d_type)
                self.calculationSCurvesReportDate = max(date_a, date_b)
            else:
                self.calculationSCurvesReportDate = self.sCurvesParameters['reportDate'].values.max().astype(d_type)

            # ----- ПАРАМЕТРЫ S-КРИВЫХ ДЛЯ РАСЧЕТА --------------------------------------------------------------------------------------- #
            s_curve_index = self.sCurvesParameters['reportDate'] == self.calculationSCurvesReportDate
            self.calculationSCurvesParameters = self.sCurvesParameters[s_curve_index].copy(deep=True)

            # ----- ДАТА АКТУАЛЬНОСТИ ИСТОРИЧЕСКОГО CDR ---------------------------------------------------------------------------------- #
            condition_1 = len(self.serviceReportsStatistics) >= 4
            if self.usePricingDateDataOnly:
                condition_2 = False
                if condition_1:
                    condition_2 = self.pricingDate >= self.serviceReportsStatistics['reportDate'].values[3] + self.poolDataDelay
                if condition_1 and condition_2:
                    index = self.serviceReportsStatistics['reportDate'].values <= self.pricingDate - self.poolDataDelay + self.ifrs * day
                    self.historicalCDRDate = self.serviceReportsStatistics['reportDate'].values[index][-1].astype(d_type)
            else:
                if condition_1:
                    self.historicalCDRDate = self.serviceReportsStatistics['reportDate'].values.max().astype(d_type)

            # ----- ИСТОРИЧЕСКИЙ CDR ----------------------------------------------------------------------------------------------------- #
            if self.historicalCDRDate is not None:
                index = self.serviceReportsStatistics['reportDate'].values == self.historicalCDRDate
                self.historicalCDR = np.round(self.serviceReportsStatistics['historicalCDR'].values[index][0], 1)

            # ----- КОНВЕНЦИОНАЛЬНЫЙ CDR ------------------------------------------------------------------------------------------------- #
            if self.historicalCDRDate is None:
                self.conventionalCDR = self.initialExpectedCDR
            else:
                self.conventionalCDR = self.historicalCDR
            self.conventionalCDR = np.round(self.conventionalCDR, 1)

            # ----- МОДЕЛЬНЫЙ CDR -------------------------------------------------------------------------------------------------------- #
            if self.cdr is not None:
                self.modelCDR = self.cdr
            else:
                self.modelCDR = self.conventionalCDR
            self.modelCDR = np.round(self.modelCDR, 1)

            # ----- КОЛИЧЕСТВО МЕСЯЦЕВ С ДАТЫ ПЕРЕДАЧИ ----------------------------------------------------------------------------------- #
            # Количество полных месяцев, которое прошло между Датой передачи и Датой среза ипотечного покрытия для расчета. Необходимо для
            # того, чтобы учесть, что на Дату передачи в ипотечном покрытии нет кредитов с просроченной задолженностью, из-за чего первые
            # три месяца после после месяца, на который приходится дата передачи, в ипотечном покрытии не будет дефолтов:
            self.deliveryMonths = int(np.floor((self.poolReportDate - self.deliveryDate) / day / 30.5))

        ####################################################################################################################################

        self.poolData = None
        self.poolCashflow = pd.DataFrame({})
        self.mbsCashflow = pd.DataFrame({})
        self.mbsCashflowFixed = pd.DataFrame({})
        self.mbsCashflowFloat = pd.DataFrame({})
        self.modelCPR = None
        self.poolModelCPR = None
        self.swapModel = None
        self.swapPrice = None

        self.pricingResult = {}
        self.yearsToCouponDate = None
        self.zcycValuesY = None
        self.discountFactorZCYCPlusZ = None
        self.discountFactorYTM = None
        self.durationMacaulay_func = None
        self.accruedCouponInterest = None
        self.accruedCouponInterestRub = None
        self.dirtyPriceRub = None
        self.cleanPriceRub = None
        self.ytm = None
        self.durationMacaulay = None
        self.durationModified = None
        self.modelKeyRatePremium = None

        self.calculationOutput = {}
        self.calculationParameters = {}
        self.mbsCashflowTable = None
        self.historicalCashflow = None
        self.mbsCashflowGraph = None
        self.zcycGraph = None
        self.sCurveEmpiricalData = None
        self.sCurveGraph = None

        # [ОБНОВЛЕНИЕ СТАТУСА РАСЧЕТА]
        self.currentPercent = 5.0
        update(self.connectionId, self.currentPercent, self.progressBar)

        ####################################################################################################################################

    def __del__(self):
        pass

    def poolCashflowModel(self):

        """ Функция, запускаающая модель денежного потока по ипотечному покрытии """

        # Для корректного отображения статуса расчета необходимо заранее знать, сколько раз будет запущена модель денежного потока по
        # ипотечному покрытию. Модель запускается как минимум один раз, однако она может быть запущена еще несколько раз (подробнее
        # см. описание блока "Добавление уже прошедших платежей по ипотечному покрытию")
        pool_model_times = 1  # Количество прошедших месяцев, за которые нужно восстановить платежи

        # Проверка на восстановление начинается с месяца, предшествующего poolReportDate:
        i = np.sum(self.paymentsStructure['reportDate'] < self.poolReportDate) - 1
        while True:

            if i < 0:
                break

            coupon_date = self.paymentsStructure['couponDate'].values[i].astype(d_type)

            # Восстановление заканчивается тогда, когда:
            # 1. Восстанавливаемый месяц не принадлежит расчетному периоду Даты первой модельной купонной выплаты:
            condition_1 = coupon_date < self.firstModelCouponDate

            # 2. При наличии субсидий: начисленные за восстанавливаемый месяц субсидии приходят в расчетной период купонной выплаты,
            # строго меньшей Даты первой модельной купонной выплаты:
            condition_2 = True
            if self.poolType in [POOL_TYPE.FLT, POOL_TYPE.MIX]:
                subsidy_coupon_date = self.paymentsStructure['subsidyCouponDate'].values[i].astype(d_type)
                condition_2 = subsidy_coupon_date < self.firstModelCouponDate

            # 3. При наличии начислений на остаток на счете Ипотечного агента: восстаналиваемый месяц принадлежит расчетному периоду
            # купонной выплаты, строго меньшей Предыдущей от даты оценки даты купонной выплаты:
            condition_3 = True
            if self.reinvestment:
                condition_3 = coupon_date < self.previousCouponDate if self.previousCouponDate is not None else False

            if condition_1 and condition_2 and condition_3:
                break

            pool_model_times += 1

            i -= 1

        # Рассчитываем дельту процентов, которая будет обновлять статус расчета при запуске (запусках) модели ипотечного покрытия:
        self.statusDelta = (math.floor(90.0 / pool_model_times)) / 10.0

        # Запуск модели денежного потока по ипотечному покрытию:
        self.loansCashflowModel_res = loansCashflowModel(bond_id=self.bondID,
                                                         report_date=self.poolReportDate,
                                                         key_rate_model_date=self.keyRateModelDate,
                                                         key_rate_model_data=self.keyRateModelData,
                                                         s_curves=self.calculationSCurvesParameters,
                                                         cdr=self.modelCDR,
                                                         cpr=self.cpr,
                                                         ifrs=self.ifrs,
                                                         no_cdr_months=[0, max(0, 3 - self.deliveryMonths)],
                                                         reinvestment=self.reinvestment,
                                                         stop_date=self.poolCashflowEndDate,
                                                         key_rate_forecast=self.keyRateForecast,
                                                         progress_bar=self.progressBar,
                                                         connection_id=self.connectionId,
                                                         current_percent=self.currentPercent,
                                                         status_delta=self.statusDelta)

        # [ОБНОВЛЕНИЕ СТАТУСА РАСЧЕТА]
        self.currentPercent += self.statusDelta * 10.0
        update(self.connectionId, self.currentPercent, self.progressBar)

        # Результат Модели денежного потока по ипотечному покрытию:
        self.macroModel = self.loansCashflowModel_res['macroModel']

        # Результат Моделей Ключевой ставки и ставки рефинансирования ипотеки:
        self.poolModel = self.loansCashflowModel_res['poolModel']

        ####################################################################################################################################

    def mbsCashflowModel(self):

        """ Функция расчета модельного денежного потока по выпуску ИЦБ ДОМ.РФ """

        # Благодаря тому, что модель денежного потока по ипотечному покрытию выстраивает денежный поток отдельно для ипотечного покрытия в
        # части кредитов без субсидий и отдельно для ипотечного покрытия в части кредитов с субсидиями, денежный поток по выпуску облигаций
        # в модельных целях можно разделить на две составные части:
        #       — денежный поток по выпуску облигаций в части кредитов без субсидий
        #       — денежный поток по выпуску облигаций в части кредитов с субсидиями
        # Для удобства и читаемости кода программной реализации методики разделение денежного потока по выпуску облигаций на две части
        # производится всегда. Однако необходимо это только в случае оценки облигаций с переменным купоном и смешанным типом ипотечного
        # покрытия. Важно подчеркнуть, что в реальности разделения ипотечного покрытия и выпуска облигаций на две части нет, поступления
        # по ипотечному покрытию направляются в выплаты по облигации пропорционально

        # Словарь self.mbsModel состоит из трех одинаково структурированных компонентов (частей):
        #       — total — компоненты денежного потока по выпуску ИЦБ ДОМ.РФ
        #       — fixed — компоненты денежного потока по выпуску ИЦБ ДОМ.РФ в части кредитов без субсидий
        #       — float — компоненты денежного потока по выпуску ИЦБ ДОМ.РФ в части кредитов с субсидиями
        # Разбиение выпуска на две части проводится всегда (т.е. независимо от типа купона). В том случае, если, например, в ипотечном
        # покрытии нет кредитов с субсидиями, то таблицы компонентов в объекте float будут содержать нулевые значения, а таблицы
        # компонентов в объектах total и fixed будут одинаковые.

        # Каждый из объектов total, fixed и float состоит из пяти компонентов:
        #       — pool   — помесячный модельный денежный поток по ипотечному покрытию (части ипотечного покрытия в случае fixed и float)
        #       — inflow — модельный денежный поток по расчетным периодам и соответствующие расчетным периодам даты купонных выплат
        #       — issue  — модельный денежный поток по выпуску ИЦБ ДОМ.РФ
        #       — bond   — модельный денежный поток по одной облигации выпуска ИЦБ ДОМ.РФ
        #       — reinvestment   — модельный денежный поток по ипотечному покрытию по дням для расчета начислений на остаток на счете
        #                          Ипотечного агента

        self.mbsModel = {
            'total': {'pool': None, 'inflow': None, 'issue': None, 'bond': None, 'reinvestment': None},
            'fixed': {'pool': None, 'inflow': None, 'issue': None, 'bond': None, 'reinvestment': None},
            'float': {'pool': None, 'inflow': None, 'issue': None, 'bond': None, 'reinvestment': None},
        }

        # Для каждой части total, fixed и float к таблице Соответствия купонных выплат и месяцев, за которые приходят платежи и субсидии
        # (poolReportDates) джоинится таблица денежного потока по ипотечному покрытию (poolModel[part]['cashflow']).
        # После джоина таблица pool читается следующим образом:
        #       1. amortization (вся амортизация), scheduled (погашения по графику), prepayment (частичные и полные досрочные погашения),
        #          defaults (выкупы дефолтов), yield (процентные поступления), пришедшие в месяце paymentMonth, направляются в купонную
        #          выплату couponDate;
        #       2. сумма остатков основного долга debt указана на дату reportDate (до амортизации, прошедшей за месяц paymentMonth);
        #       3. debt составляет fraction процентов от всего ипотечного покрытия на reportDate;
        #       4. субсидия subsidy, рассчитанная по Ключевой ставке keyRate, установленной ЦБ РФ в дату keyRateStartDate, поступит на
        #          счет Ипотечного агента в дату subsidyPaymentDate и будет направлена в купонную выплату subsidyCouponDate
        for part in self.mbsModel.keys():
            self.mbsModel[part]['pool'] = self.poolModel[part]['cashflow']
            self.mbsModel[part]['pool'] = self.paymentsStructure.merge(self.poolModel[part]['cashflow'], how='left', on='paymentMonth')

            if self.reinvestment:
                self.mbsModel[part]['reinvestment'] = self.poolModel[part]['reinvestment']

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ДОБАВЛЕНИЕ УЖЕ ПРОШЕДШИХ ПЛАТЕЖЕЙ ПО ИПОТЕЧНОМУ ПОКРЫТИЮ ----------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        # Если для формирования поступлений в расчетном периоде Даты первой модельной купонной выплаты недостаточно данных модели денежного
        # потока по ипотечному покрытию, необходимо восстановить недостающие платежи за месяцы, предшествующие Дате среза ипотечного
        # покрытия для расчета
        #
        # Например, если Дата первой модельной купонной выплаты приходится на 28 мая с расчетным периодом февраль-март-апрель, а модельный
        # денежный поток по ипотечному покрытию начинается с апреля, то необходимо восстановить информацию о том, сколько денежных средств
        # по ипотечному покрытию поступило за февраль и март (в части погашений основного долга, процентных поступлений и, в случае наличия,
        # субсидий и начисления процентной ставки на остаток на счете Ипотечного агента)
        #
        # Чтобы восстановить суммы погашений основного долга и процентов, нужно запустить модель денежного потока по ипотечному покрытию на
        # ипотечном покрытии на отчетную дату 1 февраля и смоделировать платежи только за февраль, а также на отчетную дату 1 марта и
        # смоделировать платежи только за март
        #
        # В том случае, если в ипотечном покрытии есть субсидии, то также необходимо восстановить все недостающие суммы субсидий.
        # В рассматриваемом примере модельный денежный поток по ипотечному покрытию, начинающийся с апреля, не включает субсидии,
        # начисленные за март (поступят 15 мая), за февраль (поступят 15 апреля), за январь, декабрь и ноябрь (вместе поступят 15 марта).
        # Субсидии, начисленные за март и февраль, уже рассчитаны на предыдущем этапе. Теперь нужно запустить модель денежного потока по
        # ипотечному покрытию еще три раза – на ипотечных покрытиях на отчетные даты 1 ноября (субсидии за ноябрь), 1 декабря (субсидии
        # за декабрь) и 1 января (субсидии за январь)
        #
        # В том случае, если предусмотрено начисление процентной ставки на остаток на счете Ипотечного агента, необходимо учесть все
        # поступления на счет Ипотечного агента, начисления на которые в конечном итоге поступят в расчетный период Даты первой модельной
        # купонной выплаты. В рассматриваемом примере необходимо обратить внимание на то, что в феврале, до даты списания средств перед
        # купонной выплатой 28 февраля, Ипотечному агенту будет начисляться процентная ставка на баланс, сформированный из поступлений
        # расчетного периода купонной выплаты 28 февраля (ноябрь-декабрь-январь). Для того, чтобы определить размер баланса Ипотечного
        # агента на 1 февраля, нужно восстановить платежи за весь расчетный период выплаты 28 февраля, то есть за ноябрь, декабрь и январь.
        # Однако, в данном примере это уже сделано в связи с тем, что в ипотечном покрытии есть субсидии

        recovered_pools = {}

        # Проверка на восстановление начинается с месяца, предшествующего poolReportDate:
        i = np.sum(self.mbsModel['total']['pool']['reportDate'] < self.poolReportDate) - 1
        while True:

            if i < 0:
                break

            coupon_date = self.mbsModel['total']['pool']['couponDate'].values[i].astype(d_type)

            # Восстановление заканчивается тогда, когда:
            # 1. Восстанавливаемый месяц не принадлежит расчетному периоду Даты первой модельной купонной выплаты:
            condition_1 = coupon_date < self.firstModelCouponDate

            # 2. При наличии субсидий: начисленные за восстанавливаемый месяц субсидии приходят в расчетной период купонной выплаты,
            # строго меньшей Даты первой модельной купонной выплаты:
            condition_2 = True
            if self.poolType in [POOL_TYPE.FLT, POOL_TYPE.MIX]:
                subsidy_coupon_date = self.mbsModel['total']['pool']['subsidyCouponDate'].values[i].astype(d_type)
                condition_2 = subsidy_coupon_date < self.firstModelCouponDate

            # 3. При наличии начислений на остаток на счете Ипотечного агента: восстаналиваемый месяц принадлежит расчетному периоду
            # купонной выплаты, строго меньшей Предыдущей от даты оценки даты купонной выплаты:
            condition_3 = True
            if self.reinvestment:
                condition_3 = coupon_date < self.previousCouponDate if self.previousCouponDate is not None else False

            if condition_1 and condition_2 and condition_3:
                break

            # Модель денежного потока по ипотечному покрытию запускается только на восстанавливаемый месяц:
            report_date = self.mbsModel['total']['pool']['reportDate'].values[i].astype(d_type)
            delivery_months = int(np.floor((report_date - self.deliveryDate) / day / 30.5))
            stop_date = (report_date.astype(m_type) + month).astype(d_type) - day
            pool_model = loansCashflowModel(bond_id=self.bondID,
                                            report_date=report_date,
                                            key_rate_model_date=self.keyRateModelDate,
                                            key_rate_model_data=self.keyRateModelData,
                                            s_curves=self.calculationSCurvesParameters,
                                            cdr=self.modelCDR,
                                            cpr=self.cpr,
                                            ifrs=self.ifrs,
                                            no_cdr_months=[0, max(0, 3 - delivery_months)],
                                            reinvestment=self.reinvestment,
                                            stop_date=stop_date,
                                            key_rate_forecast=self.keyRateForecast,
                                            progress_bar=self.progressBar,
                                            connection_id=self.connectionId,
                                            current_percent=self.currentPercent,
                                            status_delta=self.statusDelta)

            # [ОБНОВЛЕНИЕ СТАТУСА РАСЧЕТА]
            self.currentPercent += self.statusDelta * 10.0
            update(self.connectionId, self.currentPercent, self.progressBar)

            recovered_pools[str(report_date)] = pool_model

            # Технически, может возникнуть ситуация, когда на запрашиваемый для восстановеления месяц нет соответствующей данному месяцу
            # report_date. Например, такая ситуация может возникнуть при восстановлении денежного потока за месяц, в котором был размещен
            # выпуск ИЦБ: дата передачи составила 21.11.2023, 22.12.2023 размещен выпуск, и между датой передачи и сервисным отчетом
            # на 01.01.2024 может не быть сервисного отчета на 01.12.2023 (такая ситуация может возникнуть, но не факт, что возникнет).
            # В таком случае, декабрь 2024 будет восстанавливаться по акту передачи 21.11.2023 и по сути будет полностью модельным.
            # Для того, чтобы обезопасить себя от подобного случая, нужно четко указать значение восстанавливаемого paymentMonth:
            payment_months = pool_model['poolModel']['total']['cashflow']['paymentMonth'].values
            first_payment_month = payment_months[0].astype(d_type)
            payment_month_needed = report_date.astype(m_type).astype(d_type)

            if payment_month_needed > first_payment_month:
                valid = payment_months == payment_month_needed
                for part in pool_model['poolModel'].keys():
                    pool_model['poolModel'][part]['cashflow'] = pool_model['poolModel'][part]['cashflow'][valid]

            # В случае self.reinvestment нужно оставить только те платежи amt и yld, которые поступят между report_date и stop_date.
            # Также нужно оставить только те субсидии, которые начислены за месяц report_date:
            if self.reinvestment:
                for part in pool_model['poolModel'].keys():
                    if pool_model['poolModel'][part]['reinvestment'].empty:
                        continue
                    dates = pool_model['poolModel'][part]['reinvestment']['date'].values
                    sub_acc_months = pool_model['poolModel'][part]['reinvestment']['subsidyAccrualMonth'].values

                    # В части amt и yld (np.isnan(sub_acc_months)) должно быть (report_date <= dates) & (dates <= stop_date):
                    cond_1 = np.isnan(sub_acc_months) & (report_date <= dates) & (dates <= stop_date)
                    # В части subsidy (~np.isnan(sub_acc_months)) должно быть (report_date.astype(m_type).astype(d_type) == sub_acc_months):
                    cond_2 = ~np.isnan(sub_acc_months) & (report_date.astype(m_type).astype(d_type) == sub_acc_months)
                    pool_model['poolModel'][part]['reinvestment'] = pool_model['poolModel'][part]['reinvestment'][cond_1 | cond_2]

            # Восстановление платежей:
            for part in self.mbsModel.keys():

                for c in ['debt', 'wac', 'yield', 'fractionOfTotal', 'floatFraction',
                          'waKeyRateDeduction', 'keyRateStartDate', 'keyRate', 'subsidy']:
                    self.mbsModel[part]['pool'].loc[i, c] = pool_model['poolModel'][part]['cashflow'][c].values[0]

                # Проверка восстановленных данных на валидность:
                if self.mbsModel[part]['pool']['debt'].values[i] < self.mbsModel[part]['pool']['debt'].values[i + 1]:
                    raise Exception(EXCEPTIONS._12)

                # Фактическая амортизация за месяц:
                self.mbsModel[part]['pool'].loc[i, 'amortization'] = np.round(self.mbsModel[part]['pool']['debt'].values[i] -
                                                                              self.mbsModel[part]['pool']['debt'].values[i + 1], 2)

                # Денежный поток в месяц i уже является не модельным, а историческим:
                self.mbsModel[part]['pool'].loc[i, 'model'] = 0

                # Далее необходимо в иллюстративных целях "разделить" амортизацию на погашения по графику, досрочные погашения и
                # выкупы дефолтов. Берем модельные погашения по графику:
                scheduled = pool_model['poolModel'][part]['cashflow']['scheduled'].values[0]
                self.mbsModel[part]['pool'].loc[i, 'scheduled'] = min(self.mbsModel[part]['pool']['amortization'].values[i], scheduled)

                # Используем фактическое значение CDR:
                current = self.serviceReportsStatistics['reportDate'] == report_date
                current_cdr = 0.0
                if current.sum() == 1:
                    cdr_value = self.serviceReportsStatistics[current]['currentCDR'].values[0]
                    if not np.isnan(cdr_value):
                        current_cdr = cdr_value

                defaults = np.round(self.mbsModel[part]['pool']['debt'].values[i] * (1.0 - (1.0 - current_cdr / 100.0) ** (1.0 / 12.0)), 2)
                left = self.mbsModel[part]['pool']['amortization'].values[i] - self.mbsModel[part]['pool']['scheduled'].values[i]
                self.mbsModel[part]['pool'].loc[i, 'defaults'] = min(left, defaults)

                # Устанавливаем историческое значение досрочных погашений по остаточному принципу:
                prepayment = np.round(self.mbsModel[part]['pool']['amortization'].values[i] -
                                      self.mbsModel[part]['pool']['scheduled'].values[i] -
                                      self.mbsModel[part]['pool']['defaults'].values[i], 2)
                debt = self.mbsModel[part]['pool']['debt'].values[i] - self.mbsModel[part]['pool']['scheduled'].values[i]
                self.mbsModel[part]['pool'].loc[i, 'prepayment'] = prepayment

                if debt > 0.0:
                    self.mbsModel[part]['pool'].loc[i, 'cpr'] = (1.0 - (1.0 - prepayment / debt) ** 12.0) * 100.0

                # Добавляем поступления по дням для расчета начислений на остаток на счете Ипотечного агента:
                if self.reinvestment:
                    part_reinv = pool_model['poolModel'][part]['reinvestment']
                    self.mbsModel[part]['reinvestment'] = pd.concat([part_reinv, self.mbsModel[part]['reinvestment']])
                    self.mbsModel[part]['reinvestment'].reset_index(drop=True, inplace=True)

            i -= 1

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- РАСПРЕДЕЛЕНИЕ ДЕНЕЖНОГО ПОТОКА ПО ИПОТЕЧНОМУ ПОКРЫТИЮ ПО РАСЧЕТНЫМ ПЕРИОДАМ КУПОННЫХ ВЫПЛАТ ------------------------------ #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        # В рамках модели до пяти источников формируют денежные поступления Ипотечного агента:
        #       — погашения остатков основного долга и процентные поступления по кредитам в ипотечном покрытии
        #       — субсидии по кредитам, выданным в рамках гос. программ субсидирования ипотеки (при наличии)
        #       — начисление процентной ставки на остаток на счете (при наличии)
        #       — разница между объемом выпуска облигаций и объемом ипотечного покрытия на начало первого расчетного периода (при наличии
        #       и только в первом расчетном периоде, описание см. далее)
        #
        # На следующем этапе производится распределение данных поступлений по расчетным периодам (с учетом восстановленных платежей) на
        # основе таблицы Структуры выплат по облигациям и таблицы Соответствия купонных выплат и месяцев, за которые приходят платежи и
        # субсидии. Для каждого объекта mbsModel формируется таблица inflow, содержащая агрегированные по датам купонных платежей денежные
        # потоки по ипотечному покрытию
        #
        # Таблица читается следующим образом: в дату купонной выплаты couponDate ипотечный агент располагает и может направить на погашение
        # ИЦБ такое-то значение amortization (состоящей из scheduled, prepayment, defaults, difference) и на выплату купона такое-то
        # значение yield. В дату купонной выплаты subsidyCouponDate ипотечный агент располагает и может направить на купонную выплату
        # такое-то значение subsidy. Под difference (только для первого купона) понимается разница между первоначальным номиналом выпуска
        # и объемом переданного ипотечного покрытия (в том случае, если новинал выпуска больше). На одном из последующих этапов в таблицу
        # inflow будут добавлены (в случае наличия) значения начислений на остаток на счете, поступившие за расчетный период даты купонной
        # выплаты couponDate

        # Выбираем из всех купонных выплат по облигации только те, для которых будет рассчитан модельный денежный поток:
        coupon_dates = self.couponsStructure['couponDate'].values
        model_coupon_dates = (coupon_dates >= self.firstModelCouponDate) & (coupon_dates <= self.calculationRedemptionDate)

        for part in self.mbsModel.keys():

            self.mbsModel[part]['inflow'] = pd.DataFrame({})

            c = ['couponDate', 'couponPeriodDays', 'paymentPeriodDays']
            self.mbsModel[part]['inflow'].loc[:, c] = self.couponsStructure[c][model_coupon_dates].values

            # Группировка модельного денежного потока по ипотечному покрытию по расчетным периодам:
            c = ['couponDate', 'amortization', 'scheduled', 'prepayment', 'defaults', 'yield']
            payment_periods = self.mbsModel[part]['pool'][c].groupby('couponDate', as_index=False).sum()
            self.mbsModel[part]['inflow'] = self.mbsModel[part]['inflow'].merge(payment_periods, how='left', on='couponDate')

            # Группировка субсидий по расчетным периодам:
            c = ['subsidyCouponDate', 'subsidy']
            payment_periods = self.mbsModel[part]['pool'][c].groupby('subsidyCouponDate', as_index=False).sum()
            self.mbsModel[part]['inflow'] = self.mbsModel[part]['inflow'].merge(payment_periods, how='left',
                                                                                left_on='couponDate', right_on='subsidyCouponDate')
            # Техническая установка нулевых значений:
            self.mbsModel[part]['inflow'] = self.mbsModel[part]['inflow'].infer_objects(copy=False).fillna(0.0)
            self.mbsModel[part]['inflow']['difference'] = 0.0
            self.mbsModel[part]['inflow']['cleanUp'] = 0.0

            # Техническое округление после группировок:
            for col in ['amortization', 'scheduled', 'prepayment', 'defaults', 'yield', 'subsidy']:
                self.mbsModel[part]['inflow'][col] = np.round(self.mbsModel[part]['inflow'][col].values, 2)

        # Непогашенный номинал облигации до Даты первой модельной купонной выплаты (т.е. до даты купонной выплаты, с расчетного периода
        # которой начинается таблица inflow):
        self.mbsModel['total']['principal'] = self.startModelBondPrincipal

        # Непогашенный номинал облигации до Даты первой модельной купонной выплаты в части кредитов без субсидий как доля от непогашенного
        # номинала, равная доле кредитов без субсидий на начало расчетного периода Даты первой модельной купонной выплаты (округляется до
        # ближайшей копейки):
        index = self.mbsModel['fixed']['pool']['couponDate'] == self.firstModelCouponDate
        fixed_fraction = self.mbsModel['fixed']['pool'][index]['fractionOfTotal'].values[0] / 100.0
        self.mbsModel['fixed']['principal'] = np.round(self.startModelBondPrincipal * fixed_fraction, 2)

        # Непогашенный номинал облигации до Даты первой модельной купонной выплаты в части кредитов с субсидиями:
        self.mbsModel['float']['principal'] = np.round(self.mbsModel['total']['principal'] - self.mbsModel['fixed']['principal'], 2)

        # Учет разницы между объемом выпуска облигаций и объемом ипотечного покрытия на начало первого расчетного периода:
        num = self.numberOfBonds
        is_first_coupon = self.mbsModel['total']['inflow']['couponDate'][0] == self.firstCouponDate
        if is_first_coupon:

            # Разница между объемом выпуска облигаций и объемом ипотечного покрытия на начало первого расчетного периода:
            index = self.mbsModel['total']['pool']['couponDate'] == self.firstCouponDate
            pool_debt = self.mbsModel['total']['pool'][index]['debt'].values[0]
            dif_total = round_floor((self.mbsModel['total']['principal'] * num - pool_debt) / num, 2) * num
            dif_fixed = round_floor(dif_total * fixed_fraction / num, 2) * num
            dif_float = np.round(dif_total - dif_fixed, 2)

            # В том случае, если облигаций разместили на сумму большую, чем сумма остатков основного долга в ипотечном покрытии, то
            # полученные от размещения "излишние" средства пойдут на счет ипотечного агента и будут выплачены в части погашения
            # облигаций в первую купонную выплату:
            if dif_total > 0:

                for part, dif in zip(self.mbsModel.keys(), [dif_total, dif_fixed, dif_float]):
                    self.mbsModel[part]['inflow'].loc[0, 'difference'] = dif
                    self.mbsModel[part]['inflow'].loc[0, 'amortization'] += dif

            # В том случае, если облигаций разместили на сумму меньшую, чем сумма остатков основного долга в ипотечном покрытии на дату
            # передачи, то находящиеся у ипотечного агента "излишние" средства от погашения кредитов будут возвращены банку-оригинатору
            # и не будут направлены на погашение выпуска (речь только об амортизации, процентные поступления все равно будут направлены
            # в первый купон):
            else:

                for part, dif in zip(self.mbsModel.keys(), [dif_total, dif_fixed, dif_float]):

                    amt = self.mbsModel[part]['inflow']['amortization'].values[0]
                    prp = self.mbsModel[part]['inflow']['prepayment'].values[0]
                    dft = self.mbsModel[part]['inflow']['defaults'].values[0]

                    fraction = (amt + dif) / amt if amt > 0 else 0.0

                    if amt + dif < 0.0:
                        raise Exception(EXCEPTIONS._13.format(str(np.round(abs(dif / 1000000), 0)), str(np.round(amt / 1000000, 0))))

                    self.mbsModel[part]['inflow'].loc[0, 'amortization'] += dif
                    self.mbsModel[part]['inflow'].loc[0, 'defaults'] = np.round(dft * fraction, 2)
                    self.mbsModel[part]['inflow'].loc[0, 'prepayment'] = np.round(prp * fraction, 2)
                    self.mbsModel[part]['inflow'].loc[0, 'scheduled'] = np.round(amt - prp - dft, 2)

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- РАСЧЕТ АМОРТИЗАЦИИ ВЫПУСКА ОБЛИГАЦИЙ ------------------------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        # Пустые заготовочные таблицы issue (модельный денежный поток по выпуску ИЦБ ДОМ.РФ) и bond (модельный денежный поток по одной
        # облигации выпуска) для частей total (весь выпуск), fixed (в части кредитов без субсидий), float (в части кредитов с субсидиями):
        for part in self.mbsModel.keys():
            for type in ['bond', 'issue']:
                self.mbsModel[part][type] = self.mbsModel[part]['inflow'][['couponDate', 'couponPeriodDays']].copy(deep=True)
                for flow in ['principalStartPeriod', 'amortization', 'scheduled', 'prepayment', 'defaults', 'difference', 'cleanUp']:
                    self.mbsModel[part][type][flow] = 0.0

        # Непогашенный номинал выпуска облигаций до Даты первой модельной купонной выплаты:
        current_total_principal = self.mbsModel['total']['principal'] * self.numberOfBonds
        # Непогашенный номинал выпуска облигаций до Даты первой модельной купонной выплаты в части кредитов без субсидий:
        current_fixed_principal = self.mbsModel['fixed']['principal'] * self.numberOfBonds
        # Непогашенный номинал выпуска облигаций до Даты первой модельной купонной выплаты в части кредитов с субсидиями:
        current_float_principal = self.mbsModel['float']['principal'] * self.numberOfBonds

        # Входящий остаток в части амортизации выпуска возникает по той причине, что значение, полученное при делении амортизации ипотечного
        # покрытия на количество облигаций, округляют до копеек в меньшую сторону. Предполагается, что на Дату первой модельной купонной
        # выплаты остаток равен нулю. Указывается отдельно для части кредитов без субсидий (fixed) и кредитов с субсидиями (float):
        residual_amt_fixed = 0.0
        residual_amt_float = 0.0

        # Итерационный расчет амортизации выпуска облигаций:
        i = 0
        while True:

            # Текущая дата купонной выплаты:
            coupon_date = self.mbsModel['total']['issue']['couponDate'].values[i]
            coupon_days = self.mbsModel['total']['issue']['couponPeriodDays'].values[i]

            # Номинал выпуска облигаций на начало купонного периода текущей купонной выплаты:
            self.mbsModel['total']['issue'].loc[i, 'principalStartPeriod'] = current_total_principal

            # Номинал выпуска облигаций в части кредитов без субсидий на начало купонного периода текущей купонной выплаты:
            self.mbsModel['fixed']['issue'].loc[i, 'principalStartPeriod'] = current_fixed_principal

            # Номинал выпуска облигаций в части кредитов с субсидиями на начало купонного периода текущей купонной выплаты:
            self.mbsModel['float']['issue'].loc[i, 'principalStartPeriod'] = current_float_principal

            # Поступления за расчетный период в счет погашения основного долга по кредитам с учетом входящего остатка с предыдущего периода
            # (available_fixed — по кредитам без субсидий, available_float — по кредитам с субсидиями):
            available_fixed = self.mbsModel['fixed']['inflow']['amortization'].values[i] + residual_amt_fixed
            available_float = self.mbsModel['float']['inflow']['amortization'].values[i] + residual_amt_float

            # Если поступлений за расчетный период с учетом входящего остатка недостаточно для погашения выпуска облигаций:
            if available_fixed + available_float < current_total_principal:

                # Направляется на погашение выпуска в части кредитов без субсидий:
                issue_amt_fixed = round_floor(available_fixed / num, 2) * num

                # Направляется на погашение выпуска в части кредитов с субсидиями:
                issue_amt_float = round_floor(available_float / num, 2) * num

                # Поступление из соответствующего источника направляются в амортизацию облигаций:
                for flow in ['prepayment', 'defaults', 'difference']:
                    # В части кредитов без субсидий:
                    value_fixed = round_floor(self.mbsModel['fixed']['inflow'][flow].values[i] / num, 2) * num
                    self.mbsModel['fixed']['issue'].loc[i, flow] = value_fixed

                    # В части кредитов с субсидиями:
                    value_float = round_floor(self.mbsModel['float']['inflow'][flow].values[i] / num, 2) * num
                    self.mbsModel['float']['issue'].loc[i, flow] = value_float

                    # По всему выпуску облигаций:
                    self.mbsModel['total']['issue'].loc[i, flow] = value_fixed + value_float

                # Если номинал выпуска облигаций не достиг порога clean-up и дата купонной выплаты не равна Юридической дате
                # погашения выпуска облигаций для расчета, необходимо произвести частичное погашение выпуска облигаций:
                if current_total_principal >= self.cleanUpRubles and coupon_date < self.calculationRedemptionDate:

                    # Частичное погашение выпуска облигаций в части кредитов без субсидий:
                    self.mbsModel['fixed']['issue'].loc[i, 'amortization'] = issue_amt_fixed

                    # Частичное погашение выпуска облигаций в части кредитов с субсидиями:
                    self.mbsModel['float']['issue'].loc[i, 'amortization'] = issue_amt_float

                    # Частичное погашение выпуска облигаций:
                    self.mbsModel['total']['issue'].loc[i, 'amortization'] = issue_amt_fixed + issue_amt_float

                    # Входящий остаток амортизации выпуска облигаций в части кредитов без субсидий на следующую купонную выплату:
                    residual_amt_fixed = available_fixed - issue_amt_fixed

                    # Входящий остаток амортизации выпуска облигаций в части кредитов с субсидиями на следующую купонную выплату:
                    residual_amt_float = available_float - issue_amt_float

                    # Номинал выпуска облигаций на следующий купонный период:
                    current_total_principal -= (issue_amt_fixed + issue_amt_float)

                    # Номинал выпуска облигаций в части кредитов без субсидий на следующий купонный период:
                    current_fixed_principal -= issue_amt_fixed

                    # Номинал выпуска облигаций в части кредитов с субсидиями на следующий купонный период:
                    current_float_principal -= issue_amt_float

                    # Переход к следующей дате купонной выплаты:
                    i += 1

                # Если номинал выпуска облигаций перешел порог clean-up или дата купонной выплаты равна Юридической дате
                # погашения выпуска облигаций для расчета, необходимо произвести полное погашение выпуска облигаций:
                elif current_total_principal < self.cleanUpRubles or coupon_date == self.calculationRedemptionDate:

                    # Погашение выпуска облигаций в части кредитов без субсидий сверх поступлений по ипотечному покрытию:
                    clean_up_fixed = current_fixed_principal - issue_amt_fixed
                    self.mbsModel['fixed']['issue'].loc[i, 'cleanUp'] = clean_up_fixed
                    # Полное погашение выпуска облигации в части кредитов без субсидий:
                    self.mbsModel['fixed']['issue'].loc[i, 'amortization'] = current_fixed_principal

                    # Погашение выпуска облигаций в части кредитов с субсидиями сверх поступлений по ипотечному покрытию:
                    clean_up_float = current_float_principal - issue_amt_float
                    self.mbsModel['float']['issue'].loc[i, 'cleanUp'] = clean_up_float
                    # Полное погашение выпуска облигации в части кредитов без субсидий:
                    self.mbsModel['float']['issue'].loc[i, 'amortization'] = current_float_principal

                    # Погашение выпуска облигаций сверх поступлений по ипотечному покрытию с учетом входящего остатка:
                    self.mbsModel['total']['issue'].loc[i, 'cleanUp'] = clean_up_fixed + clean_up_float
                    # Полное погашение выпуска облигации:
                    self.mbsModel['total']['issue'].loc[i, 'amortization'] = current_total_principal

                    break

            # Если поступлений за расчетный период с учетом входящего остатка достаточно для погашения выпуска облигаций:
            elif available_fixed + available_float >= current_total_principal:

                # Поступление из соответствующего источника согласно его доле в амортизации ипотечного покрытия:
                for flow in ['prepayment', 'defaults', 'difference']:
                    # В части кредитов без субсидий:
                    fraction = self.mbsModel['fixed']['inflow'][flow].values[i] / self.mbsModel['fixed']['inflow']['amortization'].values[i]
                    value_fixed = round_floor(fraction * current_fixed_principal / num, 2) * num
                    self.mbsModel['fixed']['issue'].loc[i, flow] = value_fixed

                    # В части кредитов без субсидий:
                    fraction = self.mbsModel['float']['inflow'][flow].values[i] / self.mbsModel['float']['inflow']['amortization'].values[i]
                    value_float = round_floor(fraction * current_float_principal / num, 2) * num
                    self.mbsModel['float']['issue'].loc[i, flow] = value_float

                    # По всему выпуску облигаций:
                    self.mbsModel['total']['issue'].loc[i, flow] = value_fixed + value_float

                # Полное погашение выпуска облигации в части кредитов без субсидий:
                self.mbsModel['fixed']['issue'].loc[i, 'amortization'] = current_fixed_principal

                # Полное погашение выпуска облигации в части кредитов без субсидий:
                self.mbsModel['float']['issue'].loc[i, 'amortization'] = current_float_principal

                # Полное погашение выпуска облигаций:
                self.mbsModel['total']['issue'].loc[i, 'amortization'] = current_total_principal

                break

        # Для частей total (весь выпуск), fixed (в части кредитов без субсидий), float (в части кредитов с субсидиями) по остаточному
        # принципу рассчитываем поток погашения по графику, а также формируем таблицу bond:
        for part in self.mbsModel.keys():
            self.mbsModel[part]['issue']['scheduled'] = np.round(self.mbsModel[part]['issue']['amortization'].values -
                                                                 self.mbsModel[part]['issue']['prepayment'].values -
                                                                 self.mbsModel[part]['issue']['defaults'].values -
                                                                 self.mbsModel[part]['issue']['difference'].values -
                                                                 self.mbsModel[part]['issue']['cleanUp'].values, 2)

            c = ['principalStartPeriod', 'amortization', 'scheduled', 'prepayment', 'defaults', 'difference', 'cleanUp']
            self.mbsModel[part]['bond'][c] = np.round(self.mbsModel[part]['issue'][c].values / num, 2)

        # Модельная дата погашения выпуска облигаций:
        self.modelRedemptionDate = self.mbsModel['total']['issue']['couponDate'].values[i].astype(d_type)

        # Удаление строк, выходящих за пределы модельного денежного потока:
        outstanding_period = self.mbsModel['total']['issue']['couponDate'] <= self.modelRedemptionDate
        for part in self.mbsModel.keys():
            for table in ['inflow', 'bond', 'issue']:
                self.mbsModel[part][table] = self.mbsModel[part][table][outstanding_period]

        # То же самое в части денежного потока по ипотечному покрытию:
        index_1 = self.mbsModel['total']['pool']['couponDate'] >= self.firstModelCouponDate
        if self.poolType in [POOL_TYPE.FLT, POOL_TYPE.MIX]:
            index_1 = index_1 | (self.mbsModel['total']['pool']['subsidyCouponDate'] >= self.firstModelCouponDate)

        index_2 = self.mbsModel['total']['pool']['couponDate'] <= self.modelRedemptionDate
        outstanding_period = index_1 & index_2
        for part in self.mbsModel.keys():
            self.mbsModel[part]['pool'] = self.mbsModel[part]['pool'][outstanding_period].reset_index(drop=True)

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- РАСЧЕТ ПОМЕСЯЧНЫХ ПОСТУПЛЕНИЙ ОТ НАЧИСЛЕНИЙ ПРОЦЕНТНОЙ СТАВКИ НА ОСТАТОК НА СЧЕТЕ ИПОТЕЧНОГО АГЕНТА  --------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        # Количество дней до купонной выплаты, когда происходит списание денежных средств со счета Ипотечного агента:
        self.writeOffDays = 7 * day

        self.reinvModel = {'fixed': None, 'float': None}
        if self.reinvestment:

            for part in ['fixed', 'float']:

                if self.mbsModel[part]['reinvestment'].empty:
                    continue

                self.reinvModel[part] = pd.DataFrame([])

                # Оставляем платежи с начала расчетного периода Предыдущей от даты оценки даты купонной выплаты. Например, если
                # Предыдущая от даты оценки дата равна 28.03.2024, то, в случае квартального купона, такой датой станет 01.12.2024:
                start_date = None
                if self.previousCouponDate is not None:
                    index = self.couponsStructure['couponDate'] == self.previousCouponDate
                    start_date = self.couponsStructure[index]['paymentPeriodStart'].values[0].astype(d_type)
                    index = self.mbsModel[part]['reinvestment']['date'] >= start_date
                    self.mbsModel[part]['reinvestment'] = self.mbsModel[part]['reinvestment'][index]
                else:
                    start_date = self.deliveryDate

                # Поток поступлений на баланс Ипотечного агента амортизации, процентов и субсидий по ипотечному покрытию:
                c = ['date', 'amt', 'yld', 'subsidy']
                self.mbsModel[part]['reinvestment'] = self.mbsModel[part]['reinvestment'][c]
                self.mbsModel[part]['reinvestment'] = self.mbsModel[part]['reinvestment'].groupby('date', as_index=False).sum()
                zero_cashflow = self.mbsModel[part]['reinvestment'][['amt', 'yld', 'subsidy']].sum(axis=1) == 0.0
                self.mbsModel[part]['reinvestment'] = self.mbsModel[part]['reinvestment'][~zero_cashflow]
                self.mbsModel[part]['reinvestment'].sort_values('date', inplace=True)
                self.mbsModel[part]['reinvestment'].reset_index(inplace=True, drop=True)

                # Формируем даты с начала расчетного периода Предыдущей от даты оценки даты купонной выплаты включительно
                # до даты погашения не включительно. На эти даты будем формировать баланс Ипотечного агента:
                end_date = self.modelRedemptionDate - self.writeOffDays
                self.reinvModel[part]['date'] = np.arange(start_date, end_date + day)

                # Поток поступлений на баланс Ипотечного агента по амортизации, процентам и субсидиям на каждый день:
                self.reinvModel[part] = self.reinvModel[part].merge(self.mbsModel[part]['reinvestment'], how='left', on='date').fillna(0.0)

                # Формируем поток совокупных поступлений на каждый день:
                self.reinvModel[part]['flow'] = self.reinvModel[part][['amt', 'yld', 'subsidy']].sum(axis=1)

                # Далее необходимо определить, расчетному периоду какой купонной выплаты принадлежит платеж flow.
                # Для этого определяем месяц платежа и соответствующую ему дату купонной выплаты:
                self.reinvModel[part]['paymentMonth'] = self.reinvModel[part]['date'].values.astype(m_type).astype(d_type)
                c = ['paymentMonth', 'couponDate']
                self.reinvModel[part] = self.reinvModel[part].merge(self.paymentsStructure[c], how='left', on='paymentMonth')

                # Деньги будут списываться не в саму дату купонной выплаты, а в день выплаты свопа, поэтому вычитаем из couponDate
                # необходимое количество дней и переименовываем couponDate в writeOffDate:
                self.reinvModel[part]['couponDate'] = self.reinvModel[part]['couponDate'].values - self.writeOffDays
                self.reinvModel[part].rename(columns={'couponDate': 'writeOffDate'}, inplace=True)
                # Это значит, что указанная сумма flow будет списана с баланса в указанную writeOffDate.

                # Группируем в отдельной таблице суммы списаний:
                writeOffs = self.reinvModel[part][['writeOffDate', 'flow']].groupby('writeOffDate', as_index=False).sum(numeric_only=True)
                writeOffs.rename(columns={'writeOffDate': 'date', 'flow': 'writeOff'}, inplace=True)

                # Мерджим к reinvModel суммы списаний:
                self.reinvModel[part] = self.reinvModel[part].merge(writeOffs, how='left', on='date').fillna(0.0)

                # Баланс Ипотечного агента на каждую дату:
                self.reinvModel[part]['account'] = (self.reinvModel[part]['flow'] - self.reinvModel[part]['writeOff']).cumsum()

                # Мерджим из модели макроэкономики значения Ключевой ставки, по которым будут рассчитаны значения RUONIA:
                self.reinvModel[part] = pd.merge_asof(self.reinvModel[part], self.macroModel['allKeyRates'],
                                                      direction='backward', on='date').rename(columns={'key_rate': 'keyRate'})

                # Рассчитываем значения ставки RUONIA (КС - 0.2%) и из нее сразу значение ставки реинвестирования:
                self.reinvModel[part]['reinvestingRate'] = np.maximum(self.reinvModel[part]['keyRate'] - 0.2 - self.deductionRUONIA, 0.0)

                # Начислено за каждый день (без капитализации процентов):
                principal = self.reinvModel[part]['account'].values
                rate = self.reinvModel[part]['reinvestingRate'].values
                self.reinvModel[part]['reinvestment'] = np.round(principal * rate / 100.0 / 365.0, 2)

                # Сумма начисленных процентов за каждый paymentMonth:
                c = ['paymentMonth', 'reinvestment']
                self.reinvModel[part] = self.reinvModel[part][c].groupby('paymentMonth', as_index=False).sum(numeric_only=True)

                # Далее необходимо определить, расчетному периоду какой купонной выплаты принадлежит платеж reinvestment.
                # Для этого определяем месяц платежа и соответствующую ему дату купонной выплаты:
                c = ['paymentMonth', 'couponDate']
                self.reinvModel[part] = self.reinvModel[part].merge(self.paymentsStructure[c], how='left', on='paymentMonth')

                # Сумма начисленных процентов в соответствии с датой купонной выплаты:
                c = ['couponDate', 'reinvestment']
                self.reinvModel[part] = self.reinvModel[part][c].groupby('couponDate', as_index=False).sum(numeric_only=True)

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- РАСЧЕТ РАСХОДОВ ИПОТЕЧНОГО АГЕНТА И ПЛАВАЮЩИХ СУММ ----------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        # Рассчитываем fraction — долю соответствующей части (fixed, float) в объеме непогашенного номинала выпуска ИЦБ ДОМ.РФ:
        total_principals = self.mbsModel['total']['issue']['principalStartPeriod'].values
        fixed_principals = self.mbsModel['fixed']['issue']['principalStartPeriod'].values

        self.mbsModel['fixed']['issue']['fractionOfTotal'] = np.round(fixed_principals / total_principals * 100.0, 25)
        self.mbsModel['float']['issue']['fractionOfTotal'] = np.round(100.0 - self.mbsModel['fixed']['issue']['fractionOfTotal'].values, 25)

        self.mbsModel['fixed']['bond']['fractionOfTotal'] = self.mbsModel['fixed']['issue']['fractionOfTotal'].values
        self.mbsModel['float']['bond']['fractionOfTotal'] = self.mbsModel['float']['issue']['fractionOfTotal'].values

        self.mbsModel['total']['issue']['fractionOfTotal'] = 100.0
        self.mbsModel['total']['bond']['fractionOfTotal'] = 100.0

        for part in ['fixed', 'float']:

            d1 = self.mbsModel[part]['inflow']['paymentPeriodDays'].astype(float).values / 365.0
            d2 = self.mbsModel[part]['inflow']['couponPeriodDays'].astype(float).values / 365.0
            d3 = self.mbsModel[part]['inflow']['couponPeriodDays'].shift(-1).fillna(0.0).astype(float).values / 365.0
            p = self.mbsModel[part]['issue']['principalStartPeriod'].astype(float).values
            f = self.mbsModel[part]['issue']['fractionOfTotal'].astype(float).values / 100.0
            c = float(self.couponPeriod)

            # Основные статьи расходов:
            self.mbsModel[part]['inflow']['expense'] = np.round(p * self.mortgageAgentExpense1 / 100.0 * d3, 2)
            if self.mbsModel[part]['inflow']['couponDate'].values[0] == self.firstCouponDate:
                self.mbsModel[part]['inflow'].loc[0, 'expense'] += np.round(p[0] * self.mortgageAgentExpense1 / 100.0 * d2[0], 2)
            self.mbsModel[part]['inflow']['expensePart1'] = np.round(self.mbsModel[part]['inflow']['expense'].values, 2)
            self.mbsModel[part]['inflow']['expense'] += np.round(p * self.mortgageAgentExpense2 / 100.0 * d1, 2)

            # Вознаграждение спец. депозитария:
            minimum = self.specDepMinMonthIssueDoc * 12.0 * d1 * f
            self.mbsModel[part]['inflow']['expense'] += np.round(np.maximum(p * self.specDepRateIssueDoc / 100.0 * d1, minimum), 2)
            self.mbsModel[part]['inflow']['expense'] += np.round(self.specDepCompensationMonthIssueDoc * 12.0 * d1 * f)

            # Управляющая и бухгалтерская организации:
            self.mbsModel[part]['inflow']['expense'] += 2 * np.round(p * self.manAccQuartRateIssueDoc / 100.0 * 4.0 * d1, 2)
            self.mbsModel[part]['inflow']['expense'] += 2 * np.round(self.manAccQuartFixIssueDoc * 4.0 * d1 * f, 2)

            # Расчетный агент:
            self.mbsModel[part]['inflow']['expense'] += np.round(self.paymentAgentYearIssueDoc * d1 * f, 2)

            # Технические расчеты:
            self.mbsModel[part]['inflow']['expense'] = np.round(self.mbsModel[part]['inflow']['expense'].values, 2)
            self.mbsModel[part]['inflow']['expensePart2'] = np.round(self.mbsModel[part]['inflow']['expense'].values -
                                                                     self.mbsModel[part]['inflow']['expensePart1'].values, 2)

            # Начисленные, но не выплаченные проценты (НВП):
            self.mbsModel[part]['inflow']['accruedYield'] = 0.0
            if self.mbsModel[part]['inflow']['couponDate'].values[0] == self.firstCouponDate:
                accrued_yield = 0.0
                if self.poolReportDate == self.deliveryDate:
                    accrued_yield = self.poolModel[part]['accruedYield']
                else:
                    accrued_yield = recovered_pools[str(self.deliveryDate)]['poolModel'][part]['accruedYield']
                self.mbsModel[part]['inflow'].loc[0, 'accruedYield'] = accrued_yield
                self.mbsModel[part]['inflow']['accruedYield'] = np.round(self.mbsModel[part]['inflow']['accruedYield'].values, 2)

            # Добавляем суммы начислений на остаток на счете, если начисление есть:
            if self.reinvestment and self.reinvModel[part] is not None:
                self.mbsModel[part]['inflow'] = self.mbsModel[part]['inflow'].merge(self.reinvModel[part], how='left', on='couponDate')
                self.mbsModel[part]['inflow']['reinvestment'] = np.round(self.mbsModel[part]['inflow']['reinvestment'].values, 2)
            else:
                self.mbsModel[part]['inflow']['reinvestment'] = 0.0

            # Плавающие суммы:
            self.mbsModel[part]['inflow']['floatSum'] = np.round(self.mbsModel[part]['inflow']['yield'].values +
                                                                 self.mbsModel[part]['inflow']['subsidy'].values +
                                                                 self.mbsModel[part]['inflow']['reinvestment'].values -
                                                                 self.mbsModel[part]['inflow']['expense'].values -
                                                                 self.mbsModel[part]['inflow']['accruedYield'].values, 2)

        # Начисленные, но не выплаченные проценты, расходы и плавающие суммы всего ипотечного покрытия:
        for c in ['reinvestment', 'expense', 'expensePart1', 'expensePart2', 'accruedYield', 'floatSum']:
            self.mbsModel['total']['inflow'][c] = np.round(self.mbsModel['fixed']['inflow'][c].values +
                                                           self.mbsModel['float']['inflow'][c].values, 2)

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- РАСЧЕТ МОДЕЛЬНЫХ КУПОННЫХ ВЫПЛАТ В ЗАВИСИМОСТИ ОТ ТИПА КУПОНА ВЫПУСКА ОБЛИГАЦИЙ ------------------------------------------ #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        # ----- ФИКСИРОВАННЫЙ ТИП КУПОНА ------------------------------------------------------------------------------------------------- #
        if self.couponType == COUPON_TYPE.FXD:

            # Технические переменные для последующего расчета:
            coupon_rate = self.fixedCouponRate
            bond_principals = self.mbsModel['total']['bond']['principalStartPeriod'].astype(float).values
            coupon_days = self.mbsModel['total']['bond']['couponPeriodDays'].astype(float).values

            # Модельные купонные выплаты по одной облигации и по всему выпуску облигаций:
            self.mbsModel['total']['bond']['couponPayment'] = np.round(bond_principals * coupon_rate / 100.0 * coupon_days / 365.0, 2)
            self.mbsModel['total']['issue']['couponPayment'] = np.round(self.mbsModel['total']['bond']['couponPayment'].values * num, 2)


        # ----- ПЕРЕМЕННЫЙ ТИП КУПОНА ---------------------------------------------------------------------------------------------------- #
        elif self.couponType == COUPON_TYPE.CHG:

            # Входящий остаток в части плавающих сумм возникает по той причине, что значение, полученное при делении плавающей суммы
            # на количество облигаций, округляют до копеек в меньшую сторону. Предполагается, что на ближайшую модельную дату купонной
            # выплаты остаток равен нулю. Указывается отдельно для части кредитов без субсидий (fixed) и кредитов с субсидиями (float):
            residual_flt_sum_fixed = 0.0
            residual_flt_sum_float = 0.0

            for part in self.mbsModel.keys():
                for table in ['bond', 'issue']:
                    self.mbsModel[part][table]['couponPayment'] = 0.0

            coupons_number = len(self.mbsModel['total']['issue'])
            for i in range(coupons_number):
                # Текущая дата купонной выплаты:
                coupon_date = self.mbsModel['total']['issue']['couponDate'].values[i]
                coupon_days = self.mbsModel['total']['issue']['couponPeriodDays'].values[i]

                # Доступные на выплату купона средства: плавающая сумма + входящий остаток:
                available_fixed = self.mbsModel['fixed']['inflow']['floatSum'].values[i] + residual_flt_sum_fixed
                available_float = self.mbsModel['float']['inflow']['floatSum'].values[i] + residual_flt_sum_float

                # Направляется на выплату переменного купона в части кредитов без субсидий:
                bond_coupon_fixed = round_floor(available_fixed / num, 2)
                self.mbsModel['fixed']['bond'].loc[i, 'couponPayment'] = bond_coupon_fixed
                self.mbsModel['fixed']['issue']['couponPayment'].values[i] = bond_coupon_fixed * num

                # Направляется на выплату переменного купона в части кредитов c субсидиями:
                bond_coupon_float = round_floor(available_float / num, 2)
                self.mbsModel['float']['bond'].loc[i, 'couponPayment'] = bond_coupon_float
                self.mbsModel['float']['issue']['couponPayment'].values[i] = bond_coupon_float * num

                # Направляется на выплату переменного купона по всему выпуску:
                self.mbsModel['total']['bond'].loc[i, 'couponPayment'] = bond_coupon_fixed + bond_coupon_float
                self.mbsModel['total']['issue']['couponPayment'].values[i] = (bond_coupon_fixed + bond_coupon_float) * num

                # Входящий остаток плавающих сумм в части кредитов без субсидий на следующую купонную выплату:
                residual_flt_sum_fixed = available_fixed - bond_coupon_fixed * num

                # Входящий остаток плавающих сумм в части кредитов с субсидиями на следующую купонную выплату:
                residual_flt_sum_float = available_float - bond_coupon_float * num


        # ----- ПЛАВАЮЩИЙ ТИП КУПОНА ----------------------------------------------------------------------------------------------------- #
        elif self.couponType == COUPON_TYPE.FLT:

            # Для каждой даты купонной выплаты определяем дату, по состоянию на которую нужно взять значение Ключевой ставки для расчета
            # купонной выплаты (определяется как первый день месяца, на который приходится начало купонного периода выплаты):
            coupon_dates = self.mbsModel['total']['bond']['couponDate'].values
            self.mbsModel['total']['bond']['couponKeyRateDate'] = (coupon_dates - day * coupon_days).astype(m_type).astype(d_type)

            # Мерджим из модели макроэкономики значения Ключевой ставки, по которым будут рассчитаны купонные выплаты:
            self.mbsModel['total']['bond'] = pd.merge_asof(self.mbsModel['total']['bond'], self.macroModel['allKeyRates'],
                                                           direction='backward', left_on='couponKeyRateDate', right_on='date')
            self.mbsModel['total']['bond'].rename(columns={
                'date': 'keyRateStartDate',  # дата, с которой действует указанная Ключевая ставка
                'key_rate': 'couponKeyRate',  # значение Ключевой ставки для расчета купонной выплаты
            }, inplace=True)

            # Дублируем значения для таблицы всего выпуска:
            c = ['couponKeyRateDate', 'keyRateStartDate', 'couponKeyRate']
            self.mbsModel['total']['issue'][c] = self.mbsModel['total']['bond'][c].values

            # Технические переменные для последующего расчета:
            fixed_premium = self.fixedKeyRatePremium
            key_rates = self.mbsModel['total']['bond']['couponKeyRate'].astype(float).values
            bond_principals = self.mbsModel['total']['bond']['principalStartPeriod'].astype(float).values
            coupon_days = self.mbsModel['total']['bond']['couponPeriodDays'].astype(float).values

            # Модельные купонные выплаты по одной облигации и по всему выпуску облигаций
            # (Ключевая ставка на первый день месяца начала купонного периода + фиксированная надбавка):
            coupon_payments = np.round(bond_principals * (key_rates + fixed_premium) / 100.0 * coupon_days / 365.0, 2)
            self.mbsModel['total']['bond']['couponPayment'] = coupon_payments
            self.mbsModel['total']['issue']['couponPayment'] = np.round(coupon_payments * num, 2)

        ####################################################################################################################################

        # [ОБНОВЛЕНИЕ СТАТУСА РАСЧЕТА]
        self.currentPercent = 96.0
        update(self.connectionId, self.currentPercent, self.progressBar)

        ####################################################################################################################################

    def mbsPricing(self):

        """ Функция расчета ценовых метрик ИЦБ ДОМ.РФ """

        # Формируется таблица денежного потока по ИЦБ ДОМ.РФ (mbsCashflow). Денежный поток выстраивается по датам купонных платежей,
        # начиная с даты первого купона. Каждой строке денежного потока присваивается категория cashflowType:
        #       — код "0" означает модельный денежный поток по облигации ИЦБ ДОМ.РФ (по построению поступит строго после даты оценки)
        #       — код "1" означает известный фактический поток, который поступит строго после даты оценки
        #       — код "2" означает известный фактический поток, который поступил в дату оценки или раньше

        self.mbsCashflow['cashflowType'] = None

        if not self.investorsReportsData.empty:

            # Фактические выплаты по облигации до firstModelCouponDate (даты купонной выплаты, в расчетном периоде которой
            # начинается моделирование денежного потока по ипотечному покрытию):
            actual_data = self.investorsReportsData.copy()
            if self.firstModelCouponDate is not None and self.bondID not in fixed_amt_bonds:
                actual_period = self.investorsReportsData['couponDate'] < self.firstModelCouponDate
                actual_data = actual_data[actual_period].copy()

            self.mbsCashflow['couponDate'] = actual_data['couponDate'].values
            self.mbsCashflow['principalStartPeriod'] = actual_data['bondNextPrincipal'].values
            self.mbsCashflow['principalStartPeriod'] += actual_data['bondAmortization'].values
            self.mbsCashflow['amortization'] = actual_data['bondAmortization'].values
            self.mbsCashflow['couponPayment'] = actual_data['bondCouponPayment'].values

            history = self.mbsCashflow['couponDate'] <= self.pricingDate
            self.mbsCashflow.loc[history, 'cashflowType'] = 2
            self.mbsCashflow.loc[~history, 'cashflowType'] = 1

        if self.runCashflowModel and self.bondID not in fixed_amt_bonds:
            # Соединяем фактический денежный поток по облигации с модельным:
            c = ['couponDate', 'principalStartPeriod', 'amortization', 'couponPayment']
            self.mbsCashflow = pd.concat([self.mbsCashflow, self.mbsModel['total']['bond'][c]])
            self.mbsCashflow.loc[:, 'cashflowType'] = self.mbsCashflow['cashflowType'].infer_objects(copy=False).fillna(0).values

        self.mbsCashflow.reset_index(drop=True, inplace=True)

        # Указываем количество дней в каждом купонном периоде:
        coupon_days = self.mbsCashflow.merge(self.couponsStructure, how='left', on='couponDate')['couponPeriodDays'].astype(float).values
        self.mbsCashflow['couponDays'] = coupon_days

        # ----- ТЕХНИЧЕСКИЕ ПЕРЕМЕННЫЕ --------------------------------------------------------------------------------------------------- #

        # [КОЛИЧЕСТВО ЛЕТ МЕЖДУ ДАТОЙ ОЦЕНКИ И БУДУЩЕЙ ВЫПЛАТОЙ КУПОНА]
        self.yearsToCouponDate = (self.mbsCashflow['couponDate'].values - self.pricingDate) / np.timedelta64(1, 'D') / 365.0

        # [СОКРАЩЕНИЯ]
        future = self.mbsCashflow['couponDate'] > self.pricingDate
        future_model = future & (self.mbsCashflow['cashflowType'] == 0)
        t_future = self.yearsToCouponDate[future]
        t_future_model = self.yearsToCouponDate[future_model]
        bond_coupons = self.mbsCashflow['couponPayment'].astype(float).values
        bond_principals = self.mbsCashflow['principalStartPeriod'].astype(float).values
        cf = np.round(self.mbsCashflow['amortization'][future].values + self.mbsCashflow['couponPayment'][future].values, 2)

        # [ФАКТОР ДИСКОНТИРОВАНИЯ ПО КБД С Z-СПРЕДОМ]
        self.dfZCYCPlusZ = lambda Z, t: (1.0 + Y(self.zcycParameters, t) / 10000.0 + Z / 10000.0) ** -t
        self.defaultZSpread = 120.0

        # [ФАКТОР ДИСКОНТИРОВАНИЯ ПО YTM]
        self.dfYTM = lambda YTM: (1.0 + YTM / 100.0) ** -t_future

        # [ФУНКЦИЯ РАСЧЕТА ДЮРАЦИИ МАКОЛЕЯ]
        self.durationMacaulay_func = lambda YTM: max(0.001, (t_future * cf * self.dfYTM(YTM)).sum() / (cf * self.dfYTM(YTM)).sum())

        # ----- КУПОННЫЕ ВЫПЛАТЫ В ПРОЦЕНТАХ ГОДОВЫХ ОТ НЕПОГАШЕННОГО НОМИНАЛА ----------------------------------------------------------- #
        self.mbsCashflow['couponPaymentPercent'] = np.round(bond_coupons / bond_principals * 365.0 / coupon_days * 100.0, 2)

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ПОДГОТОВКА ДЕНЕЖНОГО ПОТОКА ПО ОБЛИГАЦИИ К ОЦЕНКЕ ------------------------------------------------------------------------ #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        # В случае плавающего купона или переменного купона с субсид. или смеш. ипотечным покрытием добавляем значения Ключевой ставки:
        if self.couponType == COUPON_TYPE.FLT or (self.couponType == COUPON_TYPE.CHG and not self.poolType == POOL_TYPE.FXD):
            # Для каждой даты купонной выплаты определяем дату, по состоянию на которую нужно взять значение Ключевой ставки для расчета
            # купонной выплаты (определяется как первый день месяца, на который приходится начало купонного периода выплаты):
            coupon_dates = self.mbsCashflow['couponDate'].values
            self.mbsCashflow['couponKeyRateDate'] = (coupon_dates - day * coupon_days).astype(m_type).astype(d_type)

            # Мерджим из модели макроэкономики значения Ключевой ставки, по которым будут рассчитаны купонные выплаты:
            self.mbsCashflow = pd.merge_asof(self.mbsCashflow, self.macroModel['allKeyRates'],
                                             direction='backward', left_on='couponKeyRateDate', right_on='date')
            self.mbsCashflow.rename(columns={
                'date': 'keyRateStartDate',  # дата, с которой действует указанная Ключевая ставка
                'key_rate': 'couponKeyRate',  # значение Ключевой ставки для расчета купонной выплаты
            }, inplace=True)

        # В случае плавающего купона добавляем в таблицу денежного потока значения начисленных фактической и требуемой надбавок:
        if self.couponType == COUPON_TYPE.FLT:

            # Выплаты по фактической надбавке:
            fixed_premium = self.fixedKeyRatePremium / 100.0
            self.mbsCashflow['fixedPremiumPayments'] = np.round(bond_principals * fixed_premium * coupon_days / 365.0, 2)

            # Выплаты по требуемой надбавке (если задана):
            if self.calculationType == CALCULATION_TYPE.SET_PREMI:
                required_premium = self.requiredKeyRatePremium / 10000.0
                self.mbsCashflow['requiredPremiumPayments'] = np.round(bond_principals * required_premium * coupon_days / 365.0, 2)

        # В случае переменного купона и присутствия в ипотечном покрытии кредитов с субсидиями разделяем ИЦБ на две части для оценки.
        # ИЦБ в части кредитов без субсидий будет оценена по текущей КБД с указанным Z-спредом, а ИЦБ в части кредитов с субсидиями
        # будет оценена путем соотнесения указанной требуемой надбавки с оцененным значением спреда, который генерируют над Ключевой
        # ставкой кредиты с субсидиями:
        elif self.couponType == COUPON_TYPE.CHG and not self.poolType == POOL_TYPE.FXD:

            # ИЦБ в части кредитов без субсидий:
            self.mbsCashflowFixed = self.mbsCashflow.copy(deep=True)
            c = ['principalStartPeriod', 'amortization', 'couponPayment']
            self.mbsCashflowFixed.loc[future_model, c] = self.mbsModel['fixed']['bond'][c].values

            # ИЦБ в части кредитов с субсидиями:
            self.mbsCashflowFloat = self.mbsCashflow.copy(deep=True)
            c = ['principalStartPeriod', 'amortization', 'couponPayment']
            self.mbsCashflowFloat.loc[future_model, c] = self.mbsModel['float']['bond'][c].values

            # В случае переменного купона с ипотечным покрытием, состоящим из субсидируемых кредитов, необходимо рассчитать спред к
            # Ключевой ставке, который генерирует ипотечное покрытие в купонах, следующих за датой оценки. В случае переменного купона со
            # смешанным типом ипотечного покрытия, необходимо рассчитать спред к Ключевой ставке, который генерирует ипотечное покрытие
            # в модельных купонах (фактические известные купоны будут продисконтированы по Z-спреду):
            if self.poolType == POOL_TYPE.FLT:
                # Для расчета Модельной фиксированной надбавки к Ключевой ставке при субсидируемом ипотечном покрытии:
                period = future
                df = self.dfZCYCPlusZ(self.defaultZSpread, t_future)
            elif self.poolType == POOL_TYPE.MIX:
                # Для расчета Модельной фиксированной надбавки к Ключевой ставке при смешанном ипотечном покрытии:
                period = future_model
                df = self.dfZCYCPlusZ(self.defaultZSpread, t_future_model)

            # Технические переменные:
            p = self.mbsCashflowFloat['principalStartPeriod'].astype(float).values[period]
            c = self.mbsCashflowFloat['couponDays'].astype(float).values[period]
            k = self.mbsCashflowFloat['couponKeyRate'].values[period] / 100.0

            # PV будущих купонных выплат, если бы они рассчитывались по Ключевой ставке с какой-либо надбавкой:
            premium_npv = lambda premium: (df * np.round(p * (k + premium / 10000.0) * c / 365.0, 2)).sum()

            # PV будущих купонных выплат (известных и модельных, относительно даты оценки):
            actual_coupons = self.mbsCashflowFloat['couponPayment'].values[period]
            actual_npv = (df * actual_coupons).sum()

            # Модельная фактическая надбавка к Ключевой ставке:
            premium_value = minimize(lambda prm: (premium_npv(prm) - actual_npv) ** 2.0, np.array([100.0]), method='Nelder-Mead').x[0]
            self.modelKeyRatePremium = premium_value

            # Выплаты по фактической надбавке:
            self.mbsCashflowFloat.loc[period, 'fixedPremiumPayments'] = np.round(p * self.modelKeyRatePremium / 10000.0 * c / 365.0, 2)

            # Выплаты по требуемой надбавке:
            if self.calculationType in [CALCULATION_TYPE.SET_PREMI, CALCULATION_TYPE.SET_Z_PRM]:
                required_premium = self.requiredKeyRatePremium / 10000.0
                self.mbsCashflowFloat.loc[period, 'requiredPremiumPayments'] = np.round(p * required_premium * c / 365.0, 2)

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- РАСЧЕТ ЦЕНОВЫХ МЕТРИК ---------------------------------------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        # ----- НАКОПЛЕННЫЙ КУПОННЫЙ ДОХОД (НКД) ----------------------------------------------------------------------------------------- #
        next_coupon_in_percents = self.mbsCashflow['couponPaymentPercent'][future].values[0]
        self.accruedCouponInterest = next_coupon_in_percents * self.daysPassedInCurrentCouponPeriod / 365.0

        # ----- ГРЯЗНАЯ ЦЕНА ------------------------------------------------------------------------------------------------------------- #
        if self.calculationType == CALCULATION_TYPE.SET_ZSPRD:
            self.dirtyPrice = (self.dfZCYCPlusZ(self.zSpread, t_future) * cf).sum() / self.currentBondPrincipal * 100.0

        elif self.calculationType == CALCULATION_TYPE.SET_GSPRD:
            self.ytm = minimize(lambda YTM:
                                (self.gSpread - YTM * 100.0 + Y(self.zcycParameters, self.durationMacaulay_func(YTM))) ** 2.0,
                                np.array([0.0])).x[0]
            self.dirtyPrice = (self.dfYTM(self.ytm) * cf).sum() / self.currentBondPrincipal * 100.0

        elif self.calculationType == CALCULATION_TYPE.SET_DIRTY:
            pass

        elif self.calculationType == CALCULATION_TYPE.SET_CLEAN:
            self.dirtyPrice = self.cleanPrice + self.accruedCouponInterest

        elif self.calculationType == CALCULATION_TYPE.SET_PREMI:
            flows = self.mbsCashflowFloat if self.couponType == COUPON_TYPE.CHG else self.mbsCashflow
            prem_act = flows['fixedPremiumPayments'].values[future]
            prem_req = flows['requiredPremiumPayments'].values[future]
            df = self.dfZCYCPlusZ(self.requiredKeyRatePremium, t_future)
            self.dirtyPrice = 100.0 + ((prem_act - prem_req) * df).sum() / self.currentBondPrincipal * 100.0 + self.accruedCouponInterest

        elif self.calculationType == CALCULATION_TYPE.SET_COUPN or self.calculationType == CALCULATION_TYPE.SET_FXPRM:
            self.dirtyPrice = 100.0

        elif self.calculationType == CALCULATION_TYPE.SET_Z_PRM:

            cf_fixed = self.mbsCashflowFixed['amortization'][future].values + self.mbsCashflowFixed['couponPayment'][future].values
            npv_fixed = (self.dfZCYCPlusZ(self.zSpread, t_future) * cf_fixed).sum()

            prem_act = self.mbsCashflowFloat['fixedPremiumPayments'].values[future_model]
            prem_req = self.mbsCashflowFloat['requiredPremiumPayments'].values[future_model]
            nominal = self.mbsCashflowFloat['principalStartPeriod'].values[future_model][0]
            npv_float = nominal + ((prem_act - prem_req) * self.dfZCYCPlusZ(self.requiredKeyRatePremium, t_future_model)).sum()

            # В том случае, если значение следующей после Даты оценки купонной выплаты известно, НКД будет по всему выпуску (полностью)
            # включен в приведенную стоимость ИЦБ в части кредитов без субсидий (потому что по построению вся выплата дисконтируется по
            # КБД с Z-спредом). В том случае, если значение следующей после Даты оценки купонной выплаты модельное, то НКД необходимо
            # разделить. НКД по ИЦБ в части кредитов без субсидий будет учтена в приведенной стоимости ИЦБ в части кредитов без субсидий,
            # а НКД по ИЦБ в части кредитов с субсидиями необходимо явно рассчитать и добавить в приведенную стоимость:

            if future.sum() == future_model.sum():
                next_coupon = self.mbsCashflowFloat['couponPayment'][future].values[0]
                accruedCouponInterestFloat = next_coupon * self.daysPassedInCurrentCouponPeriod / 365.0
                npv_float += accruedCouponInterestFloat

            self.dirtyPrice = (npv_fixed + npv_float) / self.currentBondPrincipal * 100.0

        # ----- ЧИСТАЯ ЦЕНА -------------------------------------------------------------------------------------------------------------- #
        if self.calculationType != CALCULATION_TYPE.SET_CLEAN:
            self.cleanPrice = self.dirtyPrice - self.accruedCouponInterest

        # ----- НАКОПЛЕННЫЙ КУПОННЫЙ ДОХОД (НКД) В РУБЛЯХ -------------------------------------------------------------------------------- #
        self.accruedCouponInterestRub = np.round(self.accruedCouponInterest / 100.0 * self.currentBondPrincipal, 2)

        # ----- ГРЯЗНАЯ ЦЕНА В РУБЛЯХ ---------------------------------------------------------------------------------------------------- #
        self.dirtyPriceRub = np.round(self.dirtyPrice / 100.0 * self.currentBondPrincipal, 2)

        # ----- ЧИСТАЯ ЦЕНА В РУБЛЯХ ----------------------------------------------------------------------------------------------------- #
        self.cleanPriceRub = np.round(self.dirtyPriceRub - self.accruedCouponInterestRub, 2)

        # ----- ДОХОДНОСТЬ К ПОГАШЕНИЮ --------------------------------------------------------------------------------------------------- #
        if self.couponType == COUPON_TYPE.FXD or (self.couponType == COUPON_TYPE.CHG and self.poolType == COUPON_TYPE.FXD):

            types = [CALCULATION_TYPE.SET_ZSPRD, CALCULATION_TYPE.SET_DIRTY, CALCULATION_TYPE.SET_CLEAN, CALCULATION_TYPE.SET_COUPN]
            if self.calculationType in types:
                self.ytm = minimize(lambda YTM: ((cf * self.dfYTM(YTM)).sum() / self.currentBondPrincipal * 10000.0 -
                                                 self.dirtyPrice * 100.0) ** 2.0, np.array([0.0])).x[0]

            elif self.calculationType == CALCULATION_TYPE.SET_GSPRD:
                pass  # YTM УЖЕ ОПРЕДЕЛЕНА НА ЭТАПЕ ОПРЕДЕЛЕНИЯ ГРЯЗНОЙ ЦЕНЫ

        else:
            pass

        # ----- Z-СПРЕД ------------------------------------------------------------------------------------------------------------------ #
        if self.couponType == COUPON_TYPE.FXD or (self.couponType == COUPON_TYPE.CHG and self.poolType == COUPON_TYPE.FXD):

            types = [CALCULATION_TYPE.SET_GSPRD, CALCULATION_TYPE.SET_DIRTY, CALCULATION_TYPE.SET_CLEAN, CALCULATION_TYPE.SET_COUPN]
            if self.calculationType == CALCULATION_TYPE.SET_ZSPRD:
                pass

            elif self.calculationType in types:
                self.zSpread = minimize(lambda Z: ((cf * self.dfZCYCPlusZ(Z, t_future)).sum() / self.currentBondPrincipal * 10000.0 -
                                                   self.dirtyPrice * 100.0) ** 2.0, np.array([0.0])).x[0]

        else:
            pass

        # ----- G-СПРЕД ------------------------------------------------------------------------------------------------------------------ #
        if self.couponType == COUPON_TYPE.FXD or (self.couponType == COUPON_TYPE.CHG and self.poolType == COUPON_TYPE.FXD):

            types = [CALCULATION_TYPE.SET_ZSPRD, CALCULATION_TYPE.SET_DIRTY, CALCULATION_TYPE.SET_CLEAN, CALCULATION_TYPE.SET_COUPN]
            if self.calculationType in types:
                self.gSpread = self.ytm * 100.0 - Y(self.zcycParameters, self.durationMacaulay_func(self.ytm))

            elif self.calculationType == CALCULATION_TYPE.SET_GSPRD:
                pass

        else:
            pass

        # ----- ТРЕБУЕМАЯ ФИКСИРОВАННАЯ НАДБАВКА К КЛЮЧЕВОЙ СТАВКЕ ----------------------------------------------------------------------- #
        if self.couponType == COUPON_TYPE.FLT or (self.couponType == COUPON_TYPE.CHG and self.poolType == POOL_TYPE.FLT):

            if self.calculationType in [CALCULATION_TYPE.SET_DIRTY, CALCULATION_TYPE.SET_CLEAN]:
                flows = self.mbsCashflowFloat if self.couponType == COUPON_TYPE.CHG else self.mbsCashflow
                prem_act = flows['fixedPremiumPayments'].values[future]
                prem_req = lambda prm: np.round(bond_principals[future] * prm / 10000.0 * coupon_days[future] / 365.0, 2)
                prem_req_price = lambda prm: (100.0 + ((prem_act - prem_req(prm)) * self.dfZCYCPlusZ(prm, t_future)).sum() /
                                              self.currentBondPrincipal * 100.0 + self.accruedCouponInterest)

                premium = minimize(lambda prm: (prem_req_price(prm) - self.dirtyPrice) ** 2.0, np.array([100.0]), method='Nelder-Mead').x[0]
                self.requiredKeyRatePremium = premium

            elif self.calculationType == CALCULATION_TYPE.SET_FXPRM:
                self.requiredKeyRatePremium = self.fixedKeyRatePremium

            elif self.calculationType == CALCULATION_TYPE.SET_PREMI:
                pass

        else:
            pass

        # ----- ДЮРАЦИЯ МАКОЛЕЯ ---------------------------------------------------------------------------------------------------------- #
        if self.couponType == COUPON_TYPE.FXD or (self.couponType == COUPON_TYPE.CHG and self.poolType == COUPON_TYPE.FXD):
            self.durationMacaulay = self.durationMacaulay_func(self.ytm)

        elif self.couponType == COUPON_TYPE.FLT:
            pass

        # ----- МОДИФИЦИРОВАННАЯ ДЮРАЦИЯ ------------------------------------------------------------------------------------------------- #
        if self.couponType == COUPON_TYPE.FXD or (self.couponType == COUPON_TYPE.CHG and self.poolType == COUPON_TYPE.FXD):
            self.durationModified = self.durationMacaulay / (1.0 + self.ytm / 100.0)

        elif self.couponType == COUPON_TYPE.FLT:
            pass

        # ----- ОЦЕНКА СВОПА С ИПОТЕЧНЫМ АГЕНТОМ ----------------------------------------------------------------------------------------- #
        if self.swapPricing:

            # Формируем основу модели свопа:
            c = ['couponDate', 'couponDays', 'principalStartPeriod']
            self.swapModel = self.mbsCashflow[c].copy(deep=True)

            # Непогашенный объем выпуска до выплаты купона:
            self.swapModel['principalStartPeriod'] = np.round(self.swapModel['principalStartPeriod'].values * self.numberOfBonds, 2)

            # Рассчитываем фиксированные суммы. Т.к. своп считается от лица ДОМ.РФ в отношении Ипотечного агента, фиксированные суммы
            # указываются со знаком "минус":
            self.swapModel['fixedSum'] = -np.round(self.mbsCashflow['couponPayment'].values * self.numberOfBonds, 2)

            # Добавляем модельные плавающие суммы и их компоненты:
            c = ['couponDate', 'yield', 'subsidy', 'reinvestment', 'expense', 'accruedYield', 'floatSum']
            self.swapModel = self.swapModel.merge(self.mbsModel['total']['inflow'][c], how='left', on='couponDate')
            for col in c[1:]:
                self.swapModel

            # Указываем, когда именно пройдет неттинг по свопу:
            self.swapModel['couponDate'] -= self.writeOffDays
            self.swapModel.rename(columns={'couponDate': 'nettingDate'}, inplace=True)

            # Оставляем только платежи, которые состоятся строго после Даты оценки:
            future = self.swapModel['nettingDate'] > self.pricingDate
            self.swapModel = self.swapModel[future]

            # Рассчитываем фиксированные и плавающие суммы в терминах процентов годовых:
            coupon_days = self.swapModel['couponDays'].values
            issue_principals = self.swapModel['principalStartPeriod'].values
            fixed_sums = self.swapModel['fixedSum'].values
            float_sums = self.swapModel['floatSum'].values

            self.swapModel['fixedSumPercent'] = np.round(-fixed_sums / issue_principals * 365.0 / coupon_days * 100.0, 2)
            self.swapModel['floatSumPercent'] = np.round(float_sums / issue_principals * 365.0 / coupon_days * 100.0, 2)
            self.swapModel.drop(columns=['couponDays', 'principalStartPeriod'], inplace=True)

            # Количество лет между будущей датой неттинга по свопу и Датой оценки:
            t = (self.swapModel['nettingDate'].values - self.pricingDate) / np.timedelta64(1, 'D') / 365.0

            # Фактор дисконтирования в зависимости от типа купона:
            z_spread = self.requiredKeyRatePremium if self.couponType is COUPON_TYPE.FLT else self.zSpread
            df = self.dfZCYCPlusZ(z_spread, t)

            # Стоимость свопа в рублях:
            self.swapPriceRub = np.round(np.sum((fixed_sums + float_sums) * df), 2)

            # Стоимость свопа в % от непогашенного номинала выпуска облигаций:
            self.swapPrice = self.swapPriceRub / (self.currentBondPrincipal * self.numberOfBonds) * 100.0

        # [ОБНОВЛЕНИЕ СТАТУСА РАСЧЕТА]
        self.currentPercent = 99.0
        update(self.connectionId, self.currentPercent, self.progressBar)

        ####################################################################################################################################

    def outputPreparation(self):

        """ Подготовка выходных данных расчета """

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ФОРМИРОВАНИЕ РЕЗУЛЬТАТА ОЦЕНКИ ------------------------------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        self.pricingResult = {
            'accruedCouponInterest': np.round(self.accruedCouponInterest, 2 if self.rounding else self.roundingPrecision),
            'accruedCouponInterestRub': self.accruedCouponInterestRub,
            'dirtyPrice': np.round(self.dirtyPrice, 2 if self.rounding else self.roundingPrecision),
            'dirtyPriceRub': self.dirtyPriceRub,
            'cleanPrice': np.round(self.cleanPrice, 2 if self.rounding else self.roundingPrecision),
            'cleanPriceRub': self.cleanPriceRub,
        }

        self.pricingResult['ytm'] = None
        if self.ytm is not None:
            self.pricingResult['ytm'] = np.round(self.ytm, 2 if self.rounding else self.roundingPrecision)

        self.pricingResult['zSpread'] = None
        if self.zSpread is not None:
            if self.rounding:
                self.pricingResult['zSpread'] = int(np.round(self.zSpread, 0))
            else:
                self.pricingResult['zSpread'] = np.round(self.zSpread, self.roundingPrecision)

        self.pricingResult['gSpread'] = None
        if self.gSpread is not None:
            if self.rounding:
                self.pricingResult['gSpread'] = int(np.round(self.gSpread, 0))
            else:
                self.pricingResult['gSpread'] = np.round(self.gSpread, self.roundingPrecision)

        self.pricingResult['requiredKeyRatePremium'] = None
        if self.requiredKeyRatePremium is not None:
            if self.rounding:
                self.pricingResult['requiredKeyRatePremium'] = int(np.round(self.requiredKeyRatePremium, 0))
            else:
                self.pricingResult['requiredKeyRatePremium'] = np.round(self.requiredKeyRatePremium, self.roundingPrecision)

        self.pricingResult['modelKeyRatePremium'] = None
        if self.modelKeyRatePremium is not None:
            if self.rounding:
                self.pricingResult['modelKeyRatePremium'] = int(np.round(self.modelKeyRatePremium, 0))
            else:
                self.pricingResult['modelKeyRatePremium'] = np.round(self.modelKeyRatePremium, self.roundingPrecision)

        self.pricingResult['durationMacaulay'] = None
        if self.durationMacaulay is not None:
            self.pricingResult['durationMacaulay'] = np.round(self.durationMacaulay, 2 if self.rounding else self.roundingPrecision)

        self.pricingResult['durationModified'] = None
        if self.durationModified is not None:
            self.pricingResult['durationModified'] = np.round(self.durationModified, 2 if self.rounding else self.roundingPrecision)

        self.pricingResult['swapPrice'] = None
        self.pricingResult['swapPriceRub'] = None
        if self.swapPricing:
            self.pricingResult['swapPrice'] = np.round(self.swapPrice, 2 if self.rounding else self.roundingPrecision)
            self.pricingResult['swapPriceRub'] = self.swapPriceRub

        self.calculationOutput['pricingResult'] = self.pricingResult

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ПАРАМЕТРЫ, НА КОТОРЫХ ОСНОВАН РАСЧЕТ ------------------------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        self.pricingParameters['pricingDate'] = str(self.pricingDate.astype(s_type))
        self.pricingParameters['usePricingDateDataOnly'] = self.usePricingDateDataOnly
        self.pricingParameters['cpr'] = self.cpr
        self.pricingParameters['cdr'] = self.modelCDR
        self.pricingParameters['zcycDateTime'] = str(self.zcycParameters['date'])
        self.pricingParameters['zcycParameters'] = self.zcycParameters
        self.pricingParameters['rounding'] = self.rounding

        self.calculationOutput['pricingParameters'] = self.pricingParameters

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ДЕНЕЖНЫЙ ПОТОК ПО ИПОТЕЧНОМУ ПОКРЫТИЮ ------------------------------------------------------------------------------------ #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        # Денежный поток по ипотечному покрытию:
        self.calculationOutput['poolCashflowTable'] = {
            'total': None,  # денежный поток по всем кредитам
            'fixed': None,  # денежный поток по кредитам без субсидий
            'float': None,  # денежный поток по кредитам с субсидиями
        }

        # Денежный поток, иллюстрирующий расчет субсидий:
        self.calculationOutput['subsidyCashflowTable'] = None

        if self.runCashflowModel:

            pool_parts = ['total', 'fixed', 'float'] if self.poolType is POOL_TYPE.MIX else ['total']

            for part in pool_parts:

                # Берем за основу денежный поток по ипотечному покрытию с учетом восстановленных платежей в прошлом:
                base_cf = self.mbsModel[part]['pool']

                # pool_cf заканчивается на последнем месяце расчетного периода модельной даты погашения выпуска облигаций. В том случае,
                # если пользователь установил полный расчет денежного потока по ипотечному покрытию, необходимо добавить денежный поток за
                # месяцы после последнего месяца расчетного периода модельной даты погашения выпуска облигаций:
                if self.fullPoolModel:
                    last_payment_month = base_cf['paymentMonth'].values[-1]
                    index = self.poolModel[part]['cashflow']['paymentMonth'] > last_payment_month
                    base_cf_out = self.poolModel[part]['cashflow'][index]
                    base_cf = pd.concat([base_cf, base_cf_out])

                # Преобразуем денежный поток по ипотечному покрытию таким образом, чтобы его можно было легко интерпретировать:
                pool_cf = pd.DataFrame([])

                # — model — идентификатор, указывающий, являются ли указанные значения amortization, scheduled, prepayment и defaults
                #   модельными (1) или фактическими (0). Значения yield и выплаченных субсидий subsidyPaid (при наличии) по построению
                #   всегда являются модельными:
                pool_cf['model'] = base_cf['model'].values.astype(int)

                # — reportDate — дата, по состоянию на которую указываются значения debt и wac:
                pool_cf['reportDate'] = base_cf['reportDate'].values
                nan_report_dates = np.isnan(base_cf['reportDate'].values)
                pool_cf.loc[nan_report_dates, 'reportDate'] = base_cf['paymentMonth'].values[nan_report_dates]

                # — paymentMonth — месяц, внутри которого Ипотечному агенту поступают указанные значения amortization, scheduled,
                #   prepayment, defaults, yield и, при наличии, subsidyPaid (2023-11-01T00:00:00 означает ноябрь 2023 года):
                pool_cf['paymentMonth'] = base_cf['paymentMonth'].values.astype(s_type).astype(str)

                # — couponDate — дата купонной выплаты, в расчетный период которой входит указанный paymentMonth. Если couponDate == None,
                # то в указанном paymentMonth ипотечное покрытие уже не обеспечивает выпуск облигаций:
                pool_cf['couponDate'] = base_cf['couponDate'].values.astype(s_type).astype(str)
                nan_coupons = np.isnan(base_cf['couponDate'].values)
                pool_cf.loc[nan_report_dates, 'couponDate'] = None

                # — debt — сумма остатков основного долга в ипотечном покрытии на reportDate:
                pool_cf['debt'] = np.round(base_cf['debt'].values, 2)

                # — amortization — сумма погашений остатков основного долга за paymentMonth
                # (scheduled + prepayment + defaults + amortizationIFRS):
                pool_cf['amortization'] = np.round(base_cf['amortization'].values, 2)

                # — scheduled — сумма погашений остатков основного долга по графику платежей за paymentMonth:
                pool_cf['scheduled'] = np.round(base_cf['scheduled'].values, 2)

                # — prepayment — сумма досрочных погашений основного долга (частичных + полных) по кредитам за paymentMonth:
                pool_cf['prepayment'] = np.round(base_cf['prepayment'].values, 2)

                # — defaults — выкупы дефолтных кредитов из ипотечного покрытия за paymentMonth:
                pool_cf['defaults'] = np.round(base_cf['defaults'].values, 2)

                # — yield — процентные поступления без учета субсидий, поступившие за paymentMonth:
                pool_cf['yield'] = np.round(base_cf['yield'].values, 2)

                # — subsidyPaid — сумма выплаченных внутри paymentMonth субсидий (не начисленных, а именно выплаченных):
                pool_cf['subsidyPaid'] = 0.0

                # — cpr — средневзвешенное по остаткам основного долга на reportDate значение CPR по кредидам за paymentMonth:
                pool_cf['cpr'] = np.round(base_cf['cpr'].values, 5)

                # — wac — средневзвешення по остаткам основного долга текущая процентная ставка в ипотечном покрытии на reportDate:
                pool_cf['wac'] = np.round(base_cf['wac'].values, 5)

                if self.ifrs:

                    pool_cf['amortizationIFRS'] = 0.0
                    pool_cf['yieldIFRS'] = 0.0

                    # — amortizationIFRS — сумма всех перенесенных с прошлого месяца (относительно paymentMonth) погашений основного долга:
                    pool_cf['amortizationIFRS'] = np.round(base_cf['amortizationIFRS'].fillna(0.0).values, 2)

                    # Увеличиваем debt и amortization на размер перенесенных погашений основного долга:
                    for c in ['debt', 'amortization']:
                        pool_cf[c] = np.round(pool_cf[c].values + pool_cf['amortizationIFRS'].values, 2)

                    # — yieldIFRS — оценка суммы всех перенесенных с прошлого месяца (относительно paymentMonth) процентных поступлений:
                    pool_cf['yieldIFRS'] = np.round(base_cf['yieldIFRS'].fillna(0.0).values, 2)

                    # Увеличиваем yield на размер перенесенных процентных поступлений:
                    pool_cf['yield'] = np.round(pool_cf['yield'].values + pool_cf['yieldIFRS'].values, 2)

                    # — expensePart1 — расходы Ипотечного агента, заплаченные в месяц paymentMonth (часть 1);
                    # — expensePart2 — все остальные расходы Ипотечного агента, заплаченные в месяц paymentMonth:
                    expense_parts = self.mbsModel[part]['inflow'][['couponDate', 'expensePart1', 'expensePart2']]
                    if self.swapPricing:
                        expense_parts['couponDate'] -= self.writeOffDays
                    expense_parts['couponDate'] = expense_parts['couponDate'].values.astype(m_type).astype(s_type).astype(str)
                    expense_parts.rename(columns={'couponDate': 'paymentMonth'}, inplace=True)
                    pool_cf = pool_cf.merge(expense_parts, how='left', on='paymentMonth')

                else:
                    pool_cf['expensesPart1'] = 0.0
                    pool_cf['expensesPart2'] = 0.0

                subsidy_cf = None
                # Поля, относящиеся к начислению и выплате субсидий:
                if self.poolType in [POOL_TYPE.FLT, POOL_TYPE.MIX] and part in ['total', 'float']:
                    subsidy_cf = pool_cf[['reportDate', 'paymentMonth', 'debt', ]].copy(deep=True)

                    # — keyRateStartDate — Дата заседания Совета директоров Банка России, в устанавливается Ключевая ставка, по которой
                    #                      за месяц paymentMonth начисляется субсидия subsidyAccrued:
                    subsidy_cf['keyRateStartDate'] = base_cf['keyRateStartDate'].values.astype(s_type).astype(str)

                    # — keyRate — Ключевая ставка, по которой за месяц paymentMonth начисляется субсидия subsidyAccrued:
                    subsidy_cf['keyRate'] = base_cf['keyRate'].values

                    # — waKeyRateDeduction — Средневзвешенное по остаткам основного долга значение вычета для расчета субсидии по кредитам
                    #                        с субсидией на reportDate:
                    subsidy_cf['waKeyRateDeduction'] = base_cf['waKeyRateDeduction'].values

                    # — floatFraction — доля субсидируемых кредитов в ипотечном покрытии на reportDate
                    #                   (в терминах суммы остатка основного долга):
                    subsidy_cf['floatFraction'] = base_cf['floatFraction'].values

                    # — subsidyAccrued — начисленная за paymentMonth субсидия (выплачивается не в paymentMonth):
                    subsidy_cf['subsidyAccrued'] = np.round(base_cf['subsidy'].values, 2)

                    # — subsidyPaymentDate — дата, в которую выплачивается субсидия subsidyAccrued, начисленная за месяц paymentMonth:
                    report_dates = pd.to_datetime(subsidy_cf['reportDate']).dt.month.values
                    subsidy_payment_months = pd.DataFrame(report_dates, columns=['accrualMonth'])
                    subsidy_payment_months = subsidy_payment_months.merge(subsidy_months, how='left', on='accrualMonth')
                    payment_months = subsidy_cf['paymentMonth'].values.astype(m_type)
                    subsidy_cf['subsidyPaymentDate'] = (payment_months + month * subsidy_payment_months['addMonths'].values).astype(d_type)
                    subsidy_cf['subsidyPaymentDate'] += (self.subsidyPaymentDay - 1) * day
                    subsidy_cf['subsidyPaymentDate'] = subsidy_cf['subsidyPaymentDate'].values.astype(s_type).astype(str)

                    # — subsidyCouponDate — дата купонной выплаты, в расчетный период которой выплачивается субсидия subsidyAccrued,
                    #                       начисленная за месяц paymentMonth:
                    subsidy_cf['subsidyCouponDate'] = base_cf['subsidyCouponDate'].values.astype(s_type).astype(str)
                    nan_coupons = np.isnan(base_cf['subsidyCouponDate'].values)
                    subsidy_cf.loc[nan_report_dates, 'subsidyCouponDate'] = None

                    # — subsidyPaid — сумма выплаченных внутри paymentMonth субсидий (не начисленных, а именно выплаченных):
                    subsidy_payments = subsidy_cf[['subsidyPaymentDate', 'subsidyAccrued']].copy(deep=True)
                    subsidy_payments['subsidyPaymentDate'] = pd.to_datetime(subsidy_payments['subsidyPaymentDate']).values.astype(m_type)
                    subsidy_payments = subsidy_payments.groupby('subsidyPaymentDate', as_index=False).sum()
                    subsidy_payments.rename(columns={'subsidyPaymentDate': 'paymentMonth', 'subsidyAccrued': 'subsidyPaid'}, inplace=True)
                    subsidy_payments['paymentMonth'] = subsidy_payments['paymentMonth'].values.astype(s_type).astype(str)
                    subsidy_cf = subsidy_cf.merge(subsidy_payments, how='left', on='paymentMonth')
                    subsidy_cf['subsidyPaid'] = np.round(subsidy_cf['subsidyPaid'].infer_objects(copy=False).fillna(0.0).values, 2)

                    pool_cf['subsidyPaid'] = np.round(subsidy_cf['subsidyPaid'].values, 2)

                pool_cf['reportDate'] = pool_cf['reportDate'].values.astype(s_type).astype(str)
                pool_cf.replace({np.nan: None}, inplace=True)
                self.calculationOutput['poolCashflowTable'][part] = pool_cf.to_dict('list')

                if subsidy_cf is not None and part == 'total':
                    subsidy_cf['reportDate'] = subsidy_cf['reportDate'].values.astype(s_type).astype(str)
                    subsidy_cf.replace({np.nan: None, 'NaT': None}, inplace=True)
                    self.calculationOutput['subsidyCashflowTable'] = subsidy_cf.to_dict('list')

                if part == 'total' and self.fullPoolModel:
                    # Средневзвешенный по модельным суммам остатков основного долна в ипотечном покрытии CPR до погашения последнего
                    # кредита в ипотечном покрытии (определяется только в том случае, если ипотечное покрытие моделируется до конца):
                    p = (pool_cf['model'] == 1) & (pool_cf['debt'] > 0.0) & (pool_cf['cpr'] > 0.0)
                    self.poolModelCPR = np.sum(pool_cf['debt'].values[p] * pool_cf['cpr'].values[p]) / np.sum(pool_cf['debt'].values[p])
                    self.poolModelCPR = np.round(self.poolModelCPR, 2)

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ДЕНЕЖНЫЙ ПОТОК ПО ИЦБ ДОМ.РФ --------------------------------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        self.mbsCashflowTable = pd.DataFrame([])
        self.mbsCashflowTable['couponDate'] = self.mbsCashflow['couponDate'].values.astype(s_type).astype(str)
        self.mbsCashflowTable['cashflowType'] = self.mbsCashflow['cashflowType'].values
        self.mbsCashflowTable['bondPrincipalStartPeriod'] = np.round(self.mbsCashflow['principalStartPeriod'].values, 2)
        self.mbsCashflowTable['bondAmortization'] = np.round(self.mbsCashflow['amortization'].values, 2)
        self.mbsCashflowTable['bondCouponPayments'] = np.round(self.mbsCashflow['couponPayment'].values, 2)
        self.mbsCashflowTable['bondCouponDays'] = self.mbsCashflow['couponDays'].values.astype(int)
        self.mbsCashflowTable['bondCouponPaymentsPercents'] = np.round(self.mbsCashflow['couponPaymentPercent'].values, 2)

        n = self.numberOfBonds
        self.mbsCashflowTable['issuePrincipalStartPeriod'] = np.round(self.mbsCashflow['principalStartPeriod'].values * n, 2)
        self.mbsCashflowTable['issueAmortization'] = np.round(self.mbsCashflow['amortization'].values * n, 2)
        self.mbsCashflowTable['issueCouponPayments'] = np.round(self.mbsCashflow['couponPayment'].values * n, 2)

        if self.couponType is COUPON_TYPE.FLT:
            for c in ['couponKeyRateDate', 'keyRateStartDate']:
                self.mbsCashflowTable[c] = self.mbsCashflow[c].values.astype(s_type).astype(str)
            self.mbsCashflowTable['couponKeyRate'] = np.round(self.mbsCashflow['couponKeyRate'].values, 2)
            self.mbsCashflowTable['bondFixedPremiumPayments'] = np.round(self.mbsCashflow['fixedPremiumPayments'].values, 2)

        self.calculationOutput['mbsCashflowTable'] = self.mbsCashflowTable.to_dict('list')

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ДЕНЕЖНЫЙ ПОТОК ПО СВОПУ МЕЖДУ ДОМ.РФ И ИПОТЕЧНЫМ АГЕНТОМ С ТОЧКИ ЗРЕНИЯ ДОМ.РФ ------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        self.calculationOutput['swapCashflowTable'] = None

        if self.swapPricing:
            self.swapModel['nettingDate'] = self.swapModel['nettingDate'].values.astype(s_type).astype(str)
            self.calculationOutput['swapCashflowTable'] = self.swapModel.to_dict('list')

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ДАННЫЕ ДЛЯ ГРАФИКА ДЕНЕЖНОГО ПОТОКА ПО ИЦБ ДОМ.РФ ------------------------------------------------------------------------ #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        self.mbsCashflowGraph = pd.DataFrame({})
        self.mbsCashflowGraph['couponDates'] = self.mbsCashflowTable['couponDate'].values
        self.mbsCashflowGraph['cashflowType'] = self.mbsCashflowTable['cashflowType'].values.astype(int)

        # Описание cashflowType см. выше
        h = self.mbsCashflowGraph['cashflowType'].values == 2
        r = self.mbsCashflowGraph['cashflowType'].values == 1
        m = self.mbsCashflowGraph['cashflowType'].values == 0

        self.mbsCashflowGraph.loc[h, 'historicalAmortization'] = self.mbsCashflowTable['bondAmortization'].values[h]
        self.mbsCashflowGraph.loc[h, 'historicalCouponPayments'] = self.mbsCashflowTable['bondCouponPayments'].values[h]
        self.mbsCashflowGraph.loc[r, 'futureActualAmortization'] = self.mbsCashflowTable['bondAmortization'].values[r]
        self.mbsCashflowGraph.loc[r, 'futureActualCouponPayments'] = self.mbsCashflowTable['bondCouponPayments'].values[r]

        c = ['futureModelDifference', 'futureModelScheduled', 'futureModelPrepayment',
             'futureModelDefaults', 'futureModelCleanUp', 'futureModelCouponPayments']
        for column in c:
            self.mbsCashflowGraph[c] = None

        if self.runCashflowModel and self.bondID not in fixed_amt_bonds:
            self.mbsCashflowGraph.loc[m, 'futureModelDifference'] = self.mbsModel['total']['bond']['difference'].values
            self.mbsCashflowGraph.loc[m, 'futureModelScheduled'] = self.mbsModel['total']['bond']['scheduled'].values
            self.mbsCashflowGraph.loc[m, 'futureModelPrepayment'] = self.mbsModel['total']['bond']['prepayment'].values
            self.mbsCashflowGraph.loc[m, 'futureModelDefaults'] = self.mbsModel['total']['bond']['defaults'].values
            self.mbsCashflowGraph.loc[m, 'futureModelCleanUp'] = self.mbsModel['total']['bond']['cleanUp'].values
            self.mbsCashflowGraph.loc[m, 'futureModelCouponPayments'] = self.mbsModel['total']['bond']['couponPayment'].values

        self.mbsCashflowGraph.replace({np.nan: None}, inplace=True)
        self.mbsCashflowGraph = self.mbsCashflowGraph.to_dict('list')
        self.calculationOutput['mbsCashflowGraph'] = self.mbsCashflowGraph

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ГРАФИК КБД --------------------------------------------------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        self.calculationOutput['zcycGraph'] = None
        if self.couponType == COUPON_TYPE.FXD or (self.couponType == COUPON_TYPE.CHG and not self.poolType == POOL_TYPE.FLT):
            end_range = round_ceil(max(self.mbsCashflow['couponDate'].values - self.pricingDate) / np.timedelta64(1, 'D') / 365.0, 1)
            t = np.arange(0.1, end_range + 0.1, 0.1)
            zcyc_values = np.round(Y(self.zcycParameters, t) / 100.0, 5)

            self.calculationOutput['zcycGraph'] = zcyc_values.tolist()

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ГРАФИК CPR И СТАВКИ РЕФИНАНСИРОВАНИЯ ИПОТЕКИ ----------------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        self.calculationOutput['cprGraph'] = None
        if self.runCashflowModel:
            self.cprGraph = pd.DataFrame({})

            # График CPR и ставки рефинансирования ипотеки начинается с месяца даты среза ипотечного покрытия, т.к.
            # CPR в текущем месяце зависит от ставки рефинансирования предыдущего месяца:
            first_month = self.poolReportDate.astype(m_type) - month

            # График CPR и ставки рефинансирования ипотеки заканчивается последним месяцем расчетного периода модельной даты погашения ИЦБ:
            last_payment_period = self.mbsModel['total']['pool']['couponDate'] == self.modelRedemptionDate
            last_month = self.mbsModel['total']['pool'][last_payment_period]['paymentMonth'].values[-1].astype(m_type)

            # Мерджим из модели макроэкономики среднемесячные значения Ключевой ставки и ставки рефинансирования ипотеки:
            self.cprGraph['date'] = np.arange(first_month, last_month + month, month)
            self.cprGraph = self.cprGraph.merge(self.macroModel['ratesMonthlyAvg'], how='left', on='date')

            # Мерджим из модели ипотечного покрытия значения модельных остатков основного долга и помесячных модельных CPR:
            pool_cf = self.poolModel['total']['cashflow'][['paymentMonth', 'cpr', 'debt', 'wac']]
            self.cprGraph = self.cprGraph.merge(pool_cf, how='left', left_on='date', right_on='paymentMonth')

            # Средневзвешенный по модельным суммам остатков основного долна в ипотечном покрытии CPR на протяжении обращения
            # выпуска облигаций:
            cpr, dbt = self.cprGraph['cpr'].values, self.cprGraph['debt'].values
            self.modelCPR = np.round(np.nansum(cpr * dbt) / np.nansum(dbt), 1 if self.rounding else self.roundingPrecision)
            self.cprGraph['wac'].bfill(inplace=True)

            self.cprGraph = self.cprGraph[['date', 'key_rate', 'ref_rate', 'cpr', 'wac']]
            self.cprGraph.rename(columns={'key_rate': 'keyRate', 'ref_rate': 'refinancingRate', 'cpr': 'modelCPR'}, inplace=True)

            self.cprGraph.replace({np.nan: None}, inplace=True)
            self.cprGraph['date'] = self.cprGraph['date'].values.astype(s_type).astype(str)
            self.cprGraph = self.cprGraph.to_dict('list')

            self.calculationOutput['cprGraph'] = self.cprGraph

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ИНТЕРАКТИВНЫЙ ГРАФИК КЛЮЧЕВОЙ СТАВКИ ------------------------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        if self.runCashflowModel:
            self.calculationOutput['keyRateInteractiveGraph'] = self.macroModel['keyRateInteractiveGraph']

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- СТАТИСТИКА ИПОТЕЧНОГО ПОКРЫТИЯ ------------------------------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        self.calculationOutput['poolStatistics'] = None

        if self.runCashflowModel:
            self.poolStatistics = self.loansCashflowModel_res['poolStatistics']

            self.poolStatistics['historicalCDRDate'] = None
            if self.historicalCDRDate is not None:
                self.poolStatistics['historicalCDRDate'] = str(self.historicalCDRDate.astype(s_type))

            self.poolStatistics['historicalCDR'] = self.historicalCDR

            # ----- ДАТА ТЕКУЩЕЙ СТАВКИ РЕФИНАНСИРОВАНИЯ ИПОТЕКИ ------------------------------------------------------------------------- #
            self.poolStatistics['currentRefinancingRateDate'] = str(self.macroModel['currentRefinancingRateDate'].astype(s_type))

            # ----- ТЕКУЩАЯ СТАВКА РЕФИНАНСИРОВАНИЯ ИПОТЕКИ ------------------------------------------------------------------------------ #
            self.poolStatistics['currentRefinancingRate'] = self.macroModel['currentRefinancingRate']

            # ----- ТЕКУЩИЙ СТИМУЛ К РЕФИНАНСИРОВАНИЮ ------------------------------------------------------------------------------------ #
            wac, ref_rate = self.poolStatistics['wac']['total'], self.macroModel['currentRefinancingRate']
            self.poolStatistics['currentIncentive'] = np.round(wac - ref_rate, 2)

            # ----- ДАТА АКТУАЛЬНОСТИ ИСТОРИЧЕСКОГО CPR ---------------------------------------------------------------------------------- #
            self.poolStatistics['historicalCPRDate'] = None
            condition_1 = len(self.serviceReportsStatistics) >= 2
            if self.usePricingDateDataOnly:
                condition_2 = False
                if condition_1:
                    condition_2 = self.pricingDate >= self.serviceReportsStatistics['reportDate'].values[1] + self.poolDataDelay
                if condition_1 and condition_2:
                    index = self.serviceReportsStatistics['reportDate'].values <= self.pricingDate - self.poolDataDelay + self.ifrs * day
                    historicalCPRDate = str(self.serviceReportsStatistics['reportDate'].values[index][-1].astype(s_type))
                    self.poolStatistics['historicalCPRDate'] = historicalCPRDate
            else:
                if condition_1:
                    historicalCPRDate = str(self.serviceReportsStatistics['reportDate'].values.max().astype(s_type))
                    self.poolStatistics['historicalCPRDate'] = historicalCPRDate

            # ----- ИСТОРИЧЕСКИЙ CPR (СРЕДНЕЕ С ДАТЫ РАЗМЕЩЕНИЯ) ------------------------------------------------------------------------- #
            self.poolStatistics['historicalCPR'] = None
            if self.poolStatistics['historicalCPRDate'] is not None:
                index = self.serviceReportsStatistics['reportDate'].values == np.datetime64(self.poolStatistics['historicalCPRDate'], 'D')
                self.poolStatistics['historicalCPR'] = np.round(self.serviceReportsStatistics['historicalCPR'].values[index][0], 1)

            # ----- ИСТОРИЧЕСКИЙ CPR (СРЕДНЕЕ ЗА 6 ПРЕДЫДУЩИХ МЕСЯЦЕВ) ------------------------------------------------------------------- #
            self.poolStatistics['sixMonthsCPR'] = None
            if self.poolStatistics['historicalCPRDate'] is not None:
                index = self.serviceReportsStatistics['reportDate'].values == np.datetime64(self.poolStatistics['historicalCPRDate'], 'D')
                self.poolStatistics['sixMonthsCPR'] = np.round(self.serviceReportsStatistics['sixMonthsCPR'].values[index][0], 1)

            self.calculationOutput['poolStatistics'] = self.poolStatistics

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ПЕРЕМЕННЫЕ РАСЧЕТА ------------------------------------------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #

        self.calculationParameters['currentBondPrincipal'] = self.currentBondPrincipal
        self.calculationParameters['nextCouponDate'] = str(self.nextCouponDate.astype(s_type))

        self.calculationParameters['mortgageAgentExpense1'] = self.mortgageAgentExpense1
        self.calculationParameters['mortgageAgentExpense2'] = self.mortgageAgentExpense2

        parameters = ['calculationSCurvesReportDate', 'calculationSCurvesParameters', 'keyRateModelDate', 'conventionalCDR',
                      'modelCPR', 'modelCDR', 'poolModelCPR', 'keyRateSwapForecastDate', 'currentCBForecastDate']
        for p in parameters:
            self.calculationParameters[p] = None

        if self.runCashflowModel:

            self.calculationParameters['calculationSCurvesReportDate'] = str(self.calculationSCurvesReportDate.astype(s_type))

            self.calculationSCurvesParameters.drop(columns=['reportDate'], inplace=True)
            self.calculationParameters['calculationSCurvesParameters'] = self.calculationSCurvesParameters.to_dict('list')

            self.calculationParameters['keyRateModelDate'] = str(self.keyRateModelDate.astype(s_type))
            self.calculationParameters['conventionalCDR'] = self.conventionalCDR
            self.calculationParameters['modelCDR'] = self.modelCDR

            # Средневзвешенный по модельным суммам остатков основного долна в ипотечном покрытии CPR на протяжении обращения
            # выпуска облигаций:
            self.calculationParameters['modelCPR'] = self.modelCPR
            # Средневзвешенный по модельным суммам остатков основного долна в ипотечном покрытии CPR до погашения последнего
            # кредита в ипотечном покрытии (определяется только в том случае, если ипотечное покрытие моделируется до конца):
            self.calculationParameters['poolModelCPR'] = self.poolModelCPR

            if self.macroModel['keyRateSwapForecastDate'] is not None:
                self.calculationParameters['keyRateSwapForecastDate'] = str(self.macroModel['keyRateSwapForecastDate'].astype(s_type))

            if self.macroModel['currentCBForecastDate'] is not None:
                self.calculationParameters['currentCBForecastDate'] = str(self.macroModel['currentCBForecastDate'].astype(s_type))

        self.calculationOutput['calculationParameters'] = self.calculationParameters

        ####################################################################################################################################

    def calculate(self):

        """ Запуск расчета """

        if self.runCashflowModel:
            # ---------------------------------------------------------------------------------------------------------------------------- #
            # ----- РАСЧЕТ ДЕНЕЖНОГО ПОТОКА ПО ИПОТЕЧНОМУ ПОКРЫТИЮ ----------------------------------------------------------------------- #
            # ---------------------------------------------------------------------------------------------------------------------------- #
            self.poolCashflowModel()

            # ---------------------------------------------------------------------------------------------------------------------------- #
            # ----- РАСЧЕТ ДЕНЕЖНОГО ПОТОКА ПО ИЦБ ДОМ.РФ -------------------------------------------------------------------------------- #
            # ---------------------------------------------------------------------------------------------------------------------------- #
            self.mbsCashflowModel()

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- РАСЧЕТ ЦЕНОВЫХ МЕТРИК ИЦБ ДОМ.РФ ----------------------------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #
        self.mbsPricing()

        # -------------------------------------------------------------------------------------------------------------------------------- #
        # ----- ПОДГОТОВКА ВЫХОДНЫХ ДАННЫХ РАСЧЕТА --------------------------------------------------------------------------------------- #
        # -------------------------------------------------------------------------------------------------------------------------------- #
        self.outputPreparation()

        ####################################################################################################################################

        # [ОБНОВЛЕНИЕ СТАТУСА РАСЧЕТА]
        self.currentPercent = 100.0
        update(self.connectionId, self.currentPercent, self.progressBar)
        if self.progressBar is not None:
            self.progressBar.close()

        ####################################################################################################################################

        self.endTime = np.datetime64('now') + 3 * hour
        pricingDate = str(self.pricingDate.astype(d_type))
        length = str(self.endTime - self.startTime)[:-8]
        print(self.bondID + ' ' + pricingDate +
              ' ' + str(self.startTime)[-8:] +
              ' — ' + str(self.endTime)[-8:] +
              ' ' + length + ' sec.')

        return self.calculationOutput

        ####################################################################################################################################
