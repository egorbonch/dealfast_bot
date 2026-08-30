# -*- coding: utf-8 -*-
import re
import qrcode
import io
import base64

def clean_phone_number(phone: str) -> str:
    """Очищает номер телефона, оставляя только цифры без знака + (например 79XXXXXXXXX)"""
    digits = re.sub(r'\D', '', str(phone or ""))
    if digits.startswith('8') and len(digits) == 11:
        digits = '7' + digits[1:]
    elif len(digits) == 10:
        digits = '7' + digits
    return digits

def format_phone_display(phone: str) -> str:
    """Форматирует номер для удобного чтения: +7 (9XX) XXX-XX-XX"""
    clean = clean_phone_number(phone)
    if len(clean) == 11:
        return f"+{clean[0]} ({clean[1:4]}) {clean[4:7]}-{clean[7:9]}-{clean[9:11]}"
    return phone or "Номер не указан"

def get_bank_links(phone: str, amount: float = 0, comment: str = "") -> dict:
    """Формирует корректные диплинки для перехода в мобильные приложения банков"""
    clean = clean_phone_number(phone)
    
    return {
        "sber": {
            "name": "СберБанк",
            "bg_color": "#21a038",
            "text_color": "#ffffff",
            "deeplink": f"sberbankonline://payments/p2p?phone={clean}&amount={amount}",
            "web_fallback": f"https://sberbank.ru/sms/p2p?phone={clean}&sum={amount}"
        },
        "tbank": {
            "name": "Т-Банк (Тинькофф)",
            "bg_color": "#ffdd2d",
            "text_color": "#000000",
            "deeplink": f"tinkoffbank://p2p?phone={clean}&amount={amount}",
            "web_fallback": f"https://www.tinkoff.ru/rm/{clean}/"
        },
        "alfa": {
            "name": "Альфа-Банк",
            "bg_color": "#ef3124",
            "text_color": "#ffffff",
            "deeplink": f"alfabank://p2p/phone?phone={clean}&amount={amount}",
            "web_fallback": "https://alfabank.ru/"
        },
        "vtb": {
            "name": "ВТБ",
            "bg_color": "#002882",
            "text_color": "#ffffff",
            "deeplink": f"vtb://p2p?phone={clean}",
            "web_fallback": "https://online.vtb.ru/"
        }
    }

def generate_qr_code_base64(data_url: str) -> str:
    """Генерирует QR-код для открытия страницы оплаты через камеру смартфона"""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(data_url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()