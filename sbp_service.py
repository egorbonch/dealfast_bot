import io
import base64
import urllib.parse
import qrcode

def generate_sbp_link(phone: str, amount: int, bank: str = "tbank", comment: str = "") -> str:
    """
    Формирует Deep-Link или веб-ссылку для моментального перехода в мобильный банк.
    Поддерживает: Т-Банк, Сбербанк, Альфа-Банк и универсальный формат СБП (НСПК).
    """
    clean_phone = ''.join(filter(str.isdigit, phone))
    encoded_comment = urllib.parse.quote(comment)

    bank_lower = bank.lower().strip()

    if bank_lower in ["tbank", "tinkoff", "т-банк", "тинькофф"]:
        # Ссылка формы перевода по номеру телефона в Т-Банке
        return f"https://www.tinkoff.ru/rm/{clean_phone}/?amount={amount}&comment={encoded_comment}"
    
    elif bank_lower in ["sber", "sberbank", "сбер", "сбербанк"]:
        # Deep-link для мобильного приложения СберБанк Онлайн
        return f"sberbank://payments/transfer/by-phone?phone={clean_phone}&amount={amount}"
    
    elif bank_lower in ["alfa", "alfabank", "альфа"]:
        # Deep-link / веб-ссылка Альфа-Банка
        return f"https://alfabank.ru/make-payment/?phone={clean_phone}&amount={amount}"
    
    else:
        # Стандартная динамическая СБП-ссылка НСПК
        return f"https://qr.nspk.ru/BS100000000000000000000000000000?type=01&bank=100000000004&sum={amount*100}&cur=RUB"

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

    # Генерация изображения в оперативной памяти
    img = qr.make_image(fill_color="#10b981", back_color="white")
    
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    qr_bytes = buffer.getvalue()
    
    return base64.b64encode(qr_bytes).decode('utf-8')