# -*- coding: utf8 -*-
# ----------------------------------------------------------------------------------- #
# ----- ПРОГРАММНАЯ РЕАЛИЗАЦИЯ КОНВЕНЦИИ ДЛЯ ИПОТЕЧНЫХ ЦЕННЫХ БУМАГ (ВЕРСИЯ 2.0) ---- #
# ----------------------------------------------------------------------------------- #

from requests import get
import numpy as np
import pandas as pd
import datetime as dt
from scipy.optimize import minimize
from auxiliary import *
import time


class Convention(object):

    """ Программная реализация Конвенции для ипотечных ценных бумаг (версия 2.0) """

    def __init__(self, input):

        self.calculationTime = {}

        self.pricingParameters = input

        # ----- 5.1 ISIN -----
        self.isin = None
        if 'isin' in self.pricingParameters.keys() and self.pricingParameters['isin'] is not None:
            self.isin = self.pricingParameters['isin']
        else:
            raise Exception(EXCEPTIONS.ISIN_NOT_SET)

        # ----------------------------------------------------------------------------------- #
        # ------------------ 4. ДАННЫЕ, НЕОБХОДИМЫЕ ДЛЯ ПРОВЕДЕНИЯ РАСЧЕТА ------------------ #
        # ----------------------------------------------------------------------------------- #

        self.start = time.time()
        self.dataForCalculation = get(API.DATA_FOR_CALCULATION.format(self.isin), timeout=15).json()
        self.end = time.time()
        self.calculationTime['dataForCalculationAPI'] = np.round(self.end - self.start, 2)

        # ----- 4.1 ПАРАМЕТРЫ ВЫПУСКА ИЦБ ДОМ.РФ -----
        self.bondParameters = self.dataForCalculation['bondParameters']

        self.tickerSymbol = self.bondParameters['tickerSymbol']                                        # 4.1.1 Биржевой тикер
        self.issueDate = np.datetime64(self.bondParameters['issueDate'], 'D')                          # 4.1.2 Дата размещения
        self.deliveryDate = np.datetime64(self.bondParameters['deliveryDate'], 'D')                    # 4.1.3 Дата передачи
        self.firstCouponDate = np.datetime64(self.bondParameters['firstCouponDate'], 'D')              # 4.1.4 Дата первой купонной выплаты
        self.legalRedemptionDate = np.datetime64(self.bondParameters['legalRedemptionDate'], 'D')      # 4.1.5 Юридическая дата погашения
        self.actualRedemptionDate = None                                                               # 4.1.6 Фактическая дата погашения
        if self.bondParameters['actualRedemptionDate'] is not None:
            self.actualRedemptionDate = np.datetime64(self.bondParameters['actualRedemptionDate'], 'D')
        self.couponPeriod = int(self.bondParameters['couponPeriod'])                                   # 4.1.7 Длина купонного периода
        self.couponType = int(self.bondParameters['couponType'])                                       # 4.1.8 Тип расчета купонной выплаты
        self.startBondPrincipal = float(self.bondParameters['startBondPrincipal'])                     # 4.1.9 Первоначальный номинал облигации
        self.startIssuePrincipal = float(self.bondParameters['startIssuePrincipal'])                   # 4.1.10 Первоначальный объем выпуска
        self.deliveryDebtAmount = float(self.bondParameters['deliveryDebtAmount'])                     # 4.1.11 Сумма остатков основного долга по акту передачи
        self.cleanUpPercentage = float(self.bondParameters['cleanUpPercentage'])                       # 4.1.12 Порог условия clean-up в %
        self.initialWAC = float(self.bondParameters['initialWAC'])                                     # 4.1.13 WAC по Реестру ипотечного покрытия на дату подписания решения о выпуске
        self.initialStandardWAM = float(self.bondParameters['initialStandardWAM'])                     # 4.1.14 WAM по РИП на дату подписания решения о выпуске (классическая формула)
        self.initialAdjustedWAM = float(self.bondParameters['initialAdjustedWAM'])                     # 4.1.15 WAM по РИП на дату подписания решения о выпуске (скорректированная формула)
        self.initialExpectedCDR = float(self.bondParameters['initialExpectedCDR'])                     # 4.1.16 Ожидаемый CDR на Дату передачи

        self.fixedCouponRate = None                                                                    # 4.1.17 Фиксированная ставка купона
        if self.couponType == COUPON_TYPE.FXD:
            self.fixedCouponRate = float(self.bondParameters['fixedCouponRate'])

        self.firstCouponExpensesIssueDoc = None         # 4.1.18 Оплата услуг Поручителя, Сервисного агента и Резервного сервисного агента (первый купон, согласно эмисcионной документации)
        self.otherCouponsExpensesIssueDoc = None        # 4.1.19 Оплата услуг Поручителя, Сервисного агента и Резервного сервисного агента (второй и после-дующие купоны, согласно эмисcионной документации)
        self.specDepRateIssueDoc = None                 # 4.1.20 Оплата услуг Специализированного депозитария, % годовых
        self.specDepMinMonthIssueDoc = None             # 4.1.21 Минимальная сумма оплаты услуг Специализированного депозитария
        self.specDepCompensationMonthIssueDoc = None    # 4.1.22 Возмещение расходов Специализированного депозитария
        self.manAccQuartRateIssueDoc = None             # 4.1.23 Оплата услуг управляющей и бухгалтерской организаций (тариф)
        self.manAccQuartFixIssueDoc = None              # 4.1.24 Оплата услуг управляющей и бухгалтерской организаций (фикс.)
        self.paymentAgentYearIssueDoc = None            # 4.1.25 Оплата услуг расчетного агента
        self.partialPrepaymentAllowedAnytime = None     # 4.1.26 Индикатор частичного погашения в любой день
        if self.couponType == COUPON_TYPE.CHG:
            self.firstCouponExpensesIssueDoc = float(self.bondParameters['firstCouponExpensesIssueDoc'])
            self.otherCouponsExpensesIssueDoc = float(self.bondParameters['otherCouponsExpensesIssueDoc'])
            self.specDepRateIssueDoc = float(self.bondParameters['specDepRateIssueDoc'])
            self.specDepMinMonthIssueDoc = float(self.bondParameters['specDepMinMonthIssueDoc'])
            self.specDepCompensationMonthIssueDoc = float(self.bondParameters['specDepCompensationMonthIssueDoc'])
            self.manAccQuartRateIssueDoc = float(self.bondParameters['manAccQuartRateIssueDoc']) if self.bondParameters['manAccQuartRateIssueDoc'] is not None else 0.0
            self.manAccQuartFixIssueDoc = float(self.bondParameters['manAccQuartFixIssueDoc']) if self.bondParameters['manAccQuartFixIssueDoc'] is not None else 0.0
            self.paymentAgentYearIssueDoc = float(self.bondParameters['paymentAgentYearIssueDoc'])
            self.partialPrepaymentAllowedAnytime = float(self.bondParameters['partialPrepaymentAllowedAnytime'])

        self.fixedKeyRatePremium = None                 # 4.1.27 Фиксированная надбавка к Ключевой ставке
        if self.couponType == COUPON_TYPE.FLT:
            self.fixedKeyRatePremium = float(self.bondParameters['fixedKeyRatePremium'])

        # ----- 4.2 ИСТОРИЧЕСКАЯ СТАТИСТИКА ПО ПУЛУ ЗАКЛАДНЫХ -----
        self.serviceReportsStatistics = pd.DataFrame(self.dataForCalculation['serviceReportsStatistics'])
        self.serviceReportsStatistics['serviceReportDate'] = pd.to_datetime(self.serviceReportsStatistics['serviceReportDate'])
        self.serviceReportsStatistics.sort_values(by='serviceReportDate', inplace=True)

        # ----- 4.3 ДАННЫЕ ОТЧЕТОВ ДЛЯ ИНВЕСТОРОВ -----
        self.investorsReportsData = pd.DataFrame(self.dataForCalculation['investorsReportsData'])
        self.investorsReportsData['investorsReportCouponDate'] = pd.to_datetime(self.investorsReportsData['investorsReportCouponDate'])
        self.investorsReportsData.sort_values(by='investorsReportCouponDate', inplace=True)

        # ----- 4.4 ПАРАМЕТРЫ S-КРИВОЙ -----
        self.sCurveParameters = pd.DataFrame(self.dataForCalculation['sCurveParameters'])
        self.sCurveParameters['sCurveReportDate'] = pd.to_datetime(self.sCurveParameters['sCurveReportDate'])
        self.sCurveParameters.sort_values(by='sCurveReportDate', inplace=True)

        # ----- 4.5 ДАННЫЕ ПО СТАВКЕ РЕФИНАНСИРОВАНИЯ ИПОТЕКИ -----
        self.refinancingRatesData = pd.DataFrame(self.dataForCalculation['refinancingRatesData'])
        self.refinancingRatesData['refinancingRateReportDate'] = pd.to_datetime(self.refinancingRatesData['refinancingRateReportDate'])
        self.refinancingRatesData.sort_values(by='refinancingRateReportDate', inplace=True)

        # ----- 4.6 ДАННЫЕ ПО КЛЮЧЕВОЙ СТАВКЕ ЦБ РФ -----
        self.keyRatesData = pd.DataFrame(self.dataForCalculation['keyRatesData'])
        self.keyRatesData['keyRateReportDate'] = pd.to_datetime(self.keyRatesData['keyRateReportDate'])
        self.keyRatesData.sort_values(by='keyRateReportDate', inplace=True)

        # ----------------------------------------------------------------------------------- #
        # ------------------------------- 5. ПАРАМЕТРЫ ОЦЕНКИ ------------------------------- #
        # ----------------------------------------------------------------------------------- #

        # ----- 5.8 ДАТА ОЦЕНКИ -----
        self.pricingDate = None
        if 'pricingDate' in self.pricingParameters.keys() and self.pricingParameters['pricingDate'] is not None:
            self.pricingDate = np.datetime64(self.pricingParameters['pricingDate'], 'D')
        else:
            maximum_possible_date = self.legalRedemptionDate if self.actualRedemptionDate is None else self.actualRedemptionDate
            if not self.issueDate <= np.datetime64('today') < maximum_possible_date:
                self.pricingDate = self.issueDate
            else:
                self.pricingDate = np.datetime64('today')

        # ----- 5.2-5.7 ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ -----
        self.calculationType = None                         # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ
        self.zSpread = None                                 # 5.2 ЗАДАННЫЙ Z-СПРЕД
        self.gSpread = None                                 # 5.3 ЗАДАННЫЙ G-СПРЕД
        self.dirtyPrice = None                              # 5.4 ЗАДАННАЯ ГРЯЗНАЯ ЦЕНА
        self.cleanPrice = None                              # 5.5 ЗАДАННАЯ ЧИСТАЯ ЦЕНА
        self.requiredKeyRatePremium = None                  # 5.6 ЗАДАННАЯ ТРЕБУЕМАЯ НАДБАВКА К КЛЮЧЕВОЙ СТАВКЕ
        self.couponRate = None                              # 5.7 ЗАДАННАЯ СТАВКА КУПОНА

        z_spread_is_specified = 'zSpread' in self.pricingParameters.keys() and self.pricingParameters['zSpread'] is not None
        g_spread_is_specified = 'gSpread' in self.pricingParameters.keys() and self.pricingParameters['gSpread'] is not None
        dirty_price_is_specified = 'dirtyPrice' in self.pricingParameters.keys() and self.pricingParameters['dirtyPrice'] is not None
        clean_price_is_specified = 'cleanPrice' in self.pricingParameters.keys() and self.pricingParameters['cleanPrice'] is not None
        premium_is_specified = 'requiredKeyRatePremium' in self.pricingParameters.keys() and self.pricingParameters['requiredKeyRatePremium'] is not None
        coupon_rate_is_specified = 'couponRate' in self.pricingParameters.keys() and self.pricingParameters['couponRate'] is not None

        check = z_spread_is_specified + g_spread_is_specified + dirty_price_is_specified + clean_price_is_specified + premium_is_specified + coupon_rate_is_specified
        if check > 1:
            raise Exception(EXCEPTIONS.SEVERAL_CALCULATION_TYPES)
        elif check == 0:
            raise Exception(EXCEPTIONS.CALCULATION_TYPE_NOT_SPECIFIED)

        # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 1: ЗАДАТЬ Z-СПРЕД
        if z_spread_is_specified:
            if self.couponType != COUPON_TYPE.FLT:
                self.calculationType = CALCULATION_TYPE.SET_ZSPRD
                self.zSpread = np.round(float(self.pricingParameters['zSpread']), 0)
                if not CONSTRAINTS.ZSPRD_MIN <= self.zSpread <= CONSTRAINTS.ZSPRD_MAX:
                    raise Exception(CONSTRAINTS.ZSPRD_EXCEP)
            else:
                raise Exception(EXCEPTIONS.CALCULATION_TYPE_INCORRECT_CPN)

        # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 2: ЗАДАТЬ G-СПРЕД
        elif g_spread_is_specified:
            if self.couponType != COUPON_TYPE.FLT:
                self.calculationType = CALCULATION_TYPE.SET_GSPRD
                self.gSpread = np.round(float(self.pricingParameters['gSpread']), 0)
                if not CONSTRAINTS.GSPRD_MIN <= self.gSpread <= CONSTRAINTS.GSPRD_MAX:
                    raise Exception(CONSTRAINTS.GSPRD_EXCEP)
            else:
                raise Exception(EXCEPTIONS.CALCULATION_TYPE_INCORRECT_CPN)

        # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 3: ЗАДАТЬ ГРЯЗНУЮ ЦЕНУ
        elif dirty_price_is_specified:
            self.calculationType = CALCULATION_TYPE.SET_DIRTY
            self.dirtyPrice = np.round(float(self.pricingParameters['dirtyPrice']), 2)
            if not CONSTRAINTS.DIRTY_MIN <= self.dirtyPrice <= CONSTRAINTS.DIRTY_MAX:
                raise Exception(CONSTRAINTS.DIRTY_EXCEP)

        # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 4: ЗАДАТЬ ЧИСТУЮ ЦЕНУ
        elif clean_price_is_specified:
            self.calculationType = CALCULATION_TYPE.SET_CLEAN
            self.cleanPrice = np.round(float(self.pricingParameters['cleanPrice']), 2)
            if not CONSTRAINTS.CLEAN_MIN <= self.cleanPrice <= CONSTRAINTS.CLEAN_MAX:
                raise Exception(CONSTRAINTS.CLEAN_EXCEP)

        # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 5: ЗАДАТЬ ТРЕБУЕМУЮ НАДБАВКУ
        elif premium_is_specified:
            if self.couponType == COUPON_TYPE.FLT:
                self.calculationType = CALCULATION_TYPE.SET_PREMI
                self.requiredKeyRatePremium = np.round(float(self.pricingParameters['requiredKeyRatePremium']), 0)
                if not CONSTRAINTS.PREMI_MIN <= self.requiredKeyRatePremium <= CONSTRAINTS.PREMI_MAX:
                    raise Exception(CONSTRAINTS.PREMI_EXCEP)
            else:
                raise Exception(EXCEPTIONS.CALCULATION_TYPE_INCORRECT_CPN)

        # ТИП РАСЧЕТА ЦЕНОВЫХ ПАРАМЕТРОВ 6: ЗАДАТЬ СТАВКУ КУПОНА
        elif coupon_rate_is_specified:
            if self.couponType == COUPON_TYPE.FXD:
                self.pricingDate = self.issueDate
                self.calculationType = CALCULATION_TYPE.SET_COUPN
                self.couponRate = np.round(float(self.pricingParameters['couponRate']), 2)
                if not CONSTRAINTS.COUPN_MIN <= self.couponRate <= CONSTRAINTS.COUPN_MAX:
                    raise Exception(CONSTRAINTS.COUPN_EXCEP)
            else:
                raise Exception(EXCEPTIONS.CALCULATION_TYPE_INCORRECT_CPN)

        # ----- 5.9 ИНДИКАТОР ИСПОЛЬЗОВАНИЯ ТОЛЬКО ДОСТУПНОЙ НА ДАТУ ОЦЕНКИ ИНФОРМАЦИИ -----
        self.usePricingDateDataOnly = False
        if 'usePricingDateDataOnly' in self.pricingParameters.keys() and self.pricingParameters['usePricingDateDataOnly'] is not None:
            self.usePricingDateDataOnly = bool(self.pricingParameters['usePricingDateDataOnly'])

        # ----- ВЫПУСК RU000A100DQ4 ЯВЛЯЕТСЯ УНИКАЛЬНЫМ ВЫПУСКОМ С ФИКСИРОВАННЫМ ГРАФИКОМ АМОРТИЗАЦИИ НОМИНАЛЬНОЙ СТОИМОСТИ.
        #       В СВЯЗИ С ТЕМ, ЧТО ВЕСЬ ГРАФИК ПЛАТЕЖЕЙ ПО ОБЛИГАЦИЯМ ДАННОГО ВЫПУСКА УЖЕ БЫЛ ИЗВЕСТЕН НА ДАТУ РАЗМЕЩЕНИЯ,
        #       НЕОБХОДИМО ИСКЛЮЧИТЬ ВОЗМОЖНОСТЬ ОЦЕНКИ ДАННОГО ВЫПУСКА С ИНДИКАТОРОМ, РАВНЫМ ЕДИНИЦЕ (В ПРОТИВНОМ СЛУЧАЕ,
        #       РАСЧЕТ БУДЕТ ПРОВЕДЕН С МОДЕЛИРОВАНИЕМ АМОРТИЗАЦИИ ВЫПУСКА ПО УКАЗАННЫМ CPR/CDR) -----
        if self.isin == 'RU000A100DQ4':
            self.usePricingDateDataOnly = False

        # ----- 5.10 ЗАДАННЫЙ CPR -----
        self.cpr = None
        if 'cpr' in self.pricingParameters.keys() and self.pricingParameters['cpr'] is not None:
            if float(self.pricingParameters['cpr']) <= 100.0:
                self.cpr = float(self.pricingParameters['cpr'])
                self.pricingParameters['cpr'] = np.round(self.cpr, 1)
            else:
                raise Exception(EXCEPTIONS.CPR_CDR_SUM_CHECK)

        # ----- 5.11 ЗАДАННЫЙ CDR -----
        self.cdr = None
        if 'cdr' in self.pricingParameters.keys() and self.pricingParameters['cdr'] is not None:
            if float(self.pricingParameters['cdr']) <= 100.0:
                self.cdr = float(self.pricingParameters['cdr'])
            else:
                raise Exception(EXCEPTIONS.CPR_CDR_SUM_CHECK)

        if self.cpr is not None and self.cdr is not None and self.cpr + self.cdr > 100.0:
            raise Exception(EXCEPTIONS.CPR_CDR_SUM_CHECK)

        # ----- ПАРАМЕТРЫ КРИВОЙ БЕСКУПОННОЙ ДОХОДНОСТИ (КБД) -----
        self.zcycDateTime = self.pricingDate + np.timedelta64(1, 'D') - np.timedelta64(1, 's')
        if 'zcycDateTime' in self.pricingParameters.keys() and self.pricingParameters['zcycDateTime'] is not None:
            self.zcycDateTime = np.datetime64(self.pricingParameters['zcycDateTime'])

        self.start = time.time()
        self.zcycParameters = get(API.GET_ZCYC_COEFFICIENTS.format(self.zcycDateTime), timeout=15).json()
        self.end = time.time()
        self.calculationTime['ZCYCParametersAPI'] = np.round(self.end - self.start, 2)

        # ----------------------------------------------------------------------------------- #
        # ------------------------------ 6. РАСЧЕТНЫЕ ПАРАМЕТРЫ ----------------------------- #
        # ----------------------------------------------------------------------------------- #

        # ----- 6.1 ДАТЫ КУПОННЫХ ВЫПЛАТ -----
        start_range = self.firstCouponDate.astype(m_type)
        end_range = self.legalRedemptionDate.astype(m_type) + np.timedelta64(1, 'M')
        step = np.timedelta64(self.couponPeriod, 'M')
        payment_day = np.timedelta64(self.firstCouponDate.astype(object).day - 1, 'D')
        self.allCouponDates = np.arange(start_range, end_range, step).astype(d_type) + payment_day

        self.couponDatesSeries = pd.DataFrame({'allCouponDates': self.allCouponDates.tolist()})         # 6.1.1 НАБОР ВСЕХ ДАТ КУПОННЫХ ВЫПЛАТ
        self.couponDatesSeries['couponPeriodsDays'] = self.couponDatesSeries['allCouponDates'].diff()   # 6.1.2 КОЛИЧЕСТВО ДНЕЙ В КУПОННОМ ПЕРИОДЕ, ПРЕДШЕСТВУЮЩЕМ ДАТЕ КУПОННОЙ ВЫПЛАТЫ
        self.couponDatesSeries.loc[0, 'couponPeriodsDays'] = self.firstCouponDate - self.issueDate
        self.couponDatesSeries['couponPeriodsDays'] /= np.timedelta64(1, 'D')

        # ----- 6.2 ПРЕДЫДУЩАЯ ОТ ДАТЫ ОЦЕНКИ ДАТА КУПОННОЙ ВЫПЛАТЫ -----
        self.previousCouponDate = None
        if self.pricingDate >= self.firstCouponDate:
            self.previousCouponDate = self.allCouponDates[self.allCouponDates <= self.pricingDate][-1]

        # ----- 6.3 ИНДИКАТОР ВАЛИДНОСТИ ДАТЫ ОЦЕНКИ -----
        condition_1 = self.issueDate <= self.pricingDate < self.firstCouponDate
        condition_2_1 = self.firstCouponDate <= self.pricingDate < self.legalRedemptionDate
        condition_2_2 = self.previousCouponDate in self.investorsReportsData['investorsReportCouponDate'].values
        condition_2_3 = True
        if self.actualRedemptionDate is not None:
            condition_2_3 = self.pricingDate < self.actualRedemptionDate
        condition_2 = condition_2_1 and condition_2_2 and condition_2_3

        self.pricingDateIsValid = False
        if condition_1 or condition_2:
            self.pricingDateIsValid = True
        else:
            if not condition_1 and (not condition_2_1 or not condition_2_3):
                raise Exception(EXCEPTIONS.PRICING_DATE_NOT_VALID_REASON_1)
            else:
                raise Exception(EXCEPTIONS.PRICING_DATE_NOT_VALID_REASON_2)

        # ----- 6.4 СЛЕДУЮЩАЯ ПОСЛЕ ДАТЫ ОЦЕНКИ ДАТА КУПОННОЙ ВЫПЛАТЫ -----
        self.nextCouponDate = self.allCouponDates[self.allCouponDates > self.pricingDate][0]

        # ----- 6.5 КОЛИЧЕСТВО ПРОШЕДШИХ ДНЕЙ В ТЕКУЩЕМ КУПОННОМ ПЕРИОДЕ -----
        self.daysPassedInCurrentCouponPeriod = None
        if self.nextCouponDate == self.firstCouponDate:
            self.daysPassedInCurrentCouponPeriod = float((self.pricingDate - self.issueDate) / np.timedelta64(1, 'D'))
        else:
            self.daysPassedInCurrentCouponPeriod = float((self.pricingDate - self.previousCouponDate) / np.timedelta64(1, 'D'))

        # ----- 6.6 КОЛИЧЕСТВО ПРОШЕДШИХ ДНЕЙ В ТЕКУЩЕМ КУПОННОМ ПЕРИОДЕ -----
        self.maximumCouponDateWithKnownPayment = None
        if not self.investorsReportsData.empty:
            self.maximumCouponDateWithKnownPayment = self.investorsReportsData['investorsReportCouponDate'].values.max().astype(d_type)

        # ----- 6.7 ДАТА КУПОННОЙ ВЫПЛАТЫ, С РАСЧЕТНОГО ПЕРИОДА КОТОРОЙ НАЧИНАЕТСЯ МОДЕЛИРОВАНИЕ ДЕНЕЖНОГО ПОТОКА ПО ПУЛУ ЗАКЛАДНЫХ -----
        self.poolCashflowStartCouponDate = None
        if self.usePricingDateDataOnly:
            condition_1 = self.nextCouponDate in self.investorsReportsData['investorsReportCouponDate'].values
            condition_2 = float((self.nextCouponDate - self.pricingDate) / np.timedelta64(1, 'D')) <= 12
            condition_3 = self.nextCouponDate != self.legalRedemptionDate
            condition_4 = True
            if self.actualRedemptionDate is not None:
                condition_4 = self.nextCouponDate != self.actualRedemptionDate
            if condition_1 and condition_2 and condition_3 and condition_4:
                self.poolCashflowStartCouponDate = self.allCouponDates[self.allCouponDates > self.nextCouponDate][0]
            else:
                self.poolCashflowStartCouponDate = self.nextCouponDate
        else:
            if self.maximumCouponDateWithKnownPayment is not None:
                condition_1 = self.maximumCouponDateWithKnownPayment != self.legalRedemptionDate
                condition_2 = True
                if self.actualRedemptionDate is not None:
                    condition_2 = self.maximumCouponDateWithKnownPayment != self.actualRedemptionDate
                if condition_1 and condition_2:
                    self.poolCashflowStartCouponDate = self.allCouponDates[self.allCouponDates > self.maximumCouponDateWithKnownPayment][0]
                else:
                    self.poolCashflowStartCouponDate = self.maximumCouponDateWithKnownPayment
            else:
                self.poolCashflowStartCouponDate = self.nextCouponDate

        # ----- 6.8 ЛАГ РАСЧЕТНОГО ПЕРИОДА -----
        self.paymentPeriodLag = 1 if self.firstCouponDate.astype(object).day < 16 else 0

        # ----- 6.9 ДАТА НАЧАЛА РАСЧЕТНОГО ПЕРИОДА, С КОТОРОГО НАЧИНАЕТСЯ МОДЕЛИРОВАНИЕ ДЕНЕЖНОГО ПОТОКА ПО ПУЛУ ЗАКЛАДНЫХ -----
        self.poolCashflowStartPaymentPeriodDate = None
        if self.poolCashflowStartCouponDate == self.firstCouponDate:
            self.poolCashflowStartPaymentPeriodDate = self.deliveryDate
        else:
            self.poolCashflowStartPaymentPeriodDate = (self.poolCashflowStartCouponDate.astype(m_type) - np.timedelta64(self.couponPeriod + self.paymentPeriodLag, 'M')).astype(d_type)

        # ----- 6.10 ПЕРВЫЙ ДЕНЬ МЕСЯЦА, С КОТОРОГО НАЧИНАЕТСЯ МОДЕЛИРОВАНИЕ ДЕНЕЖНОГО ПОТОКА ПО ПУЛУ ЗАКЛАДНЫХ -----
        self.poolCashflowStartDate = self.poolCashflowStartPaymentPeriodDate.astype(m_type).astype(d_type)

        # ----- 6.11 ДАТА АКТУАЛЬНОСТИ WAC, WAM -----
        self.wacwamDate = None
        if self.poolCashflowStartPaymentPeriodDate == self.deliveryDate:
            self.wacwamDate = self.deliveryDate
        else:
            if self.usePricingDateDataOnly:
                condition_1 = not self.serviceReportsStatistics.empty
                condition_2 = self.pricingDate >= self.serviceReportsStatistics['serviceReportDate'].values[0] + np.timedelta64(15, 'D')
                if condition_1 and condition_2:
                    condition_3 = self.poolCashflowStartDate in self.serviceReportsStatistics['serviceReportDate'].values
                    condition_4 = False
                    if self.poolCashflowStartDate <= self.pricingDate - np.timedelta64(15, 'D'):
                        condition_4 = True
                    if condition_3 and condition_4:
                        self.wacwamDate = self.poolCashflowStartDate
                    else:
                        index = self.serviceReportsStatistics['serviceReportDate'].values <= self.pricingDate - np.timedelta64(15, 'D')
                        self.wacwamDate = self.serviceReportsStatistics['serviceReportDate'].values[index][-1]
                else:
                    self.wacwamDate = self.deliveryDate
            else:
                if not self.serviceReportsStatistics.empty:
                    if self.poolCashflowStartDate in self.serviceReportsStatistics['serviceReportDate'].values:
                        self.wacwamDate = self.poolCashflowStartDate
                    else:
                        self.wacwamDate = self.serviceReportsStatistics['serviceReportDate'].values.max().astype(d_type)
                else:
                    self.wacwamDate = self.deliveryDate

        # ----- 6.12 WAC -----
        self.wac = None
        if self.wacwamDate == self.deliveryDate:
            self.wac = self.initialWAC
        else:
            service_reports_index = self.serviceReportsStatistics['serviceReportDate'].values == self.wacwamDate
            self.wac = self.serviceReportsStatistics['serviceReportWAC'][service_reports_index].values[0]
        self.wac = np.round(self.wac, 2)

        # ----- 6.13 WAM (КЛАССИЧЕСКАЯ ФОРМУЛА) -----
        self.standardWAM = None
        if self.wacwamDate == self.deliveryDate:
            self.standardWAM = self.initialStandardWAM
        else:
            service_reports_index = self.serviceReportsStatistics['serviceReportDate'].values == self.wacwamDate
            self.standardWAM = self.serviceReportsStatistics['serviceReportStandardWAM'][service_reports_index].values[0]
        self.standardWAM = np.round(self.standardWAM, 1)

        # ----- 6.14 WAM (СКОРРЕКТИРОВАННАЯ ФОРМУЛА) -----
        self.adjustedWAM = None
        if self.wacwamDate == self.deliveryDate:
            self.adjustedWAM = self.initialAdjustedWAM
        else:
            service_reports_index = self.serviceReportsStatistics['serviceReportDate'].values == self.wacwamDate
            self.adjustedWAM = self.serviceReportsStatistics['serviceReportAdjustedWAM'][service_reports_index].values[0]
        self.adjustedWAM = np.round(self.adjustedWAM, 1)

        # ----- 6.15 КОЭФФИЦИЕНТ СООТНОШЕНИЯ WAM -----
        self.wamCoefficient = self.adjustedWAM / self.standardWAM

        # ----- 6.16 ПЕРВЫЙ ДЕНЬ МЕСЯЦА, НА КОТОРОМ ЗАКАНЧИВАЕТСЯ МОДЕЛИРОВАНИЕ ДЕНЕЖНОГО ПОТОКА ПО ПУЛУ ЗАКЛАДНЫХ -----
        date_a = self.legalRedemptionDate.astype(m_type).astype(d_type)
        date_b = None
        if self.actualRedemptionDate is not None:
            date_b = self.actualRedemptionDate.astype(m_type).astype(d_type)
        date_c = (self.poolCashflowStartDate.astype(m_type) + np.timedelta64(int(np.floor(self.standardWAM - 1.0)), 'M')).astype(d_type)

        if self.actualRedemptionDate is not None and self.usePricingDateDataOnly:
            self.poolCashflowEndDate = min(date_a, date_b, date_c)
        else:
            self.poolCashflowEndDate = min(date_a, date_c)

        # ----- 6.17 КОЛИЧЕСТВО ДНЕЙ НАЧИСЛЕНИЯ ПРОЦЕНТОВ В МЕСЯЦЕ ПЕРЕДАЧИ ПУЛА -----
        self.deliveryMonthAccrualDays = ((self.deliveryDate.astype(m_type) + np.timedelta64(1, 'M')).astype(d_type) - self.deliveryDate) / np.timedelta64(1, 'D') - 1.0

        # ----- 6.18 КОЛИЧЕСТВО ОБЛИГАЦИЙ В ВЫПУСКЕ -----
        self.numberOfBonds = self.startIssuePrincipal / self.startBondPrincipal

        # ----- 6.19 НЕПОГАШЕННЫЙ НОМИНАЛ ОБЛИГАЦИИ НА ДАТУ ОЦЕНКИ -----
        self.currentBondPrincipal = None
        if self.issueDate <= self.pricingDate < self.firstCouponDate:
            self.currentBondPrincipal = self.startBondPrincipal
        else:
            index = self.investorsReportsData['investorsReportCouponDate'].values == self.previousCouponDate
            self.currentBondPrincipal = self.investorsReportsData['investorsReportBondNextPrincipal'].values[index][0]

        # ----- 6.20 СУММА ОСТАТКОВ ОСНОВНОГО ДОЛГА В ИПОТЕЧНОМ ПОКРЫТИИ НА ДАТУ НАЧАЛА РАСЧЕТНОГО ПЕРИОДА, С КОТОРОГО НАЧИНАЕТСЯ МОДЕЛИРОВАНИЕ ДЕНЕЖНОГО ПОТОКА ПО ПУЛУ ЗАКЛАДНЫХ -----
        self.poolCashflowStartDebt = None
        if self.poolCashflowStartCouponDate == self.firstCouponDate:
            self.poolCashflowStartDebt = self.deliveryDebtAmount
        else:
            if self.poolCashflowStartCouponDate == self.nextCouponDate:
                self.poolCashflowStartDebt = self.numberOfBonds * self.currentBondPrincipal
            else:
                coupon_date = self.allCouponDates[self.allCouponDates < self.poolCashflowStartCouponDate][-1]
                index = self.investorsReportsData['investorsReportCouponDate'].values == coupon_date
                self.poolCashflowStartDebt = self.numberOfBonds * self.investorsReportsData['investorsReportBondNextPrincipal'].values[index][0]

        # ----- 6.21 ПОРОГ УСЛОВИЯ CLEAN-UP В РУБЛЯХ -----
        self.cleanUpRubles = self.startBondPrincipal * self.cleanUpPercentage / 100.0

        # ----- 6.22 ДАТА АКТУАЛЬНОСТИ СТАВКИ РЕФИНАНСИРОВАНИЯ ИПОТЕКИ -----
        self.calculationRefinancingRateReportDate = None
        if self.usePricingDateDataOnly:
            index = self.refinancingRatesData['refinancingRateReportDate'].values <= self.pricingDate
            self.calculationRefinancingRateReportDate = self.refinancingRatesData['refinancingRateReportDate'].values[index][-1].astype(d_type)
        else:
            self.calculationRefinancingRateReportDate = self.refinancingRatesData['refinancingRateReportDate'].values.max().astype(d_type)

        # ----- 6.23 СТАВКА РЕФИНАНСИРОВАНИЯ ИПОТЕКИ, ПРИМЕНЯЕМАЯ В РАСЧЕТЕ -----
        index = self.refinancingRatesData['refinancingRateReportDate'].values == self.calculationRefinancingRateReportDate
        self.calculationRefinancingRate = self.refinancingRatesData['refinancingRate'].values[index][0]

        # ----- 6.24 СТИМУЛ К РЕФИНАНСИРОВАНИЮ -----
        self.incentiveToRefinance = np.round(self.wac - self.calculationRefinancingRate, 1)

        # ----- 6.25 ДАТА АКТУАЛЬНОСТИ S-КРИВОЙ -----
        self.calculationSCurveReportDate = None
        if self.usePricingDateDataOnly:
            date_a_1 = (self.pricingDate - np.timedelta64(15, 'D')).astype(m_type).astype(d_type)
            date_a_2 = self.sCurveParameters['sCurveReportDate'].values.max().astype(d_type)
            date_a = min(date_a_1, date_a_2)
            date_b = self.sCurveParameters['sCurveReportDate'].values.min().astype(d_type)
            self.calculationSCurveReportDate = max(date_a, date_b)
        else:
            self.calculationSCurveReportDate = self.sCurveParameters['sCurveReportDate'].values.max().astype(d_type)
        scurve_index = self.sCurveParameters['sCurveReportDate'] == self.calculationSCurveReportDate

        # ----- 6.26 BETA_HAT_0_a -----
        self.calculationSCurveBeta0 = self.sCurveParameters['sCurveBeta0'][scurve_index].values[0]

        # ----- 6.27 BETA_HAT_1_a -----
        self.calculationSCurveBeta1 = self.sCurveParameters['sCurveBeta1'][scurve_index].values[0]

        # ----- 6.28 BETA_HAT_2_a -----
        self.calculationSCurveBeta2 = self.sCurveParameters['sCurveBeta2'][scurve_index].values[0]

        # ----- 6.29 BETA_HAT_3_a -----
        self.calculationSCurveBeta3 = self.sCurveParameters['sCurveBeta3'][scurve_index].values[0]

        # ----- 6.30 CPR по S-кривой -----
        self.sCurveCPR = np.round((self.calculationSCurveBeta0 + self.calculationSCurveBeta1 * np.arctan(self.calculationSCurveBeta2 + self.calculationSCurveBeta3 * self.incentiveToRefinance)) * 100.0, 1)

        # ----- 6.31 ДАТА АКТУАЛЬНОСТИ ИСТОРИЧЕСКОГО CPR -----
        self.historicalCPRDate = None
        condition_1 = len(self.serviceReportsStatistics) >= 2
        if self.usePricingDateDataOnly:
            condition_2 = False
            if condition_1:
                condition_2 = self.pricingDate >= self.serviceReportsStatistics['serviceReportDate'].values[1] + np.timedelta64(15, 'D')
            if condition_1 and condition_2:
                index = self.serviceReportsStatistics['serviceReportDate'].values <= self.pricingDate - np.timedelta64(15, 'D')
                self.historicalCPRDate = self.serviceReportsStatistics['serviceReportDate'].values[index][-1].astype(d_type)
        else:
            if condition_1:
                self.historicalCPRDate = self.serviceReportsStatistics['serviceReportDate'].values.max().astype(d_type)

        # ----- 6.32 ИСТОРИЧЕСКИЙ CPR (СРЕДНЕЕ С ДАТЫ РАЗМЕЩЕНИЯ) -----
        self.historicalCPR = None
        if self.historicalCPRDate is not None:
            index = self.serviceReportsStatistics['serviceReportDate'].values == self.historicalCPRDate
            self.historicalCPR = np.round(self.serviceReportsStatistics['serviceReportHistoricalCPR'].values[index][0], 1)

        # ----- 6.33 ИСТОРИЧЕСКИЙ CPR (СРЕДНЕЕ ЗА 6 ПРЕДЫДУЩИХ МЕСЯЦЕВ) -----
        self.sixMonthsCPR = None
        if self.historicalCPRDate is not None:
            index = self.serviceReportsStatistics['serviceReportDate'].values == self.historicalCPRDate
            self.sixMonthsCPR = np.round(self.serviceReportsStatistics['serviceReportSixMonthsCPR'].values[index][0], 1)

        # ----- 6.34 ДАТА АКТУАЛЬНОСТИ ИСТОРИЧЕСКОГО CDR -----
        self.historicalCDRDate = None
        condition_1 = len(self.serviceReportsStatistics) >= 4
        if self.usePricingDateDataOnly:
            condition_2 = False
            if condition_1:
                condition_2 = self.pricingDate >= self.serviceReportsStatistics['serviceReportDate'].values[3] + np.timedelta64(15, 'D')
            if condition_1 and condition_2:
                index = self.serviceReportsStatistics['serviceReportDate'].values <= self.pricingDate - np.timedelta64(15, 'D')
                self.historicalCDRDate = self.serviceReportsStatistics['serviceReportDate'].values[index][-1].astype(d_type)
        else:
            if condition_1:
                self.historicalCDRDate = self.serviceReportsStatistics['serviceReportDate'].values.max().astype(d_type)

        # ----- 6.35 ИСТОРИЧЕСКИЙ CDR -----
        self.historicalCDR = None
        if self.historicalCDRDate is not None:
            index = self.serviceReportsStatistics['serviceReportDate'].values == self.historicalCDRDate
            self.historicalCDR = np.round(self.serviceReportsStatistics['serviceReportHistoricalCDR'].values[index][0], 1)

        # ----- 6.36 ДАТА АКТУАЛЬНОСТИ КОНВЕНЦИОНАЛЬНОГО CDR -----
        self.conventionalCDRDate = None
        condition_1 = self.poolCashflowStartPaymentPeriodDate == self.deliveryDate
        condition_2 = self.historicalCDRDate is None
        if condition_1 or condition_2:
            self.conventionalCDRDate = self.deliveryDate
        else:
            self.conventionalCDRDate = self.historicalCDRDate

        # ----- 6.37 КОНВЕНЦИОНАЛЬНЫЙ CDR -----
        self.conventionalCDR = None
        condition_1 = self.poolCashflowStartPaymentPeriodDate == self.deliveryDate
        condition_2 = self.historicalCDRDate is None
        if condition_1 or condition_2:
            self.conventionalCDR = self.initialExpectedCDR
        else:
            self.conventionalCDR = self.historicalCDR
        self.conventionalCDR = np.round(self.conventionalCDR, 1)

        # ----- 6.38 МОДЕЛЬНЫЙ CPR -----
        self.modelCPR = None
        if self.cpr is not None:
            self.modelCPR = self.cpr
        else:
            self.modelCPR = self.sCurveCPR
        self.modelCPR = np.round(self.modelCPR, 1)

        # ----- 6.39 МОДЕЛЬНЫЙ CDR -----
        self.modelCDR = None
        if self.cdr is not None:
            self.modelCDR = self.cdr
        else:
            self.modelCDR = self.conventionalCDR
        self.modelCDR = np.round(self.modelCDR, 1)

        # ----- 6.40 ПОМЕСЯЧНЫЙ CPR -----
        self.monthlyCPR = (1.0 - (1.0 - self.modelCPR / 100.0) ** (1.0 / 12.0)) * 100.0

        # ----- 6.41 ПОМЕСЯЧНЫЙ CDR -----
        self.monthlyCDR = (1.0 - (1.0 - self.modelCDR / 100.0) ** (1.0 / 12.0)) * 100.0

        # ДОПОЛНИТЕЛЬНЫЕ РАСЧЕТНЫЕ ПАРАМЕТРЫ, ЕСЛИ ТИП РАСЧЕТА КУПОННОЙ ВЫПЛАТЫ = 2 (ПЕРЕМЕННАЯ СТАВКА КУПОНА):
        self.firstCouponExpensesWithVAT = None
        self.otherCouponsExpensesWithVAT = None
        self.yieldCoeffientCPR = None
        self.yieldCoeffientCDR = None
        self.yieldCoeffientTotal = None

        if self.couponType == COUPON_TYPE.CHG:

            # ----- 6.42 ОПЛАТА УСЛУГ ПОРУЧИТЕЛЯ, СЕРВИСНОГО АГЕНТА И РЕЗЕРВНОГО СЕРВИСНОГО АГЕНТА (ПЕРВЫЙ КУПОН, С УЧЕТОМ НДС) -----
            self.firstCouponExpensesWithVAT = self.firstCouponExpensesIssueDoc * 0.8 + self.otherCouponsExpensesIssueDoc * 0.4

            # ----- 6.43 ОПЛАТА УСЛУГ ПОРУЧИТЕЛЯ, СЕРВИСНОГО АГЕНТА И РЕЗЕРВНОГО СЕРВИСНОГО АГЕНТА (ВТОРОЙ И ПОСЛЕДУЮЩИЙ КУПОНЫ, С УЧЕТОМ НДС) -----
            self.otherCouponsExpensesWithVAT = self.otherCouponsExpensesIssueDoc * 1.4 - self.firstCouponExpensesIssueDoc * 0.2

            # ----- 6.44 КОЭФФИЦИЕНТ ФАКТИЧЕСКИХ ПРОЦЕНТНЫХ ПОСТУПЛЕНИЙ В ЧАСТИ CPR -----
            if self.partialPrepaymentAllowedAnytime:
                self.yieldCoeffientCPR = self.monthlyCPR / 2.0
            else:
                self.yieldCoeffientCPR = (1.0 - (1.0 - max((self.modelCPR - 9.0) / 100.0, 0.0)) ** (1.0 / 12.0)) * 100.0 / 2.0

            # ----- 6.45 КОЭФФИЦИЕНТ ФАКТИЧЕСКИХ ПРОЦЕНТНЫХ ПОСТУПЛЕНИЙ В ЧАСТИ CDR -----
            self.yieldCoeffientCDR = self.monthlyCDR / 2.0

            # ----- 6.46 КОЭФФИЦИЕНТ ФАКТИЧЕСКИХ ПРОЦЕНТНЫХ ПОСТУПЛЕНИЙ -----
            self.yieldCoeffientTotal = self.yieldCoeffientCPR + self.yieldCoeffientCDR

        # ДОПОЛНИТЕЛЬНЫЕ РАСЧЕТНЫЕ ПАРАМЕТРЫ, ЕСЛИ ТИП РАСЧЕТА КУПОННОЙ ВЫПЛАТЫ = 3 (ПЛАВАЮЩАЯ СТАВКА КУПОНА):
        self.nextCouponKeyRateDate = None
        self.nextCouponKeyRate = None
        self.nextCouponKeyRatePlusPremiumValueRubles = None
        self.nextCouponKeyRatePlusPremiumValuePercents = None

        if self.couponType == COUPON_TYPE.FLT:

            # ----- 6.47 ДАТА, ПО СОСТОЯНИЮ НА КОТОРУЮ ДОЛЖНА БЫТЬ ВЗЯТА КЛЮЧЕВАЯ СТАВКА ДЛЯ РАСЧЕТА КУПОННОЙ ВЫПЛАТЫ В СЛЕДУЮЩУЮ ПОСЛЕ ДАТЫ ОЦЕНКИ ДАТУ КУПОННОЙ ВЫПЛАТЫ -----
            if self.nextCouponDate == self.firstCouponDate:
                self.nextCouponKeyRateDate = self.deliveryDate.astype(m_type).astype(d_type)
            else:
                self.nextCouponKeyRateDate = (self.nextCouponDate.astype(m_type) - np.timedelta64(self.couponPeriod + self.paymentPeriodLag, 'M')).astype(d_type)

            # ----- 6.48 ЗНАЧЕНИЕ КЛЮЧЕВОЙ СТАВКИ, КОТОРОЕ ИСПОЛЬЗУЕТСЯ ПРИ РАСЧЕТЕ КУПОННОЙ ВЫПЛАТЫ В СЛЕДУЮЩУЮ ПОСЛЕ ДАТЫ ОЦЕНКИ ДАТУ КУПОННОЙ ВЫПЛАТЫ -----
            index = self.keyRatesData['keyRateReportDate'].values == self.nextCouponKeyRateDate
            if True in index:
                self.nextCouponKeyRate = self.keyRatesData['keyRate'].values[index][0]
            else:
                raise Exception(EXCEPTIONS.NO_KEY_RATE_VALUE.format(self.nextCouponKeyRateDate))

            # ----- 6.49 СЛЕДУЮЩАЯ ПОСЛЕ ДАТЫ ОЦЕНКИ КУПОННАЯ ВЫПЛАТА (КЛЮЧЕВАЯ СТАВКА + ФИКСИРОВАННАЯ НАДБАВКА) В РУБЛЯХ -----
            index = self.couponDatesSeries['allCouponDates'].values == self.nextCouponDate
            number_of_days = self.couponDatesSeries['couponPeriodsDays'].values[index][0]
            self.nextCouponKeyRatePlusPremiumValueRubles = np.round(self.currentBondPrincipal * (self.nextCouponKeyRate + self.fixedKeyRatePremium) / 100.0 * number_of_days / 365.0, 2)

            # ----- 6.50 СЛЕДУЮЩАЯ ПОСЛЕ ДАТЫ ОЦЕНКИ КУПОННАЯ ВЫПЛАТА (КЛЮЧЕВАЯ СТАВКА + ФИКСИРОВАННАЯ НАДБАВКА) В % ГОДОВЫХ -----
            self.nextCouponKeyRatePlusPremiumValuePercents = np.round(self.nextCouponKeyRatePlusPremiumValueRubles / self.currentBondPrincipal * 365.0 / number_of_days * 100.0, 2)

        # ----------------------------------------------------------------------------------- #
        # -------------------------------- СОЗДАНИЕ ИНСТАНСОВ ------------------------------- #
        # ----------------------------------------------------------------------------------- #

        self.poolCashflow = pd.DataFrame({})
        self.mbsCashflow = pd.DataFrame({})

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

        self.calculationOutput = {}
        self.calculatedParameters = {}
        self.mbsCashflowTable = {}
        self.historicalCashflow = {}
        self.mbsCashflowGraph = {}
        self.zcycGraph = {}
        self.sCurveEmpiricalData = {}
        self.sCurveGraph = {}

    def poolCashflowModel(self):

        # ----------------------------------------------------------------------------------- #
        # ------------------- 7. РАСЧЕТ ДЕНЕЖНОГО ПОТОКА ПО ПУЛУ ЗАКЛАДНЫХ ------------------ #
        # ----------------------------------------------------------------------------------- #

        # ----- 7.1 ВРЕМЕННОЙ РЯД МЕСЯЦЕВ МОДЕЛЬНОГО ДЕНЕЖНОГО ПОТОКА ПО ПУЛУ ЗАКЛАДНЫХ -----
        start_range = self.poolCashflowStartDate.astype(m_type)
        end_range = self.poolCashflowEndDate.astype(m_type) + np.timedelta64(1, 'M')
        step = np.timedelta64(1, 'M')
        self.poolCashflow['poolCashflowMonths'] = np.arange(start_range, end_range, step).astype(d_type)
        n = len(self.poolCashflow)

        # ----- 7.2 КОЛИЧЕСТВО ДНЕЙ В МЕСЯЦЕ -----
        self.poolCashflow['monthDays'] = [((date.astype(m_type) + np.timedelta64(1, 'M')).astype(d_type) - date) / np.timedelta64(1, 'D') for date in self.poolCashflow['poolCashflowMonths'].values]

        # ----- 7.3 КОЛИЧЕСТВО ДНЕЙ В ГОДУ -----
        self.poolCashflow['yearDays'] = [float((dt.date(date.year + 1, 1, 1) - dt.date(date.year, 1, 1)).days) for date in pd.to_datetime(self.poolCashflow['poolCashflowMonths'].values)]

        # ----- 7.4 СООТНОШЕНИЕ МЕЖДУ ДАТАМИ КУПОННЫХ ВЫПЛАТ И МЕСЯЦАМИ МОДЕЛЬНОГО ДЕНЕЖНОГО ПОТОКА ПО ПУЛУ ЗАКЛАДНЫХ -----
        self.poolCashflow['couponDatesCorrespondence'] = np.datetime64('NaT')
        self.poolCashflow.loc[0, 'couponDatesCorrespondence'] = self.poolCashflowStartCouponDate
        for l in range(1, n):

            current_month = self.poolCashflow['poolCashflowMonths'].values[l]
            previous_coupon_date = self.poolCashflow['couponDatesCorrespondence'].values[l - 1]

            condition_1 = current_month == self.poolCashflowEndDate
            condition_2 = (current_month.astype(m_type) + np.timedelta64(1 + self.paymentPeriodLag, 'M')).astype(d_type) < previous_coupon_date
            condition_3 = previous_coupon_date == self.legalRedemptionDate

            if condition_1 or condition_2 or condition_3:
                self.poolCashflow.loc[l, 'couponDatesCorrespondence'] = previous_coupon_date
            else:
                next_coupon_date = self.allCouponDates[self.allCouponDates > previous_coupon_date][0]
                self.poolCashflow.loc[l, 'couponDatesCorrespondence'] = next_coupon_date

        # ----- 7.5 ВРЕМЕННОЙ РЯД ЗНАЧЕНИЙ WAM НА НАЧАЛО МЕСЯЦА -----
        self.poolCashflow['wamSeries'] = np.array([self.adjustedWAM] * n) - np.arange(0, n, step=1) * self.wamCoefficient

        # ----- 7.6 МОДЕЛЬНЫЙ ДЕНЕЖНЫЙ ПОТОК ПО ПУЛУ ЗАКЛАДНЫХ ЗА МЕСЯЦ l -----
        for l in range(0, n):

            # ----- 7.6.1 СУММА ОСТАТКОВ ОСНОВНОГО ДОЛГА ПО КРЕДИТАМ В ПУЛЕ НА НАЧАЛО МЕСЯЦА l -----
            if l == 0:
                self.poolCashflow.loc[l, 'poolStartMonthDebt'] = self.poolCashflowStartDebt
            else:
                previous_debt = self.poolCashflow['poolStartMonthDebt'].values[l - 1]
                previous_total_amort = self.poolCashflow['poolTotalAmortization'].values[l - 1]
                self.poolCashflow.loc[l, 'poolStartMonthDebt'] = np.round(previous_debt - previous_total_amort, 2)

            # ----- 7.6.2 СУММА ЕЖЕМЕСЯЧНЫХ ПЛАТЕЖЕЙ ПО ПУЛУ ЗА МЕСЯЦ l -----
            current_debt = self.poolCashflow['poolStartMonthDebt'].values[l]
            current_WAM = self.poolCashflow['wamSeries'].values[l]
            annuity_factor = (self.wac / 1200.0 * (1 + self.wac / 1200.0) ** current_WAM) / ((1 + self.wac / 1200.0) ** current_WAM - 1.0)
            self.poolCashflow.loc[l, 'poolScheduledPayment'] = np.round(current_debt * annuity_factor, 2)

            # ----- 7.6.3 ПРОЦЕНТНЫЕ ПОСТУПЛЕНИЯ ПО ГРАФИКУ ПО ПУЛУ ЗА МЕСЯЦ l -----
            month_days = self.poolCashflow['monthDays'].values[l]
            year_days = self.poolCashflow['yearDays'].values[l]
            self.poolCashflow.loc[l, 'poolScheduledYield'] = np.round(current_debt * self.wac / 100.0 * month_days / year_days, 2)

            # ----- 7.6.4 ОЖИДАЕМЫЕ ПОГАШЕНИЯ ОСНОВНОГО ДОЛГА ПО ГРАФИКУ ПО ПУЛУ ЗА МЕСЯЦ l -----
            current_payment = self.poolCashflow['poolScheduledPayment'].values[l]
            current_yield = self.poolCashflow['poolScheduledYield'].values[l]
            self.poolCashflow.loc[l, 'poolScheduledAmortization'] = np.round(current_payment - current_yield, 2)

            # ----- 7.6.5 ФАКТИЧЕСКИЕ ПОГАШЕНИЯ ОСНОВНОГО ДОЛГА ПО ГРАФИКУ ПО ПУЛУ ЗА МЕСЯЦ l -----
            current_sch_amort = self.poolCashflow['poolScheduledAmortization'].values[l]
            self.poolCashflow.loc[l, 'poolActualScheduledAmortization'] = np.round(min(current_debt, current_sch_amort * (1.0 - self.monthlyCDR / 100.0 * 3.0)), 2)

            # ----- 7.6.6 ДОСРОЧНЫЕ ПОГАШЕНИЯ ОСНОВНОГО ДОЛГА ПО ПУЛУ ЗА МЕСЯЦ l -----
            self.poolCashflow.loc[l, 'poolPrepayment'] = np.round(max(0.0, (current_debt - current_sch_amort) * self.monthlyCPR / 100.0), 2)

            # ----- 7.6.7 ВЫКУПЫ ДЕФОЛТНЫХ ЗАКЛАДНЫХ ПО ПУЛУ ЗА МЕСЯЦ l -----
            self.poolCashflow.loc[l, 'poolDefaultsBuyout'] = np.round(max(0.0, (current_debt - current_sch_amort) * self.monthlyCDR / 100.0), 2)

            # ----- 7.6.8 ПОГАШЕНИЯ ПО ПУЛУ ЗА МЕСЯЦ l -----
            current_act_sch_amort = self.poolCashflow['poolActualScheduledAmortization'].values[l]
            current_prepayment = self.poolCashflow['poolPrepayment'].values[l]
            current_def_buyout = self.poolCashflow['poolDefaultsBuyout'].values[l]
            self.poolCashflow.loc[l, 'poolTotalAmortization'] = np.round(current_act_sch_amort + current_prepayment + current_def_buyout, 2)

            # ----- 7.6.9 ФАКТИЧЕСКИЕ ПРОЦЕНТНЫЕ ПОСТУПЛЕНИЯ ПО ПУЛУ ЗА МЕСЯЦ l -----
            if self.couponType == COUPON_TYPE.CHG:
                if l == 0 and self.poolCashflow['couponDatesCorrespondence'].values[l] == self.firstCouponDate:
                    month_days = self.deliveryMonthAccrualDays
                self.poolCashflow.loc[l, 'poolActualYield'] = np.round(current_debt * (1.0 - self.yieldCoeffientTotal / 100.0) * self.wac / 100.0 * month_days / year_days, 2)

    def mbsCashflowModel(self):

        # ----------------------------------------------------------------------------------- #
        # --------------------- 8. РАСЧЕТ ДЕНЕЖНОГО ПОТОКА ПО ИЦБ ДОМ.РФ -------------------- #
        # ----------------------------------------------------------------------------------- #

        self.mbsCashflow['futureCouponDates'] = np.datetime64('NaT')

        # [ТЕХНИЧЕСКАЯ ПЕРЕМЕННАЯ]
        maximum_possible_coupon_date = max(self.poolCashflow['couponDatesCorrespondence'].values).astype(d_type)

        m = 0
        while True:

            # ----- 8.1 БУДУЩАЯ ДАТА КУПОННОЙ ВЫПЛАТЫ -----

            if m == 0:
                self.mbsCashflow.loc[m, 'futureCouponDates'] = self.nextCouponDate
            else:
                previous_coupon_date = self.mbsCashflow['futureCouponDates'].values[m - 1].astype(d_type)
                mbs_previous_principal = self.mbsCashflow['bondPrincipalStartPeriod'].values[m - 1]
                mbs_previous_actual_amort = self.mbsCashflow['bondFutureActualAmortization'].values[m - 1]
                condition_1 = previous_coupon_date == maximum_possible_coupon_date
                condition_2 = mbs_previous_principal < self.cleanUpRubles
                condition_3 = mbs_previous_principal == mbs_previous_actual_amort
                if condition_1 or condition_2 or condition_3:
                    break
                else:
                    self.mbsCashflow.loc[m, 'futureCouponDates'] = self.allCouponDates[self.allCouponDates > previous_coupon_date][0]

            # [ТЕХНИЧЕСКИЕ ПЕРЕМЕННЫЕ]
            current_coupon_date = self.mbsCashflow['futureCouponDates'].values[m].astype(d_type)
            pool_correspondence = self.poolCashflow['couponDatesCorrespondence'] == current_coupon_date
            is_first_coupon_date = current_coupon_date == self.firstCouponDate

            # ----- 8.2 ИНДИКАТОР ИСПОЛЬЗОВАНИЯ ДАННЫХ ОТЧЕТОВ ДЛЯ ИНВЕСТОРОВ ИЦБ ДОМ.РФ ДЛЯ БУДУЩЕЙ ДАТЫ КУПОННОЙ ВЫПЛАТЫ m -----
            self.mbsCashflow.loc[m, 'useInvestorsReports'] = False
            condition = current_coupon_date < self.poolCashflowStartCouponDate
            if condition:
                self.mbsCashflow.loc[m, 'useInvestorsReports'] = True

            # ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА, НЕОБХОДИМАЯ, ЕСЛИ БУДУЩАЯ ДАТА КУПОННОЙ ВЫПЛАТЫ РАВНА ФАКТИЧЕСКОЙ ДАТЕ ПОГАШЕНИЯ ИЛИ ЮРИДИЧЕСКОЙ ДАТЕ ПОГАШЕНИЯ
            check_1 = False
            if self.actualRedemptionDate is not None:
                check_1 = current_coupon_date == self.actualRedemptionDate
            check_2 = current_coupon_date == self.legalRedemptionDate
            if check_1 or check_2:
                condition_1 = self.maximumCouponDateWithKnownPayment is not None
                condition_2_1 = False
                if self.actualRedemptionDate is not None:
                    condition_2_1 = self.actualRedemptionDate == self.maximumCouponDateWithKnownPayment
                condition_2_2 = self.legalRedemptionDate == self.maximumCouponDateWithKnownPayment
                condition_2 = condition_2_1 or condition_2_2
                condition_3 = not self.usePricingDateDataOnly or float((current_coupon_date - self.pricingDate) / np.timedelta64(1, 'D')) <= 12
                if condition_1 and condition_2 and condition_3:
                    self.mbsCashflow.loc[m, 'useInvestorsReports'] = True

            # [ТЕХНИЧЕСКАЯ ПЕРЕМЕННАЯ]
            use_investors_reports = self.mbsCashflow['useInvestorsReports'].values[m]

            # ----- 8.3 КОЛИЧЕСТВО ДНЕЙ В КУПОННОМ ПЕРИОДЕ БУДУЩЕЙ ДАТЫ КУПОННОЙ ВЫПЛАТЫ m -----
            index = self.couponDatesSeries['allCouponDates'].values == current_coupon_date
            coupon_days = float(self.couponDatesSeries['couponPeriodsDays'].values[index][0])
            self.mbsCashflow.loc[m, 'futureCouponPeriodsDays'] = coupon_days

            # ----- 8.4 НЕПОГАШЕННЫЙ НОМИНАЛ ОБЛИГАЦИИ ДО БУДУЩЕЙ ДАТЫ КУПОННОЙ ВЫПЛАТЫ m -----
            if m == 0:
                self.mbsCashflow.loc[m, 'bondPrincipalStartPeriod'] = self.currentBondPrincipal
            else:
                mbs_previous_principal = self.mbsCashflow['bondPrincipalStartPeriod'].values[m - 1]
                mbs_previous_amort = self.mbsCashflow['bondFutureAmortization'].values[m - 1]
                self.mbsCashflow.loc[m, 'bondPrincipalStartPeriod'] = np.round(mbs_previous_principal - mbs_previous_amort, 2)

            # [ТЕХНИЧЕСКАЯ ПЕРЕМЕННАЯ]
            mbs_current_principal = self.mbsCashflow['bondPrincipalStartPeriod'].values[m]

            # ----- 8.5 ПОГАШЕНИЕ НОМИНАЛА ОБЛИГАЦИИ СОГЛАСНО ДАННЫМ ОТЧЕТОВ ДЛЯ ИНВЕСТОРОВ ИЦБ ДОМ.РФ В БУДУЩУЮ ДАТУ КУПОННОЙ ВЫПЛАТЫ m -----
            self.mbsCashflow.loc[m, 'bondFutureActualAmortization'] = None
            if use_investors_reports:
                index = self.investorsReportsData['investorsReportCouponDate'] == current_coupon_date
                amortization = self.investorsReportsData['investorsReportBondAmortization'].values[index][0]
                self.mbsCashflow.loc[m, 'bondFutureActualAmortization'] = amortization

            # ----- 8.6 МОДЕЛЬНОЕ ПОГАШЕНИЕ НОМИНАЛА ОБЛИГАЦИИ (В ЧАСТИ ПОГАШЕНИЙ ПО ГРАФИКУ) В БУДУЩУЮ ДАТУ КУПОННОЙ ВЫПЛАТЫ m -----
            self.mbsCashflow.loc[m, 'bondFutureModelScheduled'] = None
            pool_total_amort = self.poolCashflow['poolTotalAmortization'].values[pool_correspondence].sum()
            pool_actual_sched = self.poolCashflow['poolActualScheduledAmortization'].values[pool_correspondence].sum()
            if not use_investors_reports:
                if is_first_coupon_date:
                    self.mbsCashflow.loc[m, 'bondFutureModelScheduled'] = round_floor(((self.startIssuePrincipal - (self.deliveryDebtAmount - pool_total_amort)) * pool_actual_sched / pool_total_amort) / self.numberOfBonds, 2)
                else:
                    self.mbsCashflow.loc[m, 'bondFutureModelScheduled'] = round_floor(pool_actual_sched / self.numberOfBonds, 2)

            # ----- 8.7 МОДЕЛЬНОЕ ПОГАШЕНИЕ НОМИНАЛА ОБЛИГАЦИИ (В ЧАСТИ ДОСРОЧНЫХ ПОГАШЕНИЙ) В БУДУЩУЮ ДАТУ КУПОННОЙ ВЫПЛАТЫ m -----
            self.mbsCashflow.loc[m, 'bondFutureModelPrepayment'] = None
            pool_prepayment = self.poolCashflow['poolPrepayment'].values[pool_correspondence].sum()
            if not use_investors_reports:
                if is_first_coupon_date:
                    self.mbsCashflow.loc[m, 'bondFutureModelPrepayment'] = round_floor(((self.startIssuePrincipal - (self.deliveryDebtAmount - pool_total_amort)) * pool_prepayment / pool_total_amort) / self.numberOfBonds, 2)
                else:
                    self.mbsCashflow.loc[m, 'bondFutureModelPrepayment'] = round_floor(pool_prepayment / self.numberOfBonds, 2)

            # ----- 8.8 МОДЕЛЬНОЕ ПОГАШЕНИЕ НОМИНАЛА ОБЛИГАЦИИ (В ЧАСТИ ВЫКУПОВ ДЕФОЛТНЫХ ЗАКЛАДНЫХ) В БУДУЩУЮ ДАТУ КУПОННОЙ ВЫПЛАТЫ m -----
            self.mbsCashflow.loc[m, 'bondFutureModelDefaults'] = None
            mbs_actual_sched = self.mbsCashflow['bondFutureModelScheduled'].values[m]
            mbs_prepayment = self.mbsCashflow['bondFutureModelPrepayment'].values[m]
            if not use_investors_reports:
                if is_first_coupon_date:
                    self.mbsCashflow.loc[m, 'bondFutureModelDefaults'] = round_floor((self.startIssuePrincipal - (self.deliveryDebtAmount - pool_total_amort)) / self.numberOfBonds - mbs_actual_sched - mbs_prepayment, 2)
                else:
                    self.mbsCashflow.loc[m, 'bondFutureModelDefaults'] = round_floor(pool_total_amort / self.numberOfBonds - mbs_actual_sched - mbs_prepayment, 2)

            # ----- 8.9 МОДЕЛЬНОЕ ПОГАШЕНИЕ НОМИНАЛА ОБЛИГАЦИИ (ОПЦИОН CLEAN-UP) В БУДУЩУЮ ДАТУ КУПОННОЙ ВЫПЛАТЫ m -----
            self.mbsCashflow.loc[m, 'bondFutureModelCleanUp'] = None
            if not use_investors_reports:
                condition_1 = current_coupon_date == maximum_possible_coupon_date
                condition_2 = mbs_current_principal < self.cleanUpRubles
                self.mbsCashflow.loc[m, 'bondFutureModelCleanUp'] = 0.0
                if condition_1 or condition_2:
                    mbs_actual_sched = self.mbsCashflow['bondFutureModelScheduled'].values[m]
                    mbs_prepayment = self.mbsCashflow['bondFutureModelPrepayment'].values[m]
                    mbs_def_buyout = self.mbsCashflow['bondFutureModelDefaults'].values[m]
                    self.mbsCashflow.loc[m, 'bondFutureModelCleanUp'] = np.round(mbs_current_principal - mbs_actual_sched - mbs_prepayment - mbs_def_buyout, 2)

            # ----- 8.10  КУПОННАЯ ВЫПЛАТА ПО ОБЛИГАЦИИ СОГЛАСНО ДАННЫМ ОТЧЕТОВ ДЛЯ ИНВЕСТОРОВ ИЦБ ДОМ.РФ В БУДУЩУЮ ДАТУ КУПОННОЙ ВЫПЛАТЫ m -----
            self.mbsCashflow.loc[m, 'bondFutureActualCouponPayments'] = None
            if use_investors_reports and self.couponType != COUPON_TYPE.FLT:
                index = self.investorsReportsData['investorsReportCouponDate'] == current_coupon_date
                coupon_payment = self.investorsReportsData['investorsReportBondCouponPayment'].values[index][0]
                self.mbsCashflow.loc[m, 'bondFutureActualCouponPayments'] = coupon_payment

            # ----- 8.11  МОДЕЛЬНАЯ КУПОННАЯ ВЫПЛАТА В БУДУЩУЮ ДАТУ КУПОННОЙ ВЫПЛАТЫ m -----
            self.mbsCashflow.loc[m, 'bondFutureModelCouponPayments'] = None
            if not use_investors_reports:

                if self.couponType == COUPON_TYPE.FXD:
                    coupon_rate = self.fixedCouponRate
                    if self.calculationType == CALCULATION_TYPE.SET_COUPN:
                        coupon_rate = self.couponRate
                    self.mbsCashflow.loc[m, 'bondFutureModelCouponPayments'] = np.round(mbs_current_principal * coupon_rate / 100.0 * coupon_days / 365.0, 2)

                elif self.couponType == COUPON_TYPE.CHG:
                    pool_actual_yield = self.poolCashflow['poolActualYield'].values[pool_correspondence].sum()
                    expenses = self.firstCouponExpensesWithVAT if is_first_coupon_date else self.otherCouponsExpensesWithVAT
                    issue_payment = pool_actual_yield - mbs_current_principal * self.numberOfBonds * expenses / 100.0 * coupon_days / 365.0
                    issue_payment -= max(mbs_current_principal * self.numberOfBonds * self.specDepRateIssueDoc / 100.0 * coupon_days / 365.0, self.specDepMinMonthIssueDoc * float(self.couponPeriod))
                    issue_payment -= self.specDepCompensationMonthIssueDoc * float(self.couponPeriod)
                    issue_payment -= 2 * (mbs_current_principal * self.numberOfBonds * self.manAccQuartRateIssueDoc / 100.0 + self.manAccQuartFixIssueDoc) * float(self.couponPeriod) / 3.0
                    issue_payment -= self.paymentAgentYearIssueDoc * float(self.couponPeriod) / 12.0
                    self.mbsCashflow.loc[m, 'bondFutureModelCouponPayments'] = round_floor(issue_payment / self.numberOfBonds, 2)

            # ----- 8.12  ПОГАШЕНИЕ НОМИНАЛА ОБЛИГАЦИИ В БУДУЩУЮ ДАТУ КУПОННОЙ ВЫПЛАТЫ m -----
            self.mbsCashflow.loc[m, 'bondFutureAmortization'] = None
            if use_investors_reports:
                self.mbsCashflow.loc[m, 'bondFutureAmortization'] = self.mbsCashflow['bondFutureActualAmortization'].values[m]
            else:
                mbs_actual_sched = self.mbsCashflow['bondFutureModelScheduled'].values[m]
                mbs_prepayment = self.mbsCashflow['bondFutureModelPrepayment'].values[m]
                mbs_def_buyout = self.mbsCashflow['bondFutureModelDefaults'].values[m]
                mbs_clean_up = self.mbsCashflow['bondFutureModelCleanUp'].values[m]
                self.mbsCashflow.loc[m, 'bondFutureAmortization'] = np.round(mbs_actual_sched + mbs_prepayment + mbs_def_buyout + mbs_clean_up, 2)

            # ----- 8.13  КУПОННАЯ ВЫПЛАТА ПО ОБЛИГАЦИИ В БУДУЩУЮ ДАТУ КУПОННОЙ ВЫПЛАТЫ m -----
            self.mbsCashflow.loc[m, 'bondFutureCouponPayments'] = None
            if self.couponType in [COUPON_TYPE.FXD, COUPON_TYPE.CHG]:
                if use_investors_reports:
                    self.mbsCashflow.loc[m, 'bondFutureCouponPayments'] = self.mbsCashflow['bondFutureActualCouponPayments'].values[m]
                else:
                    self.mbsCashflow.loc[m, 'bondFutureCouponPayments'] = self.mbsCashflow['bondFutureModelCouponPayments'].values[m]

            # ----- 8.14  КУПОННАЯ ВЫПЛАТА ПО ОБЛИГАЦИИ В БУДУЩУЮ ДАТУ КУПОННОЙ ВЫПЛАТЫ m В % ГОДОВЫХ -----
            self.mbsCashflow.loc[m, 'bondFutureCouponPaymentsPercents'] = None
            if self.couponType in [COUPON_TYPE.FXD, COUPON_TYPE.CHG]:
                coupon_payment = self.mbsCashflow['bondFutureCouponPayments'].values[m]
                self.mbsCashflow.loc[m, 'bondFutureCouponPaymentsPercents'] = np.round(coupon_payment / mbs_current_principal * 365.0 / coupon_days * 100.0, 2)

            # ----- 8.15  ДЕНЕЖНЫЙ ПОТОК ПО ОБЛИГАЦИИ В БУДУЩУЮ ДАТУ КУПОННОЙ ВЫПЛАТЫ m -----
            self.mbsCashflow.loc[m, 'bondFutureCashflow'] = None
            if self.couponType in [COUPON_TYPE.FXD, COUPON_TYPE.CHG]:
                coupon_payment = self.mbsCashflow['bondFutureCouponPayments'].values[m]
                amortization = self.mbsCashflow['bondFutureAmortization'].values[m]
                self.mbsCashflow.loc[m, 'bondFutureCashflow'] = np.round(amortization + coupon_payment, 2)

            # ----- 8.16  ВЫПЛАТА НАДБАВКИ К КЛЮЧЕВОЙ СТАВКЕ ПО ОБЛИГАЦИИ В БУДУЩУЮ ДАТУ КУПОННОЙ ВЫПЛАТЫ m -----
            self.mbsCashflow.loc[m, 'bondFuturePremiumPayments'] = None
            if self.couponType == COUPON_TYPE.FLT:
                self.mbsCashflow.loc[m, 'bondFuturePremiumPayments'] = np.round(mbs_current_principal * self.fixedKeyRatePremium / 100.0 * coupon_days / 365.0, 2)

            # ----- 8.17  ВЫПЛАТА ТРЕБУЕМОЙ НАДБАВКИ К КЛЮЧЕВОЙ СТАВКЕ ПО ОБЛИГАЦИИ В БУДУЩУЮ ДАТУ КУПОННОЙ ВЫПЛАТЫ m -----
            self.mbsCashflow.loc[m, 'bondFutureRequiredPremiumPayments'] = None
            if self.couponType == COUPON_TYPE.FLT and self.calculationType == CALCULATION_TYPE.SET_PREMI:
                self.mbsCashflow.loc[m, 'bondFutureRequiredPremiumPayments'] = np.round(mbs_current_principal * self.requiredKeyRatePremium / 10000.0 * coupon_days / 365.0, 2)

            m += 1

    def mbsPricing(self):

        # ----------------------------------------------------------------------------------- #
        # ----------------------- 9. РАСЧЕТ ЦЕНОВЫХ МЕТРИК ИЦБ ДОМ.РФ ----------------------- #
        # ----------------------------------------------------------------------------------- #

        # ----- 9.1  КОЛИЧЕСТВО ЛЕТ МЕЖДУ ДАТОЙ ОЦЕНКИ И БУДУЩЕЙ ДАТОЙ ВЫПЛАТЫ КУПОНА m -----
        self.yearsToCouponDate = (self.mbsCashflow['futureCouponDates'].values - self.pricingDate) / np.timedelta64(1, 'D') / 365.0

        # ----- 9.2  СПОТ-ДОХОДНОСТЬ КБД С ГОДОВОЙ КАПИТАЛИЗАЦИЕЙ ПРОЦЕНТОВ -----
        self.zcycValuesY = Y(self.zcycParameters, self.yearsToCouponDate)

        # ----- 9.3  ФАКТОР ДИСКОНТИРОВАНИЯ ПО КБД С Z-СПРЕДОМ -----
        self.discountFactorZCYCPlusZ = lambda Z: (1.0 + self.zcycValuesY / 10000.0 + Z / 10000.0) ** -self.yearsToCouponDate

        # ----- 9.4  ФАКТОР ДИСКОНТИРОВАНИЯ ПО YTM -----
        self.discountFactorYTM = lambda YTM: (1.0 + YTM / 100.0) ** -self.yearsToCouponDate

        # ----- 9.5  НАКОПЛЕННЫЙ КУПОННЫЙ ДОХОД (НКД) -----
        if self.couponType in [COUPON_TYPE.FXD, COUPON_TYPE.CHG]:
            next_coupon_in_percents = self.mbsCashflow['bondFutureCouponPaymentsPercents'].values[0]
            self.accruedCouponInterest = next_coupon_in_percents * self.daysPassedInCurrentCouponPeriod / 365.0
        else:
            self.accruedCouponInterest = self.nextCouponKeyRatePlusPremiumValuePercents * self.daysPassedInCurrentCouponPeriod / 365.0

        # [СОКРАЩЕНИЯ]
        t, cf = self.yearsToCouponDate, self.mbsCashflow['bondFutureCashflow'].values
        # [ТЕХНИЧЕСКАЯ ФУНКЦИЯ РАСЧЕТА ДЮРАЦИИ МАКОЛЕЯ]
        self.durationMacaulay_func = lambda YTM: max(0.001, (t * cf * self.discountFactorYTM(YTM)).sum() / (cf * self.discountFactorYTM(YTM)).sum())

        # ----- 9.6 ГРЯЗНАЯ ЦЕНА -----
        if self.calculationType == CALCULATION_TYPE.SET_ZSPRD:
            self.dirtyPrice = (self.discountFactorZCYCPlusZ(self.zSpread) * cf).sum() / self.currentBondPrincipal * 100.0

        elif self.calculationType == CALCULATION_TYPE.SET_GSPRD:
            self.ytm = minimize(lambda YTM: (self.gSpread - YTM * 100.0 + Y(self.zcycParameters, self.durationMacaulay_func(YTM))) ** 2.0, np.array([0.0])).x[0]
            self.dirtyPrice = (self.discountFactorYTM(self.ytm) * cf).sum() / self.currentBondPrincipal * 100.0

        elif self.calculationType == CALCULATION_TYPE.SET_DIRTY:
            pass

        elif self.calculationType == CALCULATION_TYPE.SET_CLEAN:
            self.dirtyPrice = self.cleanPrice + self.accruedCouponInterest

        elif self.calculationType == CALCULATION_TYPE.SET_PREMI:
            prem_act = self.mbsCashflow['bondFuturePremiumPayments'].values
            prem_req = self.mbsCashflow['bondFutureRequiredPremiumPayments'].values
            self.dirtyPrice = 100.0 + ((prem_act - prem_req) * self.discountFactorZCYCPlusZ(self.requiredKeyRatePremium)).sum() / self.currentBondPrincipal * 100.0 + self.accruedCouponInterest

        elif self.calculationType == CALCULATION_TYPE.SET_COUPN:
            self.dirtyPrice = 100.0

        # ----- 9.7 ЧИСТАЯ ЦЕНА -----
        if self.calculationType != CALCULATION_TYPE.SET_CLEAN:
            self.cleanPrice = self.dirtyPrice - self.accruedCouponInterest

        # ----- 9.8 НАКОПЛЕННЫЙ КУПОННЫЙ ДОХОД (НКД) В РУБЛЯХ -----
        self.accruedCouponInterestRub = np.round(self.accruedCouponInterest / 100.0 * self.currentBondPrincipal, 2)

        # ----- 9.9 ГРЯЗНАЯ ЦЕНА В РУБЛЯХ -----
        self.dirtyPriceRub = np.round(self.dirtyPrice / 100.0 * self.currentBondPrincipal, 2)

        # ----- 9.10 ЧИСТАЯ ЦЕНА В РУБЛЯХ -----
        self.cleanPriceRub = np.round(self.dirtyPriceRub - self.accruedCouponInterestRub, 2)

        # ----- 9.11 ДОХОДНОСТЬ К ПОГАШЕНИЮ -----
        if self.couponType in [COUPON_TYPE.FXD, COUPON_TYPE.CHG]:

            if self.calculationType in [CALCULATION_TYPE.SET_ZSPRD, CALCULATION_TYPE.SET_DIRTY, CALCULATION_TYPE.SET_CLEAN, CALCULATION_TYPE.SET_COUPN]:
                self.ytm = minimize(lambda YTM: ((cf * self.discountFactorYTM(YTM)).sum() / self.currentBondPrincipal * 10000.0 - self.dirtyPrice * 100.0) ** 2.0, np.array([0.0])).x[0]

            elif self.calculationType == CALCULATION_TYPE.SET_GSPRD:
                pass  # YTM УЖЕ ОПРЕДЕЛЕНА НА ЭТАПЕ ОПРЕДЕЛЕНИЯ ГРЯЗНОЙ ЦЕНЫ

        elif self.couponType == COUPON_TYPE.FLT:
            pass

        # ----- 9.12 Z-СПРЕД -----
        if self.couponType in [COUPON_TYPE.FXD, COUPON_TYPE.CHG]:

            if self.calculationType == CALCULATION_TYPE.SET_ZSPRD:
                pass

            elif self.calculationType in [CALCULATION_TYPE.SET_GSPRD, CALCULATION_TYPE.SET_DIRTY, CALCULATION_TYPE.SET_CLEAN, CALCULATION_TYPE.SET_COUPN]:
                self.zSpread = minimize(lambda Z: ((cf * self.discountFactorZCYCPlusZ(Z)).sum() / self.currentBondPrincipal * 10000.0 - self.dirtyPrice * 100.0) ** 2.0, np.array([0.0])).x[0]

        elif self.couponType == COUPON_TYPE.FLT:
            pass

        # ----- 9.13 G-СПРЕД -----
        if self.couponType in [COUPON_TYPE.FXD, COUPON_TYPE.CHG]:

            if self.calculationType in [CALCULATION_TYPE.SET_ZSPRD, CALCULATION_TYPE.SET_DIRTY, CALCULATION_TYPE.SET_CLEAN, CALCULATION_TYPE.SET_COUPN]:
                self.gSpread = self.ytm * 100.0 - Y(self.zcycParameters, self.durationMacaulay_func(self.ytm))

            elif self.calculationType == CALCULATION_TYPE.SET_GSPRD:
                pass

        elif self.couponType == COUPON_TYPE.FLT:
            pass

        # ----- 9.14 ТРЕБУЕМАЯ ФИКСИРОВАННАЯ НАДБАВКА К КЛЮЧЕВОЙ СТАВКЕ -----
        if self.couponType == COUPON_TYPE.FLT:

            if self.calculationType in [CALCULATION_TYPE.SET_DIRTY, CALCULATION_TYPE.SET_CLEAN]:
                prem_act = self.mbsCashflow['bondFuturePremiumPayments'].values
                prem_req = lambda prm: np.round(self.mbsCashflow['bondPrincipalStartPeriod'].values * prm / 10000.0 * self.mbsCashflow['futureCouponPeriodsDays'].values / 365.0, 2)
                prem_req_price = lambda prm: 100.0 + ((prem_act - prem_req(prm)) * self.discountFactorZCYCPlusZ(prm)).sum() / self.currentBondPrincipal * 100.0 + self.accruedCouponInterest
                self.requiredKeyRatePremium = minimize(lambda prm: (prem_req_price(prm) - self.dirtyPrice) ** 2.0, np.array([0.0]), method='Nelder-Mead').x[0]

            elif self.calculationType == CALCULATION_TYPE.SET_PREMI:
                pass

        elif self.couponType in [COUPON_TYPE.FXD, COUPON_TYPE.CHG]:
            pass

        # ----- 9.15 ДЮРАЦИЯ МАКОЛЕЯ -----
        if self.couponType in [COUPON_TYPE.FXD, COUPON_TYPE.CHG]:
            self.durationMacaulay = self.durationMacaulay_func(self.ytm)

        elif self.couponType == COUPON_TYPE.FLT:
            pass

        # ----- 9.16 МОДИФИЦИРОВАННАЯ ДЮРАЦИЯ -----
        if self.couponType in [COUPON_TYPE.FXD, COUPON_TYPE.CHG]:
            self.durationModified = self.durationMacaulay / (1.0 + self.ytm / 100.0)

        elif self.couponType == COUPON_TYPE.FLT:
            pass

        self.pricingResult = {
            'accruedCouponInterest': np.round(self.accruedCouponInterest, 2),
            'accruedCouponInterestRub': self.accruedCouponInterestRub,
            'dirtyPrice': np.round(self.dirtyPrice, 2),
            'dirtyPriceRub': self.dirtyPriceRub,
            'cleanPrice': np.round(self.cleanPrice, 2),
            'cleanPriceRub': self.cleanPriceRub,
            'ytm': np.round(self.ytm, 2) if self.ytm is not None else None,
            'zSpread': int(np.round(self.zSpread, 0)) if self.zSpread is not None else None,
            'gSpread': int(np.round(self.gSpread, 0)) if self.gSpread is not None else None,
            'requiredKeyRatePremium': int(np.round(self.requiredKeyRatePremium, 0)) if self.requiredKeyRatePremium is not None else None,
            'durationMacaulay': np.round(self.durationMacaulay, 2) if self.durationMacaulay is not None else None,
            'durationModified': np.round(self.durationModified, 2) if self.durationModified is not None else None,
        }

    def outputPreparation(self):

        # ----------------------------------------------------------------------------------- #
        # ------------------------ ПОДГОТОВКА ВЫХОДНЫХ ДАННЫХ РАСЧЕТА ----------------------- #
        # ----------------------------------------------------------------------------------- #

        # В ТОМ СЛУЧАЕ, ЕСЛИ МОДЕЛЬ НЕ СМОДЕЛИРОВАЛА НИ ОДНОГО ДЕНЕЖНОГО ПОТОКА
        # (Т.Е. ВСЕ БУДУЩИЕ ПОТОКИ ВЗЯТЫ ИЗ ОТЧЕТОВ ДЛЯ ИНВЕСТОРОВ), API НЕ ДОЛЖНО
        # ВОЗВРАЩАТЬ ПАРАМЕТРЫ, СВЯЗАННЫЕ С МОДЕЛИРОВАНИЕ ДОСРОЧНЫХ ПОГАШЕНИЙ И ДЕФОЛТОВ
        # (ГРАФИК S-КРИВОЙ, МОДЕЛЬНЫЕ CPR/CDR И Т.Д.)
        self.no_model_flows = False
        if False not in self.mbsCashflow['useInvestorsReports'].values:
            self.no_model_flows = True

        # ----- ПАРАМЕТРЫ ОЦЕНКИ -----
        self.pricingParameters['pricingDate'] = str(self.pricingDate.astype(s_type))
        self.pricingParameters['usePricingDateDataOnly'] = self.usePricingDateDataOnly
        self.pricingParameters['cpr'] = self.modelCPR if not self.no_model_flows else None
        self.pricingParameters['cdr'] = self.modelCDR if not self.no_model_flows else None
        self.pricingParameters['zcycDateTime'] = str(self.zcycParameters['date'])
        self.pricingParameters['zcycParameters'] = self.zcycParameters

        self.calculationOutput['pricingParameters'] = self.pricingParameters

        # ----- РЕЗУЛЬТАТ ОЦЕНКИ -----
        self.calculationOutput['pricingResult'] = self.pricingResult

        # ----- ДЕНЕЖНЫЙ ПОТОК ПО ИЦБ ДОМ.РФ -----
        columns = ['futureCouponDates', 'useInvestorsReports', 'bondPrincipalStartPeriod', 'bondFutureAmortization',
                   'bondFutureModelScheduled', 'bondFutureModelPrepayment', 'bondFutureModelDefaults', 'bondFutureModelCleanUp']
        self.mbsCashflowTable = self.mbsCashflow[columns].copy(deep=True)
        self.mbsCashflowTable['futureCouponDates'] = self.mbsCashflowTable['futureCouponDates'].values.astype(s_type).astype(str)
        self.mbsCashflowTable['useInvestorsReports'] = self.mbsCashflowTable['useInvestorsReports'].astype(int)
        self.mbsCashflowTable.rename(columns={'futureCouponDates': 'couponDates',
                                              'useInvestorsReports': 'cashflowType',
                                              'bondFutureAmortization': 'bondAmortization'}, inplace=True)

        self.mbsCashflowTable['bondCouponPayments'] = None
        if self.couponType in [COUPON_TYPE.FXD, COUPON_TYPE.CHG]:
            self.mbsCashflowTable['bondCouponPayments'] = self.mbsCashflow['bondFutureCouponPayments'].values
        elif self.couponType == COUPON_TYPE.FLT:
            self.mbsCashflowTable['bondCouponPayments'] = self.mbsCashflow['bondFuturePremiumPayments'].values

        coupon_payments = self.mbsCashflowTable['bondCouponPayments'].values
        mbs_current_principals = self.mbsCashflowTable['bondPrincipalStartPeriod'].values
        coupon_days = self.mbsCashflow['futureCouponPeriodsDays'].values
        percents = (coupon_payments / mbs_current_principals * 365.0 / coupon_days * 100.0).astype(float)
        self.mbsCashflowTable.loc[:, 'bondCouponPaymentsPercents'] = np.round(percents, 2)

        historical_reports = self.investorsReportsData['investorsReportCouponDate'] < self.nextCouponDate
        self.historicalCashflow = self.investorsReportsData[historical_reports].copy(deep=True)
        if not self.historicalCashflow.empty:
            self.historicalCashflow.rename(columns={'investorsReportCouponDate': 'couponDates',
                                                    'investorsReportBondNextPrincipal': 'bondPrincipalStartPeriod',
                                                    'investorsReportBondAmortization': 'bondAmortization'}, inplace=True)
            # Нужно добавить амортизацию, т.к. в отчетах указывается номинал после выплаты:
            self.historicalCashflow['bondPrincipalStartPeriod'] += self.historicalCashflow['bondAmortization'].values
            self.historicalCashflow['cashflowType'] = 2
            self.historicalCashflow['couponDates'] = self.historicalCashflow['couponDates'].values.astype(s_type).astype(str)

            mbs_current_principals = self.historicalCashflow['bondPrincipalStartPeriod'].values
            coupon_days = self.couponDatesSeries['couponPeriodsDays'][self.couponDatesSeries['allCouponDates'].values < self.nextCouponDate].values
            self.historicalCashflow['bondCouponPayments'] = None
            if self.couponType in [COUPON_TYPE.FXD, COUPON_TYPE.CHG]:
                self.historicalCashflow['bondCouponPayments'] = self.historicalCashflow['investorsReportBondCouponPayment'].values
            elif self.couponType == COUPON_TYPE.FLT:
                self.historicalCashflow['bondCouponPayments'] = np.round(mbs_current_principals * self.fixedKeyRatePremium / 100.0 * coupon_days / 365.0, 2)

            coupon_payments = self.historicalCashflow['bondCouponPayments'].values
            self.historicalCashflow['bondCouponPaymentsPercents'] = np.round(coupon_payments / mbs_current_principals * 365.0 / coupon_days * 100.0, 2)

            for col in ['bondFutureModelScheduled', 'bondFutureModelPrepayment', 'bondFutureModelDefaults', 'bondFutureModelCleanUp']:
                self.historicalCashflow[col] = np.nan

            columns = ['couponDates', 'cashflowType', 'bondPrincipalStartPeriod',
                       'bondAmortization', 'bondCouponPayments', 'bondCouponPaymentsPercents',
                       'bondFutureModelScheduled', 'bondFutureModelPrepayment', 'bondFutureModelDefaults', 'bondFutureModelCleanUp']

            self.mbsCashflowTable = pd.concat([self.historicalCashflow[columns], self.mbsCashflowTable[columns]]).reset_index(drop=True)

        for col in ['bondPrincipalStartPeriod', 'bondAmortization', 'bondCouponPayments', 'bondCouponPaymentsPercents']:
            self.mbsCashflowTable[col] = np.round(self.mbsCashflowTable[col].values.astype(float), 2)

        columns = ['couponDates', 'cashflowType', 'bondPrincipalStartPeriod',
                   'bondAmortization', 'bondCouponPayments', 'bondCouponPaymentsPercents']
        self.calculationOutput['mbsCashflowTable'] = self.mbsCashflowTable[columns].to_dict('records')

        # ----- ГРАФИК ДЕНЕЖНОГО ПОТОКА ПО ИЦБ ДОМ.РФ -----
        self.mbsCashflowGraph = pd.DataFrame({})
        self.mbsCashflowGraph['graphCouponDates'] = self.mbsCashflowTable['couponDates'].values
        self.mbsCashflowGraph['graphCashflowType'] = self.mbsCashflowTable['cashflowType'].values

        historical_cashflow = self.mbsCashflowGraph['graphCashflowType'].values == 2
        inv_report_cashflow = self.mbsCashflowGraph['graphCashflowType'].values == 1
        modeled_cashflow = self.mbsCashflowGraph['graphCashflowType'].values == 0

        self.mbsCashflowGraph.loc[historical_cashflow, 'graphBondHisroticalAmortization'] = self.mbsCashflowTable['bondAmortization'].values[historical_cashflow]
        self.mbsCashflowGraph.loc[inv_report_cashflow, 'graphBondFutureActualAmortization'] = self.mbsCashflowTable['bondAmortization'].values[inv_report_cashflow]
        self.mbsCashflowGraph['graphBondFutureModelScheduled'] = self.mbsCashflowTable['bondFutureModelScheduled'].values
        self.mbsCashflowGraph['graphBondFutureModelPrepayment'] = self.mbsCashflowTable['bondFutureModelPrepayment'].values
        self.mbsCashflowGraph['graphBondFutureModelDefaults'] = self.mbsCashflowTable['bondFutureModelDefaults'].values
        self.mbsCashflowGraph['graphBondFutureModelCleanUp'] = self.mbsCashflowTable['bondFutureModelCleanUp'].values

        self.mbsCashflowGraph.loc[historical_cashflow, 'graphBondHistoricalCouponPayments'] = self.mbsCashflowTable['bondCouponPayments'].values[historical_cashflow]
        self.mbsCashflowGraph.loc[inv_report_cashflow, 'graphBondFutureActualCouponPayments'] = self.mbsCashflowTable['bondCouponPayments'].values[inv_report_cashflow]
        self.mbsCashflowGraph.loc[modeled_cashflow, 'graphBondFutureModelCouponPayments'] = self.mbsCashflowTable['bondCouponPayments'].values[modeled_cashflow]

        self.mbsCashflowGraph.replace({np.nan: None}, inplace=True)
        self.mbsCashflowGraph = self.mbsCashflowGraph.to_dict('list')
        self.calculationOutput['mbsCashflowGraph'] = self.mbsCashflowGraph

        # ----- ГРАФИК КБД -----
        if self.couponType in [COUPON_TYPE.FXD, COUPON_TYPE.CHG]:
            self.zcycGraph = {}

            end_range = round_ceil(max(self.mbsCashflow['futureCouponDates'].values - self.pricingDate) / np.timedelta64(1, 'D') / 365.0, 1)
            t = np.arange(0.1, end_range + 0.1, 0.1)
            zcyc_values = np.round(Y(self.zcycParameters, t) / 100.0, 5)

            self.calculationOutput['zcycGraph'] = zcyc_values.tolist()

        # ----- ГРАФИК S-КРИВОЙ -----
        self.calculationOutput['sCurveGraph'] = None
        if not self.no_model_flows:
            self.sCurveGraph = pd.DataFrame({})

            default_left = -7.0
            default_right = 7.0
            too_negative = self.incentiveToRefinance < default_left
            too_positive = self.incentiveToRefinance > default_right
            start_range = default_left if not too_negative else np.floor(self.incentiveToRefinance)
            end_range = default_right if not too_positive else np.ceil(self.incentiveToRefinance)

            self.sCurveGraph.loc[:, 'graphIncentiveToRefinance'] = np.round(np.arange(start_range, end_range + 0.1, 0.1), 1)
            self.sCurveGraph.loc[:, 'graphCPR'] = (self.calculationSCurveBeta0 + self.calculationSCurveBeta1 * np.arctan(self.calculationSCurveBeta2 + self.calculationSCurveBeta3 * self.sCurveGraph['graphIncentiveToRefinance'].values)) * 100.0

            self.start = time.time()
            self.sCurveEmpiricalData = pd.DataFrame(get(API.GET_SCURVE_EMPIRICAL_DATA, timeout=15).json())
            self.end = time.time()
            self.calculationTime['sCurveEmpiricalDataAPI'] = np.round(self.end - self.start, 2)

            self.sCurveEmpiricalData['sCurveReportDate'] = pd.to_datetime(self.sCurveEmpiricalData['sCurveReportDate'])
            self.sCurveEmpiricalData = self.sCurveEmpiricalData[self.sCurveEmpiricalData['sCurveReportDate'].values == self.calculationSCurveReportDate]
            self.sCurveEmpiricalData['sCurveIncentiveToRefinance'] = np.round(self.sCurveEmpiricalData['sCurveIncentiveToRefinance'].values, 1)

            self.sCurveGraph = self.sCurveGraph.merge(self.sCurveEmpiricalData, left_on='graphIncentiveToRefinance', right_on='sCurveIncentiveToRefinance', how='left')
            self.sCurveGraph.rename(columns={'sCurveEmpiricalCPR': 'graphEmpiricalCPR', 'sCurveEmpiricalDataVolume': 'graphEmpiricalDataVolume'}, inplace=True)
            columns = ['graphIncentiveToRefinance', 'graphEmpiricalDataVolume', 'graphEmpiricalCPR', 'graphCPR']
            self.sCurveGraph = self.sCurveGraph[columns]

            self.sCurveGraph['graphEmpiricalDataVolume'] = np.round(self.sCurveGraph['graphEmpiricalDataVolume'].values, 2)
            self.sCurveGraph['graphEmpiricalCPR'] = np.round(self.sCurveGraph['graphEmpiricalCPR'].values, 5)
            self.sCurveGraph['graphCPR'] = np.round(self.sCurveGraph['graphCPR'].values, 5)
            self.sCurveGraph.replace({np.nan: None}, inplace=True)

            self.sCurveGraph = self.sCurveGraph.to_dict('list')

            self.sCurveGraph['mbsPosition'] = {
                'incentiveToRefinance': self.incentiveToRefinance,
                'sCurveCPR': np.round((self.calculationSCurveBeta0 + self.calculationSCurveBeta1 * np.arctan(self.calculationSCurveBeta2 + self.calculationSCurveBeta3 * self.incentiveToRefinance)) * 100.0, 5)
            }
            self.calculationOutput['sCurveGraph'] = self.sCurveGraph

        # ----- ПЕРЕМЕННЫЕ РАСЧЕТА -----
        self.couponDatesSeries.loc[:, 'allCouponDates'] = self.couponDatesSeries['allCouponDates'].values.astype(s_type).astype(str)
        self.couponDatesSeries = self.couponDatesSeries.to_dict('list')
        self.calculatedParameters['couponDatesSeries'] = self.couponDatesSeries
        self.calculatedParameters['previousCouponDate'] = str(self.previousCouponDate.astype(s_type)) if self.previousCouponDate is not None else None
        self.calculatedParameters['pricingDateIsValid'] = self.pricingDateIsValid
        self.calculatedParameters['nextCouponDate'] = str(self.nextCouponDate.astype(s_type))
        self.calculatedParameters['daysPassedInCurrentCouponPeriod'] = int(self.daysPassedInCurrentCouponPeriod)
        self.calculatedParameters['maximumCouponDateWithKnownPayment'] = str(self.maximumCouponDateWithKnownPayment.astype(s_type)) if self.maximumCouponDateWithKnownPayment is not None else None
        self.calculatedParameters['poolCashflowStartCouponDate'] = str(self.poolCashflowStartCouponDate.astype(s_type))
        self.calculatedParameters['paymentPeriodLag'] = int(self.paymentPeriodLag)
        self.calculatedParameters['poolCashflowStartPaymentPeriodDate'] = str(self.poolCashflowStartPaymentPeriodDate.astype(s_type))
        self.calculatedParameters['poolCashflowStartDate'] = str(self.poolCashflowStartDate.astype(s_type))
        self.calculatedParameters['wacwamDate'] = str(self.wacwamDate.astype(s_type))
        self.calculatedParameters['wac'] = self.wac
        self.calculatedParameters['standardWAM'] = self.standardWAM
        self.calculatedParameters['adjustedWAM'] = self.adjustedWAM
        self.calculatedParameters['wamCoefficient'] = self.wamCoefficient
        self.calculatedParameters['poolCashflowEndDate'] = str(self.poolCashflowEndDate.astype(s_type))
        self.calculatedParameters['deliveryMonthAccrualDays'] = int(self.deliveryMonthAccrualDays)
        self.calculatedParameters['numberOfBonds'] = int(self.numberOfBonds)
        self.calculatedParameters['currentBondPrincipal'] = self.currentBondPrincipal
        self.calculatedParameters['poolCashflowStartDebt'] = self.poolCashflowStartDebt
        self.calculatedParameters['cleanUpRubles'] = self.cleanUpRubles
        self.calculatedParameters['calculationRefinancingRateReportDate'] = str(self.calculationRefinancingRateReportDate.astype(s_type))
        self.calculatedParameters['calculationRefinancingRate'] = self.calculationRefinancingRate
        self.calculatedParameters['incentiveToRefinance'] = self.incentiveToRefinance
        self.calculatedParameters['calculationSCurveReportDate'] = str(self.calculationSCurveReportDate.astype(s_type))
        self.calculatedParameters['calculationSCurveBeta0'] = self.calculationSCurveBeta0
        self.calculatedParameters['calculationSCurveBeta1'] = self.calculationSCurveBeta1
        self.calculatedParameters['calculationSCurveBeta2'] = self.calculationSCurveBeta2
        self.calculatedParameters['calculationSCurveBeta3'] = self.calculationSCurveBeta3
        self.calculatedParameters['sCurveCPR'] = self.sCurveCPR
        self.calculatedParameters['historicalCPRDate'] = str(self.historicalCPRDate.astype(s_type)) if self.historicalCPRDate is not None else None
        self.calculatedParameters['historicalCPR'] = self.historicalCPR
        self.calculatedParameters['sixMonthsCPR'] = self.sixMonthsCPR
        self.calculatedParameters['historicalCDRDate'] = str(self.historicalCDRDate.astype(s_type)) if self.historicalCDRDate is not None else None
        self.calculatedParameters['historicalCDR'] = self.historicalCDR
        self.calculatedParameters['conventionalCDRDate'] = str(self.conventionalCDRDate.astype(s_type))
        self.calculatedParameters['conventionalCDR'] = self.conventionalCDR
        self.calculatedParameters['modelCPR'] = self.modelCPR
        self.calculatedParameters['modelCDR'] = self.modelCDR
        self.calculatedParameters['monthlyCPR'] = self.monthlyCPR
        self.calculatedParameters['monthlyCDR'] = self.monthlyCDR

        self.calculatedParameters['firstCouponExpensesWithVAT'] = self.firstCouponExpensesWithVAT
        self.calculatedParameters['otherCouponsExpensesWithVAT'] = self.otherCouponsExpensesWithVAT
        self.calculatedParameters['yieldCoeffientCPR'] = self.yieldCoeffientCPR
        self.calculatedParameters['yieldCoeffientCDR'] = self.yieldCoeffientCDR
        self.calculatedParameters['yieldCoeffientTotal'] = self.yieldCoeffientTotal

        self.calculatedParameters['nextCouponKeyRateDate'] = str(self.nextCouponKeyRateDate.astype(s_type)) if self.nextCouponKeyRateDate is not None else None
        self.calculatedParameters['nextCouponKeyRate'] = self.nextCouponKeyRate
        self.calculatedParameters['nextCouponKeyRatePlusPremiumValueRubles'] = self.nextCouponKeyRatePlusPremiumValueRubles
        self.calculatedParameters['nextCouponKeyRatePlusPremiumValuePercents'] = self.nextCouponKeyRatePlusPremiumValuePercents

        if self.no_model_flows:
            important_parameters = ['couponDatesSeries', 'previousCouponDate', 'pricingDateIsValid', 'nextCouponDate', 'daysPassedInCurrentCouponPeriod',
                                    'maximumCouponDateWithKnownPayment', 'numberOfBonds', 'currentBondPrincipal',
                            ]
            for parameter in self.calculatedParameters.keys():
                if parameter not in important_parameters:
                    self.calculatedParameters[parameter] = None

        self.calculationOutput['calculatedParameters'] = self.calculatedParameters

    def calculate(self):

        # ----------------------------------------------------------------------------------- #
        # ------------------- 7. РАСЧЕТ ДЕНЕЖНОГО ПОТОКА ПО ПУЛУ ЗАКЛАДНЫХ ------------------ #
        # ----------------------------------------------------------------------------------- #
        self.poolCashflowModel()

        # ----------------------------------------------------------------------------------- #
        # --------------------- 8. РАСЧЕТ ДЕНЕЖНОГО ПОТОКА ПО ИЦБ ДОМ.РФ -------------------- #
        # ----------------------------------------------------------------------------------- #
        self.mbsCashflowModel()

        # ----------------------------------------------------------------------------------- #
        # ----------------------- 9. РАСЧЕТ ЦЕНОВЫХ МЕТРИК ИЦБ ДОМ.РФ ----------------------- #
        # ----------------------------------------------------------------------------------- #
        self.mbsPricing()

        # ----------------------------------------------------------------------------------- #
        # ------------------------ ПОДГОТОВКА ВЫХОДНЫХ ДАННЫХ РАСЧЕТА ----------------------- #
        # ----------------------------------------------------------------------------------- #
        self.outputPreparation()

        self.calculationOutput['calculationTime'] = self.calculationTime

        return self.calculationOutput
