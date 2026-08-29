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
    Очищает предмет сделки от лишних глаголов, вводных и хвостовых слов.
    Пример: 'Необходимо сделать дизайн сайта за 4 дня' -> 'Дизайн сайта'
    """
    if not raw_subject:
        return ""
    
    text = raw_subject.strip()

    # 1. Удаление начальных вводных слов, глаголов и предлогов
    noise_prefixes = (
        r"^(необходимо|нужно|надо|требуется|хочу|заказать|делаю|делают|сделать|"
        r"создать|разработать|написать|нарисую|рисую|продам|купить|выполнить|выполню|"
        r"оформление|написание|создание|разработка|услуги|услуга|заказ|по|для|на|про|за|из|под)\s+"
    )
    
    # Рекурсивно удаляем стоп-слова в начале строки
    while re.search(noise_prefixes, text, flags=re.IGNORECASE):
        text = re.sub(noise_prefixes, "", text, flags=re.IGNORECASE).strip()

    # 2. Удаление хвостов (фразы про срок, сумму или предоплату)
    noise_suffixes = (
        r"\s+(за\s+срок.*|на\s+сумму.*|за\s+\d+.*|с\s+предоплатой.*|предоплата.*|аванс.*|срок.*)$"
    )
    text = re.sub(noise_suffixes, "", text, flags=re.IGNORECASE).strip()

    # 3. Финальная очистка пробелов и знаков препинания
    text = re.sub(r'\s+', ' ', text).strip(" .,:-–—\"'")

    return text.capitalize() if text else ""

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
    
    # Применяем улучшенную очистку предмета сделки
    subject = clean_subject(cleaned)
    
    if not subject or len(subject) < 3:
        subject = ""

    return {
        "full_text": text,
        "subject": subject,
        "amount": amount,
        "prepayment_percent": prepayment_percent,
        "prepayment_amount": prepayment_amount,
        "term": term
    }