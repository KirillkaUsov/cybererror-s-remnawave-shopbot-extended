"""Единый список доступных способов оплаты.

Раньше он был продублирован в трёх местах — в клавиатуре покупки, в клавиатуре
пополнения баланса и в ручке веб-аппа, — и списки успели разойтись: в
пополнении, например, не было выбора между CryptoBot и Heleket. Теперь порядок
и условия доступности живут здесь, а вызывающие только рисуют кнопки.
"""

from shop_bot.data_manager.remnawave_repository import get_setting


def _enabled(key: str) -> bool:
    return (get_setting(key) or "false").strip().lower() == "true"


def _method(
    method: str,
    purchase_callback: str | None,
    topup_callback: str | None,
    bot_default_label: str,
    webapp_default_label: str,
    icon: str,
    suffix: str = "",
) -> dict:
    return {
        "method": method,
        "purchase_callback": purchase_callback,
        "topup_callback": topup_callback,
        "webapp_id": purchase_callback,
        "bot_default_label": bot_default_label,
        "webapp_default_label": webapp_default_label,
        "icon": icon,
        "suffix": suffix,
    }


def get_available_payment_methods(include_balance: bool = False, balance: float | None = None) -> list[dict]:
    """Способы оплаты, настроенные в админке, в порядке показа.

    `include_balance` добавляет оплату с баланса — она уместна при покупке, но
    не при пополнении самого баланса.
    """
    methods: list[dict] = []

    if include_balance:
        suffix = ""
        if balance is not None:
            try:
                suffix = f" ({balance:.0f} RUB)"
            except Exception:
                pass
        balance_method = _method(
            "balance", "pay_balance", None,
            "💼 Оплатить с баланса", "Баланс", "account_balance", suffix,
        )
        methods.append(balance_method)

    if (get_setting("yookassa_shop_id") or "") and (get_setting("yookassa_secret_key") or ""):
        sbp = _enabled("sbp_enabled")
        methods.append(_method(
            "yookassa", "pay_yookassa", "topup_pay_yookassa",
            "🏦 СБП / Банковская карта" if sbp else "🏦 Банковская карта",
            "СБП / Банковская карта" if sbp else "Банковская карта",
            "credit_card",
        ))

    if _enabled("platega_payform_enabled"):
        methods.append(_method(
            "platega_payform", "pay_platega_payform", "topup_pay_platega_payform",
            "💳 Platega", "Platega", "credit_card",
        ))
    if _enabled("platega_enabled"):
        methods.append(_method(
            "platega", "pay_platega", "topup_pay_platega",
            "💳 СБП / Platega", "СБП / Platega", "payments",
        ))
    if _enabled("platega_crypto_enabled"):
        methods.append(_method(
            "platega_crypto", "pay_platega_crypto", "topup_pay_platega_crypto",
            "🪙 Криптовалюта", "Криптовалюта", "payments",
        ))

    # CryptoBot и Heleket закрывают одну и ту же кнопку «Криптовалюта»,
    # поэтому показываем только один из них.
    if get_setting("cryptobot_token"):
        methods.append(_method(
            "cryptobot", "pay_cryptobot", "topup_pay_cryptobot",
            "💎 Криптовалюта", "Криптовалюта", "currency_bitcoin",
        ))
    elif (get_setting("heleket_merchant_id") or "") and (get_setting("heleket_api_key") or ""):
        methods.append(_method(
            "heleket", "pay_heleket", "topup_pay_heleket",
            "💎 Криптовалюта", "Криптовалюта", "currency_bitcoin",
        ))

    if (get_setting("ton_wallet_address") or "") and (get_setting("tonapi_key") or ""):
        methods.append(_method(
            "tonconnect", "pay_tonconnect", "topup_pay_tonconnect",
            "🪙 TON Connect", "TON Connect", "wallet",
        ))
    if _enabled("stars_enabled"):
        methods.append(_method(
            "stars", "pay_stars", "topup_pay_stars",
            "⭐ Telegram Stars", "Telegram Stars", "star",
        ))
    if _enabled("yoomoney_enabled"):
        methods.append(_method(
            "yoomoney", "pay_yoomoney", "topup_pay_yoomoney",
            "💜 ЮMoney (кошелёк)", "ЮMoney (кошелёк)", "account_balance_wallet",
        ))

    return methods


def payment_method_label(method: dict, *, for_webapp: bool = False) -> str:
    """Название кнопки: заданное в админке или встроенное по умолчанию."""
    custom = get_setting(f"payment_button_{method['method']}_text")
    default = method["webapp_default_label"] if for_webapp else method["bot_default_label"]
    return f"{(custom or default)}{method.get('suffix', '')}"
