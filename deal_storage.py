# -*- coding: utf-8 -*-
from typing import Optional
from db import db_pool


async def create_deal(
    user_name: str,
    subject: str,
    amount: int,
    prepayment_amount: int,
    prepayment_percent: int,
    term: str
) -> str:
    """Сохраняет сделку в Supabase и возвращает короткий 8-значный ID"""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO invoices (title, amount, prepayment, user_name, term)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id;
            """,
            subject, amount, prepayment_amount, user_name, term
        )
        full_uuid = str(row["id"])
        return full_uuid[:8]


async def get_deal(deal_id: str) -> Optional[dict]:
    """Получает сделку из Supabase по полному или короткому ID"""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM invoices WHERE id::text LIKE $1 LIMIT 1",
            f"{deal_id}%"
        )
        if not row:
            return None
        
        data = dict(row)
        return {
            "id": str(data["id"])[:8],
            "subject": data.get("title") or data.get("subject", ""),
            "amount": data.get("amount", 0),
            "prepayment_amount": data.get("prepayment", 0),
            "user_name": data.get("user_name", "Исполнитель"),
            "term": data.get("term", "Не указан")
        }