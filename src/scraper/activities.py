"""
Módulo 1 - Scraping de Atividades (Manhã)
Navega até o calendário do portal UVV, identifica células do dia atual e captura os cards verdes de atividades.
"""

import re
import json
import logging
from datetime import datetime, date

from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from playwright.async_api import ElementHandle, TimeoutError as PlaywrightTimeoutError

from config import settings
from .client import UVVPortalClient
from .attachment_handler import extract_attachment_links
from .completed_store import load_completed_keys, get_activity_key

logger = logging.getLogger(__name__)


def clean_html(html_str: str) -> str:
    """Remove elementos/tags HTML preservando a formatação e quebras de linha."""
    if not html_str:
        return ""
    text = re.sub(r'<br\s*/?>', '\n', html_str, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace("&nbsp;", " ").replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&").replace("&quot;", '"')
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


class ActivityItem(BaseModel):
    """Modelo de dados para representação estruturada de uma atividade."""
    id: str
    titulo: str
    disciplina: str
    horario_limite: str
    url_tarefa: str
    enunciado: str
    data_vencimento: str = ""       # Ex: "2026-08-18"
    dias_restantes: int = 0         # Ex: 0 (hoje), 3, 5, 7
    status_prazo: str = "🚨 VENCE HOJE!"  # Ex: "🚨 VENCE HOJE!", "⚠️ Faltam 3 Dias", "🗓️ Falta 1 Semana (7 dias)"
    data_captura: str
    anexos: List[Dict[str, Any]] = []  # Lista de anexos com nome e url

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)


class ActivityScraper:
    """
    Extrator de atividades do calendário do portal UVV.
    """

    def __init__(self, client: UVVPortalClient):
        self.client = client

    async def navigate_to_calendar(self):
        """Garante a navegação até a página do calendário do aluno."""
        page = self.client.page
        if "/Calendario/" in page.url:
            return

        # 1. Tentar encontrar o link dinâmico de Calendário no menu ou dashboard do portal
        try:
            cal_link = await page.query_selector("a[href*='/Calendario/'], a:has-text('Calendário'), a:has-text('Calendario')")
            if cal_link:
                href = await cal_link.get_attribute("href")
                if href:
                    url = href if href.startswith("http") else f"https://aluno.uvv.br{href}"
                    logger.info("Navegando para o calendário via link dinâmico do portal: %s", url)
                    await page.goto(url, wait_until="networkidle")
                    return
        except Exception as e:
            logger.warning("Erro ao buscar link dinâmico de calendário: %s", str(e))

        # 2. Fallback para URL configurada em settings
        logger.info("Navegando para a URL padrão de calendário: %s", settings.uvv_calendar_url)
        await page.goto(settings.uvv_calendar_url, wait_until="networkidle")

    async def fetch_today_activities(self) -> List[ActivityItem]:
        """
        Navega até a página de calendário, localiza o dia atual e extrai os cards verdes de atividades.
        Realiza deduplicação para garantir apenas tarefas distintas e calcula prazos (hoje, 3 dias, 5 dias, 1 semana).
        """
        await self.client.ensure_logged_in()
        page = self.client.page

        await self.navigate_to_calendar()

        # Aguardar carregamento da estrutura do calendário (FullCalendar .fc-day-grid ou containers padrão)
        try:
            await page.wait_for_selector(".fc-day-grid, .fc-view, .calendar-container, table, .fc", timeout=15000)
        except PlaywrightTimeoutError:
            logger.warning("Elemento padrão de calendário não localizado a tempo. Tentando prosseguir...")

        today_dt = datetime.now()
        day_str = str(today_dt.day)
        date_iso = today_dt.strftime("%Y-%m-%d")

        logger.info("Buscando células do calendário correspondentes ao dia de hoje (%s / %s)...", day_str, date_iso)

        today_cell = await self._locate_today_cell(page, day_str, date_iso)
        
        cards = []
        if today_cell:
            try:
                week_row = await today_cell.evaluate_handle("el => el.closest('.fc-row.fc-week, .fc-row, table')")
                if week_row:
                    cards = await self._find_green_cards(week_row)
            except Exception as e:
                logger.debug("Erro ao extrair via linha da semana: %s", str(e))
            
            if not cards:
                cards = await self._find_green_cards(today_cell)

        if not cards:
            logger.info("Buscando cards verdes em todo o grid do calendário...")
            cards = await self._find_green_cards(page)

        logger.info("Encontrados %d elementos candidatos a cards no calendário.", len(cards))

        raw_activities: List[ActivityItem] = []

        for idx, card in enumerate(cards, start=1):
            try:
                item = await self._process_activity_card(page, card, idx, date_iso)
                if item:
                    raw_activities.append(item)
            except Exception as e:
                logger.error("Erro ao processar card verde #%d: %s", idx, str(e))

        # DEDUPLICAÇÃO DE ATIVIDADES:
        distinct_activities: List[ActivityItem] = []
        seen_keys = set()
        for act in raw_activities:
            # Normalizar título, disciplina e data de vencimento para determinar unicidade real da tarefa
            norm_title = act.titulo.strip().lower()
            norm_disc = act.disciplina.strip().lower()
            key = f"{norm_title}_{norm_disc}_{act.data_vencimento}"
            if key not in seen_keys:
                seen_keys.add(key)
                distinct_activities.append(act)

        # Ordenar por proximidade do vencimento (mais urgentes primeiro: HOJE, 3 DIAS, 5 DIAS, 7 DIAS)
        distinct_activities.sort(key=lambda a: a.dias_restantes)

        # FILTRAR ATIVIDADES JÁ MARCADAS COMO CONCLUÍDAS ("Já feita"):
        completed_keys = load_completed_keys()
        pending_activities: List[ActivityItem] = []
        for act in distinct_activities:
            key = get_activity_key(act.titulo, act.disciplina, act.data_vencimento)
            if key in completed_keys:
                logger.info("Atividade '%s' ignorada pois está registrada como JÁ FEITA.", act.titulo)
            else:
                pending_activities.append(act)

        logger.info("Total de %d atividades DISTINTAS pendentes extraídas com sucesso (%d já concluída(s) ignorada(s)).", 
                    len(pending_activities), len(distinct_activities) - len(pending_activities))
        return pending_activities

    async def _locate_today_cell(self, page, day_str: str, date_iso: str) -> Optional[ElementHandle]:
        """Tenta encontrar o elemento HTML que representa a célula de hoje no calendário (ex: FullCalendar)."""
        selectors = [
            "td.fc-day.fc-today",
            "td.fc-today",
            "td.fc-state-highlight",
            f"td[data-date='{date_iso}']",
            settings.selector_today_cell,
            f"td:has-text('{day_str}'):has(.card-atividade, .badge, .evento, .fc-event)",
            f".dia:has-text('{day_str}')"
        ]

        for selector in selectors:
            try:
                cell = await page.query_selector(selector)
                if cell and await cell.is_visible():
                    logger.debug("Célula do dia encontrada com seletor: %s", selector)
                    return cell
            except Exception:
                continue

        return None

    async def _find_green_cards(self, scope) -> List[ElementHandle]:
        """Busca elementos com estilo/classe que identificam cards verdes de atividade, evitando sub-elementos duplicados."""
        selectors = [
            "a.fc-day-grid-event",
            ".fc-event",
            "a.fc-event",
            "[style*='#4cae4c']",
            "[style*='4cae4c']",
            "[style*='#28a745']",
            "[style*='green']",
            ".card-atividade",
            settings.selector_green_card,
            ".bg-success",
            ".badge-success"
        ]

        found_cards: List[ElementHandle] = []

        for selector in selectors:
            try:
                elements = await scope.query_selector_all(selector)
                for el in elements:
                    if await el.is_visible():
                        # Obter o elemento pai top-level do card para evitar seleções filhas/duplicadas
                        top_el = await el.evaluate_handle("e => e.closest('.fc-event, a.fc-day-grid-event, .card-atividade') || e")
                        el_handle = top_el.as_element() or el

                        # Verificar se este elemento HTML já foi adicionado
                        is_duplicate = False
                        for existing in found_cards:
                            same = await el_handle.evaluate("(a, b) => a === b", existing)
                            if same:
                                is_duplicate = True
                                break
                        
                        if is_duplicate:
                            continue

                        style_attr = (await el_handle.get_attribute("style") or "").lower()
                        class_attr = (await el_handle.get_attribute("class") or "").lower()

                        is_green = any(c in style_attr or c in class_attr for c in ["4cae4c", "28a745", "198754", "green", "verde", "success"])
                        if not is_green:
                            bg_color = await el_handle.evaluate("el => window.getComputedStyle(el).backgroundColor")
                            if "76, 174, 76" in bg_color or "40, 167, 69" in bg_color or "25, 135, 84" in bg_color:
                                is_green = True

                        if is_green or "fc-day-grid-event" in class_attr or "fc-event" in class_attr:
                            found_cards.append(el_handle)
            except Exception:
                continue

        return found_cards

    async def _extract_event_date(self, card: ElementHandle, default_date_iso: str) -> tuple[str, int, str]:
        """
        Determina a data de vencimento da atividade no FullCalendar ou texto.
        Retorna a tupla (data_vencimento_iso, dias_restantes, status_prazo).
        """
        date_str = None
        try:
            date_str = await card.evaluate("""el => {
                const eventEl = el.closest('.fc-event, a.fc-day-grid-event') || el;
                const td = eventEl.closest('td');
                const weekRow = eventEl.closest('.fc-row.fc-week, .fc-row');
                
                if (td && weekRow) {
                    const tr = td.parentElement;
                    const colIdx = Array.from(tr.children).indexOf(td);
                    const bgTd = weekRow.querySelector(`.fc-bg tr td:nth-child(${colIdx + 1})`);
                    if (bgTd) {
                        return bgTd.getAttribute('data-date');
                    }
                }
                
                const text = eventEl.innerText || '';
                const match = text.match(/(\\d{2})\\/(\\d{2})\\/(\\d{4})/);
                if (match) {
                    return `${match[3]}-${match[2]}-${match[1]}`;
                }
                return null;
            }""")
        except Exception:
            pass

        if not date_str:
            date_str = default_date_iso

        try:
            due_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            today = datetime.now().date()
            days_left = (due_date - today).days

            if days_left == 0:
                status = "🚨 VENCE HOJE!"
            elif days_left == 1:
                status = "⚠️ Vence Amanhã"
            elif days_left == 3:
                status = "⚠️ Faltam 3 Dias"
            elif days_left == 5:
                status = "📅 Faltam 5 Dias"
            elif days_left in (6, 7):
                status = "🗓️ Falta 1 Semana (7 dias)"
            elif days_left < 0:
                status = f"⌛ Vencida (há {abs(days_left)} dia(s))"
            else:
                status = f"🗓️ Faltam {days_left} dias"

            return date_str, days_left, status
        except Exception:
            return default_date_iso, 0, "🚨 VENCE HOJE!"

    async def _process_activity_card(self, page, card: ElementHandle, index: int, date_iso: str) -> Optional[ActivityItem]:
        """Clica no card da atividade, extrai as informações da modal/detalhes e retorna o item."""
        card_text = (await card.inner_text() or "").strip()
        
        horario_limite = "23:59"
        # Extrair data de vencimento e cálculo de prazo
        data_vencimento, dias_restantes, status_prazo = await self._extract_event_date(card, date_iso)

        logger.info("Processando card verde #%d [%s]: %s...", index, status_prazo, card_text.replace('\n', ' '))
        
        # Fechar modais de comunicado/anúncios do portal (ex: #myMessage) que possam bloquear cliques
        try:
            announcement = await page.query_selector("#myMessage.in, #myMessage.show, #myMessage[aria-hidden='false']")
            if announcement and await announcement.is_visible():
                close_btn = await announcement.query_selector("button.close, .btn-close, [data-dismiss='modal'], button")
                if close_btn:
                    await close_btn.click(force=True)
                    await page.wait_for_timeout(500)
        except Exception:
            pass

        obter_postagem_data = None

        try:
            # Capturar o payload JSON retornado pelo endpoint /Calendario/ObterPostagem ao clicar no card
            async with page.expect_response(lambda res: "ObterPostagem" in res.url and res.status == 200, timeout=4000) as response_info:
                await card.click(force=True)
            
            response = await response_info.value
            obter_postagem_data = await response.json()
            logger.info("ObterPostagem JSON capturado com sucesso para a atividade #%d!", index)
        except Exception as e:
            logger.debug("Falha ao capturar via expect_response: %s. Efetuando clique simples...", str(e))
            try:
                await card.click(force=True)
                await page.wait_for_timeout(1000)
            except Exception:
                pass

        titulo = ""
        disciplina = ""
        url_tarefa = page.url
        enunciado = ""

        if obter_postagem_data and isinstance(obter_postagem_data, dict):
            raw_title = obter_postagem_data.get("title") or ""
            raw_sub = obter_postagem_data.get("subtitle") or ""
            raw_desc = obter_postagem_data.get("description") or ""

            if raw_title:
                titulo = raw_title.strip()
            if raw_sub:
                disciplina = raw_sub.strip()
            if raw_desc:
                enunciado = clean_html(raw_desc)

        # Fallback se a captura da API AJAX falhou
        if not enunciado:
            modal = await page.query_selector(".modal.in, .modal.show, .modal-dialog, #modalDetalhesAtividade, .swal2-popup")
            if modal and await modal.is_visible():
                logger.info("Modal de detalhes detectada para a atividade #%d.", index)
                modal_text = await modal.inner_text()
                
                title_el = await modal.query_selector(".modal-title, h3, h4, .titulo-atividade")
                if title_el:
                    titulo = (await title_el.inner_text()).strip()

                disc_el = await modal.query_selector(".disciplina, .nome-materia, .badge-info")
                if disc_el:
                    disciplina = (await disc_el.inner_text()).strip()

                body_el = await modal.query_selector(".modal-body, .descricao-atividade, .conteudo-tarefa")
                enunciado = (await body_el.inner_text()).strip() if body_el else modal_text.strip()

                close_btn = await modal.query_selector("button.close, .btn-close, [data-dismiss='modal']")
                if close_btn:
                    await close_btn.click(force=True)
                    await page.wait_for_timeout(500)

        if not titulo:
            lines = [l.strip() for l in card_text.split("\n") if l.strip()]
            if lines:
                titulo = lines[0]
                if not disciplina and len(lines) > 1:
                    disciplina = lines[1]
            else:
                titulo = f"Atividade {index}"

        if not disciplina:
            disciplina = "Disciplina Não Especificada"
        if not enunciado:
            enunciado = f"Título: {titulo}. Atividade publicada no portal UVV."

        act_id = f"act_{data_vencimento}_{index}"

        # Captura e extração de anexos da atividade
        anexos_extraidos = []
        raw_html_content = ""
        if obter_postagem_data and isinstance(obter_postagem_data, dict):
            raw_html_content = obter_postagem_data.get("description") or ""

        if not raw_html_content:
            try:
                modal_el = await page.query_selector(".modal.in, .modal.show, .modal-dialog, #modalDetalhesAtividade, .swal2-popup")
                if modal_el:
                    raw_html_content = await modal_el.inner_html()
            except Exception:
                pass

        if raw_html_content:
            attachment_links = extract_attachment_links(raw_html_content)
            if attachment_links:
                logger.info("Encontrados %d anexo(s) para a atividade %s.", len(attachment_links), act_id)
                anexos_extraidos = [{"nome": att["nome"], "url": att["url"]} for att in attachment_links]

        item = ActivityItem(
            id=act_id,
            titulo=titulo,
            disciplina=disciplina,
            horario_limite=horario_limite,
            url_tarefa=url_tarefa,
            enunciado=enunciado,
            data_vencimento=data_vencimento,
            dias_restantes=dias_restantes,
            status_prazo=status_prazo,
            data_captura=datetime.now().isoformat(),
            anexos=anexos_extraidos
        )

        return item


def format_activities_json(activities: List[ActivityItem]) -> str:
    """Converte lista de ActivityItem em JSON formatado."""
    data = [item.model_dump() for item in activities]
    return json.dumps(data, indent=2, ensure_ascii=False)



