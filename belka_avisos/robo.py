"""
Belka RPA · Avisos oficiais · orquestração (o mesmo desenho do BPMN em docs/).

  E1 Carregar e validar a configuração
  E2 Ler o feed de avisos do INMET (novas tentativas; se cair, decide se publica da base anterior)
  E3 Para cada aviso do feed: já visto? baixar CAP -> validar -> é real? -> cancela/atualiza/novo?
     -> atinge município piloto? -> converter severidade em nível Belka -> gravar
  E4 Comparar com o nível calculado pela Belka (belka_mvp.json)
  E5 Montar, validar e publicar saida/avisos_oficiais.json para o MVP
  E6 Exportar divergências para a equipe revisar os limiares
  E7 Notificar a equipe sobre avisos graves e falhas
  E8 Relatório, log e registro da execução
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import cap, publicacao, regras
from .auditoria import FUSO, Auditoria, agora as relogio
from .banco import Banco
from .fonte import FonteINMET, FonteIndisponivel, FonteLocal, com_retentativa

SUCESSO, COM_PENDENCIAS, FALHA = "SUCESSO", "SUCESSO_COM_PENDENCIAS", "FALHA"
REPROCESSAR = {"falha_download", "erro"}          # situações que merecem nova tentativa na próxima execução


class FalhaCritica(Exception):
    """Erro que impede publicar com segurança. O arquivo anterior do MVP continua no ar."""


@dataclass
class Resultado:
    status: str
    codigo_saida: int
    relatorio: dict
    caminho_relatorio: Path


def _validar_config(cfg: dict) -> list[dict]:
    try:
        piloto = cfg["municipios_piloto"]
        for chave in ("severidade_para_nivel", "cor_para_nivel", "grau_para_nivel", "evento_para_riscos"):
            if not isinstance(cfg[chave], dict) or not cfg[chave]:
                raise FalhaCritica(f"tabela '{chave}' vazia na configuração")
        cfg["fonte"]["feed_url"]
    except (KeyError, TypeError) as e:
        raise FalhaCritica(f"configuração incompleta: falta {e}") from e
    if not piloto:
        raise FalhaCritica("lista de municípios piloto vazia")
    for m in piloto:
        if not (isinstance(m.get("ibge"), int) and 1_000_000 <= m["ibge"] <= 9_999_999):
            raise FalhaCritica(f"código IBGE inválido na configuração: {m.get('ibge')}")
        if not all(m.get(k) for k in ("nome", "uf", "mesorregiao")):
            raise FalhaCritica(f"município {m['ibge']} sem nome, UF ou mesorregião")
    return piloto


def executar(raiz: Path, agora: datetime | None = None, local: Path | None = None, config: Path | None = None,
             sessao=None, dormir=time.sleep, ecoar_console: bool = True, estrito: bool = False) -> Resultado:
    raiz = Path(raiz).resolve()
    inicio = relogio()
    referencia = (agora or inicio).astimezone(FUSO)       # "agora" pode ser fixado para reprocessar um dia
    execucao_id = inicio.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]

    cfg_path = Path(config) if config else raiz / "config" / "config_avisos.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        erro_cfg = None
    except (OSError, json.JSONDecodeError) as e:
        cfg, erro_cfg = {}, f"configuração ilegível ({cfg_path.name}): {type(e).__name__}"
    pastas = {"saida": "saida", "quarentena": "saida/quarentena", "logs": "logs", **cfg.get("pastas", {})}
    P = {k: raiz / v for k, v in pastas.items()}

    aud = Auditoria(P["logs"], execucao_id, ecoar_console)
    banco = Banco(P["saida"] / "belka_avisos.db")
    banco.abrir_execucao(execucao_id, inicio.isoformat(timespec="seconds"))

    rel: dict = {
        "execucao_id": execucao_id, "inicio": inicio.isoformat(timespec="seconds"),
        "referencia_tempo": referencia.isoformat(timespec="seconds"),
        "parametros": {"fonte_local": str(local) if local else None, "estrito": estrito},
        "feed": {}, "itens": Counter(), "decisoes": Counter(), "comparacao": {}, "publicacao": {},
        "notificacoes": Counter(), "erro": None,
    }
    status = FALHA
    aud.evento("inicio", "ok", execucao_id, f"robô de avisos iniciado · referência {rel['referencia_tempo']}")

    try:
        # ------------------------------------------------------------ E1 configuração
        if erro_cfg:
            raise FalhaCritica(erro_cfg)
        piloto = _validar_config(cfg)
        ids_piloto = {m["ibge"] for m in piloto}
        nomes = {m["ibge"]: m["nome"] for m in piloto}
        rede = cfg.get("rede", {})
        tent, espera = rede.get("tentativas", 3), rede.get("espera_inicial_s", 2)
        horizonte = cfg.get("horizonte_proximos_dias", 3)
        fonte = FonteLocal(local) if local else FonteINMET(cfg["fonte"]["feed_url"], sessao, rede.get("timeout_s", 30))
        aud.evento("config", "ok", None, f"{len(piloto)} municípios piloto · fonte: {fonte.descricao}")

        # ------------------------------------------------------------ E2 feed
        itens, feed_ok = [], False
        try:
            texto = com_retentativa(fonte.feed, "feed INMET", aud, tent, espera, dormir)
            itens, sem_guid = cap.ler_rss(texto)
            feed_ok = True
            rel["feed"] = {"lido": True, "itens": len(itens), "itens_sem_guid": sem_guid}
            aud.evento("feed", "ok", None, f"{len(itens)} aviso(s) no feed")
            if sem_guid:
                aud.evento("feed", "aviso", None, f"{sem_guid} item(ns) sem guid/link utilizável foram descartados")
        except (FonteIndisponivel, cap.FeedInvalido) as e:
            rel["feed"] = {"lido": False, "motivo": str(e)}
            ultimo = banco.controle("ultimo_feed_ok")
            if ultimo is None:                                             # decisão: há base para publicar?
                raise FalhaCritica(f"feed indisponível e nenhuma leitura anterior para usar: {e}") from e
            aud.evento("feed", "pendencia", None,
                       f"{e} · publicando a partir da base de {ultimo} (fonte marcada como desatualizada)")

        # ------------------------------------------------------------ E3 cada aviso
        quarentena = P["quarentena"] / execucao_id

        def registrar(item, situacao, motivo, identifier=None):
            banco.registrar_item(item.rss_id, item.url, item.titulo, situacao, motivo, identifier,
                                 relogio().isoformat(timespec="seconds"), execucao_id)
            rel["itens"][situacao] += 1

        def para_quarentena(item, texto_xml, motivo):
            quarentena.mkdir(parents=True, exist_ok=True)
            (quarentena / f"{item.rss_id}.xml").write_text(texto_xml or "", encoding="utf-8")
            with (quarentena / "motivos.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"rss_id": item.rss_id, "motivo": motivo}, ensure_ascii=False) + "\n")
            registrar(item, "quarentena", motivo)
            aud.evento("aviso_cap", "pendencia", item.rss_id, f"quarentena: {motivo}")

        for item in itens:                                                 # repetição: um aviso por vez
            try:
                visto = banco.item(item.rss_id)
                if visto is not None and visto["situacao"] not in REPROCESSAR:   # decisão: já processado?
                    rel["itens"]["ja_processados"] += 1
                    continue

                try:
                    xml = com_retentativa(lambda i=item: fonte.cap(i.rss_id, i.url), f"CAP {item.rss_id}",
                                          aud, tent, espera, dormir)
                except FonteIndisponivel as e:
                    registrar(item, "falha_download", str(e))
                    aud.evento("aviso_cap", "pendencia", item.rss_id, f"{e} · nova tentativa na próxima execução")
                    continue

                try:
                    aviso = cap.ler_cap(xml, item.rss_id)
                except cap.AvisoInvalido as e:                             # decisão: documento válido?
                    para_quarentena(item, xml, str(e))
                    continue

                if aviso.status != "Actual":                              # decisão: aviso real ou exercício?
                    registrar(item, "ignorado", f"status {aviso.status} (não é aviso real)", aviso.identifier)
                    aud.evento("decisao", "ignorado", item.rss_id, f"status {aviso.status}: não é aviso real")
                    continue
                if banco.aviso(aviso.identifier) is not None:              # decisão: mesmo aviso, outro item?
                    registrar(item, "ignorado", "identifier já registrado (duplicado)", aviso.identifier)
                    aud.evento("decisao", "ignorado", item.rss_id, f"{aviso.identifier} já registrado (duplicado)")
                    continue

                # decisão: tipo da mensagem (Alert / Update / Cancel)
                if aviso.msg_type in ("Cancel", "Update"):
                    novo_estado = "cancelado" if aviso.msg_type == "Cancel" else "substituido"
                    for ref in aviso.references:
                        if banco.mudar_estado(ref, novo_estado, f"{aviso.msg_type} {aviso.identifier}"):
                            rel["decisoes"][novo_estado] += 1
                            aud.evento("decisao", "decisao", item.rss_id, f"{ref} -> {novo_estado}")
                        elif banco.aviso(ref) is None:
                            banco.guardar_referencia_orfa(ref, aviso.msg_type, aviso.identifier,
                                                          relogio().isoformat(timespec="seconds"))
                            aud.evento("decisao", "decisao", item.rss_id,
                                       f"{aviso.msg_type} de {ref}, que ainda não chegou: guardado para aplicar depois")
                    if aviso.msg_type == "Cancel":
                        registrar(item, "processado", "cancelamento", aviso.identifier)
                        continue
                elif aviso.msg_type != "Alert":
                    registrar(item, "ignorado", f"msgType {aviso.msg_type}", aviso.identifier)
                    aud.evento("decisao", "ignorado", item.rss_id, f"msgType {aviso.msg_type} não traz aviso")
                    continue

                afetados, criterio = regras.municipios_afetados(aviso, piloto)
                if aviso.municipios_malformados:
                    aud.evento("qualidade", "aviso", item.rss_id,
                               f"{aviso.municipios_malformados} entrada(s) da lista de municípios fora do padrão")
                if not afetados:                                           # decisão: atinge a área piloto?
                    registrar(item, "ignorado", "fora da área piloto", aviso.identifier)
                    rel["decisoes"]["fora_da_area"] += 1
                    aud.evento("decisao", "ignorado", item.rss_id,
                               f"{aviso.event}: nenhum município piloto atingido ({criterio})")
                    continue
                if criterio == "mesorregiao":
                    aud.evento("qualidade", "aviso", item.rss_id,
                               "CAP sem lista de municípios: área definida pela mesorregião (menos preciso)")

                try:
                    nivel, sinais, conflito = regras.nivel_do_aviso(aviso, cfg)
                except cap.AvisoInvalido as e:                             # decisão: severidade reconhecida?
                    para_quarentena(item, xml, str(e))
                    continue
                if conflito:
                    aud.evento("qualidade", "aviso", item.rss_id, f"{conflito}; usado o mais grave ({nivel})")

                sit = regras.situacao(aviso.onset, aviso.expires, referencia, horizonte)
                banco.inserir_aviso({
                    "identifier": aviso.identifier, "rss_id": item.rss_id, "sent": aviso.sent.isoformat(),
                    "msg_type": aviso.msg_type, "evento": aviso.event, "severidade": aviso.severity,
                    "cor": aviso.cor, "nivel": nivel, "riscos": json.dumps(regras.riscos_do_evento(aviso.event, cfg)),
                    "onset": aviso.onset.isoformat(), "expires": aviso.expires.isoformat(),
                    "headline": aviso.headline, "descricao": aviso.description, "instrucao": aviso.instruction,
                    "web": aviso.web, "criterio_area": criterio,
                    "registrado_em": relogio().isoformat(timespec="seconds"), "execucao_id": execucao_id,
                }, afetados)
                orfa = banco.consumir_referencia_orfa(aviso.identifier)
                if orfa is not None:                                       # cancelado antes de chegar
                    estado = "cancelado" if orfa["tipo"] == "Cancel" else "substituido"
                    banco.mudar_estado(aviso.identifier, estado, f"{orfa['tipo']} {orfa['por_identifier']}")
                    aud.evento("decisao", "decisao", item.rss_id, f"{orfa['tipo']} recebido antes: aviso já entra {estado}")
                registrar(item, "processado", sit, aviso.identifier)
                rel["decisoes"][f"nivel_{nivel}"] += 1
                aud.evento("aviso_cap", "ok", item.rss_id,
                           f"{aviso.event} · {regras.GRAU_INMET[nivel]} -> {regras.NIVEIS[nivel]} ({sinais}) · "
                           f"{', '.join(nomes[m] for m in sorted(afetados))} · {sit}")
            except Exception as e:   # um aviso com problema não derruba os outros
                registrar(item, "erro", f"{type(e).__name__}: {e}")
                aud.evento("aviso_cap", "pendencia", item.rss_id, f"erro inesperado: {type(e).__name__}: {e}")

        if feed_ok:
            banco.definir_controle("ultimo_feed_ok", relogio().isoformat(timespec="seconds"))
        avisos = banco.avisos_ativos()
        rel["base"] = banco.contagem_por_estado()

        # ------------------------------------------------------------ E4 comparação com a Belka
        try:
            dia_belka, niveis_belka = publicacao.ler_belka(raiz / cfg.get("entrada_belka_mvp", "entrada/belka_mvp.json"),
                                                           ids_piloto)
            comparacao = publicacao.comparar_com_belka(avisos, piloto, dia_belka, niveis_belka, banco.primeiro_envio())
            if comparacao["disponivel"]:
                res = Counter(c["resultado"] for c in comparacao["municipios"])
                aud.evento("comparacao", "ok", dia_belka, ", ".join(f"{k}: {v}" for k, v in sorted(res.items())))
            else:
                aud.evento("comparacao", "decisao", dia_belka, comparacao["motivo"])
        except publicacao.EntradaBelkaInvalida as e:
            comparacao = {"disponivel": False, "dia_belka": None, "motivo": str(e)}
            aud.evento("comparacao", "pendencia", None, f"comparação indisponível: {e}")
        rel["comparacao"] = {k: v for k, v in comparacao.items() if k != "municipios"}

        # ------------------------------------------------------------ E5 publicação para o MVP
        fonte_info = {"nome": cfg["fonte"].get("nome", "INMET"), "url": cfg["fonte"]["feed_url"],
                      "lida_nesta_execucao": feed_ok, "ultima_leitura_ok": banco.controle("ultimo_feed_ok"),
                      "desatualizada": not feed_ok}
        snapshot = publicacao.montar_snapshot(avisos, piloto, referencia, horizonte, comparacao, fonte_info,
                                              {"gerado_em": relogio().isoformat(timespec="seconds"),
                                               "execucao_id": execucao_id})
        erros = publicacao.validar_snapshot(snapshot, ids_piloto)
        if erros:                                                          # decisão: contrato íntegro?
            raise FalhaCritica("arquivo do MVP reprovado, versão anterior mantida: " + "; ".join(erros))
        destino = P["saida"] / "avisos_oficiais.json"
        publicacao.publicar_atomico(destino, snapshot)
        rel["publicacao"] = {"publicado": True, "arquivo": str(destino.relative_to(raiz)), **snapshot["resumo"]}
        aud.evento("publicacao", "ok", destino.name,
                   f"{snapshot['resumo']['avisos_vigentes']} vigente(s), {snapshot['resumo']['avisos_proximos']} "
                   f"próximo(s) · {snapshot['resumo']['municipios_com_aviso_vigente']} município(s) com aviso agora")

        # ------------------------------------------------------------ E6 divergências
        if comparacao.get("disponivel"):
            csv_div, n_div = publicacao.exportar_divergencias(comparacao, P["saida"], execucao_id)
            rel["comparacao"]["divergencias"] = n_div
            rel["comparacao"]["arquivo"] = str(csv_div.relative_to(raiz))
            for c in comparacao["municipios"]:
                if c["resultado"] == "belka_abaixo":
                    aud.evento("divergencia", "aviso", c["municipio_nome"],
                               f"Belka {c['nivel_belka_nome']} x INMET {c['nivel_oficial_nome']} em "
                               f"{comparacao['dia_belka']}: revisar limiares")

        # ------------------------------------------------------------ E7 avisos graves
        minimo = cfg.get("notificar_nivel_minimo", 3)
        graves = {c["identifier"]: (m["municipio_nome"], c) for m in snapshot["municipios"]
                  for c in m["avisos_vigentes"] + m["proximos_avisos"] if c["nivel_id"] >= minimo}
        for ident, (municipio, c) in graves.items():                       # decisão: avisar a equipe?
            if banco.ja_notificado(ident):
                rel["notificacoes"]["ja_avisados"] += 1
                continue
            texto = f"Belka · aviso oficial {c['grau_inmet']} ({c['evento']}) em {municipio}: {c['inicio']} a {c['fim']}"
            if _webhook(sessao, texto, aud, local):
                banco.marcar_notificado(ident, relogio().isoformat(timespec="seconds"))
                rel["notificacoes"]["enviadas"] += 1
            else:
                rel["notificacoes"]["sem_canal"] += 1
                aud.evento("notificacao", "decisao", ident, f"aviso grave sem canal configurado: {texto}")

        status = COM_PENDENCIAS if aud.pendencias else SUCESSO

    except FalhaCritica as e:
        rel["erro"] = str(e)
        aud.evento("fim", "erro", None, str(e))
    except Exception as e:   # nada termina em silêncio
        rel["erro"] = f"{type(e).__name__}: {e}"
        aud.evento("fim", "erro", None, f"erro inesperado: {rel['erro']}")
        aud.log.exception("traceback")

    # ---------------------------------------------------------------- E8 relatório
    fim = relogio()
    rel.update({
        "fim": fim.isoformat(timespec="seconds"), "duracao_s": round((fim - inicio).total_seconds(), 2),
        "status": status, "pendencias": list(aud.pendencias), "avisos_de_qualidade": list(aud.avisos),
        "itens": dict(rel["itens"]), "decisoes": dict(rel["decisoes"]), "notificacoes": dict(rel["notificacoes"]),
        "eventos": dict(aud.contadores), "log": str(aud.arquivo_log.relative_to(raiz)),
    })
    pasta_rel = P["saida"] / "relatorios"
    pasta_rel.mkdir(parents=True, exist_ok=True)
    caminho_rel = pasta_rel / f"relatorio_{execucao_id}.json"
    caminho_rel.write_text(json.dumps(rel, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    shutil.copy2(caminho_rel, P["saida"] / "ultima_execucao.json")
    banco.fechar_execucao(execucao_id, rel["fim"], status, rel)
    if status != SUCESSO:
        _webhook(sessao, f"Belka avisos · {status} · {len(rel['pendencias'])} pendência(s)"
                         + (f" · erro: {rel['erro']}" if rel["erro"] else ""), aud, local)
    aud.evento("fim", "ok" if status != FALHA else "erro", execucao_id,
               f"status {status} · itens {rel['itens']} · {len(aud.pendencias)} pendência(s) · {rel['duracao_s']} s")
    aud.fechar()
    banco.fechar()
    return Resultado(status, {SUCESSO: 0, COM_PENDENCIAS: 1 if estrito else 0, FALHA: 2}[status], rel, caminho_rel)


def _webhook(sessao, texto: str, aud: Auditoria, local) -> bool:
    """Envia para Teams/Slack/Discord/n8n se BELKA_WEBHOOK_URL estiver definido. Nunca derruba a execução."""
    url = os.environ.get("BELKA_WEBHOOK_URL")
    if not url or local is not None and sessao is None:
        return False
    try:
        import requests
        r = (sessao or requests).post(url, json={"text": texto}, timeout=10)
        ok = r.status_code < 300
        aud.evento("notificacao", "ok" if ok else "aviso", None, f"webhook HTTP {r.status_code}")
        return ok
    except Exception as e:
        aud.evento("notificacao", "aviso", None, f"webhook falhou: {type(e).__name__}")
        return False
