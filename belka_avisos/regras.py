"""
Regras de negócio do robô. Todas as tabelas de conversão vêm de config/config_avisos.json.

Nível da Belka (o mesmo do MVP, campo 'equivalente_inmet'):
  0 Sem alerta · 1 Fique de olho (perigo potencial) · 2 Prepare-se (perigo) · 3 Aja agora (grande perigo)
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from .cap import Aviso, AvisoInvalido

NIVEIS = {0: "Sem alerta", 1: "Fique de olho", 2: "Prepare-se", 3: "Aja agora"}
GRAU_INMET = {1: "Perigo Potencial", 2: "Perigo", 3: "Grande Perigo"}

_GRAU_NO_TITULO = re.compile(r"grau:\s*(.+)$", re.I)


def nivel_do_aviso(aviso: Aviso, cfg: dict) -> tuple[int, str, str | None]:
    """
    Converte a severidade do INMET no nível da Belka.
    Usa três sinais do próprio aviso: <severity>, a cor (ColorRisk) e o grau escrito no título.
    Devolve (nível, sinais usados, inconsistência ou None). Sinais em conflito: vale o mais grave.
    """
    sinais = {}
    if aviso.severity in cfg["severidade_para_nivel"]:
        sinais["severity"] = cfg["severidade_para_nivel"][aviso.severity]
    if aviso.cor and aviso.cor in cfg["cor_para_nivel"]:
        sinais["cor"] = cfg["cor_para_nivel"][aviso.cor]
    m = _GRAU_NO_TITULO.search(aviso.headline or "")
    if m and m.group(1).strip().rstrip(".").lower() in cfg["grau_para_nivel"]:
        sinais["titulo"] = cfg["grau_para_nivel"][m.group(1).strip().rstrip(".").lower()]

    if not sinais:
        raise AvisoInvalido(f"severidade não reconhecida (severity='{aviso.severity}', cor='{aviso.cor}')")
    nivel = max(sinais.values())
    inconsistencia = None
    if len(set(sinais.values())) > 1:
        inconsistencia = "sinais de severidade em conflito: " + ", ".join(f"{k}={v}" for k, v in sinais.items())
    return nivel, "+".join(sinais), inconsistencia


def riscos_do_evento(evento: str, cfg: dict) -> list[str]:
    return list(cfg["evento_para_riscos"].get(evento, ["outro"]))


def municipios_afetados(aviso: Aviso, piloto: list[dict]) -> tuple[set[int], str]:
    """
    Quais municípios piloto o aviso atinge.
    1º critério: código IBGE na lista 'Municipios' do CAP (exato).
    2º critério, se o CAP não trouxer a lista: mesorregião citada em areaDesc.
    """
    ids_piloto = {m["ibge"] for m in piloto}
    if aviso.municipios:
        return {ibge for _, _, ibge in aviso.municipios} & ids_piloto, "codigo_ibge"
    if aviso.mesorregioes:
        citadas = {m.lower() for m in aviso.mesorregioes}
        return {m["ibge"] for m in piloto if m["mesorregiao"].lower() in citadas}, "mesorregiao"
    return set(), "sem_area"


def situacao(onset: datetime, expires: datetime, agora: datetime, horizonte_dias: int) -> str:
    if expires <= agora:
        return "expirado"
    if onset <= agora:
        return "vigente"
    if onset <= agora + timedelta(days=horizonte_dias):
        return "proximo"
    return "fora_do_horizonte"


def comparar(nivel_oficial: int, nivel_belka: int) -> str:
    if nivel_oficial == nivel_belka:
        return "concorda"
    return "belka_abaixo" if nivel_belka < nivel_oficial else "belka_acima"
