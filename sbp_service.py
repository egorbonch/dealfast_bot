# -*- coding: utf-8 -*-
import io
import base64
import urllib.parse
import re
import qrcode


def clean_phone_number(phone: str) -> str:
    """Очищает номер телефона до 10 цифр (без 7 или 8 в начале)."""
    digits = re.sub(r'\D', '', str(phone))
    if len(digits) == 11 and digits[0] in ('7', '8'):
        digits = digits[1:]
    return digits


def get_bank_links(phone: str, amount: float | int, comment: str = "") -> dict:
    """
    Формирует словарь проверенных прямых ссылок и Deep-Link'ов для каждого банка.
    """
    phone_10 = clean_phone_number(phone)
    formatted_amount = int(amount)
    encoded_comment = urllib.parse.quote(comment)

    return {
        # Т-Банк: Офиц. форма сбер/т-переводов
        "tbank": f"https://www.tinkoff.ru/rm/7{phone_10}/?amount={formatted_amount}&comment={encoded_comment}",
        
        # Сбербанк: Deep-link для моментального открытия СберБанк Онлайн
        "sber": f"sberbank://payments/transfer/by-phone?phone=7{phone_10}&amount={formatted_amount}",
        
        # Альфа-Банк
        "alfa": f"https://alfabank.ru/make-payment/?phone=7{phone_10}&amount={formatted_amount}",
        
        # Чистый номер телефона для копирования (для перевода по СБП вручную)
        "phone_raw": f"+7{phone_10}"
    }


def generate_qr_code_base64(data_url: str) -> str:
    """
    Генерирует QR-код со ссылкой на страницу счёта.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(data_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#10b981", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode('utf-8')