# -*- coding: utf-8 -*-
import asyncio
import os
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import Message

from config import settings
from nlu_service import convert_ogg_to_wav, transcribe_audio, parse_deal_details
from deal_storage import create_deal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Используем ParseMode.HTML — он максимально надежен и не ломается от символов
bot = Bot(
    token=settings.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "ℹ️ <b>Как пользоваться ботом DealFast:</b>\n\n"
        "1. Запишите и отправьте голосовое сообщение с условиями сделки.\n"
        "2. Бот автоматически распознает условия и сгенерирует счёт.\n"
        "3. Отправьте полученную ссылку покупателю для оплаты через СБП."
    )


@dp.message(CommandStart())
async def handle_start(message: types.Message):
    first_name = message.from_user.first_name or "пользователь"
    welcome_text = (
        f"👋 <b>Здравствуйте, {first_name}!</b>\n\n"
        f"Запишите голосовое сообщение с условиями сделки.\n"
        f"Пример: <i>«Делаю дизайн лендинга за 20000 рублей, предоплата 50%, срок 4 дня»</i>."
    )
    await message.answer(welcome_text)


# --- 1. ПЕРЕХВАТ ОБЫЧНЫХ ТЕКСТОВЫХ СООБЩЕНИЙ ---
@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text_message(message: Message):
    await message.answer(
        "🎙️ <b>Пожалуйста, отправьте именно голосовое сообщение</b> с описанием условий сделки.\n\n"
        "Текстовые сообщения не поддерживаются."
    )


# --- 2. ОБРАБОТКА ГОЛОСОВЫХ СООБЩЕНИЙ И ПРОВЕРКА УСЛОВИЙ ---
@dp.message(F.voice)
async def handle_voice_message(message: types.Message):
    if message.voice.file_size and message.voice.file_size > 10 * 1024 * 1024:
        await message.answer("⚠️ Голосовое сообщение слишком длинное. Пожалуйста, запишите более короткое сообщение.")
        return
        
    status_msg = await message.answer("🔄 Обрабатываю голосовое сообщение...")

    user_id = message.from_user.id
    msg_id = message.message_id
    
    ogg_path = f"temp_voice_{user_id}_{msg_id}.ogg"
    wav_path = f"temp_voice_{user_id}_{msg_id}.wav"

    try:
        file_info = await bot.get_file(message.voice.file_id)
        await bot.download_file(file_info.file_path, ogg_path)

        if not convert_ogg_to_wav(ogg_path, wav_path):
            await status_msg.edit_text("❌ Ошибка при конвертации аудиофайла.")
            return

        recognized_text = transcribe_audio(wav_path)

        if not recognized_text:
            await status_msg.edit_text("❌ Не удалось распознать речь. Запишите сообщение еще раз.")
            return

        deal_data = parse_deal_details(recognized_text)

        subject = deal_data.get("subject")
        amount = deal_data.get("amount")
        prepayment = deal_data.get("prepayment_percent")
        term = deal_data.get("term")

        if not subject or not amount or prepayment is None or not term or term == "Не указан":
            await status_msg.edit_text(
                "⚠️ <b>Не удалось чётко распознать все условия сделки.</b>\n\n"
                "Пожалуйста, запишите новое голосовое сообщение и <b>чётче проговорите пункты</b>:\n"
                "• Что именно нужно сделать (предмет работы)\n"
                "• Итоговую сумму (например: <i>15 000 рублей</i>)\n"
                "• Размер предоплаты (например: <i>10%</i> или <i>без предоплаты</i>)\n"
                "• Срок выполнения (например: <i>3 дня</i>)"
            )
            return

        user_name = message.from_user.full_name or message.from_user.first_name

        deal_id = await create_deal(
            user_name=user_name,
            subject=subject,
            amount=amount,
            prepayment_amount=deal_data["prepayment_amount"],
            prepayment_percent=prepayment,
            term=term
        )

        deal_url = f"{settings.BASE_URL}/deal/{deal_id}"

        builder = InlineKeyboardBuilder()
        builder.button(text="💳 Открыть Счёт-Соглашение", url=deal_url)

        response = (
            f"✅ <b>Счёт-Соглашение №{deal_id} сформирован!</b>\n\n"
            f"• <b>Предмет:</b> <code>{subject}</code>\n"
            f"• <b>Сумма:</b> <code>{amount} руб.</code>\n"
            f"• <b>Предоплата:</b> <code>{prepayment}%</code> ({deal_data['prepayment_amount']} руб.)\n"
            f"• <b>Срок:</b> <code>{term}</code>\n\n"
            f"🔗 Отправьте ссылку или нажмите кнопку ниже для перехода к оплате:"
        )

        await status_msg.edit_text(response, reply_markup=builder.as_markup())

    except Exception as e:
        logger.error(f"Ошибка при обработке голоса: {e}", exc_info=True)
        await status_msg.edit_text("❌ Произошла ошибка при обработке сообщения.")

    finally:
        for path in [ogg_path, wav_path]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass