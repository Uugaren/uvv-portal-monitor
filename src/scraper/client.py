"""
Cliente Base de Web Scraping para o Portal UVV com Playwright Assíncrono.
Gerencia ciclo de vida do navegador, autenticação e recuperação de sessão.
"""

import logging
import asyncio
from typing import Optional
from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError
from config import settings

logger = logging.getLogger(__name__)

class UVVPortalClient:
    """
    Gerenciador assíncrono de sessão do Playwright para o portal aluno.uvv.br.
    """

    def __init__(self, headless: Optional[bool] = None):
        self.headless = headless if headless is not None else settings.headless
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.is_logged_in = False

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def start(self):
        """Inicializa o Playwright e cria o contexto de navegação."""
        logger.info("Iniciando instância do Playwright (Headless: %s)...", self.headless)
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        self.page = await self._context.new_page()
        self.page.set_default_timeout(settings.browser_timeout_ms)

    async def close(self):
        """Encerra com segurança as instâncias do navegador."""
        try:
            if self.page:
                await self.page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
            logger.info("Instância do Playwright encerrada com sucesso.")
        except Exception as e:
            logger.warning("Erro ao encerrar navegador: %s", str(e))

    async def login(self) -> bool:
        """
        Realiza login headless no portal aluno.uvv.br com suporte a retentativas.
        Usa credenciais das variáveis de ambiente UVV_USER e UVV_PASS.
        """
        if not settings.uvv_user or not settings.uvv_pass:
            raise ValueError("As variáveis de ambiente UVV_USER e UVV_PASS devem estar configuradas.")

        for attempt in range(1, settings.max_login_retries + 1):
            try:
                logger.info("Tentativa de login %d/%d no portal UVV...", attempt, settings.max_login_retries)
                await self.page.goto(settings.uvv_login_url, wait_until="networkidle")

                # Verificar se já está logado ou redirecionado para a Home
                if "Home" in self.page.url or await self.page.locator(".user-profile, .menu-aluno").is_visible():
                    logger.info("Sessão válida já estabelecida no portal.")
                    self.is_logged_in = True
                    return True

                # Preencher campo de usuário
                user_input = self.page.locator(settings.selector_login_input).first
                await user_input.wait_for(state="visible", timeout=10000)
                await user_input.fill(settings.uvv_user)

                # Preencher campo de senha
                pass_input = self.page.locator(settings.selector_pass_input).first
                await pass_input.wait_for(state="visible", timeout=10000)
                await pass_input.fill(settings.uvv_pass)

                # Clicar no botão de login
                submit_btn = self.page.locator(settings.selector_submit_btn).first
                await submit_btn.click()

                # Aguardar navegação ou carregamento do Dashboard pós-login
                await self.page.wait_for_load_state("networkidle")
                
                # Validação de sucesso no login (Redirecionamento ou elemento de dashboard)
                current_url = self.page.url
                if "Login" not in current_url or await self.page.locator(".avatar, .nome-aluno, #dashboard, .header-aluno").count() > 0:
                    logger.info("Login realizado com sucesso! URL atual: %s", current_url)
                    self.is_logged_in = True
                    return True

                logger.warning("Tentativa %d: Permaneceu na página de login. Tentando novamente...", attempt)

            except PlaywrightTimeoutError as te:
                logger.error("Timeout durante tentativa de login %d: %s", attempt, str(te))
                await self._take_debug_screenshot(f"login_timeout_attempt_{attempt}.png")
            except Exception as e:
                logger.error("Erro durante login %d: %s", attempt, str(e))
                await self._take_debug_screenshot(f"login_error_attempt_{attempt}.png")

            await asyncio.sleep(2)

        self.is_logged_in = False
        raise RuntimeError("Falha ao realizar login no portal UVV após múltiplas tentativas.")

    async def ensure_logged_in(self):
        """Verifica se a sessão está ativa; se expirada, tenta relogar."""
        if not self.is_logged_in or "Login" in self.page.url:
            logger.info("Sessão não identificada ou expirada. Efetuando reautenticação...")
            await self.login()

    async def _take_debug_screenshot(self, filename: str):
        """Captura screenshot para diagnóstico em caso de erros."""
        try:
            path = f"debug_{filename}"
            if self.page:
                await self.page.screenshot(path=path, full_page=True)
                logger.debug("Screenshot de diagnóstico salvo em: %s", path)
        except Exception:
            pass
