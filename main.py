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
from sbp_service import generate_sbp_link, generate_qr_code_base64

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Жизненный цикл приложения: старт и остановка"""
    # 1. Устанавливаем Webhook СРАЗУ при старте
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
    
    # 2. Инициализируем базу данных
    try:
        await init_db()
        print("✅ База данных подключена")
    except Exception as e:
        print(f"❌ Ошибка подключения к БД: {e}")
    
    yield
    
    # 3. Очистка при завершении
    await bot.delete_webhook()
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

@app.post(settings.WEBHOOK_PATH)
async def bot_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None)
):
    if x_telegram_bot_api_secret_token != settings.WEBHOOK_SECRET:
        return Response(status_code=401)
    
    try:
        data = await request.json()
        update = Update.model_validate(data, context={"bot": bot})
        
        # Асинхронно запускаем обработку сообщения и СРАЗУ отвечаем Telegram 200 OK
        asyncio.create_task(dp.feed_update(bot, update))
    except Exception as e:
        logger.error(f"Ошибка разбора структуры сообщения: {e}")
        
    return JSONResponse(content={"status": "ok"})

@app.get("/deal/{deal_id}", response_class=HTMLResponse)
async def render_deal_page(request: Request, deal_id: str):
    """Вывод микро-лендинга сделки с загрузкой из Supabase"""
    invoice = await get_deal(deal_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Счёт не найден или был удалён")
    
    pay_amount = float(invoice["prepayment"]) if invoice["prepayment"] > 0 else float(invoice["amount"])
    comment = f"Оплата по сделке №{invoice['id']}"
    
    pay_url = generate_sbp_link(
        phone=settings.RECEIVER_PHONE,
        amount=int(pay_amount),
        bank=settings.RECEIVER_BANK,
        comment=comment
    )
    qr_code_base64 = generate_qr_code_base64(pay_url)

    return templates.TemplateResponse(
        request=request,
        name="deal.html",
        context={
            "deal": {
                "id": str(invoice["id"])[:8],
                "subject": invoice["title"],
                "amount": float(invoice["amount"]),
                "prepayment_amount": float(invoice["prepayment"]),
                "user_name": "Исполнитель",
                "term": "По договоренности"
            },
            "pay_amount": pay_amount,
            "pay_url": pay_url,
            "qr_code_base64": qr_code_base64
        }
    )

if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=False)