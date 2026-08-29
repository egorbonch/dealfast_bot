# -*- coding: utf-8 -*-
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from aiogram.types import Update
import uvicorn

from config import settings
from bot_instance import bot, dp
from db import init_db, close_db, get_invoice
from sbp_service import get_bank_links, generate_qr_code_base64

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Жизненный цикл приложения: старт и остановка"""
    # 1. Первым делом подключаемся к базе данных
    try:
        await init_db()
        print("✅ База данных подключена")
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")

    # 2. Устанавливаем Webhook
    webhook_url = f"{settings.BASE_URL}{settings.WEBHOOK_PATH}"
    try:
        await bot.set_webhook(
            url=webhook_url,
            secret_token=settings.WEBHOOK_SECRET,
            drop_pending_updates=True
        )
        print(f"🚀 Webhook успешно установлен на: {webhook_url}")
    except Exception as e:
        print(f"❌ Ошибка при установке Webhook: {e}")

    yield

    # 3. Очистка при остановке сервера
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


# Обработчик webhook:
@app.post(settings.WEBHOOK_PATH)
async def bot_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None)
):
    # БЕЗОПАСНОСТЬ: Запрос обрабатывается ТОЛЬКО если секретный токен совпадает
    if settings.WEBHOOK_SECRET:
        if x_telegram_bot_api_secret_token != settings.WEBHOOK_SECRET:
            logger.warning("⛔ Заблокирована попытка несанкционированного доступа к Webhook")
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

    # Расчет суммы к оплате (предоплата или полная сумма)
    pay_amount = prepayment if prepayment > 0 else total_amount
    comment = f"Оплата по сделке №{str(invoice['id'])[:8]}"

    # 1. Формируем ссылки для всех банков (для модального окна)
    bank_links = get_bank_links(
        phone=settings.RECEIVER_PHONE,
        amount=pay_amount,
        comment=comment
    )

    # 2. В QR-код зашиваем URL текущей страницы сделки
    deal_page_url = str(request.url)
    qr_code_base64 = generate_qr_code_base64(deal_page_url)

    # 3. Передаем обновленный контекст в HTML-шаблон
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