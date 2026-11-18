"""
O que o robô entrega ao MVP.

  saida/avisos_oficiais.json   avisos oficiais por município piloto (vigentes e próximos) + comparação com a Belka
  saida/divergencias.csv       municípios onde o nível da Belka ficou abaixo do aviso oficial (revisar limiares)
"""
from __future__ import annotations

import csv
import json
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .auditoria import FUSO
from .regras import GRAU_INMET, NIVEIS, comparar, situacao

VERSAO_CONTRATO = "1.0"


class EntradaBelkaInvalida(Exception):
    """O snapshot da Belka (belka_mvp.json) não existe ou não tem o formato esperado."""


def ler_belka(caminho: Path, ids_piloto: set[int]) -> tuple[str, dict[int, dict]]:
    """Lê o nível calculado pela Belka para o último dia do snapshot do MVP."""
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        linhas = dados["pergunta1_hoje"]
        dia = dados["periodo"]["ultimo_dia"]
        date.fromisoformat(dia)
    except FileNotFoundError as e:
        raise EntradaBelkaInvalida(f"{caminho.name} não encontrado") from e
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        raise EntradaBelkaInvalida(f"{caminho.name} fora do formato esperado ({type(e).__name__})") from e
    niveis = {}
    for l in linhas:
        if l.get("municipio_id") in ids_piloto and l.get("nivel_id") in NIVEIS:
            niveis[l["municipio_id"]] = {"nivel_id": l["nivel_id"], "risco_principal": l.get("risco_principal")}
    if not niveis:
        raise EntradaBelkaInvalida(f"{caminho.name} sem nível para nenhum município piloto")
    return dia, niveis


def _iso(texto: str) -> datetime:
    return datetime.fromisoformat(texto)


def _cartao(a: dict, sit: str) -> dict:
    return {
        "identifier": a["identifier"], "evento": a["evento"], "situacao": sit,
        "nivel_id": a["nivel"], "nivel_nome": NIVEIS[a["nivel"]], "grau_inmet": GRAU_INMET[a["nivel"]],
        "riscos": a["riscos"], "inicio": a["onset"], "fim": a["expires"],
        "titulo": a["headline"], "descricao": a["descricao"], "instrucao": a["instrucao"],
        "link": a["web"], "criterio_area": a["criterio_area"],
    }


def comparar_com_belka(avisos: list[dict], piloto: list[dict], dia_belka: str, niveis_belka: dict[int, dict],
                       primeiro_envio: str | None) -> dict:
    d = date.fromisoformat(dia_belka)
    ini, fim = datetime.combine(d, time.min, FUSO), datetime.combine(d + timedelta(days=1), time.min, FUSO)
    if primeiro_envio is None or _iso(primeiro_envio).astimezone(FUSO).date() > d:
        return {"disponivel": False, "dia_belka": dia_belka,
                "motivo": "o robô ainda não tem avisos registrados que cubram esse dia"}
    linhas = []
    for m in piloto:
        doDia = [a for a in avisos if m["ibge"] in a["municipios"] and _iso(a["onset"]) < fim and _iso(a["expires"]) > ini]
        oficial = max((a["nivel"] for a in doDia), default=0)
        belka = niveis_belka.get(m["ibge"])
        if belka is None:
            linhas.append({"municipio_id": m["ibge"], "municipio_nome": m["nome"], "nivel_oficial": oficial,
                           "nivel_belka": None, "resultado": "sem_dado_belka", "avisos": [a["identifier"] for a in doDia]})
            continue
        linhas.append({
            "municipio_id": m["ibge"], "municipio_nome": m["nome"],
            "nivel_oficial": oficial, "nivel_oficial_nome": NIVEIS[oficial],
            "nivel_belka": belka["nivel_id"], "nivel_belka_nome": NIVEIS[belka["nivel_id"]],
            "risco_principal_belka": belka["risco_principal"],
            "resultado": comparar(oficial, belka["nivel_id"]),
            "avisos": [a["identifier"] for a in doDia],
        })
    return {"disponivel": True, "dia_belka": dia_belka, "municipios": linhas}


def montar_snapshot(avisos: list[dict], piloto: list[dict], agora: datetime, horizonte: int,
                    comparacao: dict, fonte: dict, meta: dict) -> dict:
    municipios = []
    for m in piloto:
        vigentes, proximos = [], []
        for a in avisos:
            if m["ibge"] not in a["municipios"]:
                continue
            sit = situacao(_iso(a["onset"]), _iso(a["expires"]), agora, horizonte)
            if sit == "vigente":
                vigentes.append(_cartao(a, sit))
            elif sit == "proximo":
                proximos.append(_cartao(a, sit))
        vigentes.sort(key=lambda c: (-c["nivel_id"], c["inicio"]))
        proximos.sort(key=lambda c: (c["inicio"], -c["nivel_id"]))
        nivel = max((c["nivel_id"] for c in vigentes), default=0)
        municipios.append({
            "municipio_id": m["ibge"], "municipio_nome": m["nome"], "uf": m["uf"],
            "nivel_oficial_agora": nivel, "nivel_nome": NIVEIS[nivel],
            "grau_inmet": GRAU_INMET.get(nivel, "sem aviso"),
            "avisos_vigentes": vigentes, "proximos_avisos": proximos,
        })
    divergentes = [c for c in comparacao.get("municipios", []) if c["resultado"] == "belka_abaixo"]
    return {
        "versao_contrato": VERSAO_CONTRATO,
        "gerado_em": meta["gerado_em"], "gerado_por": "belka-rpa-avisos", "execucao_id": meta["execucao_id"],
        "referencia_tempo": agora.isoformat(timespec="seconds"),
        "fonte": fonte,
        "aviso_legal": "Avisos meteorológicos oficiais do INMET, reproduzidos sem alteração de conteúdo. "
                       "Em situação de risco siga a Defesa Civil (199) e o Corpo de Bombeiros (193).",
        "niveis": [{"nivel_id": k, "nivel_nome": v, "grau_inmet": GRAU_INMET.get(k, "sem aviso")} for k, v in NIVEIS.items()],
        "municipios": municipios,
        "comparacao_belka": comparacao,
        "resumo": {
            "municipios_com_aviso_vigente": sum(1 for m in municipios if m["avisos_vigentes"]),
            "avisos_vigentes": len({c["identifier"] for m in municipios for c in m["avisos_vigentes"]}),
            "avisos_proximos": len({c["identifier"] for m in municipios for c in m["proximos_avisos"]}),
            "divergencias_belka_abaixo": len(divergentes),
        },
    }


def validar_snapshot(s: dict, ids_piloto: set[int]) -> list[str]:
    """Confere o contrato antes de publicar. Qualquer erro impede a publicação."""
    erros = []
    ids = [m.get("municipio_id") for m in s.get("municipios", [])]
    if set(ids) != ids_piloto or len(ids) != len(ids_piloto):
        erros.append("lista de municípios diferente dos municípios piloto")
    for m in s.get("municipios", []):
        if m.get("nivel_oficial_agora") not in NIVEIS:
            erros.append(f"nível inválido em {m.get('municipio_nome')}")
        for c in m.get("avisos_vigentes", []) + m.get("proximos_avisos", []):
            if _iso(c["fim"]) <= _iso(c["inicio"]):
                erros.append(f"aviso {c['identifier']} com fim antes do início")
            if c["nivel_id"] not in (1, 2, 3):
                erros.append(f"aviso {c['identifier']} com nível {c['nivel_id']}")
    if not s.get("fonte", {}).get("url"):
        erros.append("fonte não identificada")
    return erros


def publicar_atomico(destino: Path, conteudo: dict) -> None:
    """Grava num .tmp e troca de uma vez: o MVP nunca lê um arquivo pela metade."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        destino.replace(destino.with_name(destino.stem + ".anterior.json"))
    tmp = destino.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, destino)


def exportar_divergencias(comparacao: dict, pasta: Path, execucao_id: str) -> tuple[Path, int]:
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / "divergencias.csv"
    linhas = [c for c in comparacao.get("municipios", []) if c["resultado"] in ("belka_abaixo", "belka_acima")]
    with destino.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["execucao_id", "dia", "municipio_id", "municipio", "nivel_belka", "nivel_oficial",
                    "resultado", "acao_sugerida", "avisos"])
        for c in linhas:
            acao = ("revisar limiares da Belka: o aviso oficial foi mais grave"
                    if c["resultado"] == "belka_abaixo" else "conferir se a Belka antecipou um risco local")
            w.writerow([execucao_id, comparacao["dia_belka"], c["municipio_id"], c["municipio_nome"],
                        c["nivel_belka_nome"], c["nivel_oficial_nome"], c["resultado"], acao, " ".join(c["avisos"])])
    return destino, len(linhas)
