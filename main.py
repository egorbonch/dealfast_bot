# -*- coding: utf-8 -*-
import os
import asyncio
import logging
import time
from typing import Any, Callable, Dict, Awaitable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
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

# Защитный таймштамп для предотвращения слишком частых сбросов вебхука (Flood Protection)
LAST_RESET_TIME = 0.0


def get_clean_base_url(request: Request = None) -> str:
    """
    Многоуровневое автоматическое определение внешнего URL:
    1. Переменная BASE_URL из config.py
    2. Автоматическая переменная RENDER_EXTERNAL_URL от хостинга Render
    3. Домен из входящего HTTP-запроса (при обращении через браузер)
    """
    base = getattr(settings, "BASE_URL", "") or os.getenv("RENDER_EXTERNAL_URL", "")
    
    if not base and request:
        base = str(request.base_url)

    base = base.strip().rstrip('/')
    if base and not base.startswith("http"):
        base = f"https://{base}"
    elif base.startswith("http://"):
        base = base.replace("http://", "https://")
        
    return base


def get_webhook_url(request: Request = None) -> str:
    base = get_clean_base_url(request)
    path = getattr(settings, "WEBHOOK_PATH", "webhook").strip().lstrip('/')
    return f"{base}/{path}" if base else ""


# --- БЕЗОПАСНАЯ ФУНКЦИЯ ВОССТАНОВЛЕНИЯ ВЕБХУКА ---
async def safe_repair_webhook(drop_pending: bool = False, request: Request = None) -> bool:
    """Переподключает вебхук с жестким ограничением частоты (кулдаун 60 сек)"""
    global LAST_RESET_TIME
    now = time.time()
    
    target_url = get_webhook_url(request=request)
    if not target_url:
        logger.error("❌ Не удалось определить BASE_URL для вебхука! Задайте RENDER_EXTERNAL_URL или BASE_URL.")
        return False

    # Защита от бана API Telegram: не чаще 1 раза в 60 секунд
    if now - LAST_RESET_TIME < 60:
        logger.info("⏳ Пропуск перезапуска Webhook: кулдаун безопасности еще не истек.")
        return False

    LAST_RESET_TIME = now
    try:
        await bot.delete_webhook(drop_pending_updates=drop_pending)
        await asyncio.sleep(0.5)
        res = await bot.set_webhook(
            url=target_url,
            drop_pending_updates=drop_pending,
            allowed_updates=["message", "callback_query"]
        )
        logger.info(f"🚀 Webhook успешно зарегистрирован: {target_url} (Result: {res})")
        return res
    except Exception as e:
        logger.error(f"❌ Ошибка установки Webhook: {e}")
        return False


# --- УМНЫЙ ФОНОВЫЙ МОНИТОР (SMART WATCHDOG) ---
async def smart_webhook_watchdog():
    """Каждую минуту проверяет состояние соединения и авто-восстанавливает его ТОЛЬКО при сбоях"""
    while True:
        try:
            await asyncio.sleep(60)
            target_url = get_webhook_url()
            info = await bot.get_webhook_info()
            
            # Критерии для автоматического восстановления:
            # 1. Telegram официально зафиксировал ошибку (info.last_error_message)
            # 2. В очереди накопилось больше 5 неотвеченных сообщений (затор)
            # 3. Адрес отвязался или не совпадает с текущим сервером
            has_error = bool(info.last_error_message)
            stuck_queue = info.pending_update_count > 5
            url_mismatch = bool(target_url and info.url != target_url)

            if has_error or stuck_queue or url_mismatch:
                logger.warning(
                    f"⚠️ Фиксация сбоя Webhook! (Ошибка: '{info.last_error_message}', "
                    f"Застряло: {info.pending_update_count}, URL в Telegram: '{info.url}'). "
                    f"Запуск авто-исправления..."
                )
                await safe_repair_webhook(drop_pending=True)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ Ошибка монитора вебхука: {e}")


# --- 1. MIDDLEWARE ДЛЯ ЗАЩИТЫ ОТ СПАМА (RATE LIMIT) ---
class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, limit: float = 0.3):
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
                    await event.answer("Слишком часто!", show_alert=False)
                return
            self.user_timestamps[user.id] = now
            
        return await handler(event, data)


dp.message.middleware(RateLimitMiddleware(limit=0.3))
dp.callback_query.middleware(RateLimitMiddleware(limit=0.3))


# --- 2. ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК ---
@dp.error()
async def global_error_handler(event: ErrorEvent):
    if isinstance(event.exception, TelegramRetryAfter):
        logger.warning(f"⚠️ Ошибка 429: ожидание {event.exception.retry_after} секунд")
        await asyncio.sleep(event.exception.retry_after + 0.5)
        return True
    logger.error(f"❌ Ошибка в обработчике aiogram: {event.exception}", exc_info=True)


# --- 3. ЖИЗНЕННЫЙ ЦИКЛ ПРИЛОЖЕНИЯ ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
        logger.info("✅ База данных подключена")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к БД: {e}")

    # Инициализация вебхука при старте
    if get_webhook_url():
        await safe_repair_webhook(drop_pending=False)

    # Запуск фонового авто-исправителя
    watchdog_task = asyncio.create_task(smart_webhook_watchdog())

    yield

    # Завершение работы без вызова delete_webhook (чтобы не отключать при деплоях)
    watchdog_task.cancel()
    await close_db()
    logger.info("🛑 Сервисы остановлены")


app = FastAPI(title="DealFast WebApp & Bot", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


# --- 4. ДИАГНОСТИЧЕСКИЕ И МОНИТОРИНГОВЫЕ ЭНДПОИНТЫ ---
@app.get("/health")
async def health_check():
    """Эндпоинт для UptimeRobot: предотвращает уход сервера в спящий режим"""
    return {"status": "ok", "database": "connected"}


@app.get("/debug/webhook")
async def debug_webhook(request: Request):
    """Полный отчет о текущем статусе соединения с Telegram"""
    try:
        info = await bot.get_webhook_info()
        return {
            "status": "ok",
            "current_telegram_url": info.url,
            "calculated_server_url": get_webhook_url(request),
            "pending_update_count": info.pending_update_count,
            "last_error_date": info.last_error_date,
            "last_error_message": info.last_error_message,
            "allowed_updates": info.allowed_updates
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/debug/reset-webhook")
async def force_reset_webhook(request: Request):
    """Принудительный ручной пересброс вебхука при тестировании"""
    res = await safe_repair_webhook(drop_pending=True, request=request)
    return {"status": "ok", "webhook_reset": res, "url": get_webhook_url(request)}


@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {"status": "ok", "message": "DealFast Bot is running"}


# --- 5. ОБРАБОТЧИК WEBHOOK (МГНОВЕННЫЙ ИЗОЛИРОВАННЫЙ ОТВЕТ) ---
async def process_update_safely(update: Update):
    """Изолированная фоновая обработка событий бота"""
    try:
        await dp.feed_update(bot, update)
    except Exception as e:
        logger.error(f"❌ Ошибка обработки обновления бота: {e}", exc_info=True)


@app.api_route("/webhook", methods=["GET", "POST"])
@app.api_route(f"/{getattr(settings, 'WEBHOOK_PATH', 'webhook').strip().lstrip('/')}", methods=["GET", "POST"])
async def bot_webhook(request: Request):
    # При открытии ссылки в браузере (GET) подтягиваем адрес хоста и настраиваем вебхук
    if request.method == "GET":
        res = await safe_repair_webhook(drop_pending=True, request=request)
        return JSONResponse(content={
            "status": "ok",
            "message": "Webhook endpoint active",
            "webhook_updated": res,
            "active_url": get_webhook_url(request)
        })

    # При получении события от Telegram (POST) мгновенно отдаем 200 OK
    try:
        data = await request.json()
        update = Update.model_validate(data, context={"bot": bot})
        asyncio.create_task(process_update_safely(update))
    except Exception as e:
        logger.error(f"❌ Ошибка приема вебхука Telegram: {e}", exc_info=True)

    return JSONResponse(content={"status": "ok"})


# --- 6. СТРАНИЦА ОФОРМЛЕНИЯ СДЕЛКИ ---
@app.get("/deal/{deal_id}", response_class=HTMLResponse)
async def render_deal_page(request: Request, deal_id: str):
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
    port = int(os.getenv("PORT", getattr(settings, "PORT", 10000)))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)