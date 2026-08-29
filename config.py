import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    
    # URL публичного сервера (Render.com), например: https://dealfast-app.onrender.com
    BASE_URL: str = os.getenv("BASE_URL", "https://dealfast-bot.onrender.com")
    WEBHOOK_PATH: str = "/webhook"
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "my_secret_bot_5007")
    
    # Строка подключения к Supabase PostgreSQL
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    
    # Параметры СБП
    RECEIVER_PHONE: str = os.getenv("RECEIVER_PHONE", "79991234567")
    RECEIVER_BANK: str = os.getenv("RECEIVER_BANK", "tbank")
    
    HOST: str = "0.0.0.0"
    PORT: int = int(os.getenv("PORT", 8000))

    class Config:
        env_file = ".env"

settings = Settings()