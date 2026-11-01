"""
Módulo 3 - Scraping de Horário de Aulas (18:50)
Navega até a seção de horários do portal UVV, identifica o dia da semana atual e captura as disciplinas do 1º e 2º tempos.
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict
from pydantic import BaseModel
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from config import settings
from .client import UVVPortalClient

logger = logging.getLogger(__name__)

# Mapeamento do dia da semana em português
WEEKDAYS_PT = {
    0: "Segunda-feira",
    1: "Terça-feira",
    2: "Quarta-feira",
    3: "Quinta-feira",
    4: "Sexta-feira",
    5: "Sábado",
    6: "Domingo"
}


class ScheduleItem(BaseModel):
    """Modelo de representação do horário das aulas da noite."""
    dia_semana: str
    data_formatada: str
    primeiro_tempo: str  # 19:10
    segundo_tempo: str   # 21:05
    sala_primeiro_tempo: Optional[str] = "Não informada"
    sala_segundo_tempo: Optional[str] = "Não informada"
    professor_primeiro_tempo: Optional[str] = None
    professor_segundo_tempo: Optional[str] = None


class ScheduleScraper:
    """
    Extrator de grade de horários de aula da noite.
    """

    def __init__(self, client: UVVPortalClient):
        self.client = client

    async def fetch_evening_schedule(self) -> ScheduleItem:
        """
        Acessa o portal, localiza a tabela de horários e extrai as matérias da noite do dia atual.
        """
        await self.client.ensure_logged_in()
        page = self.client.page

        today = datetime.now()
        weekday_idx = today.weekday()
        weekday_name = WEEKDAYS_PT.get(weekday_idx, "Hoje")
        date_formatted = today.strftime("%d/%m/%Y")

        logger.info("Acessando seção de horário de aulas: %s (%s)...", settings.uvv_schedule_url, weekday_name)
        await page.goto(settings.uvv_schedule_url, wait_until="networkidle")

        try:
            await page.wait_for_selector("table, .grade-horarios, .schedule-grid, .grid-horario", timeout=15000)
        except PlaywrightTimeoutError:
            logger.warning("Tabela de horário padrão não carregou a tempo. Prosseguindo extração com seletores alternativos.")

        primeiro_tempo = "Sem aula cadastrada / Janela"
        segundo_tempo = "Sem aula cadastrada / Janela"
        sala_1 = "Consulte o portal"
        sala_2 = "Consulte o portal"
        prof_1 = None
        prof_2 = None

        try:
            # 1. Tentar localizar coluna ou linha do dia da semana
            day_elements = await page.query_selector_all(f"th:has-text('{weekday_name}'), td:has-text('{weekday_name}'), .col-dia:has-text('{weekday_name}')")
            
            # Buscar linhas correspondentes aos tempos das 19:10 e 21:05
            row_1910 = await page.query_selector("tr:has-text('19:10'), tr:has-text('1º Tempo'), .tempo-1")
            row_2105 = await page.query_selector("tr:has-text('21:05'), tr:has-text('2º Tempo'), .tempo-2")

            if row_1910:
                text_1 = await row_1910.inner_text()
                primeiro_tempo, sala_1, prof_1 = self._parse_class_info(text_1)

            if row_2105:
                text_2 = await row_2105.inner_text()
                segundo_tempo, sala_2, prof_2 = self._parse_class_info(text_2)

            # Se não encontrou por linha de tempo, tenta buscar cards de matérias da grade geral
            if primeiro_tempo.startswith("Sem aula") and segundo_tempo.startswith("Sem aula"):
                cards = await page.query_selector_all(".materia-card, .horario-item, .aula-item")
                for card in cards:
                    txt = await card.inner_text()
                    if weekday_name.lower() in txt.lower() or "hoje" in txt.lower():
                        if "19:10" in txt or "19h" in txt or "1º" in txt:
                            primeiro_tempo, sala_1, prof_1 = self._parse_class_info(txt)
                        elif "21:05" in txt or "21h" in txt or "2º" in txt:
                            segundo_tempo, sala_2, prof_2 = self._parse_class_info(txt)

        except Exception as e:
            logger.error("Erro ao analisar grade de horário: %s", str(e))

        return ScheduleItem(
            dia_semana=weekday_name,
            data_formatada=date_formatted,
            primeiro_tempo=primeiro_tempo,
            segundo_tempo=segundo_tempo,
            sala_primeiro_tempo=sala_1,
            sala_segundo_tempo=sala_2,
            professor_primeiro_tempo=prof_1,
            professor_segundo_tempo=prof_2
        )

    def _parse_class_info(self, raw_text: str) -> tuple:
        """Extrai nome da disciplina, sala e professor a partir do texto bruto da célula/linha."""
        lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
        
        disciplina = "Disciplina Não Identificada"
        sala = "Sala/Bloco não informado"
        prof = None

        if lines:
            # Filtra linhas de horário
            clean_lines = [l for l in lines if not any(t in l for t in ["19:10", "21:05", "1º Tempo", "2º Tempo"])]
            if clean_lines:
                disciplina = clean_lines[0]
            if len(clean_lines) > 1:
                sala = clean_lines[1]
            if len(clean_lines) > 2:
                prof = clean_lines[2]

        return disciplina, sala, prof
