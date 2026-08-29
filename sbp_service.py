# -*- coding: utf-8 -*-
import io
import base64
import urllib.parse
import re
import qrcode


def clean_phone_number(phone: str) -> str:
    """Очищает номер телефона до 10 цифр без +7 или 8 в начале."""
    digits = re.sub(r'\D', '', str(phone))
    if len(digits) == 11 and digits[0] in ('7', '8'):
        digits = digits[1:]
    return digits


def generate_sbp_link(phone: str, amount: float | int, bank: str = "tbank", comment: str = "") -> str:
    """
    Формирует корректную HTTPS-ссылку для перевода.
    Использует универсальные HTTPS веб-ссылки вместо диплинков (sberbank://), 
    чтобы избежать ошибок 404 и блокировок внутри встроенного браузера Telegram.
    """
    phone_10 = clean_phone_number(phone)
    formatted_amount = int(amount)
    encoded_comment = urllib.parse.quote(comment)
    bank_lower = bank.lower().strip()

    # 1. Т-Банк (Форма перевода по номеру телефона)
    if bank_lower in ["tbank", "tinkoff", "т-банк", "тинькофф", "тбанк"]:
        return f"https://www.tinkoff.ru/rm/7{phone_10}/?amount={formatted_amount}&comment={encoded_comment}"

    # 2. Сбербанк (Веб-универсальная ссылка СберБанк Онлайн)
    elif bank_lower in ["sber", "sberbank", "сбер", "сбербанк"]:
        return f"https://www.sberbank.ru/ph/app/dl/pay?phone=7{phone_10}&amount={formatted_amount}"

    # 3. Альфа-Банк
    elif bank_lower in ["alfa", "alfabank", "альфа", "альфа-банк"]:
        return f"https://alfabank.ru/make-payment/?phone=7{phone_10}&amount={formatted_amount}"

    # По умолчанию — Т-Банк
    return f"https://www.tinkoff.ru/rm/7{phone_10}/?amount={formatted_amount}&comment={encoded_comment}"


def generate_qr_code_base64(data: str) -> str:
    """
    Генерирует QR-код в формате PNG и кодирует его в Base64 для прямой вставки в HTML:
    <img src="data:image/png;base64,..." />
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#10b981", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    qr_bytes = buffer.getvalue()

    return base64.b64encode(qr_bytes).decode('utf-8')