"""
Módulo de Configuração Centralizada
Carrega e valida variáveis de ambiente e padrões do sistema.
"""

import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(BASE_DIR, ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # UVV Portal Credentials & URLs
    uvv_user: str = Field(default="", env="UVV_USER")
    uvv_pass: str = Field(default="", env="UVV_PASS")
    uvv_login_url: str = Field(default="https://aluno.uvv.br/Login", env="UVV_LOGIN_URL")
    uvv_home_url: str = Field(default="https://aluno.uvv.br/Home", env="UVV_HOME_URL")
    uvv_calendar_url: str = Field(default="https://aluno.uvv.br/Calendario", env="UVV_CALENDAR_URL")
    uvv_schedule_url: str = Field(default="https://aluno.uvv.br/Horario", env="UVV_SCHEDULE_URL")

    # Telegram Credentials
    telegram_bot_token: str = Field(default="", env="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", env="TELEGRAM_CHAT_ID")

    # Browser & Scraping Settings
    headless: bool = Field(default=True, env="HEADLESS")
    browser_timeout_ms: int = Field(default=30000, env="BROWSER_TIMEOUT_MS")
    max_login_retries: int = Field(default=3, env="MAX_LOGIN_RETRIES")

    # Cron / Scheduler Timings
    morning_cron_hour: int = Field(default=7, env="MORNING_CRON_HOUR")
    morning_cron_minute: int = Field(default=0, env="MORNING_CRON_MINUTE")
    evening_cron_hour: int = Field(default=18, env="EVENING_CRON_HOUR")
    evening_cron_minute: int = Field(default=50, env="EVENING_CRON_MINUTE")

    # Portal UI Selectors (Fallback Resilience)
    selector_login_input: str = "input[name='Usuario'], input[name='Login'], input[type='text']"
    selector_pass_input: str = "input[name='Senha'], input[type='password']"
    selector_submit_btn: str = "button[type='submit'], input[type='submit'], .btn-login"
    
    # Green Activity Cards Selectors
    selector_green_card: str = ".card-atividade.verde, .badge-success, [data-status='verde'], .atividade-pendente-verde"
    selector_today_cell: str = ".dia-atual, td.today, .fc-day-today, [data-date-today='true']"

settings = Settings()
