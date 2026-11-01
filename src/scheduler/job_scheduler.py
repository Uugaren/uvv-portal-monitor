"""
Módulo de Agendamento (APScheduler)
Orquestra tarefas periódicas: Scraping de atividades de manhã e scraping de horários às 18:50.
"""

import logging
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import settings
from src.scraper import UVVPortalClient, ActivityScraper, ScheduleScraper, format_activities_json
from src.bot import UVVTelegramBot

logger = logging.getLogger(__name__)


class UVVScheduler:
    """
    Gerenciador de agendamentos assíncronos para o robô da UVV.
    """

    def __init__(self, bot: UVVTelegramBot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler()

    def start(self):
        """Configura os crons e inicia o agendador."""
        logger.info("Configurando jobs no APScheduler...")

        # Job da Manhã - Scraping de Atividades (ex: 07:00)
        self.scheduler.add_job(
            func=self.run_morning_routine,
            trigger=CronTrigger(hour=settings.morning_cron_hour, minute=settings.morning_cron_minute),
            id="job_morning_activities",
            name="Scraping de Atividades Matutinas",
            replace_existing=True
        )
        logger.info(
            "Job Matutino agendado para rodar diariamente às %02d:%02d.",
            settings.morning_cron_hour, settings.morning_cron_minute
        )

        # Job das 18:50 - Scraping de Horário de Aulas
        self.scheduler.add_job(
            func=self.run_evening_routine,
            trigger=CronTrigger(hour=settings.evening_cron_hour, minute=settings.evening_cron_minute),
            id="job_evening_schedule",
            name="Scraping de Horário de Aulas (Noite)",
            replace_existing=True
        )
        logger.info(
            "Job Noturno agendado para rodar diariamente às %02d:%02d.",
            settings.evening_cron_hour, settings.evening_cron_minute
        )

        self.scheduler.start()
        logger.info("APScheduler iniciado com sucesso.")

    def stop(self):
        """Para o agendador."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("APScheduler parado.")

    async def run_morning_routine(self):
        """Executa Módulo 1 (Scraping de Atividades) + Módulo 2 (Notificação Telegram)."""
        logger.info("--- Iniciando Rotina Matutina (Módulo 1 & 2) ---")
        try:
            async with UVVPortalClient() as client:
                scraper = ActivityScraper(client)
                activities = await scraper.fetch_today_activities()
                
                # Exibir payload JSON formatado nos logs
                json_payload = format_activities_json(activities)
                logger.info("Payload JSON gerado para atividades matutinas:\n%s", json_payload)

                # Enviar resumo diário para o Telegram
                await self.bot.send_daily_activities_summary(activities)

        except Exception as e:
            logger.error("Erro crítico na rotina matutina: %s", str(e), exc_info=True)

    async def run_evening_routine(self):
        """Executa Módulo 3 (Scraping de Horário de Aulas 18:50) + Notificação Telegram."""
        logger.info("--- Iniciando Rotina Noturna 18:50 (Módulo 3) ---")
        try:
            async with UVVPortalClient() as client:
                scraper = ScheduleScraper(client)
                schedule_item = await scraper.fetch_evening_schedule()
                
                logger.info("Dados obtidos das aulas da noite: %s", schedule_item.model_dump_json())

                # Enviar notificação direta do horário para o Telegram
                await self.bot.send_evening_schedule_notification(schedule_item)

        except Exception as e:
            logger.error("Erro crítico na rotina noturna (18:50): %s", str(e), exc_info=True)
