STOREFRONTS = {
    "de": ("www.mediamarkt.de", "EUR", ("de",)),
    "at": ("www.mediamarkt.at", "EUR", ("de",)),
    "ch": ("www.mediamarkt.ch", "CHF", ("de", "fr", "it")),
    "nl": ("www.mediamarkt.nl", "EUR", ("nl",)),
    "be": ("www.mediamarkt.be", "EUR", ("nl", "fr")),
    "es": ("www.mediamarkt.es", "EUR", ("es",)),
    "it": ("www.mediaworld.it", "EUR", ("it",)),
    "pl": ("www.mediamarkt.pl", "PLN", ("pl",)),
    "hu": ("www.mediamarkt.hu", "HUF", ("hu",)),
    "tr": ("www.mediamarkt.com.tr", "TRY", ("tr",)),
}



DELIVERY_FILTERS = {
    ("de", "de"): "sofort lieferbar", ("at", "de"): "auf Lager",
    ("ch", "de"): "sofort lieferbar", ("ch", "fr"): "En stock", ("ch", "it"): "Pronta consegna",
    ("nl", "nl"): "Op voorraad", ("be", "nl"): "Op voorraad", ("be", "fr"): "En stock",
    ("pl", "pl"): "Wysyłka natychmiastowa", ("hu", "hu"): "Raktáron",
}


def cofr_config(base):
    return {"isEnabled": True, "baseDomain": base, "channel": "DESKTOP", "isLegacyDataExcluded": False,
            "features": {"badges": {"isFreeShippingBadgeIncluded": False}, "crossSalesLine": {"isEnabled": True, "isOutputForced": False},
                "onlineStatus": {"isPermanentlyNaIndexEnabled": True}, "pickup": {"isStrictPickupDisplayStatusEnabled": False},
                "price": {"strikePriceTypes": [{"strikePriceType": "lop"}, {"strikePriceType": "rrp", "shouldBeStruck": True, "showDiscountBadge": True, "isLegalTextInlineAllowed": False}], "isBasePriceRequiredFlagRespected": False, "isDiscountLabelEnabled": True, "isDiscountPercentageShown": True, "isDisplayPriceWithStrikePriceRrpThemed": True, "isLongerStrikePricePrefixAllowed": False, "isPromoPriceFiltered": True, "isPromoPriceUsedAsDisplayPriceInApp": False, "isHistoryChartEnabled": False, "discountPercentageMinimum": 10, "discountPercentageMinimumFractionDigits": 0},
                "delivery": {"isDeliveryStatusByEarliestDateEnabled": True, "isLocationSourcingEnabled": True, "isLocationSourcingMarketplaceEnabled": True}, "refurbishedGoods": {"isEnabled": True}}, "client": {}}
