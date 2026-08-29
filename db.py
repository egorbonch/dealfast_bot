# -*- coding: utf-8 -*-
import asyncpg
from typing import Optional, Dict, Any
from config import settings

db_pool: Optional[asyncpg.Pool] = None


async def init_db():
    """Инициализация пула подключений к PostgreSQL Supabase"""
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(
            dsn=settings.DATABASE_URL,
            min_size=1,
            max_size=10,
            timeout=30.0
        )
        print("✅ Пул подключений к PostgreSQL (Supabase) успешно создан")


async def close_db():
    """Закрытие пула подключений при остановке приложения"""
    global db_pool
    if db_pool:
        await db_pool.close()
        db_pool = None
        print("🛑 Пул подключений к PostgreSQL закрыт")


async def create_invoice(
    creator_id: int, 
    title: str, 
    amount: float, 
    prepayment: float = 0.0
) -> Dict[str, Any]:
    """Создание нового счёта в БД"""
    query = """
        INSERT INTO invoices (creator_id, title, amount, prepayment, status)
        VALUES ($1, $2, $3, $4, 'created')
        RETURNING id, creator_id, title, amount, prepayment, status, created_at;
    """
    async with db_pool.acquire() as connection:
        row = await connection.fetchrow(query, creator_id, title, amount, prepayment)
        return dict(row)


async def get_invoice(deal_id: str) -> Optional[Dict[str, Any]]:
    """Получение счёта по полному или сокращённому UUID (первые 8 символов)"""
    query = """
        SELECT *
        FROM invoices
        WHERE id::text LIKE $1
        LIMIT 1;
    """
    async with db_pool.acquire() as con:
        row = await con.fetchrow(query, f"{deal_id}%")
        return dict(row) if row else None


async def update_invoice_status(invoice_id: str, new_status: str) -> bool:
    """Обновление статуса счёта по полному или сокращённому UUID"""
    query = """
        UPDATE invoices
        SET status = $1
        WHERE id::text LIKE $2;
    """
    async with db_pool.acquire() as connection:
        result = await connection.execute(query, new_status, f"{invoice_id}%")
        return "UPDATE" in result