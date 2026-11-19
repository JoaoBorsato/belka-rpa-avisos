"""
Cenários de ponta a ponta: sucesso, decisão e falha.
Cada teste roda o robô inteiro numa cópia temporária do repositório.
"""
import json
import sqlite3

import requests

from belka_avisos.robo import COM_PENDENCIAS, FALHA, SUCESSO

from .conftest import Resposta, SessaoFalsa, municipio, publicado, rodar, sessao_do_feed
from .fabrica import cap_xml, identificador, rss_xml

SP, GRU, FRA, CPS, SSB = 3550308, 3518800, 3516408, 3509502, 3550704
FEED = "https://apiprevmet3.inmet.gov.br/avisos/rss"


def consulta(repo, sql):
    con = sqlite3.connect(repo / "saida" / "belka_avisos.db")
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def gravar_feed(pasta, avisos, publicado_em="2026-11-07T14:00:00-03:00"):
    """avisos: [(rss_id, evento, severidade, início, fim, municípios, extras)]"""
    (pasta / "cap").mkdir(parents=True, exist_ok=True)
    for rss_id, ev, sev, ini, fim, munis, extra in avisos:
        (pasta / "cap" / f"{rss_id}.xml").write_text(cap_xml(rss_id, ev, sev, ini, fim, munis, **extra), encoding="utf-8")
    itens = [{"rss_id": a[0], "evento": a[1], "severidade": a[2], "inicio": a[3], "fim": a[4], "municipios": a[5]}
             for a in avisos]
    (pasta / "rss.xml").write_text(rss_xml(itens, publicado_em), encoding="utf-8")
    return pasta


DIA = ("2026-11-07T00:00:00-03:00", "2026-11-07T23:59:00-03:00")


# ======================================================================= SUCESSO
def test_sucesso_publica_avisos_por_municipio_para_o_mvp(repo):
    r = rodar(repo)
    assert r.status == SUCESSO and r.codigo_saida == 0
    s = publicado(repo)
    assert s["versao_contrato"] == "1.0" and len(s["municipios"]) == 5
    assert s["fonte"]["lida_nesta_execucao"] and not s["fonte"]["desatualizada"]
    sp = municipio(s, SP)
    assert sp["nivel_oficial_agora"] == 1 and sp["grau_inmet"] == "Perigo Potencial"
    assert [a["evento"] for a in sp["avisos_vigentes"]] == ["Tempestade"]
    ssb = municipio(s, SSB)
    assert ssb["nivel_nome"] == "Prepare-se" and ssb["avisos_vigentes"][0]["riscos"] == ["enchente", "deslizamento"]
    assert ssb["proximos_avisos"][0]["nivel_nome"] == "Aja agora"
    assert r.relatorio["itens"] == {"processado": 8, "ignorado": 2}


def test_segunda_execucao_nao_duplica_nada(repo):
    rodar(repo)
    antes = consulta(repo, "SELECT COUNT(*) FROM avisos")[0][0]
    r = rodar(repo)
    assert r.status == SUCESSO
    assert r.relatorio["itens"] == {"ja_processados": 10}
    assert consulta(repo, "SELECT COUNT(*) FROM avisos")[0][0] == antes == 7


def test_trilha_de_auditoria_e_relatorio(repo):
    r = rodar(repo)
    eventos = [json.loads(l) for l in (repo / "logs" / "auditoria.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {"inicio", "feed", "aviso_cap", "decisao", "comparacao", "publicacao", "fim"} <= {e["etapa"] for e in eventos}
    assert all(e["execucao_id"] == r.relatorio["execucao_id"] for e in eventos)
    assert (repo / "saida" / "ultima_execucao.json").exists()
    assert consulta(repo, "SELECT status FROM execucoes")[0][0] == SUCESSO


def test_le_o_feed_pela_internet_com_rede_simulada(repo):
    r = rodar(repo, sessao=sessao_do_feed(repo / "feed", FEED))
    assert r.status == SUCESSO and municipio(publicado(repo), SSB)["nivel_oficial_agora"] == 2


# ======================================================================= DECISÃO
def test_cancelamento_tira_o_aviso_do_mvp(repo):
    rodar(repo)
    for m in (GRU, FRA):
        assert all(a["evento"] != "Vendaval" for a in municipio(publicado(repo), m)["proximos_avisos"])
    assert consulta(repo, f"SELECT estado FROM avisos WHERE identifier = '{identificador(55905)}'")[0][0] == "cancelado"


def test_atualizacao_substitui_o_aviso_anterior(repo):
    rodar(repo)
    proximos = municipio(publicado(repo), CPS)["proximos_avisos"]
    assert [(a["evento"], a["nivel_nome"]) for a in proximos] == [("Onda de Calor", "Prepare-se")]
    assert consulta(repo, f"SELECT estado FROM avisos WHERE identifier = '{identificador(55907)}'")[0][0] == "substituido"


def test_exercicio_e_area_fora_do_piloto_sao_ignorados(repo):
    r = rodar(repo)
    motivos = dict(consulta(repo, "SELECT rss_id, motivo FROM itens_rss WHERE situacao = 'ignorado'"))
    assert motivos == {"55903": "fora da área piloto", "55909": "status Exercise (não é aviso real)"}
    assert r.relatorio["decisoes"]["fora_da_area"] == 1


def test_comparacao_aponta_onde_a_belka_ficou_abaixo(repo):
    r = rodar(repo)
    comp = {c["municipio_id"]: c["resultado"] for c in publicado(repo)["comparacao_belka"]["municipios"]}
    assert comp == {SP: "concorda", GRU: "concorda", FRA: "concorda", CPS: "concorda", SSB: "belka_abaixo"}
    linhas = (repo / "saida" / "divergencias.csv").read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 2 and "São Sebastião" in linhas[1] and "revisar limiares" in linhas[1]
    assert r.relatorio["comparacao"]["divergencias"] == 1


def test_aviso_expirado_fica_no_historico_mas_nao_aparece_agora(repo):
    rodar(repo)
    assert all(a["evento"] != "Acumulado de Chuva" for a in municipio(publicado(repo), SP)["avisos_vigentes"])
    assert consulta(repo, f"SELECT estado FROM avisos WHERE identifier = '{identificador(55880)}'")[0][0] == "ativo"


def test_cancelamento_que_chega_antes_do_aviso_original(repo):
    feed = repo / "feed_parcial"
    gravar_feed(feed, [(200, "Vendaval", "Moderate", *DIA, [SP],
                        {"msg_type": "Cancel", "referencias": [identificador(199)]})])
    r1 = rodar(repo, local=feed)
    gravar_feed(feed, [(199, "Vendaval", "Moderate", *DIA, [SP], {}),
                       (200, "Vendaval", "Moderate", *DIA, [SP], {"msg_type": "Cancel", "referencias": [identificador(199)]})])
    r = rodar(repo, local=feed)
    assert r.status == SUCESSO
    assert consulta(repo, f"SELECT estado FROM avisos WHERE identifier = '{identificador(199)}'")[0][0] == "cancelado"
    primeira = (repo / r1.relatorio["log"]).read_text(encoding="utf-8")
    assert primeira.count("citam avisos que não estão na base") == 1
    assert municipio(publicado(repo), SP)["avisos_vigentes"] == []


def test_mesmo_aviso_em_dois_itens_do_feed_nao_duplica(repo):
    feed = gravar_feed(repo / "feed_dup", [(300, "Tempestade", "Moderate", *DIA, [SP], {}),
                                          (301, "Tempestade", "Moderate", *DIA, [SP], {"identifier": identificador(300)})])
    r = rodar(repo, local=feed)
    assert r.relatorio["itens"] == {"processado": 1, "ignorado": 1}
    assert len(municipio(publicado(repo), SP)["avisos_vigentes"]) == 1


def test_cap_sem_lista_de_municipios_usa_a_mesorregiao(repo):
    feed = gravar_feed(repo / "feed_meso", [(400, "Vendaval", "Moderate", *DIA, [SSB], {"incluir_municipios": False})])
    r = rodar(repo, local=feed)
    assert r.status == SUCESSO and municipio(publicado(repo), SSB)["avisos_vigentes"][0]["criterio_area"] == "mesorregiao"
    assert any("mesorregião" in a for a in r.relatorio["avisos_de_qualidade"])


def test_aviso_grave_notifica_a_equipe_uma_vez_so(repo, monkeypatch):
    monkeypatch.setenv("BELKA_WEBHOOK_URL", "https://hooks.exemplo.com/servicos/T0K3N-SECRETO")
    sessao = sessao_do_feed(repo / "feed", FEED)
    rodar(repo, sessao=sessao)
    envios = [c for c in sessao.chamadas if c[0] == "POST"]
    assert len(envios) == 1 and "Grande Perigo" in envios[0][2]["text"] and "São Sebastião" in envios[0][2]["text"]
    sessao2 = sessao_do_feed(repo / "feed", FEED)
    r = rodar(repo, sessao=sessao2)
    assert [c for c in sessao2.chamadas if c[0] == "POST"] == [] and r.relatorio["notificacoes"] == {"ja_avisados": 1}
    logs = "".join(p.read_text(encoding="utf-8") for p in (repo / "logs").iterdir())
    assert "T0K3N-SECRETO" not in logs


# ======================================================================= FALHA
def test_feed_fora_do_ar_sem_base_falha_e_nao_publica(repo):
    sessao = SessaoFalsa({FEED: [requests.ConnectionError("fora do ar")]})
    r = rodar(repo, sessao=sessao)
    assert r.status == FALHA and r.codigo_saida == 2 and "nenhuma leitura anterior" in r.relatorio["erro"]
    assert len([c for c in sessao.chamadas if c[1] == FEED]) == 3
    assert not (repo / "saida" / "avisos_oficiais.json").exists()


def test_feed_fora_do_ar_com_base_publica_marcando_desatualizado(repo):
    rodar(repo)
    r = rodar(repo, sessao=SessaoFalsa({FEED: [requests.Timeout("lento")]}))
    assert r.status == COM_PENDENCIAS and r.codigo_saida == 0
    s = publicado(repo)
    assert s["fonte"]["desatualizada"] and not s["fonte"]["lida_nesta_execucao"]
    assert municipio(s, SSB)["nivel_oficial_agora"] == 2
    assert rodar(repo, sessao=SessaoFalsa({FEED: [requests.Timeout("lento")]}), estrito=True).codigo_saida == 1


def test_feed_volta_na_terceira_tentativa(repo):
    sessao = sessao_do_feed(repo / "feed", FEED)
    sessao.rotas[FEED] = [requests.ConnectionError("1"), Resposta(503)] + sessao.rotas[FEED]
    r = rodar(repo, sessao=sessao)
    assert r.status == SUCESSO
    log = (repo / r.relatorio["log"]).read_text(encoding="utf-8")
    assert "tentativa 1/3 falhou" in log and "tentativa 2/3 falhou" in log and "tentativa 3/3" not in log


def test_falha_ao_baixar_um_cap_vira_pendencia_e_e_refeita(repo):
    sessao = sessao_do_feed(repo / "feed", FEED)
    sessao.rotas[f"{FEED}/55902"] = [Resposta(500)]
    r = rodar(repo, sessao=sessao)
    assert r.status == COM_PENDENCIAS and r.relatorio["itens"]["falha_download"] == 1
    assert municipio(publicado(repo), SSB)["avisos_vigentes"] == []          # o resto foi publicado
    r2 = rodar(repo, sessao=sessao_do_feed(repo / "feed", FEED))
    assert r2.status == SUCESSO and r2.relatorio["itens"] == {"ja_processados": 9, "processado": 1}
    assert municipio(publicado(repo), SSB)["nivel_oficial_agora"] == 2


def test_cap_corrompido_e_sem_severidade_vao_para_quarentena(repo):
    (repo / "feed" / "cap" / "55901.xml").write_text("<alert><identifier>quebrado", encoding="utf-8")
    xml = (repo / "feed" / "cap" / "55902.xml").read_text(encoding="utf-8")
    xml = (xml.replace("<severity>Severe</severity>", "<severity>Unknown</severity>")
              .replace("#FB9C00", "#123456").replace("Severidade Grau: Perigo", "Aviso"))
    (repo / "feed" / "cap" / "55902.xml").write_text(xml, encoding="utf-8")
    r = rodar(repo)
    assert r.status == COM_PENDENCIAS and r.relatorio["itens"]["quarentena"] == 2
    q = repo / "saida" / "quarentena" / r.relatorio["execucao_id"]
    motivos = [json.loads(l)["motivo"] for l in (q / "motivos.jsonl").read_text(encoding="utf-8").splitlines()]
    assert (q / "55901.xml").exists() and "XML inválido" in motivos[0] and "severidade" in motivos[1]
    assert r.relatorio["itens"]["processado"] == 6                             # os outros avisos seguiram


def test_sem_snapshot_da_belka_publica_sem_comparacao(repo):
    (repo / "entrada" / "belka_mvp.json").unlink()
    r = rodar(repo)
    assert r.status == COM_PENDENCIAS
    s = publicado(repo)
    assert s["comparacao_belka"]["disponivel"] is False and "não encontrado" in s["comparacao_belka"]["motivo"]
    assert municipio(s, SSB)["nivel_oficial_agora"] == 2


def test_comparacao_sem_historico_do_dia_nao_inventa_resultado(repo):
    feed = gravar_feed(repo / "feed_tarde", [(500, "Tempestade", "Moderate", "2026-11-12T00:00:00-03:00",
                                             "2026-11-12T23:59:00-03:00", [SP], {})])
    rodar(repo, local=feed, agora=__import__("datetime").datetime.fromisoformat("2026-11-12T10:00:00-03:00"))
    comp = publicado(repo)["comparacao_belka"]
    assert comp["disponivel"] is False and "não tem avisos" in comp["motivo"]


def test_configuracao_invalida_falha_com_log(repo):
    (repo / "config" / "config_avisos.json").write_text("{ quebrado", encoding="utf-8")
    r = rodar(repo)
    assert r.status == FALHA and "configuração" in r.relatorio["erro"]
    assert "ERROR" in (repo / r.relatorio["log"]).read_text(encoding="utf-8")


def test_falha_mantem_o_arquivo_anterior_do_mvp(repo):
    rodar(repo)
    antes = (repo / "saida" / "avisos_oficiais.json").read_text(encoding="utf-8")
    cfg = json.loads((repo / "config" / "config_avisos.json").read_text(encoding="utf-8"))
    cfg["municipios_piloto"][0]["ibge"] = 123
    (repo / "config" / "config_avisos.json").write_text(json.dumps(cfg), encoding="utf-8")
    r = rodar(repo)
    assert r.status == FALHA and (repo / "saida" / "avisos_oficiais.json").read_text(encoding="utf-8") == antes
