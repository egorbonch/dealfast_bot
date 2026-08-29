# -*- coding: utf-8 -*-
import asyncio
import logging
import time
from typing import Any, Callable, Dict, Awaitable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from aiogram import BaseMiddleware
from aiogram.types import Update, TelegramObject, CallbackQuery, ErrorEvent
from aiogram.exceptions import TelegramRetryAfter
import uvicorn

from config import settings
from bot_instance import bot, dp
from db import init_db, close_db, get_invoice
from sbp_service import get_bank_links, generate_qr_code_base64

logger = logging.getLogger(__name__)


# --- 1. MIDDLEWARE ДЛЯ ЗАЩИТЫ ОТ СПАМА ---
class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, limit: float = 0.5):
        self.limit = limit
        self.user_timestamps: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if user:
            now = time.time()
            last_time = self.user_timestamps.get(user.id, 0)
            if now - last_time < self.limit:
                if isinstance(event, CallbackQuery):
                    await event.answer("Слишком часто! Подождите секунду.", show_alert=False)
                return
            self.user_timestamps[user.id] = now
            
        return await handler(event, data)


dp.message.middleware(RateLimitMiddleware(limit=0.5))
dp.callback_query.middleware(RateLimitMiddleware(limit=0.5))


# --- 2. ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБКИ 429 ---
@dp.error()
async def global_error_handler(event: ErrorEvent):
    if isinstance(event.exception, TelegramRetryAfter):
        logger.warning(f"⚠️ Ошибка 429: ожидание {event.exception.retry_after} секунд")
        await asyncio.sleep(event.exception.retry_after + 0.5)
        return True


# --- 3. НАДЕЖНЫЙ ЖИЗНЕННЫЙ ЦИКЛ ПРИЛОЖЕНИЯ ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Жизненный цикл приложения: гарантированный сброс и установка Webhook"""
    # 1. Подключение к БД
    try:
        await init_db()
        print("✅ База данных подключена")
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")

    # 2. ПРИНУДИТЕЛЬНЫЙ СБРОС И ОБНОВЛЕНИЕ WEBHOOK
    webhook_url = f"{settings.BASE_URL}{settings.WEBHOOK_PATH}"
    secret = settings.WEBHOOK_SECRET.strip() if getattr(settings, "WEBHOOK_SECRET", None) else None

    try:
        # Сначала обязательно удаляем старый webhook, чтобы сбросить секретный токен в Telegram
        await bot.delete_webhook(drop_pending_updates=True)
        await asyncio.sleep(0.5)
        
        # Регистрируем Webhook заново с актуальным секретным токеном
        await bot.set_webhook(
            url=webhook_url,
            secret_token=secret,
            drop_pending_updates=True
        )
        print(f"🚀 Webhook гарантированно обновлен: {webhook_url}")
    except Exception as e:
        print(f"❌ Ошибка при установке Webhook: {e}")

    yield

    # 3. Очистка при остановке
    try:
        await bot.delete_webhook()
    except Exception as e:
        logger.error(f"Ошибка при удалении Webhook: {e}")

    await close_db()
    print("🛑 Сервисы остановлены")


app = FastAPI(title="DealFast WebApp & Bot", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {"status": "ok", "message": "DealFast Bot is running"}


@app.get("/health")
async def health_check():
    return {"status": "ok", "database": "connected"}


# --- 4. БЕЗОПАСНЫЙ ОБРАБОТЧИК WEBHOOK ---
@app.post(settings.WEBHOOK_PATH)
async def bot_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None)
):
    expected_secret = settings.WEBHOOK_SECRET.strip() if getattr(settings, "WEBHOOK_SECRET", None) else None

    # Проверка секретного токена с подробным логированием при расхождении
    if expected_secret:
        if x_telegram_bot_api_secret_token != expected_secret:
            logger.warning(
                f"⛔ Отклонен запрос Webhook! Получен токен: '{x_telegram_bot_api_secret_token}', ожидался: '{expected_secret}'"
            )
            return Response(status_code=401)

    try:
        data = await request.json()
        update = Update.model_validate(data, context={"bot": bot})
        asyncio.create_task(dp.feed_update(bot, update))
    except Exception as e:
        logger.error(f"❌ Ошибка разбора обновления: {e}")

    return JSONResponse(content={"status": "ok"})


@app.get("/deal/{deal_id}", response_class=HTMLResponse)
async def render_deal_page(request: Request, deal_id: str):
    """Вывод микро-лендинга сделки с загрузкой из Supabase"""
    invoice = await get_invoice(deal_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Счёт не найден или был удалён")

    prepayment = float(invoice.get("prepayment") or 0)
    total_amount = float(invoice.get("amount") or 0)

    pay_amount = prepayment if prepayment > 0 else total_amount
    comment = f"Оплата по сделке №{str(invoice['id'])[:8]}"

    bank_links = get_bank_links(
        phone=settings.RECEIVER_PHONE,
        amount=pay_amount,
        comment=comment
    )

    deal_page_url = str(request.url)
    qr_code_base64 = generate_qr_code_base64(deal_page_url)

    return templates.TemplateResponse(
        request=request,
        name="deal.html",
        context={
            "request": request,
            "deal": {
                "id": str(invoice["id"])[:8],
                "subject": invoice.get("title") or invoice.get("subject", "Услуга"),
                "amount": total_amount,
                "prepayment_amount": prepayment,
                "user_name": invoice.get("user_name", "Исполнитель"),
                "term": invoice.get("term", "По договоренности")
            },
            "pay_amount": pay_amount,
            "bank_links": bank_links,
            "qr_code_base64": qr_code_base64
        }
    )


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=False)