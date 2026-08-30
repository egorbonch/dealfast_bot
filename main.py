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

# Время последнего принудительного сброса вебхука (для кулдауна)
LAST_RESET_TIME = 0.0


def get_clean_base_url(request_host: str = None) -> str:
    """Определяет базовый URL из настроек, переменных Render или хоста запроса"""
    base = getattr(settings, "BASE_URL", "") or os.getenv("RENDER_EXTERNAL_URL", "")
    if not base and request_host:
        base = f"https://{request_host}"

    base = base.strip().rstrip('/')
    if base and not base.startswith("http"):
        base = f"https://{base}"
    elif base.startswith("http://"):
        base = base.replace("http://", "https://")
        
    return base


def get_webhook_url(request_host: str = None) -> str:
    base = get_clean_base_url(request_host)
    path = getattr(settings, "WEBHOOK_PATH", "webhook").strip().lstrip('/')
    return f"{base}/{path}" if base else ""


# --- БЕЗОПАСНАЯ ФУНКЦИЯ СБРОСА И ПЕРЕПРИВЯЗКИ ВЕБХУКА ---
async def safe_repair_webhook(drop_pending: bool = True) -> bool:
    """Выполняет перепривязку вебхука с защитой от слишком частого вызова"""
    global LAST_RESET_TIME
    now = time.time()
    
    # Защитный кулдаун: не чаще 1 раза в 60 секунд
    if now - LAST_RESET_TIME < 60:
        logger.info("⏳ Пропуск сброса Webhook: кулдаун еще не истек.")
        return False

    LAST_RESET_TIME = now
    target_url = get_webhook_url()
    if not target_url:
        logger.error("❌ Не удалось получить webhook URL для перепривязки")
        return False

    try:
        await bot.delete_webhook(drop_pending_updates=drop_pending)
        await asyncio.sleep(0.5)
        res = await bot.set_webhook(
            url=target_url,
            drop_pending_updates=drop_pending,
            allowed_updates=["message", "callback_query"]
        )
        logger.info(f"🔄 Webhook успешно перепривязан! Result: {res}, URL: {target_url}")
        return res
    except Exception as e:
        logger.error(f"❌ Ошибка перепривязки Webhook: {e}")
        return False


# --- УМНЫЙ ФОНОВЫЙ МОНИТОР (SMART WATCHDOG) ---
async def smart_webhook_watchdog():
    """Раз в 30 секунд проверяет статус Telegram и авто-восстанавливает вебхук ТОЛЬКО при проблемах"""
    while True:
        try:
            await asyncio.sleep(30)
            target_url = get_webhook_url()
            if not target_url:
                continue

            info = await bot.get_webhook_info()
            
            # Условия, указывающие на то, что Telegram застрял или заблокировал доставку:
            # 1. Telegram сам сообщает об ошибке доставки (info.last_error_message)
            # 2. Накопилось более 3 зависших сообщений (info.pending_update_count > 3)
            # 3. URL слетел или не совпадает с текущим
            has_error = bool(info.last_error_message)
            stuck_queue = info.pending_update_count > 3
            url_mismatch = info.url != target_url

            if has_error or stuck_queue or url_mismatch:
                logger.warning(
                    f"⚠️ Обнаружен сбой соединения! (Ошибка: '{info.last_error_message}', "
                    f"Застряло сообщений: {info.pending_update_count}, URL: '{info.url}'). "
                    f"Запуск авто-восстановления..."
                )
                await safe_repair_webhook(drop_pending=True)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ Ошибка в работе фонового монитора: {e}")


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

    # Первоначальный авто-сброс и установка при запуске сервера
    await safe_repair_webhook(drop_pending=True)

    # Запуск умного монитора
    watchdog_task = asyncio.create_task(smart_webhook_watchdog())

    yield

    watchdog_task.cancel()
    await close_db()
    logger.info("🛑 Сервисы остановлены")


app = FastAPI(title="DealFast WebApp & Bot", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


# --- 4. ДИАГНОСТИЧЕСКИЕ ЭНДПОИНТЫ ---
@app.get("/debug/webhook")
async def debug_webhook():
    try:
        info = await bot.get_webhook_info()
        return {
            "status": "ok",
            "url": info.url,
            "pending_update_count": info.pending_update_count,
            "last_error_date": info.last_error_date,
            "last_error_message": info.last_error_message,
            "allowed_updates": info.allowed_updates
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/debug/reset-webhook")
async def force_reset_webhook(request: Request):
    """Ручной эндпоинт восстановления на случай проверки"""
    res = await safe_repair_webhook(drop_pending=True)
    return {"status": "ok", "webhook_reset": res}


@app.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {"status": "ok", "message": "DealFast Bot is running"}


@app.get("/health")
async def health_check():
    return {"status": "ok", "database": "connected"}


# --- 5. ОБРАБОТЧИК WEBHOOK (МГНОВЕННЫЙ ОТВЕТ TELEGRAM) ---
async def process_update_safely(update: Update):
    try:
        await dp.feed_update(bot, update)
    except Exception as e:
        logger.error(f"❌ Ошибка обработки обновления бота: {e}", exc_info=True)


@app.post("/webhook")
@app.post(f"/{getattr(settings, 'WEBHOOK_PATH', 'webhook').strip().lstrip('/')}")
async def bot_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.model_validate(data, context={"bot": bot})
        
        # Передаем работу в фоновый таск, а Telegram отдаем 200 OK за 1 мс
        asyncio.create_task(process_update_safely(update))
    except Exception as e:
        logger.error(f"❌ Ошибка приема вебхука Telegram: {e}", exc_info=True)

    return JSONResponse(content={"status": "ok"})


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