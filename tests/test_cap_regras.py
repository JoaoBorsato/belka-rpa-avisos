"""Regras isoladas: leitura do RSS e do CAP, conversão de severidade, área, situação e máscara do log."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from belka_avisos import cap, regras
from belka_avisos.auditoria import sanitizar

from .fabrica import cap_xml, identificador, rss_xml

CFG = json.loads((Path(__file__).resolve().parents[1] / "config" / "config_avisos.json").read_text(encoding="utf-8"))
PILOTO = CFG["municipios_piloto"]
INI, FIM = "2026-11-07T00:00:00-03:00", "2026-11-07T23:59:00-03:00"


def aviso(**kw):
    base = dict(rss_id=1, evento="Tempestade", severidade="Moderate", inicio=INI, fim=FIM, municipios=[3550308])
    base.update(kw)
    pos = [base.pop(k) for k in ("rss_id", "evento", "severidade", "inicio", "fim", "municipios")]
    return cap.ler_cap(cap_xml(*pos, **base), str(pos[0]))


# ------------------------------------------------------------------ RSS
def test_rss_extrai_guid_e_ordena_do_mais_antigo():
    itens = [{"rss_id": n, "evento": "Tempestade", "severidade": "Moderate", "inicio": INI, "fim": FIM,
              "municipios": [3550308]} for n in (30, 10, 20)]
    lidos, sem_guid = cap.ler_rss(rss_xml(itens, INI))
    assert [i.rss_id for i in lidos] == ["10", "20", "30"] and sem_guid == 0
    assert lidos[0].url == "https://apiprevmet3.inmet.gov.br/avisos/rss/10"


def test_rss_item_sem_guid_e_descartado_e_contado():
    texto = rss_xml([], INI).replace("</channel>", "<item><title>sem guid</title></item></channel>")
    itens, sem_guid = cap.ler_rss(texto)
    assert itens == [] and sem_guid == 1


@pytest.mark.parametrize("texto", ["", "<rss><channel><item>", "<html><body>manutenção</body></html>",
                                   '<?xml version="1.0"?><rss version="2.0"><channel><title>Avisos</title></channel></rss>'])
def test_rss_invalido(texto):
    with pytest.raises(cap.FeedInvalido):
        cap.ler_rss(texto)


# ------------------------------------------------------------------ CAP
def test_cap_le_campos_municipios_e_mesorregioes():
    a = aviso(municipios=[3550308, 3509502, 3304557])
    assert a.identifier == identificador(1) and a.msg_type == "Alert" and a.status == "Actual"
    assert a.event == "Tempestade" and a.severity == "Moderate" and a.cor == "#FFFE00"
    assert (("São Paulo", "SP", 3550308) in a.municipios) and len(a.municipios) == 3
    assert "Metropolitana de São Paulo" in a.mesorregioes and "Campinas" in a.mesorregioes
    assert a.onset == datetime.fromisoformat(INI)


def test_cap_entrada_de_municipio_fora_do_padrao_e_contada():
    a = aviso(extra_municipios=", Cidade sem código - SP, Outra (12)")
    assert a.municipios_malformados == 2 and len(a.municipios) == 1


def test_cap_referencias_no_formato_cap():
    a = aviso(msg_type="Cancel", referencias=[identificador(9), identificador(8)])
    assert a.references == [identificador(9), identificador(8)]


@pytest.mark.parametrize("troca, motivo", [
    (("identifier>", "codigo>"), "obrigatório"),
    (("<onset>2026-11-07T00:00:00-03:00</onset>", "<onset>2026-11-08T00:00:00-03:00</onset>"), "posterior"),
    (("<onset>2026-11-07T00:00:00-03:00</onset>", "<onset>2026-11-07T00:00:00</onset>"), "fuso"),
    (("<onset>2026-11-07T00:00:00-03:00</onset>", "<onset>amanhã</onset>"), "data inválida"),
    (("<info>", "<inf>"), "XML inválido"),
])
def test_cap_invalido(troca, motivo):
    xml = cap_xml(1, "Tempestade", "Moderate", INI, FIM, [3550308]).replace(*troca)
    with pytest.raises(cap.AvisoInvalido, match=motivo):
        cap.ler_cap(xml, "1")


def test_cap_com_entidade_externa_e_recusado():
    xml = ('<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
           '<alert><identifier>&x;</identifier></alert>')
    with pytest.raises(cap.AvisoInvalido, match="segurança"):
        cap.ler_cap(xml, "1")


# ------------------------------------------------------------------ regras
@pytest.mark.parametrize("sev, nivel", [("Moderate", 1), ("Severe", 2), ("Extreme", 3)])
def test_severidade_vira_nivel_belka(sev, nivel):
    n, sinais, conflito = regras.nivel_do_aviso(aviso(severidade=sev), CFG)
    assert n == nivel and sinais == "severity+cor+titulo" and conflito is None


def test_sinais_em_conflito_usa_o_mais_grave():
    n, _, conflito = regras.nivel_do_aviso(aviso(severidade="Moderate", cor="#FF0000"), CFG)
    assert n == 3 and "conflito" in conflito


def test_so_a_cor_ja_basta():
    n, sinais, _ = regras.nivel_do_aviso(aviso(severidade="Unknown", cor="#FB9C00", titulo="Aviso"), CFG)
    assert n == 2 and sinais == "cor"


def test_sem_nenhum_sinal_de_severidade_e_invalido():
    with pytest.raises(cap.AvisoInvalido, match="severidade"):
        regras.nivel_do_aviso(aviso(severidade="Unknown", cor=None, titulo="Aviso"), CFG)


def test_evento_para_riscos():
    assert regras.riscos_do_evento("Chuvas Intensas", CFG) == ["enchente", "deslizamento"]
    assert regras.riscos_do_evento("Geada", CFG) == ["outro"]


def test_area_por_codigo_ibge_e_por_mesorregiao():
    assert regras.municipios_afetados(aviso(municipios=[3509502, 3304557]), PILOTO) == ({3509502}, "codigo_ibge")
    sem_lista = aviso(municipios=[3550308, 3550704], incluir_municipios=False)
    assert regras.municipios_afetados(sem_lista, PILOTO) == ({3550308, 3518800, 3516408, 3550704}, "mesorregiao")
    sem_area = aviso(incluir_municipios=False, incluir_area=False)
    assert regras.municipios_afetados(sem_area, PILOTO) == (set(), "sem_area")


@pytest.mark.parametrize("agora, esperado", [
    ("2026-11-06T12:00:00-03:00", "proximo"), ("2026-11-07T10:00:00-03:00", "vigente"),
    ("2026-11-08T10:00:00-03:00", "expirado"), ("2026-11-01T10:00:00-03:00", "fora_do_horizonte"),
])
def test_situacao(agora, esperado):
    ini, fim, ref = (datetime.fromisoformat(x) for x in (INI, FIM, agora))
    assert regras.situacao(ini, fim, ref, 3) == esperado


def test_comparar():
    assert regras.comparar(2, 2) == "concorda"
    assert regras.comparar(2, 1) == "belka_abaixo"
    assert regras.comparar(0, 1) == "belka_acima"


def test_log_nao_expoe_dados_sensiveis():
    s = sanitizar("token=abc123 senha: x1 joao@exemplo.com (11) 98765-4321 https://u:p@host/x execução 20261118-202920-0782")
    assert "abc123" not in s and "x1" not in s and "joao" not in s and "98765" not in s and "u:p" not in s
    assert "20261118-202920-0782" in s
