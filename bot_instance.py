import os
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import Message, ErrorEvent
from config import settings
from nlu_service import convert_ogg_to_wav, transcribe_audio, parse_deal_details
from deal_storage import create_deal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

bot = Bot(
    token=settings.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)
dp = Dispatcher()

@dp.error()
async def global_error_handler(event: ErrorEvent):
    print(f"[CRITICAL ERROR] Неперехваченная ошибка: {event.exception}")
    
    if event.update.message:
        await event.update.message.answer(
            "⚠️ Произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте ещё раз."
        )
    return True

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "ℹ️ *Как пользоваться ботом DealFast:*\n\n"
        "1. Запишите и отправьте голосовое сообщение с условиями сделки.\n"
        "2. Бот автоматически распознает условия и сгенерирует счёт.\n"
        "3. Отправьте полученную ссылку покупателю для оплаты через СБП.",
        parse_mode="Markdown"
    )

@dp.message(CommandStart())
async def handle_start(message: types.Message):
    welcome_text = (
        f"👋 **Здравствуйте, {message.from_user.first_name}!**\n\n"
        f"Запишите голосовое сообщение с условиями сделки.\n"
        f"Пример: _«Делаю дизайн лендинга за 20000 рублей, предоплата 50%, срок 4 дня»_."
    )
    await message.answer(welcome_text)

# --- 1. ПЕРЕХВАТ ОБЫЧНЫХ ТЕКСТОВЫХ СООБЩЕНИЙ ---
@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text_message(message: Message):
    await message.answer(
        "🎙️ **Пожалуйста, отправьте именно голосовое сообщение** с описанием условий сделки.\n\n"
        "Текстовые сообщения не поддерживаются."
    )

# --- 2. ОБРАБОТКА ГОЛОСОВЫХ СООБЩЕНИЙ И ПРОВЕРКА УСЛОВИЙ ---
@dp.message(F.voice)
async def handle_voice_message(message: types.Message):
    status_msg = await message.answer("🔄 Обрабатываю голосовое сообщение...")

    user_id = message.from_user.id
    ogg_path = f"temp_voice_{user_id}.ogg"
    wav_path = f"temp_voice_{user_id}.wav"

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

        # ПРОВЕРКА: Если не удалось разобрать хотя бы один параметр
        if not subject or not amount or prepayment is None or not term or term == "Не указан":
            await status_msg.edit_text(
                "⚠️ **Не удалось чётко распознать все условия сделки.**\n\n"
                "Пожалуйста, запишите новое голосовое сообщение и **чётче проговорите пункты**:\n"
                "• Что именно нужно сделать (предмет работы)\n"
                "• Итоговую сумму (например: *15 000 рублей*)\n"
                "• Размер предоплаты (например: *10%* или *без предоплаты*)\n"
                "• Срок выполнения (например: *3 дня*)"
            )
            return

        user_name = message.from_user.full_name or message.from_user.first_name

        # Сохранение сделки в БД/память
        deal_id = create_deal(
            user_name=user_name,
            subject=subject,
            amount=amount,
            prepayment_amount=deal_data["prepayment_amount"],
            prepayment_percent=prepayment,
            term=term
        )

        # Формирование веб-ссылки
        deal_url = f"{settings.BASE_URL}/deal/{deal_id}"

        # Создание Inline-кнопки
        builder = InlineKeyboardBuilder()
        builder.button(text="💳 Открыть Счёт-Соглашение", url=deal_url)

        response = (
            f"✅ **Счёт-Соглашение №{deal_id} сформирован!**\n\n"
            f"• **Предмет:** `{subject}`\n"
            f"• **Сумма:** `{amount} руб.`\n"
            f"• **Предоплата:** `{prepayment}%` ({deal_data['prepayment_amount']} руб.)\n"
            f"• **Срок:** `{term}`\n\n"
            f"🔗 Отправьте ссылку или нажмите кнопку ниже для перехода к оплате:"
        )

        await status_msg.edit_text(response, reply_markup=builder.as_markup())

    except Exception as e:
        logger.error(f"Ошибка при обработке голоса: {e}")
        await status_msg.edit_text("❌ Произошла ошибка при обработке сообщения.")

    finally:
        for path in [ogg_path, wav_path]:
            if os.path.exists(path):
                os.remove(path)