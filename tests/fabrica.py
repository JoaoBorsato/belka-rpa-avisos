"""
Monta RSS e documentos CAP 1.2 no mesmo formato publicado pelo INMET (apiprevmet3.inmet.gov.br/avisos/rss).
Usada pelos testes e por exemplos/montar_feed_exemplo.py.
"""
from __future__ import annotations

from email.utils import format_datetime
from datetime import datetime
from html import escape

BASE_RSS = "https://apiprevmet3.inmet.gov.br/avisos/rss"
NS = "urn:oasis:names:tc:emergency:cap:1.2"
COR = {"Moderate": "#FFFE00", "Severe": "#FB9C00", "Extreme": "#FF0000"}
GRAU = {"Moderate": "Perigo Potencial", "Severe": "Perigo", "Extreme": "Grande Perigo"}

# nome, UF, código IBGE, mesorregião
MUNICIPIOS = {
    3550308: ("São Paulo", "SP", "Metropolitana de São Paulo"),
    3518800: ("Guarulhos", "SP", "Metropolitana de São Paulo"),
    3516408: ("Franco da Rocha", "SP", "Metropolitana de São Paulo"),
    3534401: ("Osasco", "SP", "Metropolitana de São Paulo"),
    3509502: ("Campinas", "SP", "Campinas"),
    3525904: ("Jundiaí", "SP", "Macro Metropolitana Paulista"),
    3556206: ("Valinhos", "SP", "Campinas"),
    3550704: ("São Sebastião", "SP", "Vale do Paraíba Paulista"),
    3510500: ("Caraguatatuba", "SP", "Vale do Paraíba Paulista"),
    3555406: ("Ubatuba", "SP", "Vale do Paraíba Paulista"),
    3520400: ("Ilhabela", "SP", "Vale do Paraíba Paulista"),
    3548500: ("Santos", "SP", "Metropolitana de São Paulo"),
    3304557: ("Rio de Janeiro", "RJ", "Metropolitana do Rio de Janeiro"),
    3106200: ("Belo Horizonte", "MG", "Metropolitana de Belo Horizonte"),
    5208707: ("Goiânia", "GO", "Centro Goiano"),
    1721000: ("Palmas", "TO", "Oriental do Tocantins"),
}
ESTADO = {"SP": "São Paulo", "RJ": "Rio de Janeiro", "MG": "Minas Gerais", "GO": "Goiás", "TO": "Tocantins"}

DESCRICAO = {
    "Tempestade": ("Chuva entre 20 e 30 mm/h ou até 50 mm/dia, ventos intensos (40-60 km/h) e queda de granizo.",
                   "Baixo risco de corte de energia elétrica, estragos em plantações, queda de galhos de árvores e de alagamentos."),
    "Chuvas Intensas": ("Chuva entre 30 e 60 mm/h ou 50 e 100 mm/dia.",
                        "Risco de corte de energia elétrica, estragos em plantações, queda de árvores e de alagamentos."),
    "Acumulado de Chuva": ("Acumulado de chuva acima de 100 mm/dia.",
                           "Grande risco de alagamentos, deslizamentos de encostas e transbordamento de rios."),
    "Baixa Umidade": ("Umidade relativa do ar variando entre 30% e 20%.",
                      "Baixo risco de incêndios florestais e à saúde."),
    "Vendaval": ("Ventos entre 40-60 km/h.", "Baixo risco de queda de galhos de árvores."),
    "Onda de Calor": ("Temperatura 5 °C acima da média por um período de 2 a 3 dias.", "Baixo risco à saúde."),
}
INSTRUCAO = ("Em caso de rajadas de vento: não se abrigue debaixo de árvores. Evite enfrentar o mau tempo. "
             "Obtenha mais informações junto à Defesa Civil (telefone 199) e ao Corpo de Bombeiros (telefone 193).")


def identificador(n: int, versao: int = 1) -> str:
    return f"urn:oid:2.49.0.0.76.0.2026.{n}.{versao}"


def cap_xml(rss_id: int, evento: str, severidade: str, inicio: str, fim: str, municipios: list[int], *,
            enviado: str | None = None, msg_type: str = "Alert", status: str = "Actual", referencias: list[str] = (),
            identifier: str | None = None, cor: str | None = "auto", titulo: str | None = None,
            incluir_municipios: bool = True, incluir_area: bool = True, extra_municipios: str = "") -> str:
    identifier = identifier or identificador(rss_id)
    enviado = enviado or inicio
    cor = COR.get(severidade) if cor == "auto" else cor
    grau = GRAU.get(severidade, severidade)
    titulo = titulo if titulo is not None else f"Aviso de {evento}. Severidade Grau: {grau}"
    desc, risco = DESCRICAO.get(evento, ("Aviso meteorológico.", "Fique atento."))
    lista = ", ".join(f"{MUNICIPIOS[m][0]} - {MUNICIPIOS[m][1]} ({m})" for m in municipios) + extra_municipios
    mesos = sorted({MUNICIPIOS[m][2] for m in municipios})
    estados = sorted({ESTADO[MUNICIPIOS[m][1]] for m in municipios})
    refs = " ".join(f"inmet.gov.br,{r},{enviado}" for r in referencias)
    params = ""
    if cor:
        params += f"<parameter><valueName>ColorRisk</valueName><value>{cor}</value></parameter>"
    ts_ini = int(datetime.fromisoformat(inicio).timestamp())
    ts_fim = int(datetime.fromisoformat(fim).timestamp())
    params += (f"<parameter><valueName>TimeStampDateOnSet</valueName><value>{ts_ini}</value></parameter>"
               f"<parameter><valueName>TimeStampDateExpires</valueName><value>{ts_fim}</value></parameter>")
    if incluir_municipios:
        params += f"<parameter><valueName>Municipios</valueName><value>{escape(lista)}</value></parameter>"
    params += f"<parameter><valueName>Estados</valueName><value>{escape(', '.join(estados))}</value></parameter>"
    area = ""
    if incluir_area:
        area = (f"<area><areaDesc>Aviso para as áreas: {escape(', '.join(mesos))}</areaDesc>"
                "<polygon>-23.10,-47.20 -23.10,-45.30 -23.95,-45.30 -23.95,-47.20 -23.10,-47.20</polygon></area>")
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<alert xmlns="{NS}">'
        f"<identifier>{identifier}</identifier><sender>inmet.gov.br</sender><sent>{enviado}</sent>"
        f"<status>{status}</status><msgType>{msg_type}</msgType><scope>Public</scope>"
        + (f"<references>{refs}</references>" if refs else "") +
        "<info><language>pt-BR</language><category>Met</category>"
        f"<event>{evento}</event><responseType>Prepare</responseType><urgency>Future</urgency>"
        f"<severity>{severidade}</severity><certainty>Likely</certainty>"
        f"<onset>{inicio}</onset><expires>{fim}</expires><senderName>INMET</senderName>"
        f"<headline>{escape(titulo)}</headline><description>{escape(desc + ' ' + risco)}</description>"
        f"<instruction>{escape(INSTRUCAO)}</instruction><web>https://alertas2.inmet.gov.br/{rss_id}</web>"
        f"<contact>INMET</contact>{params}{area}</info></alert>\n"
    )


def rss_xml(itens: list[dict], publicado: str) -> str:
    """itens: [{'rss_id', 'evento', 'severidade', 'inicio', 'fim', 'municipios'}], do mais novo para o mais antigo."""
    partes = []
    for i in itens:
        grau = GRAU.get(i["severidade"], i["severidade"])
        mesos = ", ".join(sorted({MUNICIPIOS[m][2] for m in i["municipios"]}))
        tabela = (f"<table><tr><th>Status</th><td>Alert</td></tr><tr><th>Evento</th><td>{i['evento']}</td></tr>"
                  f"<tr><th>Severidade</th><td>{grau}</td></tr><tr><th>Início</th><td>{i['inicio'][:16].replace('T', ' ')}</td></tr>"
                  f"<tr><th>Fim</th><td>{i['fim'][:16].replace('T', ' ')}</td></tr>"
                  f"<tr><th>Área</th><td>Aviso para as Áreas: {mesos}</td></tr>"
                  f"<tr><th>Link Gráfico</th><td><a href='https://avisos.inmet.gov.br/{i['rss_id']}'>"
                  f"https://avisos.inmet.gov.br/{i['rss_id']}</a></td></tr></table>")
        partes.append(
            f"<item><title>{escape('Aviso de ' + i['evento'] + '. Severidade Grau: ' + grau)}</title>"
            f"<link>https://avisos.inmet.gov.br/{i['rss_id']}</link>"
            f"<description><![CDATA[{tabela}]]></description>"
            f"<pubDate>{format_datetime(datetime.fromisoformat(i['inicio']))}</pubDate>"
            f"<guid>{BASE_RSS}/{i['rss_id']}</guid></item>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>Avisos</title>'
            "<link>https://avisos.inmet.gov.br</link><description>Avisos atuais na América do Sul</description>"
            f"<copyright>public domain</copyright><language>pt-BR</language>"
            f"<pubDate>{format_datetime(datetime.fromisoformat(publicado))}</pubDate>"
            + "".join(partes) + "</channel></rss>\n")
