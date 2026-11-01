"""
Módulo de Captura de Anexos das Atividades.
Extrai nome e link de cada anexo publicado na atividade do portal.
"""

import re
import html
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


def extract_attachment_links(html_str: str, base_url: str = "https://aluno.uvv.br") -> List[Dict[str, str]]:
    """
    Inspeciona HTML em busca de links de anexos (ex: /Aluno/BaixarArquivoPost?aId=...&pId=...).
    Retorna uma lista de dicionários com 'nome' e 'url'.
    """
    if not html_str:
        return []

    attachments: List[Dict[str, str]] = []
    seen_urls = set()

    # Regex para capturar tags <a> completas
    a_tag_pattern = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
    
    # Atributos adicionais (title, download, etc.)
    title_pattern = re.compile(r'title=["\']([^"\']+)["\']', re.IGNORECASE)

    for match in a_tag_pattern.finditer(html_str):
        raw_href = match.group(1).strip()
        inner_html = match.group(2).strip()
        full_tag = match.group(0)

        # Verificar se é link de download de arquivo (contém Baixar, Arquivo, Post, ou extensão conhecida)
        is_attachment = any(kw in raw_href.lower() for kw in [
            "baixar", "arquivo", "download", "post", "anexo"
        ])

        # Se tiver atributo title com extensão de arquivo, também consideraremos
        title_match = title_pattern.search(full_tag)
        title_val = title_match.group(1).strip() if title_match else ""

        has_file_extension = any(ext in (title_val + raw_href + inner_html).lower() for ext in [
            ".pptx", ".ppt", ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".zip", ".rar", ".txt", ".png", ".jpg", ".jpeg", ".csv"
        ])

        if is_attachment or has_file_extension:
            # Formatar URL completa
            raw_href = html.unescape(raw_href)
            if raw_href.startswith("http://") or raw_href.startswith("https://"):
                url = raw_href
            else:
                if not raw_href.startswith("/"):
                    raw_href = "/" + raw_href
                url = f"{base_url.rstrip('/')}{raw_href}"

            if url in seen_urls:
                continue
            seen_urls.add(url)

            # Determinar nome do arquivo
            filename = title_val
            if not filename:
                # Tentar limpar o inner_html (remover tags internas se houver)
                clean_inner = re.sub(r'<[^>]+>', '', inner_html).strip()
                if clean_inner and not clean_inner.lower().startswith("baixar"):
                    filename = clean_inner
                else:
                    # Extrair do parâmetro title ou nome na URL
                    filename = "anexo_atividade"

            # Garantir sanitização simples do nome do arquivo
            filename = re.sub(r'[\\/*?:"<>|]', '_', filename)

            attachments.append({
                "nome": filename,
                "url": url
            })

    logger.info("Extraídos %d link(s) de anexo(s) do HTML.", len(attachments))
    return attachments
