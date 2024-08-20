# -*- coding: utf8 -*-

# ---------------------------------------------------------------------------------------------------------------------------------------- #
# ----- КОНВЕНЦИЯ ДЛЯ ИПОТЕЧНЫХ ЦЕННЫХ БУМАГ: МОДЕЛИ КЛЮЧЕВОЙ СТАВКИ И СТАВКИ РЕФИНАНСИРОВАНИЯ ИПОТЕКИ ----------------------------------- #
# ---------------------------------------------------------------------------------------------------------------------------------------- #

import numpy as np
import pandas as pd

from requests import get
from convention_2.auxiliary import *

import warnings
warnings.filterwarnings('ignore')
np.seterr(all='ignore')


def refinancingRatesModel(key_rate_model_date, key_rate_model_data, start_month, stop_month, key_rate_forecast=None):

    """
    ----------------------------------------------------------------------------------------------------------------------------------------
    Расчет Модельной траектории Ключевой ставки и Модельной траектории среднемесячной рыночной ставки рефинансирования ипотеки
    ----------------------------------------------------------------------------------------------------------------------------------------

    Параметры функции:

        Обязательные:
            1. key_rate_model_date   — дата, по состоянию на которую производится расчет Модельной траектории среднемесячной рыночной
                                       ставки рефинансирования ипотеки (Опорная дата модели Ключевой ставки)
            2. key_rate_model_data   — данные, необходимые для расчета необходимые для расчета Модельной траектории Ключевой ставки и
                                       Модельной траектории среднемесячной ставки рефинансирования ипотеки
            3. start_month           — месяц, с которого должен начинаться результирующий временной ряд Модельной траектории
                                       среднемесячной ставки рефинансирования ипотеки
            4. stop_month            — месяц, на котором должен заканчиваться результирующий временной ряд Модельной траектории
                                       среднемесячной ставки рефинансирования ипотеки

        Опциональные:
            1. key_rate_forecast     — пользовательская траектория значений Ключевой ставки. Устроена как DataFrame из двух колонок:
                                        · date — дата, с которой действует соответствующее ей значение Ключевой ставки
                                        · rate — значение Ключевой ставки в % годовых (например, 10.75, 7.00 и т.п.)
                                     Траектория устанавливается с точностью до дня. Например, если key_rate_model_date = 09.04.2024,
                                     траектория
                                            [
                                                 {'date': '2024-02-11', 'rate': 17.00},
                                                 {'date': '2025-07-10', 'rate': 12.00},
                                                 {'date': '2026-02-15', 'rate': 9.50},
                                                 {'date': '2028-09-20', 'rate': 7.75},
                                            ]
                                     означает, что значение 17.00 на 11.02.2024 будет проигнорировано, с 10.04.2024 по 09.07.2025 будет
                                     использована актуальная на 09.04.2024 Ключевая ставка 16.00% год., с 10.07.2025 по 14.02.2026 будет
                                     ипользована Ключевая ставка 9.50% год., с 15.02.2026 по 19.09.2028 будет использована Ключевая ставка
                                     9.50% год., а с 20.09.2028 и до бесконечности — Ключевая ставка 7.75% год

    ----------------------------------------------------------------------------------------------------------------------------------------

    В том случае, если аргумент key_rate_forecast не задан:

        — если key_rate_model_date < MODEL_MINIMUM_DATE:

            · в качестве Модельной траектории Ключевой ставки будет использовано ее текущеее на key_rate_model_date значение
            · в качестве Модельной траектории среднемесячной ставки рефинансирования ипотеки будет использовано ее текущеее на
              key_rate_model_date значение

        — если key_rate_model_date >= MODEL_MINIMUM_DATE:

            — если на key_rate_model_date есть актуальная (енее 14 дней давности) Рыночная траектория Ключевой ставки:
                    · Модельная траектория Ключевой ставки рассчитывается путем взвешивания Рыночной траектории Ключевой ставки по состоянию
                      на дату, наиболее близкую в прошлом к key_rate_model_date (включительно) и Сглаженного прогноза Банка России, рассчи-
                      танного по итогам заседания Совета директоров Банка России в дату, наиболее близкую в прошлом к key_rate_model_date
                      (включительно). Расчет Рыночной траектории Ключевой ставки по котировкам свопов и Сглаженного прогноза Банка России
                      осуществляется вне рамок данной функции, данные временные ряды рассчитываются по алгоритмам ДОМ.РФ заранее и выгру-
                      жается из баз данных ДОМ.РФ методам API GetMacroData. В рамках данной функции производится только итоговое взвешивание
                      (т.е. расчет Модельной траектории Ключевой ставки)

            — иначе:
                    · в качестве Модельной траектории Ключевой ставки используется Сглаженный прогноз Банка России, рассчитанный по итогам
                      заседания Совета директоров Банка России в дату, наиболее близкую в прошлом к key_rate_model_date (включительно)

            Модельная траектория среднемесячной рыночной ставки рефинансирования ипотеки рассчитывается на основе эконометрической модели,
            регрессорами в которой выступают константа и среднемесячные значения Ключевой ставки, соответствующие полученной Модельной
            траектории Ключевой ставки

    В том случае, если аргумент key_rate_forecast задан:

            Модельная траектория среднемесячной рыночной ставки рефинансирования ипотеки рассчитывается на основе эконометрической модели,
            регрессорами в которой выступают константа и среднемесячные значения Ключевой ставки, соответствующие заданной пользовательской
            траектории Ключевой ставки

    ----------------------------------------------------------------------------------------------------------------------------------------

    Результат функции:

            1. allKeyRates                  — DataFrame, состоящий из 2 колонок:
                                                    · date     — дата, с которой действует соответствующее ей значение Ключевой ставки
                                                    · key_rate — значение Ключевой ставки в % годовых (например, 10.75, 7.00 и т.п.)
                                              В этой таблице собраны исторические Ключевые ставки совместно с итоговой Модельной траекторией
                                              Ключевой ставки, по которой рассчитывается Модельная траектория среднемесячной рыночной ставки
                                              рефинансирования ипотеки

            2. ratesMonthlyAvg              — DataFrame, состоящий из 3 колонок:
                                                    · date     — месяц, за который указаны key_rate и ref_rate
                                                                 (от start_month включительно до stop_month включительно)
                                                    · key_rate — среднемесячная Ключевая ставка за месяц month
                                                    · ref_rate — среднемесячная рыночная ставка рефинансирования ипотеки за месяц month
                                              В этой таблице представлены среднемесячные значения Модельной траекетории Ключевой ставки и
                                              Модельная траектория среднемесячной рыночной ставки рефинансирования ипотеки от start_month
                                              включительно до stop_month включительно (совместно с историческими среднемесячными значениями
                                              в начале, если необходимо)

            3. keyRateInteractiveGraph      — технический объект, содержащий данные для построения интерактивного графика для изменения
                                              Модельной траектории Ключевой ставки на сайте Калькулятора ИЦБ ДОМ.РФ. Содержит:
                                                    · часть графика c историческими значениями Ключевой ставки
                                                    · несглаженнный Среднесрочный прогноз Банка России (Ключевой ставки)
                                                    · Сглаженный прогноз Банка России (Ключевой ставки)
                                                    · Рыночная траектория Ключевой ставки (по котировкам свопов)
                                                    · Модельная траектория Ключевой ставки
                                                    · стартовые значения и границы модельных участков, которые можно передвигать на графике
                                                      по вертикали и тем самым самостоятельно задавать Модельную траекторию Ключевой ставки

            4. keyRateSwapForecastDate      — дата, по состоянию на которую взяты котировки свопов на Ключевую ставку, на основании которых
                                              рассчитана Рыночная траектория Ключевой ставки (указывается в том случае, если используется,
                                              иначе None)

            5. currentCBForecastDate        — дата заседания Совета директоров Банка России, по итогам которого взят используемый Сглаженный
                                              прогноз Банка России (указывается в том случае, если используется, иначе None)

            6. currentRefinancingRateDate   — дата отчета Аналитического центра ДОМ.РФ, актуального на key_rate_model_date

            7. currentRefinancingRate       — значение рыночной ставки рефинансирования ипотеки по отчету на currentRefinancingRateDate

    ----------------------------------------------------------------------------------------------------------------------------------------
    """

    # До указанной MODEL_MINIMUM_DATE в качестве Модельной траектории Ключевой ставки будет использовано ее текущеее на key_rate_model_date
    # значение, а в качестве Модельной траектории среднемесячной рыночной ставки рефинансирования ипотеки будет использовано ее текущеее на
    # key_rate_model_date значение:
    MODEL_MINIMUM_DATE = np.datetime64('2022-06-01')
    do_model_rates = key_rate_model_date >= MODEL_MINIMUM_DATE

    # Важно: код устроен таким образом, что key_rate_model_date — это дата, по состоянию на которую известны данные.
    # Первая моделируемая дата — это дата, следующая за key_rate_model_date.

    # ------------------------------------------------------------------------------------------------------------------------------------ #
    # ----- ОБРАБОТКА ДАННЫХ ДЛЯ МОДЕЛИ -------------------------------------------------------------------------------------------------- #
    # ------------------------------------------------------------------------------------------------------------------------------------ #

    # Обработка данных и подготовка всех необходимых таблиц:

    # ----- meetingsCBR ------------------------------------------------------------------------------------------------------------------ #
    # Вся имеющаяся на сегодня история заседаний Совета директоров Банка России и значения Ключевой ставки по итогам заседаний:
    #     · date — дата заседания Совета директоров Банка России, с которой действует соответствующее ей значение Ключевой ставки
    #     · rate — значение Ключевой ставки в % годовых по итогам заседания (например, 10.75, 7.00 и т.п.)

    meetingsCBR = pd.DataFrame(key_rate_model_data['meetingsCBR'])
    meetingsCBR['date'] = pd.to_datetime(meetingsCBR['date']).values.astype(d_type)
    meetingsCBR['rate'] /= 100.0
    meetingsCBR = meetingsCBR[meetingsCBR['rate'].notna()]
    meetingsCBR.rename(columns={'rate': 'key_rate'}, inplace=True)
    meetingsCBR.sort_values(by='date', inplace=True)

    # -- meetingsCBRForecasts ------------------------------------------------------------------------------------------------------------ #
    # Среднесрочные прогнозы Банка России по Ключевой ставке, опубликованные по итогам заседаний Совета директоров Банка России (только
    # для заседаний, по итогам которых был опубликован прогноз). Прогноз задается в виде массива значений:
    #     · date — дата заседания Совета директоров Банка России, на которую опубликован Среднесрочный прогноз Ключевой ставки
    #     · year — год, на который указан диапазон среднесрочного прогноза Ключевой ставки (если year равен году, на
    #              который приходится заседание на дату date, то подразумевается период с date по конец года)
    #     · min  — нижняя граница прогноза Ключевой ставки в течение года year
    #     · max  — верхняя граница прогноза Ключевой ставки в течение года year

    meetingsCBRForecasts = None
    currentCBForecast = None
    currentCBForecastDate = None

    if do_model_rates:

        meetingsCBRForecasts = pd.DataFrame(key_rate_model_data['meetingsCBRForecasts'])
        meetingsCBRForecasts['date'] = pd.to_datetime(meetingsCBRForecasts['date']).values.astype(d_type)
        meetingsCBRForecasts.sort_values(by=['date', 'year'], inplace=True)
        meetingsCBRForecasts['cb_key_rate'] =  np.round(meetingsCBRForecasts[['min', 'max']].mean(axis=1).values * 4.0, 0) / 4.0

        # Выделяем самый актуальный среднесрочный прогноз Ключевой ставки Банка России на key_rate_model_date:
        available_forecasts_dates = meetingsCBRForecasts['date'].unique()
        currentCBForecastDate = np.datetime64(available_forecasts_dates[available_forecasts_dates <= key_rate_model_date][-1], 'D')

        currentCBForecast = meetingsCBRForecasts[meetingsCBRForecasts['date'] == currentCBForecastDate].reset_index(drop=True)
        currentCBForecast.loc[0, 'date'] = currentCBForecastDate
        if len(currentCBForecast) > 1:
            currentCBForecast.loc[1:, 'date'] = [np.datetime64(str(year) + '-01-01') for year in currentCBForecast.year[1:]]
        currentCBForecast = currentCBForecast[['date', 'cb_key_rate']]
        currentCBForecast.sort_values(by='date', inplace=True)

    # ----- meetingsCBRSmooth ------------------------------------------------------------------------------------------------------------ #
    # Сглаженный прогноз Банка России по Ключевой ставке, актуальный на key_rate_model_date. Если на предыдущую дату заседания Совета
    # директоров прогноз не был опубликован, то для расчета Сглаженного прогноза на эту дату берется Среднесрочный прогноз Банка России с
    # предыдущей даты заседания совета директоров, на которую Среднесрочный прогноз был опубликован. Ззначения прогнозной Ключевой ставки
    # устанавливаются на каждую будущую дату заседания Совета директоров Банка России:
    #     · meetingDate — дата заседания Совета директоров Банка России, которой соответствует Сглаженный прогноз (равна самой актуальной
    #                     дате заседания, <= key_rate_model_date)
    #     · data — Сглаженный прогноз Банка России на meetingDate:
    #                · date — дата, с которой действует соответствующее ей значение Ключевой ставки
    #                · rate — значение Ключевой ставки в % годовых (например, 10.75, 7.00 и т.п.)

    meetingsCBRSmooth = None
    if do_model_rates:

        meetingsCBRSmooth = pd.DataFrame(key_rate_model_data['meetingsCBRSmooth']['data'])
        meetingsCBRSmooth['date'] = pd.to_datetime(meetingsCBRSmooth['date']).values.astype(d_type)
        meetingsCBRSmooth['rate'] /= 100.0
        meetingsCBRSmooth.rename(columns={'rate': 'smooth_cb_key_rate'}, inplace=True)
        meetingsCBRSmooth.sort_values(by='date', inplace=True)

    # ----- keyRateSwapForecast ---------------------------------------------------------------------------------------------------------- #
    # Самая актуальная на key_rate_model_date Рыночная траектория Ключевой ставки (на основе котировок свопов):
    #     · forecastDate — дата, по окончанию на которую взяты котировки свопов на Ключевую ставку для расчета траектории
    #                      (самая актуальная дата, на которую есть котировки, <= key_rate_model_date)
    #     · data — Рыночная траектория Ключевой ставки на forecastDate:
    #                · date — дата, с которой действует соответствующее ей значение Ключевой ставки
    #                · rate — значение Ключевой ставки в % годовых (например, 10.75, 7.00 и т.п.)

    # Определяем валидность траектории Ключевой ставки по своповым котировкам. Валидность определяется тем, что:
    #       1. значения траектории непустые;
    #       2. траектория свежая, т.е. key_rate_model_date может быть больше forecastDate максимум на 14 дней (на случай праздников и т.п.);

    keyRateSwapForecast = None
    keyRateSwapForecastDate = None
    swap_forecast_is_valid = False

    if do_model_rates:

        if key_rate_model_data['keyRateSwapForecast'] is not None:
            keyRateSwapForecastDate = np.datetime64(key_rate_model_data['keyRateSwapForecast']['forecastDate'], 'D')
            condition_2 = (key_rate_model_date - keyRateSwapForecastDate) / day <= 14
            if condition_2:
                swap_forecast_is_valid = True

        if swap_forecast_is_valid:
            keyRateSwapForecast = pd.DataFrame(key_rate_model_data['keyRateSwapForecast']['data'])
            keyRateSwapForecast['date'] = pd.to_datetime(keyRateSwapForecast['date']).values.astype(d_type)
            keyRateSwapForecast['rate'] /= 100.0
            keyRateSwapForecast.sort_values(by='date', inplace=True)
            keyRateSwapForecast.rename(columns={'rate': 'swap_key_rate'}, inplace=True)

    # ----- refinancingRateHistory ------------------------------------------------------------------------------------------------------- #
    # Вся имеющаяся на сегодняшний день история рыночной ставки рефинансирования ипотеки
    # (по еженедельным отчетам Аналитического центра ДОМ.РФ):
    #     · date — дата, с которой действует соответствующее ей значение рыночной ставки рефинансирования ипотеки
    #     · rate — значение рыночной ставки рефинансирования ипотеки в % годовых (например, 9.65, 14.10 и т.п.)

    refinancingRateHistory = pd.DataFrame(key_rate_model_data['refinancingRateHistory'])
    refinancingRateHistory['date'] = pd.to_datetime(refinancingRateHistory['date']).values.astype(d_type)
    refinancingRateHistory['rate'] /= 100.0
    refinancingRateHistory.rename(columns={'rate': 'ref_rate'}, inplace=True)
    refinancingRateHistory.sort_values(by='date', inplace=True)

    # Текущая по состоянию на key_rate_model_date ставка рефинансирования ипотеки (для отображения на сайте):
    history_period = refinancingRateHistory['date'] <= key_rate_model_date
    currentRefinancingRateDate = refinancingRateHistory[history_period]['date'].values[-1]
    currentRefinancingRate = np.round(refinancingRateHistory[history_period]['ref_rate'].values[-1] * 100.0, 2)

    # ----- refinancingRateParameters ---------------------------------------------------------------------------------------------------- #
    # Параметры модели ставки рефинансирования ипотеки
    #     · date — дата, на которую рассчитаны параметры
    #     · alpha0 — оценка параметра alpha0 на date
    #     · alpha1 — оценка параметра alpha1 на date
    refinancingRateParameters = pd.DataFrame(key_rate_model_data['refinancingRateParameters'])
    refinancingRateParameters['date'] = pd.to_datetime(refinancingRateParameters['date']).values.astype(d_type)
    refinancingRateParameters.sort_values(by='date', inplace=True)

    # Текущие по состоянию на key_rate_model_date параметры модели ставки рефинансирования ипотеки:
    alpha0, alpha1 = None, None
    if do_model_rates:
        history_period = refinancingRateParameters['date'] <= key_rate_model_date
        alpha0 = refinancingRateParameters[history_period]['alpha0'].values[-1]
        alpha1 = refinancingRateParameters[history_period]['alpha1'].values[-1]


    # ------------------------------------------------------------------------------------------------------------------------------------ #
    # ----- РАСЧЕТ МОДЕЛЬНОЙ ТРАЕКТОРИИ КЛЮЧЕВОЙ СТАВКИ ---------------------------------------------------------------------------------- #
    # ------------------------------------------------------------------------------------------------------------------------------------ #

    # В том случае, если пользовательская траектория Ключевой ставки не задана (аргумент key_rate_forecast is None):
    if key_rate_forecast is None:

        # Если key_rate_model_date < MODEL_MINIMUM_DATE:
        if not do_model_rates:
            # В качестве Модельной траектории Ключевой ставки будет использовано ее текущеее на key_rate_model_date значение:
            key_rate_forecast = pd.DataFrame({'date': [], 'key_rate': []})

        # Если key_rate_model_date >= MODEL_MINIMUM_DATE:
        else:

            # Если Рыночная траектория Ключевой ставки валидна:
            if swap_forecast_is_valid:
                # Модельная траектория Ключевой ставки рассчитывается путем взвешивания Рыночной траектории Ключевой ставки по состоянию на
                # дату, наиболее близкую в прошлом к key_rate_model_date (включительно) и Сглаженного прогноза Банка России, опубликованного
                # по итогам заседания Совета директоров Банка России в дату, наиболее близкую в прошлом к key_rate_model_date (включительно)
                #
                # Расчет Рыночной траектории Ключевой ставки и Сглаженного прогноза Банка России осуществляется вне рамок данной функции,
                # данные временные ряды рассчитываются по алгоритмам ДОМ.РФ заранее и выгружается из баз данных ДОМ.РФ методам API
                # GetMacroData. В рамках данной функции производится итоговое взвешивание
                #
                # В дату заседания Совета директоров Банка России может возникнуть следуюащя ситуация: Ключевая ставка изменилась, Сглажен-
                # ный прогноз Банка России изменился, но Рыночная траектория Ключевой ставки еще не обновилась (обновление происхлодит вече-
                # ром по итогам закрытия торгов на Московской бирже). В таком случае необходимо убрать прогнозное значение Рыночной траекто-
                # рии на день заседания. Иными словами, нельзя использовать значения Рыночной траектории на сегодня:
                only_future_dates = keyRateSwapForecast['date'] > key_rate_model_date
                key_rate_forecast = keyRateSwapForecast[only_future_dates].copy(deep=True)
                key_rate_forecast = pd.merge_asof(key_rate_forecast, meetingsCBRSmooth, direction='backward', on='date')

                weights = 1.0 / (1.0 + (key_rate_forecast['date'].values - keyRateSwapForecastDate) / day / 365.0)
                swap_part = key_rate_forecast['swap_key_rate'].values
                cb_part = key_rate_forecast['smooth_cb_key_rate'].values
                key_rate_forecast['key_rate'] = np.round((swap_part * weights + cb_part * (1.0 - weights)) * 4.0, 2) / 4.0

            # Если Рыночная траектория Ключевой ставки невалидна:
            else:
                # В качестве Модельной траектории Ключевой ставки используется Сглаженный прогноз Банка России, опубликованный по итогам
                # заседания Совета директоров Банка России в дату, наиболее близкую в прошлом к key_rate_model_date (включительно)
                key_rate_forecast = meetingsCBRSmooth.copy(deep=True)
                key_rate_forecast.rename(columns={'smooth_cb_key_rate': 'key_rate'}, inplace=True)

    # В том случае, если пользовательская траектория Ключевой ставки задана (аргумент key_rate_forecast is not None):
    else:
        # В качестве Модельной траектории Ключевой ставки используется заданная в аргументе key_rate_forecast траектория:
        key_rate_forecast.rename(columns={'rate': 'key_rate'}, inplace=True)
        key_rate_forecast['key_rate'] /= 100.0

    # Следующая задача — соединить таблицу заседаний Совета директоров Банка России meetingsCBR с таблицей Модельной траектории Ключевой
    # ставки key_rate_forecast:
    allKeyRates = meetingsCBR[meetingsCBR['date'] <= key_rate_model_date].copy(deep=True)
    if not key_rate_forecast.empty:
        key_rate_forecast = key_rate_forecast[key_rate_forecast['date'] > key_rate_model_date]
        allKeyRates = pd.concat([allKeyRates, key_rate_forecast[['date','key_rate']]])
    allKeyRates.reset_index(drop=True, inplace=True)
    allKeyRates.sort_values(by='date', inplace=True)
    duplicates = allKeyRates['key_rate'] == allKeyRates['key_rate'].shift(1)
    allKeyRates = allKeyRates[~duplicates].reset_index(drop=True)

    # Рассчитываем среднемесячные Ключевые ставки по соединенной таблице:
    start = allKeyRates['date'].min()
    end = (stop_month + month).astype(d_type) - day
    key_rates_avg = pd.DataFrame({'date': pd.date_range(start, end)})
    key_rates_avg = key_rates_avg.merge(allKeyRates, how='left', on='date').ffill().set_index('date')
    key_rates_avg = key_rates_avg.resample('ME').mean().reset_index()
    key_rates_avg['date'] = key_rates_avg['date'].values.astype(m_type).astype(d_type)

    allKeyRates['key_rate'] = np.round(allKeyRates['key_rate'].values * 100.0, 2)


    # ------------------------------------------------------------------------------------------------------------------------------------ #
    # ----- РАСЧЕТ МОДЕЛЬНОЙ ТРАЕКТОРИИ СРЕДНЕМЕСЯЧНОЙ РЫНОЧНОЙ СТАВКИ РЕФИНАНСИРОВАНИЯ ИПОТЕКИ ------------------------------------------ #
    # ------------------------------------------------------------------------------------------------------------------------------------ #

    # Cчитаем исторические среднемесячные значения рыночной ставки рефинансирования ипотеки:
    start = refinancingRateHistory['date'].min()

    end = None
    # Если key_rate_model_date < MODEL_MINIMUM_DATE:
    if not do_model_rates:
        # В качестве Модельной траектории среднемесячной рыночной ставки рефинансирования ипотеки будет использовано ее текущеее на
        # key_rate_model_date значение:
        end = (stop_month + month).astype(d_type) - day

    # Если key_rate_model_date >= MODEL_MINIMUM_DATE:
    else:
        # Последний месяц, на который приходится историческое среднее — месяц, на который приходится key_rate_model_date
        # (т.е. полагается, что в месяце key_rate_model_date рыночная ставка рефинансирования ипотеки больше не меняется):
        end = (key_rate_model_date.astype(m_type) + month).astype(d_type) - day

    ref_rates = refinancingRateHistory[refinancingRateHistory['date'] <= key_rate_model_date].copy(deep=True)
    ref_rates_avg = pd.DataFrame({'date': pd.date_range(start, end)})
    ref_rates_avg = ref_rates_avg.merge(ref_rates, how='left', on='date').ffill().set_index('date')
    ref_rates_avg = ref_rates_avg.resample('ME').mean().reset_index()
    ref_rates_avg['date'] = ref_rates_avg['date'].values.astype(m_type).astype(d_type)

    # merge таблицы среднемесячной Ключевой ставки с таблицей исторической среднемесячной рыночной ставки рефинансирования ипотеки:
    ratesMonthlyAvg = key_rates_avg.merge(ref_rates_avg, how='left', on='date')

    if do_model_rates:
        # Модельная траектория среднемесячной рыночной ставки рефинансирования ипотеки рассчитывается на основе эконометрической модели,
        # регрессорами в которой выступают константа и среднемесячные значения Ключевой ставки, соответствующие полученной/заданной
        # траектории Ключевой ставки

        # Создаем регрессоры для спреда, который зависит от константы и текущего значения среднемесячной Ключевой ставки:
        ratesMonthlyAvg['const'] = 1

        # Убираем в начале ratesMonthlyAvg все строки с nan:
        ratesMonthlyAvg = ratesMonthlyAvg[ratesMonthlyAvg[~ratesMonthlyAvg.isnull().any(axis=1)].index[0]:].reset_index(drop=True)

        # Коэффициенты для модели рыночной ставки рефинансирования ипотеки:
        reg_names = ['const', 'key_rate']
        ref_rate_model = np.array([alpha0, alpha1])

        # Расчет спредов между траекторией среднемесячной рыночной ставкой рефинансирования ипотеки и среднемесячной Ключевой ставкой:
        i = np.sum(~np.isnan(ratesMonthlyAvg['ref_rate'].values))   # индекс первого спреда для моделирования
        n = len(ratesMonthlyAvg) - 1
        while i <= n:
            # Спред:
            spread = np.exp(np.dot(ratesMonthlyAvg.loc[i, reg_names].values, ref_rate_model))

            # Может возникнуть ситуация, что в настоящий момент спред выше, чем установила бы модель. Тогда при восходящем прогнозе Ключевой
            # ставки модель на один или несколько следующих месяцев выставит среднемесячную ставку рефинансирования ниже, чем сейчас.
            # Чтобы избежать такой ситуации, необходимо добавить проверку:
            next_model_ref_rate = ratesMonthlyAvg.loc[i, 'key_rate'] + spread
            key_rate_up = ratesMonthlyAvg.loc[i, 'key_rate'] - ratesMonthlyAvg.loc[i - 1, 'key_rate'] >= 0.0
            ref_rate_down = next_model_ref_rate - ratesMonthlyAvg.loc[i - 1, 'ref_rate'] < 0.0
            if key_rate_up and ref_rate_down:
                ratesMonthlyAvg.loc[i, 'ref_rate'] = ratesMonthlyAvg.loc[i - 1, 'ref_rate']
            else:
                ratesMonthlyAvg.loc[i, 'ref_rate'] = next_model_ref_rate

            i += 1

    ratesMonthlyAvg['key_rate'] = np.round(ratesMonthlyAvg['key_rate'].values * 100.0, 2)
    ratesMonthlyAvg['ref_rate'] = np.round(ratesMonthlyAvg['ref_rate'].values * 100.0, 2)

    # Итоговая таблица модели: Модельная траектория среднемесячной рыночной ставки рефинансирования ипотеки, начинающаяся с start_month
    # (включительно) и заканчивающаяся stop_month (включительно). В иллюстративных целях также приводятся значения траектории среднемесяч-
    # ной Ключевой ставки:
    period = (ratesMonthlyAvg['date'] >= start_month) & (ratesMonthlyAvg['date'] <= stop_month)
    ratesMonthlyAvg = ratesMonthlyAvg[period][['date', 'key_rate', 'ref_rate']]

    # ------------------------------------------------------------------------------------------------------------------------------------ #
    # ----- ПОДГОТОВКА ДАННЫХ ДЛЯ ИЗМЕНЕНИЯ КЛЮЧЕВОЙ СТАВКИ НА ИНТЕРАКТИВНОМ ГРАФИКЕ ----------------------------------------------------- #
    # ------------------------------------------------------------------------------------------------------------------------------------ #

    # Формирование keyRateInteractiveGraph — технический объект, содержащий данные для построения интерактивного графика для изменения
    # Модельной траектории Ключевой ставки на сайте Калькулятора ИЦБ ДОМ.РФ

    # Дата начала графика — дата заседания Совета директоров Банка России, с которой будет начинаться историческая часть графика:
    start_date = None
    dates = meetingsCBR[meetingsCBR['date'] <= key_rate_model_date - 365 * 4 * day]['date']
    if not dates.empty:
        start_date = dates.values[-1].astype(d_type)
    else:
        start_date = meetingsCBR['date'].values[0].astype(d_type)
    # Дата окончания графика — десять полных лет после окончания года, на который приходится key_rate_model_date:
    stop_date = (key_rate_model_date.astype(y_type) + 11 * year).astype(d_type) - day

    # ----- ИСТОРИЧЕСКАЯ ЧАСТЬ ИНТЕРАКТИВНОГО ГРАФИКА ------------------------------------------------------------------------------------ #
    # key_rate_model_date принадлежит истории (т.е. если в key_rate_model_date изменилась Ключевая ставка, полагается, что на
    # key_rate_model_date это уже известно):
    history_period = (meetingsCBR['date'] >= start_date) & (meetingsCBR['date'] <= key_rate_model_date)
    history = meetingsCBR[['date', 'key_rate']][history_period].copy(deep=True)

    history = pd.DataFrame({
                'date':  history['date'].values.astype(s_type).astype(str).tolist(),
                'value': np.round(history['key_rate'].values * 100.0, 2).tolist()
        }).to_dict('list')

    # ----- НЕСГЛАЖЕННЫЙ ПРОГНОЗ БАНКА РОССИИ ПО КЛЮЧЕВОЙ СТАВКЕ  ------------------------------------------------------------------------ #
    cb_forecast = None
    if do_model_rates:

        cb_forecast = currentCBForecast.copy(deep=True)

        # Явно задаем последнюю координату:
        if cb_forecast['date'].values[-1] < stop_date:
            stop_rate = cb_forecast['cb_key_rate'].values[-1]
            cb_forecast = pd.concat([cb_forecast, pd.DataFrame({'date': [stop_date], 'cb_key_rate': [stop_rate]})])

        cb_forecast = pd.DataFrame({
                    'date':  cb_forecast['date'].values.astype(s_type).astype(str).tolist(),
                    'value': np.round(cb_forecast['cb_key_rate'].values, 2).tolist()
            }).to_dict('list')

    # ----- НЕСГЛАЖЕННЫЙ ПРОГНОЗ БАНКА РОССИИ ПО КЛЮЧЕВОЙ СТАВКЕ  ------------------------------------------------------------------------ #
    cb_forecast_smooth = None
    if do_model_rates:

        cb_forecast_smooth = meetingsCBRSmooth.copy(deep=True)

        # Явно задаем последнюю координату:
        if cb_forecast_smooth['date'].values[-1] < stop_date:
            stop_rate = cb_forecast_smooth['smooth_cb_key_rate'].values[-1]
            cb_forecast_smooth = pd.concat([cb_forecast_smooth, pd.DataFrame({'date': [stop_date], 'smooth_cb_key_rate': [stop_rate]})])

        cb_forecast_smooth = pd.DataFrame({
                    'date':  cb_forecast_smooth['date'].values.astype(s_type).astype(str).tolist(),
                    'value': np.round(cb_forecast_smooth['smooth_cb_key_rate'].values * 100.0, 2).tolist()
            }).to_dict('list')

    # ----- РЫНОЧНАЯ ТРАЕКТОРИЯ КЛЮЧЕВОЙ СТАВКИ ПО КОТИРОВКАМ СВОПОВ --------------------------------------------------------------------- #
    swap_forecast = None
    if do_model_rates and swap_forecast_is_valid:

        swap_forecast = keyRateSwapForecast.copy(deep=True)
        swap_forecast.sort_values(by='date', inplace=True)
        duplicates = swap_forecast['swap_key_rate'] == swap_forecast['swap_key_rate'].shift(1)
        swap_forecast = swap_forecast[~duplicates].reset_index(drop=True)

        # Явно задаем первую координату:
        if swap_forecast['date'].values[0] > keyRateSwapForecastDate:
            actual_rate = meetingsCBR[meetingsCBR['date'] <= keyRateSwapForecastDate]['key_rate'].values[-1]
            swap_forecast = pd.concat([pd.DataFrame({'date': [keyRateSwapForecastDate], 'swap_key_rate': [actual_rate]}), swap_forecast])

        # Явно задаем последнюю координату:
        if swap_forecast['date'].values[-1] < stop_date:
            stop_rate = swap_forecast['swap_key_rate'].values[-1]
            swap_forecast = pd.concat([swap_forecast, pd.DataFrame({'date': [stop_date], 'swap_key_rate': [stop_rate]})])

        swap_forecast['swap_key_rate'] = np.round(swap_forecast['swap_key_rate'].values * 100.0, 2)

        swap_forecast = pd.DataFrame({
                    'date': swap_forecast['date'].values.astype(s_type).astype(str).tolist(),
                    'value': swap_forecast['swap_key_rate'].values.tolist()
            }).to_dict('list')

    # ----- МОДЕЛЬНАЯ ТРАЕКТОРИЯ КЛЮЧЕВОЙ СТАВКИ ----------------------------------------------------------------------------------------- #
    current_forecast = None
    if not key_rate_forecast.empty:
        forecast_period = (key_rate_forecast['date'] > key_rate_model_date) & (key_rate_forecast['date'] <= stop_date)
        current_forecast = key_rate_forecast[['date', 'key_rate']][forecast_period]

        current_forecast.sort_values(by='date', inplace=True)
        duplicates = current_forecast['key_rate'] == current_forecast['key_rate'].shift(1)
        current_forecast = current_forecast[~duplicates].reset_index(drop=True)

        # Явно задаем первую координату:
        if current_forecast['date'].values[0] > key_rate_model_date + day:
            start_rate = meetingsCBR[history_period]['key_rate'].values[-1]
            current_forecast = pd.concat([pd.DataFrame({'date': [key_rate_model_date + day], 'key_rate': [start_rate]}), current_forecast])

        # Явно задаем последнюю координату:
        if current_forecast['date'].values[-1] < stop_date:
            stop_rate = current_forecast['key_rate'].values[-1]
            current_forecast = pd.concat([current_forecast, pd.DataFrame({'date': [stop_date], 'key_rate': [stop_rate]})])

    else:
    # Если Модельная траектория Ключевой ставки состоит из текущего значения Ключевой ставки на key_rate_model_date:
        start_rate = meetingsCBR[history_period]['key_rate'].values[-1]
        current_forecast = pd.DataFrame({'date': [key_rate_model_date + day, stop_date], 'key_rate': [start_rate, start_rate]})

    current_forecast['key_rate'] = np.round(current_forecast['key_rate'].values * 100.0, 2)
    current_forecast_cache = current_forecast.copy(deep=True)

    current_forecast = pd.DataFrame({
                'date': current_forecast['date'].values.astype(s_type).astype(str).tolist(),
                'value': current_forecast['key_rate'].values.tolist()
        }).to_dict('list')

    # ----- МОДЕЛЬНЫЕ УЧАСТКИ ------------------------------------------------------------------------------------------------------------ #
    # Модельный участок — горизонтальный участок на интерактивном графике, который можно с помощью мыши передвигать вверх или вниз, чтобы
    # устанавливать пользовательскую траекторию Ключевой ставки на сайте. По умолчанию устанавливается на среднегодовых значениях
    # Модельной траектории Ключевой ставки. Индикатор stop регулирует количество модельных участков, необходимое для графика:
    stop = False

    # Переформируем Модельную траекторию Ключевой ставки по дням, чтобы затем считать средние значения модельных участках:
    daily_forecast = pd.DataFrame({'date': pd.date_range(key_rate_model_date + day, stop_date)})
    daily_forecast = daily_forecast.merge(current_forecast_cache, how='left', on='date').ffill()

    # Первый модельный участок — с даты, следующей после key_rate_model_date по конец года key_rate_model_date:
    first_start = key_rate_model_date + day
    first_end = (first_start.astype(y_type) + year).astype(d_type)
    # В том случае, если first_end больше, чем stop_date, ограничиваем первый участок на stop_date:
    if stop_date < first_end:
        stop = Truefirst_end
        first_end = stop_date
    # Определяем значение, которое необходимо выставить по умолчанию на первом участке:
    first_period = (daily_forecast['date'] >= first_start) & (daily_forecast['date'] < first_end)
    first_val = np.round(daily_forecast['key_rate'][first_period].values.mean() * 4.0, 0) / 4.0

    # По аналогии определяем дату начала, дату конца и значение на втором модельном участке (если он может быть):
    second_start = None
    second_end = None
    second_val = None
    if not stop:
        second_start = first_end
        second_end = (second_start.astype(y_type) + year).astype(d_type)
        if stop_date < second_end:
            stop = True
            second_end = stop_date
        second_period = (daily_forecast['date'] >= second_start) & (daily_forecast['date'] < second_end)
        second_val = np.round(daily_forecast['key_rate'][second_period].values.mean() * 4.0, 0) / 4.0

    # По аналогии определяем дату начала, дату конца и значение на третьем модельном участке (если он может быть):
    third_start = None
    third_end = None
    third_val = None
    if not stop:
        third_start = second_end
        third_end = (third_start.astype(y_type) + year).astype(d_type)
        if stop_date < third_end:
            stop = True
            third_end = stop_date
        third_period = (daily_forecast['date'] >= third_start) & (daily_forecast['date'] < third_end)
        third_val = np.round(daily_forecast['key_rate'][third_period].values.mean() * 4.0, 0) / 4.0

    # По аналогии определяем дату начала, дату конца и значение на третьем модельном участке (если он может быть). Четвертый участок всегда
    # заканчивается на stop_date, потому что максимум модельных участков может быть четыре:
    fourth_start = None
    fourth_end = None
    fourth_val = None
    if not stop:
        fourth_start = third_end
        fourth_end = stop_date
        fourth_period = (daily_forecast['date'] >= fourth_start) & (daily_forecast['date'] <= fourth_end)
        fourth_val = np.round(daily_forecast['key_rate'][fourth_period].values.mean() * 4.0, 0) / 4.0

    keyRateInteractiveGraph = {
        'minRateLimit': 0.25,
        'maxRateLimit': 25.0,
        'macroDate': ((key_rate_model_date + day).astype(s_type) - second).astype(str),
        'history': history,
        'currentForecast': current_forecast,
        'swapForecast': swap_forecast,
        'cbForecast': cb_forecast,
        'cbForecastSmooth': cb_forecast_smooth,
        'model': [
            {
                'start': first_start.astype(s_type).astype(str),
                'end': first_end.astype(s_type).astype(str),
                'value': first_val,
            },
            {
                'start': second_start.astype(s_type).astype(str) if second_start is not None else None,
                'end': second_end.astype(s_type).astype(str) if second_end is not None else None,
                'value': second_val if second_val is not None else None,
            },
            {
                'start': third_start.astype(s_type).astype(str) if third_start is not None else None,
                'end': third_end.astype(s_type).astype(str) if third_end is not None else None,
                'value': third_val if third_val is not None else None,
            },
            {
                'start': fourth_start.astype(s_type).astype(str) if fourth_start is not None else None,
                'end': fourth_end.astype(s_type).astype(str) if fourth_end is not None else None,
                'value': fourth_val if fourth_val is not None else None,
            },
        ],

    }

    ########################################################################################################################################

    return {
        'allKeyRates': allKeyRates,
        'ratesMonthlyAvg': ratesMonthlyAvg,
        'keyRateInteractiveGraph': keyRateInteractiveGraph,
        'keyRateSwapForecastDate': keyRateSwapForecastDate,
        'currentCBForecastDate': currentCBForecastDate,
        'currentRefinancingRateDate': currentRefinancingRateDate,
        'currentRefinancingRate': currentRefinancingRate,
    }
