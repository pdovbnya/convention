# -*- coding: utf8 -*-
# ----------------------------------------------------------------------------------- #
# ------------------------------ ПРИМЕР ЗАПУСКА РАСЧЕТА ----------------------------- #
# ----------------------------------------------------------------------------------- #

from convention import Convention

pricingParameters = {
                     'isin': 'RU000A105NP4',
                     'zSpread': 100
                    }

calculation_output = Convention(pricingParameters).calculate()
pricing_result = calculation_output['pricingResult']

print('---------------------------------------------------------------------')
print(u'НКД               ' + '{:.2f}'.format(pricing_result['accruedCouponInterest']) + '%  | ' + '{:.2f}'.format(pricing_result['accruedCouponInterestRub']) + u' RUB')
print(u'Грязная цена      ' + '{:.2f}'.format(pricing_result['dirtyPrice']) + '% | ' + '{:.2f}'.format(pricing_result['dirtyPriceRub']) + u' RUB')
print(u'Чистая цена       ' + '{:.2f}'.format(pricing_result['cleanPrice']) + '% | ' + '{:.2f}'.format(pricing_result['cleanPriceRub']) + u' RUB')

if pricing_result['ytm'] is not None:
    print(u'YTM               ' + '{:.2f}'.format(pricing_result['ytm']) + u' % год.')

if pricing_result['zSpread'] is not None:
    print(u'Z-спред           ' + str(pricing_result['zSpread']) + u' б.п.')

if pricing_result['gSpread'] is not None:
    print(u'G-спред           ' + str(pricing_result['gSpread']) + u' б.п.')

if pricing_result['requiredKeyRatePremium'] is not None:
    print(u'Треб. надбавка    ' + str(pricing_result['requiredKeyRatePremium']) + u' б.п.')

if pricing_result['durationMacaulay'] is not None:
    print(u'Дюрация Маколея   ' + '{:.2f}'.format(pricing_result['durationMacaulay']) + u' лет')

if pricing_result['durationModified'] is not None:
    print(u'Дюрация мод.      ' + '{:.2f}'.format(pricing_result['durationModified']) + u' п.п.')
print('---------------------------------------------------------------------')
