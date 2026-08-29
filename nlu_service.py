# -*- coding: utf-8 -*-
import os
import re
import logging
import speech_recognition as sr
from pydub import AudioSegment

logger = logging.getLogger(__name__)

def convert_ogg_to_wav(ogg_path: str, wav_path: str) -> bool:
    """Конвертирует голосовое сообщение Telegram (.ogg) в формат .wav (16kHz Mono)"""
    try:
        sound = AudioSegment.from_file(ogg_path, format="ogg")
        sound = sound.set_frame_rate(16000).set_channels(1)
        sound.export(wav_path, format="wav")
        return True
    except Exception as e:
        logger.error(f"Ошибка при конвертации аудио: {e}")
        return False

def transcribe_audio(wav_path: str) -> str:
    """Переводит WAV-файл в текст с помощью Google Speech Recognition API"""
    recognizer = sr.Recognizer()
    with sr.AudioFile(wav_path) as source:
        audio_data = recognizer.record(source)
        try:
            text = recognizer.recognize_google(audio_data, language="ru-RU")
            return text
        except sr.UnknownValueError:
            logger.warning("Речь не распознана")
            return ""
        except sr.RequestError as e:
            logger.error(f"Ошибка сервиса распознавания речи: {e}")
            return ""

def clean_subject(raw_subject: str) -> str:
    """
    Очищает предмет сделки от глаголов, предлогов и мусорных слов.
    Пример: 'Делаю дизайн лендинга' -> 'Дизайн лендинга'
    Пример: 'по разработке сайта для компании' -> 'Сайт для компании'
    """
    if not raw_subject:
        return "Услуга"
    
    text = raw_subject.strip()

    # Регулярное выражение для удаления начальных глаголов и предлогов
    noise_prefixes = (
        r"^(делаю|сделать|нужно|надо|создать|разработать|написать|рисую|продам|купить|"
        r"оформление|написание|создание|разработка|услуги|услуга|по|для|на|про|за|из|под)\s+"
    )

    # Повторяем удаление, если в начале несколько мусорных слов подряд
    while re.search(noise_prefixes, text, flags=re.IGNORECASE):
        text = re.sub(noise_prefixes, "", text, flags=re.IGNORECASE).strip()

    # Очищаем края от символов и лишних пробелов
    text = text.strip(" .,:-–—\"'")

    # Возвращаем с заглавной буквы
    return text.capitalize() if text else "Услуга"

def parse_deal_details(text: str) -> dict:
    """
    Извлекает параметры сделки из текста:
    - Сумма
    - Предоплата (процент и сумма)
    - Срок
    - Предмет сделки (очищенное описание)
    """
    # 1. Нормализация разрядов (например: "15.000" -> "15000")
    normalized_text = re.sub(r'(\d+)[.,](\d{3})', r'\1\2', text)

    # 2. Извлечение суммы
    amount = 0
    amount_match = re.search(
        r'(\d+[\d\s]*)\s*(рубл[ей|я|ь]|руб|тыс|тысяч[а|и]?|к\b)', 
        normalized_text, 
        re.IGNORECASE
    )
    if amount_match:
        raw_amount = amount_match.group(1).replace(" ", "")
        unit = amount_match.group(2).lower()
        if unit in ["тыс", "тысяч", "тысячи", "тысяча", "к"]:
            amount = int(raw_amount) * 1000
        else:
            amount = int(raw_amount)
    else:
        digits = re.findall(r'\b\d+\b', normalized_text)
        amount = int(digits[0]) if digits else 0

    # 3. Извлечение предоплаты
    prepayment_percent = 0
    prep_match = re.search(r'(предоплат[а|ы]|аванс)?\s*(\d+)\s*%', text, re.IGNORECASE)
    if prep_match:
        prepayment_percent = int(prep_match.group(2))

    prepayment_amount = int(amount * (prepayment_percent / 100)) if prepayment_percent else 0

    # 4. Извлечение сроков
    days_match = re.search(
        r'(\d+)\s*(дн[ей|я|ь]|день|недел[ь|и|я])', 
        text, 
        re.IGNORECASE
    )
    if days_match:
        count = int(days_match.group(1))
        period_type = days_match.group(2).lower()
        if "недел" in period_type:
            term = f"{count * 7} дней"
        else:
            term = f"{count} дней"
    else:
        term = "Не указан"

    # 5. Формирование предмета сделки (очистка от цифр, сумм и сроков)
    cleaned = normalized_text
    # Удаление упоминаний сумм и валют
    cleaned = re.sub(r'\d+[\d\s]*\s*(рубл[ей|я|ь]|руб|тыс|тысяч[а|и]?|к\b)', '', cleaned, flags=re.IGNORECASE)
    # Удаление упоминаний предоплаты
    cleaned = re.sub(r'(предоплат[а|ы]|аванс)?\s*\d+\s*%', '', cleaned, flags=re.IGNORECASE)
    # Удаление упоминаний сроков
    cleaned = re.sub(r'(\bсрок\b|\bза\b|\bна\b)?\s*\d+\s*(дн[ей|я|ь]|день|недел[ь|и|я])', '', cleaned, flags=re.IGNORECASE)
    # Удаление оставшихся стоящих отдельно цифр
    cleaned = re.sub(r'\b\d+\b', '', cleaned)
    # Очистка лишних пробелов и знаков препинания
    subject = re.sub(r'\s+', ' ', cleaned).strip(" ,.-")
    
    if not subject or len(subject) < 3:
        subject = "Выполнение работ по договоренности"
    else:
        subject = subject.capitalize()

    return {
        "full_text": text,
        "subject": clean_subject(subject),
        "amount": amount,
        "prepayment_percent": prepayment_percent,
        "prepayment_amount": prepayment_amount,
        "term": term
    }