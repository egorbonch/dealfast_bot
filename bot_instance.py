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

bot = Bot(
    token=settings.BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
)
dp = Dispatcher()

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "ℹ️ *Как пользоваться ботом DealFast:*\n\n"
        "1. Отправьте голосовое или текстовое сообщение с условиями сделки (например: *'Сайт за 15000 рублей, предоплата 10%'*).\n"
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
        user_name = message.from_user.full_name or message.from_user.first_name

        # Сохранение сделки в БД/память
        deal_id = create_deal(
            user_name=user_name,
            subject=deal_data["subject"],
            amount=deal_data["amount"],
            prepayment_amount=deal_data["prepayment_amount"],
            prepayment_percent=deal_data["prepayment_percent"],
            term=deal_data["term"]
        )

        # Формирование веб-ссылки
        deal_url = f"{settings.BASE_URL}/deal/{deal_id}"

        # Создание Inline-кнопки
        builder = InlineKeyboardBuilder()
        builder.button(text="💳 Открыть Счёт-Соглашение", url=deal_url)

        response = (
            f"✅ **Счёт-Соглашение №{deal_id} сформирован!**\n\n"
            f"• **Предмет:** `{deal_data['subject']}`\n"
            f"• **Сумма:** `{deal_data['amount']} руб.`\n"
            f"• **Предоплата:** `{deal_data['prepayment_percent']}%` ({deal_data['prepayment_amount']} руб.)\n"
            f"• **Срок:** `{deal_data['term']}`\n\n"
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