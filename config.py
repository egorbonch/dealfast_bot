import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    
    # URL публичного сервера (Render.com), например: https://dealfast-app.onrender.com
    BASE_URL: str = os.getenv("BASE_URL", "http://127.0.0.1:8000")
    WEBHOOK_PATH: str = "/webhook"
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "my_super_secret_token_123")
    
    # Строка подключения к Supabase PostgreSQL
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/postgres")
    
    # Параметры СБП
    RECEIVER_PHONE: str = os.getenv("RECEIVER_PHONE", "79991234567")
    RECEIVER_BANK: str = os.getenv("RECEIVER_BANK", "tbank")
    
    HOST: str = "0.0.0.0"
    PORT: int = int(os.getenv("PORT", 8000))

    class Config:
        env_file = ".env"

settings = Settings()