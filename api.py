# -*- coding: utf8 -*-
from requests import post, get

# ----------------------------------------------------------------------------------- #
# ------- ПРИМЕРЫ ЗАПУСКА МЕТОДОВ API КАЛЬКУЛЯТОРА ИЦБ ДОМ.РФ (КОНВЕНЦИЯ 2.0) ------- #
# ----------------------------------------------------------------------------------- #

""" МЕТОД GetDataForCalculation """

link = u'https://xn--80atbdbsooh2gqb.xn--d1aqf.xn--p1ai:8193/DataSource/v1/GetDataForCalculation?isin={}'
isin = 'RU000A105NP4'

getDataForCalculation_result = get(link.format(isin)).json()

# ----------------------------------------------------------------------------------- #

""" МЕТОД Calculate """

link = u'https://xn--80atbdbsooh2gqb.xn--d1aqf.xn--p1ai:8193/Convention2/v1/Calculate'
header_dict = {'Content-Type': 'application/json'}

pricingParameters = {
                     'isin': 'RU000A105NP4',
                     'zSpread': 100
                    }

calculate_result = post(link, json = pricingParameters, headers = header_dict).json()

# ----------------------------------------------------------------------------------- #

""" МЕТОД GetZCYCCoefficients """

link = u'https://xn--80atbdbsooh2gqb.xn--d1aqf.xn--p1ai:8193/DataSource/v1/GetZCYCCoefficients?zcycDate={}'
zcycDateTime = '2023-07-26T11:27:58'

getZCYCCoefficients_result = get(link.format(zcycDateTime)).json()

# ----------------------------------------------------------------------------------- #

""" МЕТОД GetSCurveEmpiricalData """

link = u'https://xn--80atbdbsooh2gqb.xn--d1aqf.xn--p1ai:8193/DataSource/v1/GetSCurveEmpiricalData'

getSCurveEmpiricalData_result = get(link).json()

# ----------------------------------------------------------------------------------- #
