# -*- coding: utf-8 -*-
from typing import Optional
from db import create_invoice, get_invoice


async def create_deal(
    user_name: str,
    subject: str,
    amount: int,
    prepayment_amount: int,
    prepayment_percent: int,
    term: str
) -> str:
    """Создаёт сделку в Supabase через db.py и возвращает короткий 8-значный ID"""
    res = await create_invoice(
        creator_id=0,
        title=subject,
        amount=float(amount),
        prepayment=float(prepayment_amount)
    )
    return str(res["id"])[:8]


async def get_deal(deal_id: str) -> Optional[dict]:
    """Получает сделку из Supabase и притягивает структуру к полям сделки"""
    invoice = await get_invoice(deal_id)
    if not invoice:
        return None

    return {
        "id": str(invoice["id"])[:8],
        "subject": invoice.get("title") or invoice.get("subject", ""),
        "amount": invoice.get("amount", 0),
        "prepayment_amount": invoice.get("prepayment", 0),
        "user_name": invoice.get("user_name", "Исполнитель"),
        "term": invoice.get("term", "По договоренности")
    }