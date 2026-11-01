"""
Ponto de Entrada Principal - Automação do Portal Acadêmico UVV
Orquestra o Bot do Telegram, APScheduler e suporte a comandos CLI manuais.
"""

import sys
import argparse
import asyncio
import logging
from config import settings
from src.bot import UVVTelegramBot
from src.scheduler import UVVScheduler

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Configuração de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("UVVAutomation")



async def main():
    parser = argparse.ArgumentParser(description="Automação Acadêmica do Portal UVV (aluno.uvv.br)")
    parser.add_argument("--run-morning", action="store_true", help="Executa imediatamente a rotina matutina de scraping de atividades")
    parser.add_argument("--run-evening", action="store_true", help="Executa imediatamente a rotina das 18:50 de horário de aulas")
    parser.add_argument("--daemon", action="store_true", help="Executa o daemon contínuo (Bot Telegram + APScheduler)")

    args = parser.parse_args()

    # Se nenhum argumento for passado, o modo daemon é o padrão se houver token do Telegram
    if not (args.run_morning or args.run_evening or args.daemon):
        args.daemon = True

    bot = UVVTelegramBot()
    scheduler = UVVScheduler(bot=bot)

    if args.run_morning:
        logger.info("Executando disparo manual da Rotina Matutina...")
        bot.setup()
        await scheduler.run_morning_routine()
        
        logger.info("Iniciando o Telegram Bot para escutar cliques de botões ('Já Feita' / 'Ignorar')...")
        try:
            await bot.start()
            logger.info("Bot ativo e aguardando suas respostas no Telegram! Pressione Ctrl+C para encerrar.")
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Encerrando o bot interativo...")
        finally:
            await bot.stop()
        return


    if args.run_evening:
        logger.info("Executando disparo manual da Rotina Noturna (18:50)...")
        bot.setup()
        await scheduler.run_evening_routine()
        return

    if args.daemon:
        logger.info("Iniciando sistema no modo Daemon (APScheduler + Telegram Bot)...")
        bot.setup()
        scheduler.start()
        
        try:
            await bot.start()
            logger.info("Sistema em execução. Pressione Ctrl+C para encerrar.")
            # Manter o evento rodando indefinidamente
            while True:
                await asyncio.sleep(3600)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Encerrando aplicação...")
        finally:
            scheduler.stop()
            await bot.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Programa finalizado pelo usuário.")
