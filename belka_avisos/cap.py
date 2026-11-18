"""
Leitura do feed RSS e dos documentos CAP 1.2 (Common Alerting Protocol) publicados pelo INMET.

Formato real observado no feed (apiprevmet3.inmet.gov.br/avisos/rss):
  RSS  <item> ... <guid>https://apiprevmet3.inmet.gov.br/avisos/rss/56448</guid>
  CAP  <alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
         identifier, sender, sent, status, msgType, scope, references
         <info> event, urgency, severity, certainty, onset, expires, headline, description, instruction, web
                <parameter> ColorRisk = #FFFE00
                <parameter> Municipios = "Sapeaçu - BA (2929602), Sapiranga - RS (4319901), ..."
                <area> areaDesc = "Aviso para as áreas: Metropolitana de São Paulo, Campinas, ..." + polygon

O XML é lido com defusedxml: entidades externas e "bomba de entidades" são recusadas.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

_MUNICIPIO = re.compile(r"^\s*(?P<nome>.+?)\s+-\s+(?P<uf>[A-Z]{2})\s+\((?P<ibge>\d{7})\)\s*$")


class FeedInvalido(Exception):
    """O feed RSS veio vazio, quebrado ou sem itens reconhecíveis."""


class AvisoInvalido(Exception):
    """Um documento CAP não pode ser usado (XML quebrado, campo obrigatório ausente, datas incoerentes)."""


@dataclass
class ItemRSS:
    rss_id: str
    url: str
    titulo: str


@dataclass
class Aviso:
    rss_id: str
    identifier: str
    sent: datetime
    status: str
    msg_type: str
    references: list[str]
    event: str
    severity: str
    urgency: str
    certainty: str
    onset: datetime | None
    expires: datetime | None
    headline: str
    description: str
    instruction: str
    web: str
    cor: str | None
    municipios: list[tuple[str, str, int]] = field(default_factory=list)
    municipios_malformados: int = 0
    mesorregioes: list[str] = field(default_factory=list)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _filho(el, nome: str):
    for c in el:
        if _local(c.tag) == nome:
            return c
    return None


def _texto(el, nome: str) -> str:
    c = _filho(el, nome) if el is not None else None
    return (c.text or "").strip() if c is not None and c.text else ""


def _ler_xml(texto: str, erro):
    if not texto or not texto.strip():
        raise erro("documento vazio")
    try:
        return ET.fromstring(texto.encode("utf-8"))
    except DefusedXmlException as e:
        raise erro(f"XML recusado por segurança ({type(e).__name__})") from e
    except ET.ParseError as e:
        raise erro(f"XML inválido: {e}") from e


def ler_rss(texto: str) -> tuple[list[ItemRSS], int]:
    """Devolve (itens, itens_sem_guid). Itens sem guid utilizável são contados e descartados."""
    raiz = _ler_xml(texto, FeedInvalido)
    canal = _filho(raiz, "channel") if _local(raiz.tag) == "rss" else None
    if canal is None:
        raise FeedInvalido(f"raiz <{_local(raiz.tag)}> não é um RSS com <channel>")
    itens, sem_guid = [], 0
    for item in canal:
        if _local(item.tag) != "item":
            continue
        url = _texto(item, "guid") or _texto(item, "link")
        rss_id = url.rstrip("/").rsplit("/", 1)[-1] if url else ""
        if not url.startswith("http") or not rss_id.isdigit():
            sem_guid += 1
            continue
        itens.append(ItemRSS(rss_id, url, _texto(item, "title")))
    if not itens and sem_guid == 0:
        raise FeedInvalido("feed sem nenhum <item>")
    # mais antigo primeiro: um cancelamento ou atualização sempre chega depois do aviso original
    itens.sort(key=lambda i: int(i.rss_id))
    return itens, sem_guid


def _data(texto: str, campo: str, obrigatoria: bool) -> datetime | None:
    if not texto:
        if obrigatoria:
            raise AvisoInvalido(f"campo <{campo}> ausente")
        return None
    try:
        d = datetime.fromisoformat(texto)
    except ValueError as e:
        raise AvisoInvalido(f"<{campo}> com data inválida: {texto[:30]}") from e
    if d.tzinfo is None:
        raise AvisoInvalido(f"<{campo}> sem fuso horário: {texto[:30]}")
    return d


def _referencias(texto: str) -> list[str]:
    """CAP: 'sender,identifier,sent' separados por espaço. Aceita também só o identifier."""
    refs = []
    for parte in texto.split():
        campos = parte.split(",")
        refs.append(campos[1] if len(campos) >= 3 else campos[0])
    return [r for r in refs if r]


def ler_cap(texto: str, rss_id: str) -> Aviso:
    raiz = _ler_xml(texto, AvisoInvalido)
    if _local(raiz.tag) != "alert":
        raise AvisoInvalido(f"raiz <{_local(raiz.tag)}> não é um <alert> CAP")
    info = _filho(raiz, "info")
    if info is None:
        raise AvisoInvalido("documento CAP sem <info>")

    obrig = {c: _texto(raiz, c) for c in ("identifier", "status", "msgType")}
    obrig["event"] = _texto(info, "event")
    faltando = [c for c, v in obrig.items() if not v]
    if faltando:
        raise AvisoInvalido("campo(s) obrigatório(s) ausente(s): " + ", ".join(faltando))

    msg_type = obrig["msgType"]
    onset = _data(_texto(info, "onset"), "onset", obrigatoria=msg_type != "Cancel")
    expires = _data(_texto(info, "expires"), "expires", obrigatoria=msg_type != "Cancel")
    if onset and expires and expires <= onset:
        raise AvisoInvalido(f"fim ({expires.isoformat()}) não é posterior ao início ({onset.isoformat()})")

    params = {}
    for p in info:
        if _local(p.tag) == "parameter":
            params[_texto(p, "valueName")] = _texto(p, "value")

    municipios, malformados = [], 0
    if params.get("Municipios"):
        for trecho in params["Municipios"].split(","):
            if not trecho.strip():
                continue
            m = _MUNICIPIO.match(trecho)
            if m:
                municipios.append((m["nome"], m["uf"], int(m["ibge"])))
            else:
                malformados += 1

    area = _filho(info, "area")
    area_desc = _texto(area, "areaDesc") if area is not None else ""
    mesos = [m.strip() for m in area_desc.split(":", 1)[-1].split(",") if m.strip()] if area_desc else []

    return Aviso(
        rss_id=rss_id, identifier=obrig["identifier"],
        sent=_data(_texto(raiz, "sent"), "sent", obrigatoria=True),
        status=obrig["status"], msg_type=msg_type, references=_referencias(_texto(raiz, "references")),
        event=obrig["event"], severity=_texto(info, "severity"), urgency=_texto(info, "urgency"),
        certainty=_texto(info, "certainty"), onset=onset, expires=expires,
        headline=_texto(info, "headline"), description=_texto(info, "description"),
        instruction=_texto(info, "instruction"), web=_texto(info, "web"),
        cor=(params.get("ColorRisk") or "").upper() or None,
        municipios=municipios, municipios_malformados=malformados, mesorregioes=mesos,
    )
