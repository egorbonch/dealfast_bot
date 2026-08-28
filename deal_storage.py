import uuid
from typing import Dict, Optional

# Временное хранилище сделок в памяти (In-Memory DB)
deals_db: Dict[str, dict] = {}

def create_deal(user_name: str, subject: str, amount: int, prepayment_amount: int, prepayment_percent: int, term: str) -> str:
    """Генерирует уникальный ID и сохраняет сделку"""
    deal_id = str(uuid.uuid4())[:8]
    deals_db[deal_id] = {
        "id": deal_id,
        "user_name": user_name,
        "subject": subject,
        "amount": amount,
        "prepayment_amount": prepayment_amount,
        "prepayment_percent": prepayment_percent,
        "term": term,
        "status": "pending"
    }
    return deal_id

def get_deal(deal_id: str) -> Optional[dict]:
    """Получает данные сделки по ID"""
    return deals_db.get(deal_id)