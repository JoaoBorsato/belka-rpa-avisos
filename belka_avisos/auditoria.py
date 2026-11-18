"""
Logs e trilha de auditoria do robô.

  logs/belka_avisos_<execucao>.log   log legível: data/hora | nível | etapa | resultado | item | mensagem
  logs/auditoria.jsonl               um evento JSON por linha, acumulado entre execuções

Todo texto passa por sanitizar() antes de ser gravado: tokens, senhas, e-mails, telefones e
URLs com credenciais nunca chegam ao log.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")

_MASCARAS = [
    (re.compile(r"(?i)\b(bearer|token|senha|password|api[_-]?key|secret)\b(\s*[:=]\s*|\s+)\S+"), r"\1\2***"),
    (re.compile(r"https?://[^/\s:@]+:[^/\s@]+@"), "https://***:***@"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "***@***"),
    # telefone só com DDD entre parênteses ou com +55, para não confundir com datas e IDs de execução
    (re.compile(r"(?<![\w-])(?:\+55\s?\(?\d{2}\)?|\(\d{2}\))\s?9?\d{4}-?\d{4}(?![\w-])"), "(**) *****-****"),
    (re.compile(r"(hooks\.[\w.-]+|webhook[\w.-]*)/\S+", re.I), r"\1/***"),
]


def agora() -> datetime:
    return datetime.now(FUSO)


def sanitizar(texto: object) -> str:
    s = str(texto)
    for padrao, troca in _MASCARAS:
        s = padrao.sub(troca, s)
    return s


# resultado -> nível do log
_NIVEL = {"ok": logging.INFO, "decisao": logging.INFO, "ignorado": logging.INFO,
          "aviso": logging.WARNING, "pendencia": logging.WARNING, "erro": logging.ERROR}


class Auditoria:
    def __init__(self, pasta: Path, execucao_id: str, ecoar_console: bool = True):
        pasta.mkdir(parents=True, exist_ok=True)
        self.execucao_id = execucao_id
        self.arquivo_log = pasta / f"belka_avisos_{execucao_id}.log"
        self.arquivo_jsonl = pasta / "auditoria.jsonl"
        self.contadores: Counter = Counter()
        self.pendencias: list[str] = []
        self.avisos: list[str] = []

        self.log = logging.getLogger(f"belka_avisos.{execucao_id}")
        self.log.setLevel(logging.INFO)
        self.log.propagate = False
        fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S%z")
        self._handlers = [logging.FileHandler(self.arquivo_log, encoding="utf-8")]
        if ecoar_console:
            self._handlers.append(logging.StreamHandler())
        for h in self._handlers:
            h.setFormatter(fmt)
            self.log.addHandler(h)
        self._jsonl = self.arquivo_jsonl.open("a", encoding="utf-8")

    def evento(self, etapa: str, resultado: str, item: object, mensagem: str) -> None:
        item_s = sanitizar(item) if item is not None else "-"
        msg = sanitizar(mensagem)
        self.contadores[resultado] += 1
        if resultado in ("pendencia", "erro"):
            self.pendencias.append(f"{etapa}: {item_s} {msg}".strip())
        elif resultado == "aviso":
            self.avisos.append(f"{etapa}: {item_s} {msg}".strip())
        self.log.log(_NIVEL.get(resultado, logging.INFO), f"{etapa:<12} | {resultado:<9} | {item_s} | {msg}")
        self._jsonl.write(json.dumps({
            "quando": agora().isoformat(timespec="seconds"), "execucao_id": self.execucao_id,
            "etapa": etapa, "resultado": resultado, "item": item_s, "mensagem": msg,
        }, ensure_ascii=False) + "\n")
        self._jsonl.flush()

    def fechar(self) -> None:
        self._jsonl.close()
        for h in self._handlers:
            h.close()
            self.log.removeHandler(h)
