"""
De onde vêm os avisos.

FonteINMET  lê o feed RSS do INMET e baixa o documento CAP de cada aviso, com novas tentativas.
FonteLocal  lê uma cópia do feed gravada em disco (rss.xml + cap/<id>.xml): serve para demonstração,
            testes e para reprocessar um dia sem depender da internet.
"""
from __future__ import annotations

import time
from pathlib import Path

import requests

LIMITE_BYTES = 5 * 1024 * 1024   # um CAP do INMET tem ~120 KB; acima disso é resposta anômala


class FonteIndisponivel(Exception):
    """A fonte não respondeu depois de todas as tentativas."""


def com_retentativa(funcao, descricao: str, aud, tentativas: int, espera_inicial: float, dormir=time.sleep):
    """Repete 'funcao' com espera crescente (2 s, 4 s, 8 s...). Cada falha vai para o log."""
    ultimo = None
    for n in range(1, tentativas + 1):
        try:
            return funcao()
        except (requests.RequestException, OSError, ValueError) as e:
            ultimo = e
            aud.evento("fonte", "aviso", descricao, f"tentativa {n}/{tentativas} falhou: {type(e).__name__}: {e}")
            if n < tentativas:
                dormir(espera_inicial * 2 ** (n - 1))
    raise FonteIndisponivel(f"{descricao}: {tentativas} tentativas sem sucesso ({type(ultimo).__name__})")


class FonteINMET:
    def __init__(self, feed_url: str, sessao=None, timeout: float = 30):
        self.feed_url = feed_url
        self.sessao = sessao or requests.Session()
        self.timeout = timeout
        self.descricao = feed_url

    def _get(self, url: str) -> str:
        r = self.sessao.get(url, timeout=self.timeout, headers={"User-Agent": "belka-rpa-avisos/1.0"})
        r.raise_for_status()
        corpo = r.content
        if len(corpo) > LIMITE_BYTES:
            raise ValueError(f"resposta com {len(corpo)} bytes, acima do limite")
        return corpo.decode("utf-8", errors="replace")

    def feed(self) -> str:
        return self._get(self.feed_url)

    def cap(self, rss_id: str, url: str) -> str:
        return self._get(url)


class FonteLocal:
    def __init__(self, pasta: Path):
        self.pasta = Path(pasta)
        self.descricao = f"cópia local {self.pasta.name}"

    def feed(self) -> str:
        p = self.pasta / "rss.xml"
        if not p.exists():
            raise FileNotFoundError(f"{p.name} não encontrado")
        return p.read_text(encoding="utf-8")

    def cap(self, rss_id: str, url: str) -> str:
        p = self.pasta / "cap" / f"{rss_id}.xml"
        if not p.exists():
            raise FileNotFoundError(f"cap/{p.name} não encontrado")
        return p.read_text(encoding="utf-8")
