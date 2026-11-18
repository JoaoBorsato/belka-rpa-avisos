"""Ambiente de teste: cópia mínima do repositório numa pasta temporária, com o feed em disco ou rede simulada."""
import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest
import requests

from belka_avisos.robo import executar
from exemplos.montar_feed_exemplo import montar

RAIZ = Path(__file__).resolve().parents[1]
REFERENCIA = datetime.fromisoformat("2026-11-07T15:00:00-03:00")


class Resposta:
    def __init__(self, status=200, texto=""):
        self.status_code, self.content = status, texto.encode("utf-8")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class SessaoFalsa:
    """Substitui requests.Session. 'rotas' = {url: [resposta ou exceção, ...]} consumidas em ordem."""

    def __init__(self, rotas=None, post=None):
        self.rotas = {k: list(v) for k, v in (rotas or {}).items()}
        self.respostas_post = list(post or [])
        self.chamadas = []

    def get(self, url, **kw):
        self.chamadas.append(("GET", url))
        fila = self.rotas.get(url)
        r = (fila.pop(0) if len(fila) > 1 else fila[0]) if fila else Resposta(404)
        if isinstance(r, Exception):
            raise r
        return r

    def post(self, url, **kw):
        self.chamadas.append(("POST", url, kw.get("json")))
        return self.respostas_post.pop(0) if self.respostas_post else Resposta(200)


def sessao_do_feed(pasta: Path, feed_url: str) -> SessaoFalsa:
    """Serve uma cópia do feed em disco como se fosse o site do INMET."""
    rotas = {feed_url: [Resposta(200, (pasta / "rss.xml").read_text(encoding="utf-8"))]}
    for cap in (pasta / "cap").glob("*.xml"):
        rotas[f"https://apiprevmet3.inmet.gov.br/avisos/rss/{cap.stem}"] = [Resposta(200, cap.read_text(encoding="utf-8"))]
    return SessaoFalsa(rotas)


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "config").mkdir()
    cfg = json.loads((RAIZ / "config" / "config_avisos.json").read_text(encoding="utf-8"))
    cfg["rede"]["espera_inicial_s"] = 0
    (tmp_path / "config" / "config_avisos.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "entrada").mkdir()
    shutil.copy(RAIZ / "entrada" / "belka_mvp.json", tmp_path / "entrada")
    montar(tmp_path / "feed")
    return tmp_path


@pytest.fixture(autouse=True)
def sem_webhook(monkeypatch):
    monkeypatch.delenv("BELKA_WEBHOOK_URL", raising=False)


def rodar(repo, **kw):
    kw.setdefault("agora", REFERENCIA)
    kw.setdefault("ecoar_console", False)
    kw.setdefault("dormir", lambda s: None)
    if "sessao" not in kw:
        kw.setdefault("local", repo / "feed")
    return executar(repo, **kw)


def publicado(repo) -> dict:
    return json.loads((repo / "saida" / "avisos_oficiais.json").read_text(encoding="utf-8"))


def municipio(snapshot: dict, ibge: int) -> dict:
    return next(m for m in snapshot["municipios"] if m["municipio_id"] == ibge)
