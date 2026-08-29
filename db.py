import asyncpg
from typing import Optional, Dict, Any
from config import settings

pool: Optional[asyncpg.Pool] = None

async def init_db():
    """Инициализация пула подключений к PostgreSQL Supabase"""
    global pool
    pool = await asyncpg.create_pool(
        dsn=settings.DATABASE_URL,
        min_size=1,
        max_size=10,
        timeout=30.0
    )
    print("✅ Пул подключений к PostgreSQL (Supabase) успешно создан")

async def close_db():
    """Закрытие пула подключений при остановке приложения"""
    global pool
    if pool:
        await pool.close()
        print("🛑 Пул подключений к PostgreSQL закрыт")

async def create_invoice(creator_id: int, title: str, amount: float, prepayment: float = 0.0) -> Dict[str, Any]:
    """Создание нового счёта в БД"""
    query = """
        INSERT INTO invoices (creator_id, title, amount, prepayment, status)
        VALUES ($1, $2, $3, $4, 'created')
        RETURNING id, creator_id, title, amount, prepayment, status, created_at;
    """
    async with pool.acquire() as connection:
        row = await connection.fetchrow(query, creator_id, title, amount, prepayment)
        return dict(row)

async def get_invoice(deal_id: str):
    """Получение счета по UUID"""
    query = """
        SELECT id, creator_id, title, amount, prepayment, status, created_at
        FROM invoices
        WHERE id = $1::uuid;
    """
    async with pool.acquire() as con:
        # Ищем запись, ID которой начинается с переданной строки deal_id
        row = await con.fetchrow(
            "SELECT * FROM invoices WHERE id::text LIKE $1 LIMIT 1",
            f"{deal_id}%"
        )
        return dict(row) if row else None

async def update_invoice_status(invoice_id: str, new_status: str) -> bool:
    """Обновление статуса счёта ('created' -> 'accepted' -> 'paid')"""
    query = """
        UPDATE invoices
        SET status = $1
        WHERE id = $2::uuid;
    """
    async with pool.acquire() as connection:
        result = await connection.execute(query, new_status, invoice_id)
        return result == "UPDATE 1"