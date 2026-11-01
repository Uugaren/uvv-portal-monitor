"""
Módulo 2 - Orquestração do Bot Telegram (python-telegram-bot v20+)
Gerencia envio de resumos diários, notificações de aulas e botões inline de acompanhamento.
"""

import logging
from typing import List, Dict, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
from config import settings
from src.scraper.activities import ActivityItem
from src.scraper.schedule import ScheduleItem
from src.scraper.completed_store import mark_activity_as_done

logger = logging.getLogger(__name__)


class UVVTelegramBot:
    """
    Gerenciador e Orquestrador do Telegram Bot para o Portal UVV.
    """

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token or settings.telegram_bot_token
        self.chat_id = chat_id or settings.telegram_chat_id
        self.application: Optional[Application] = None
        
        # Cache em memória para guardar atividades enviadas: {activity_id: ActivityItem}
        self.activity_store: Dict[str, ActivityItem] = {}

    def setup(self):
        """Inicializa os handlers da aplicação do Telegram Bot."""
        if not self.token:
            logger.warning("TELEGRAM_BOT_TOKEN não configurado. O Bot do Telegram não responderá a interações.")
            return

        self.application = (
            ApplicationBuilder()
            .token(self.token)
            .read_timeout(60)
            .write_timeout(60)
            .connect_timeout(60)
            .get_updates_read_timeout(60)
            .build()
        )

        # Registrar Handlers
        # Só responde ao chat configurado: outras pessoas que acharem o bot são ignoradas
        only_owner = filters.Chat(chat_id=int(self.chat_id)) if self.chat_id else filters.ALL
        self.application.add_handler(CommandHandler("start", self._cmd_start, filters=only_owner))
        self.application.add_handler(CommandHandler("ajuda", self._cmd_help, filters=only_owner))
        self.application.add_handler(CallbackQueryHandler(self._handle_callback))

    async def start(self):
        """Inicia a escuta ativa do bot (polling)."""
        if not self.application:
            self.setup()
        if self.application:
            logger.info("Iniciando escuta do Telegram Bot via polling...")
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()

    async def stop(self):
        """Encerra a execução do Telegram Bot."""
        if self.application:
            logger.info("Parando o Telegram Bot...")
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()

    async def send_daily_activities_summary(self, activities: List[ActivityItem]):
        """
        Envia a mensagem de resumo diário de atividades para o Telegram com botões inline.
        """
        if not self.token or not self.chat_id:
            logger.error("Token ou Chat ID do Telegram ausentes. Impossível enviar resumo.")
            return

        if not self.application:
            self.setup()

        bot = self.application.bot

        if not activities:
            text = "🎉 *Resumo Diário - Portal UVV*\n\nNenhuma atividade pendente encontrada para o dia de hoje! Bom descanso!"
            await bot.send_message(chat_id=self.chat_id, text=text, parse_mode="Markdown")
            return

        # Armazenar no cache para acesso posterior via callback
        for act in activities:
            self.activity_store[act.id] = act

        intro_text = (
            f"📋 *Resumo de Atividades UVV - Scanner de Prazos*\n"
            f"Encontrada(s) *{len(activities)}* atividade(s) distinta(s) pendente(s):\n"
        )
        await bot.send_message(chat_id=self.chat_id, text=intro_text, parse_mode="Markdown")

        # Enviar cada atividade com seus respectivos botões inline
        for act in activities:
            anexos_str = ""
            if act.anexos:
                n_anexos = len(act.anexos)
                links = "\n".join([f"  • [{a.get('nome', 'Anexo')}]({a.get('url', '')})" for a in act.anexos])
                anexos_str = f"\n📎 *Anexos ({n_anexos}):*\n{links}"

            msg_content = (
                f"📌 *{act.titulo}*\n"
                f"🏷️ *Status:* `{act.status_prazo}`\n"
                f"📚 *Disciplina:* {act.disciplina}\n"
                f"📅 *Vencimento:* `{act.data_vencimento}` (às {act.horario_limite})\n"
                f"🔗 [Acessar Tarefa no Portal]({act.url_tarefa})"
                f"{anexos_str}\n\n"
                f"📝 *Enunciado:* {act.enunciado[:300]}{'...' if len(act.enunciado) > 300 else ''}"
            )

            keyboard = [
                [
                    InlineKeyboardButton("✅ Já Feita", callback_data=f"done:{act.id}"),
                    InlineKeyboardButton("❌ Ignorar", callback_data=f"ignore:{act.id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await bot.send_message(
                chat_id=self.chat_id,
                text=msg_content,
                parse_mode="Markdown",
                disable_web_page_preview=True,
                reply_markup=reply_markup
            )

    async def send_evening_schedule_notification(self, schedule: ScheduleItem):
        """
        Envia a notificação com os horários de aulas da noite (18:50).
        """
        if not self.token or not self.chat_id:
            logger.error("Token ou Chat ID do Telegram ausentes. Impossível enviar lembrete de aula.")
            return

        if not self.application:
            self.setup()

        bot = self.application.bot

        message = (
            f"🔔 *Lembrete de Aulas da Noite - UVV*\n"
            f"🗓 *{schedule.dia_semana} ({schedule.data_formatada})*\n\n"
            f"🕗 *1º Tempo (19:10):*\n"
            f"📖 Disciplina: *{schedule.primeiro_tempo}*\n"
            f"📍 Local: `{schedule.sala_primeiro_tempo}`\n"
            f"{f'👨‍🏫 Prof: {schedule.professor_primeiro_tempo}' if schedule.professor_primeiro_tempo else ''}\n\n"
            f"🕘 *2º Tempo (21:05):*\n"
            f"📖 Disciplina: *{schedule.segundo_tempo}*\n"
            f"📍 Local: `{schedule.sala_segundo_tempo}`\n"
            f"{f'👨‍🏫 Prof: {schedule.professor_segundo_tempo}' if schedule.professor_segundo_tempo else ''}\n\n"
            f"Boa aula! 🚀"
        )

        await bot.send_message(chat_id=self.chat_id, text=message, parse_mode="Markdown")

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Trata cliques nos botões 'Já Feita' e 'Ignorar'."""
        query = update.callback_query
        if self.chat_id and str(update.effective_chat.id) != str(self.chat_id):
            await query.answer()
            return
        await query.answer()

        data = query.data
        if not data or ":" not in data:
            return

        action, act_id = data.split(":", 1)
        activity = self.activity_store.get(act_id)

        if action == "done":
            if not activity:
                await query.edit_message_reply_markup(reply_markup=None)
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="⚠️ Detalhes da atividade não encontrados em memória."
                )
                return

            mark_activity_as_done(activity.titulo, activity.disciplina, activity.data_vencimento)

            done_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Marcar como Já Feita", callback_data="none")]
            ])
            await query.edit_message_reply_markup(reply_markup=done_keyboard)

            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"✅ Atividade *\"{activity.titulo}\"* foi salva como JÁ FEITA! Ela não será mais enviada nos próximos resumos.",
                parse_mode="Markdown"
            )
            logger.info("Atividade %s (%s) marcada como concluída pelo usuário.", act_id, activity.titulo)

        elif action == "ignore":
            ignored_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Ignorado", callback_data="none")]
            ])
            await query.edit_message_reply_markup(reply_markup=ignored_keyboard)
            logger.info("Atividade %s ignorada pelo usuário.", act_id)

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "👋 Olá! Eu sou o Bot de Automação do Portal UVV.\n"
            "Vou monitorar suas atividades matutinas e enviar lembretes das suas aulas às 18:50!"
        )

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "ℹ️ *Comandos Disponíveis:*\n"
            "/start - Iniciar interação com o bot\n"
            "/ajuda - Exibir este menu de ajuda",
            parse_mode="Markdown"
        )
