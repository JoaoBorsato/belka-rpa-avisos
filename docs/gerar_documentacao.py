"""
Gera a documentação da entrega em PDF (docs/Belka_RPA_Documentacao.pdf).

Os resultados dos testes vêm dos arquivos em evidencias/, então o PDF sempre bate com a última execução.
Depois de criar o repositório e gravar o vídeo, gere de novo com os links:

    pip install reportlab pillow
    python docs/gerar_documentacao.py --github https://github.com/USUARIO/belka-rpa-avisos --video https://youtu.be/XXXX
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, Image, KeepTogether, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Preformatted, Spacer, Table, TableStyle)

DOCS = Path(__file__).resolve().parent
RAIZ = DOCS.parent
EVID = RAIZ / "evidencias"

# Cores do manual de marca da Belka
NOITE = colors.HexColor("#0B1B34")
BRANCO = colors.HexColor("#F7F3EC")
AMBAR = colors.HexColor("#FFAA33")
AZUL = colors.HexColor("#2F5FD0")
CEU = colors.HexColor("#9DB8F5")
NEVOA = colors.HexColor("#ECE7DE")
GRAFITE = colors.HexColor("#1E2635")
NIVEL = {1: colors.HexColor("#F5C518"), 2: colors.HexColor("#F07C1B"), 3: colors.HexColor("#C81E35")}

# ----------------------------------------------------------------------- fontes
F = {"txt": "Helvetica", "neg": "Helvetica-Bold", "tit": "Helvetica-Bold", "mono": "Courier"}
try:
    for nome, arq in {"Txt": "DejaVuSans.ttf", "Neg": "DejaVuSans-Bold.ttf", "Mono": "DejaVuSansMono.ttf",
                      "Tit": "Poppins-Bold.ttf"}.items():
        pdfmetrics.registerFont(TTFont(nome, str(DOCS / "fontes" / arq)))
    pdfmetrics.registerFontFamily("Txt", normal="Txt", bold="Neg", italic="Txt", boldItalic="Neg")
    F = {"txt": "Txt", "neg": "Neg", "tit": "Tit", "mono": "Mono"}
except Exception:
    pass   # sem as fontes do repositório, usa Helvetica (os acentos continuam funcionando)


def t(s: str) -> str:
    """Troca símbolos que a Helvetica não tem, se as fontes do repositório não carregaram."""
    return s if F["txt"] == "Txt" else s.replace("→", "->").replace("✓", "OK").replace("≥", ">=")


S = {
    "corpo": ParagraphStyle("corpo", fontName=F["txt"], fontSize=9.6, leading=14, textColor=GRAFITE,
                            alignment=TA_LEFT, spaceAfter=6),
    "h1": ParagraphStyle("h1", fontName=F["tit"], fontSize=17, leading=21, textColor=NOITE, spaceBefore=4, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName=F["tit"], fontSize=11.5, leading=15, textColor=NOITE, spaceBefore=8, spaceAfter=4),
    "rotulo": ParagraphStyle("rotulo", fontName=F["neg"], fontSize=7.5, leading=10, textColor=AZUL, spaceAfter=2),
    "cel": ParagraphStyle("cel", fontName=F["txt"], fontSize=8.4, leading=11.2, textColor=GRAFITE),
    "celh": ParagraphStyle("celh", fontName=F["neg"], fontSize=8.4, leading=11.2, textColor=BRANCO),
    "mono": ParagraphStyle("mono", fontName=F["mono"], fontSize=6.9, leading=9.2, textColor=GRAFITE),
    "legenda": ParagraphStyle("legenda", fontName=F["txt"], fontSize=8, leading=11, textColor=colors.HexColor("#5A6478")),
    "bala": ParagraphStyle("bala", fontName=F["txt"], fontSize=9.6, leading=14, textColor=GRAFITE, leftIndent=12,
                           bulletIndent=2, spaceAfter=3),
}


def P(texto, estilo="corpo"):
    return Paragraph(t(texto), S[estilo])


def balas(itens):
    return [Paragraph(t(i), S["bala"], bulletText="•") for i in itens]


def tabela(cab, linhas, larguras, destaque_col=None):
    dados = [[Paragraph(t(c), S["celh"]) for c in cab]]
    dados += [[c if not isinstance(c, str) else Paragraph(t(c), S["cel"]) for c in l] for l in linhas]
    tb = Table(dados, colWidths=larguras, repeatRows=1)
    est = [("BACKGROUND", (0, 0), (-1, 0), NOITE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
           ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9D2C5")),
           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
           ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]
    for i in range(1, len(dados)):
        if i % 2 == 0:
            est.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F3EFE7")))
    tb.setStyle(TableStyle(est))
    return tb


def linha_log(l: str, limite: int = 112) -> str:
    """Encurta uma linha de log para caber na página: só a hora, sem colunas de alinhamento."""
    l = re.sub(r"^\S+ (\d\d:\d\d:\d\d)-0300", r"\1", l)
    l = re.sub(r" {2,}", " ", l)
    return l if len(l) <= limite else l[: limite - 1] + "…"


def codigo(texto):
    bloco = Preformatted(texto, S["mono"])
    tb = Table([[bloco]], colWidths=[LARG])
    tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFEAE1")),
                            ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9D2C5")),
                            ("LEFTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 6),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return tb


def selo(nivel, texto):
    cor_txt = BRANCO if nivel == 3 else NOITE
    tb = Table([[Paragraph(f'<font color="{cor_txt.hexval()}">{t(texto)}</font>', S["celh"])]])
    tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), NIVEL[nivel]), ("LEFTPADDING", (0, 0), (-1, -1), 5),
                            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return tb


# ----------------------------------------------------------------------- páginas
LARG_PAG, ALT_PAG = A4
MARGEM = 20 * mm
LARG = LARG_PAG - 2 * MARGEM


def capa(c, doc):
    c.saveState()
    c.setFillColor(NOITE)
    c.rect(0, 0, LARG_PAG, ALT_PAG, fill=1, stroke=0)
    c.setStrokeColor(CEU)
    c.setLineWidth(0.6)
    for r, a in ((420, 0.35), (520, 0.22)):
        c.setStrokeAlpha(a)
        c.circle(LARG_PAG * 0.82, ALT_PAG * 0.18, r, stroke=1, fill=0)
    c.setStrokeAlpha(1)
    c.setFillColor(AMBAR)
    c.circle(LARG_PAG - 52 * mm, ALT_PAG * 0.43, 5, fill=1, stroke=0)
    c.circle(MARGEM + 3, ALT_PAG - 38 * mm + 3, 3, fill=1, stroke=0)
    c.setFillColor(CEU)
    c.setFont(F["neg"], 8.5)
    c.drawString(MARGEM + 10, ALT_PAG - 38 * mm, "GLOBAL SOLUTION 2026.2 · CITIZENTECH · ROBOTIC PROCESS AUTOMATION")
    c.setFillColor(BRANCO)
    c.setFont(F["tit"], 46)
    c.drawString(MARGEM, ALT_PAG - 68 * mm, "belka")
    c.setFont(F["tit"], 24)
    c.drawString(MARGEM, ALT_PAG - 86 * mm, "Robô de avisos oficiais")
    c.setFillColor(AMBAR)
    c.drawString(MARGEM, ALT_PAG - 97 * mm, "do INMET")
    c.setFillColor(BRANCO)
    c.setFont(F["txt"], 11)
    y = ALT_PAG - 112 * mm
    for linha in ("Do processo manual à automação inteligente: o robô lê os avisos do INMET,",
                  "encontra os municípios piloto, converte para os níveis da Belka, publica para",
                  "o MVP e aponta onde o modelo da Belka ficou abaixo do aviso oficial."):
        c.drawString(MARGEM, y, linha)
        y -= 15
    c.setFont(F["tit"], 13)
    c.drawString(MARGEM, 96 * mm, "Olhar longe.")
    c.setFillColor(AMBAR)
    c.drawString(MARGEM + 88, 96 * mm, "Proteger perto.")
    c.setFillColor(CEU)
    c.setFont(F["neg"], 8)
    c.drawString(MARGEM, 80 * mm, "EQUIPE")
    c.setFillColor(BRANCO)
    c.setFont(F["txt"], 10)
    y = 73 * mm
    for nome, rm in EQUIPE:
        c.drawString(MARGEM, y, nome)
        c.drawString(MARGEM + 175, y, f"RM {rm}")
        y -= 14
    c.setFillColor(CEU)
    c.setFont(F["neg"], 8)
    c.drawString(MARGEM, 34 * mm, "LINKS")
    c.setFillColor(BRANCO)
    c.setFont(F["txt"], 9.5)
    c.drawString(MARGEM, 28 * mm, f"Repositório: {doc.links['github']}")
    c.drawString(MARGEM, 22.5 * mm, f"Vídeo: {doc.links['video']}")
    c.setFillColor(CEU)
    c.setFont(F["txt"], 8)
    c.drawString(MARGEM, 13 * mm, "Engenharia de Software · 4º ano · FIAP · novembro de 2026")
    c.restoreState()


def rodape(c, doc):
    c.saveState()
    c.setFillColor(AMBAR)
    c.circle(MARGEM + 2.5, ALT_PAG - 12 * mm + 2.5, 2.5, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#5A6478"))
    c.setFont(F["neg"], 7.5)
    c.drawString(MARGEM + 9, ALT_PAG - 12 * mm, "BELKA · RPA · AVISOS OFICIAIS DO INMET")
    c.setStrokeColor(colors.HexColor("#D9D2C5"))
    c.line(MARGEM, 14 * mm, LARG_PAG - MARGEM, 14 * mm)
    c.setFont(F["txt"], 7.5)
    c.drawString(MARGEM, 9.5 * mm, "Belka · Olhar longe. Proteger perto.")
    c.drawRightString(LARG_PAG - MARGEM, 9.5 * mm, str(doc.page))
    c.restoreState()


EQUIPE = [("Fernanda Kaory Saito", "551104"), ("João Pedro Borsato", "550294"),
          ("Maria Fernanda Camargo", "97956"), ("Pedro Lucas Nunes", "550366")]


# ----------------------------------------------------------------------- dados das evidências
def ler_cenarios():
    nomes = {
        "01_sucesso_e_decisoes": ("Feed de 07/11 com todos os tipos de aviso", "Sucesso e decisão"),
        "02_idempotencia": ("Mesmo feed outra vez", "Idempotência"),
        "03_inmet_fora_do_ar_com_base": ("INMET fora do ar depois de uma leitura", "Falha recuperável"),
        "04_dados_invalidos": ("CAP corrompido, sem severidade e indisponível", "Falha recuperável"),
        "05_falha_sem_base": ("INMET fora do ar na primeira execução", "Falha crítica"),
    }
    linhas = []
    for pasta in sorted((EVID / "cenarios").iterdir()):
        r = json.loads((pasta / "relatorio.json").read_text(encoding="utf-8"))
        desc, tipo = nomes.get(pasta.name, (pasta.name, "-"))
        itens = ", ".join(f"{k}: {v}" for k, v in r["itens"].items()) or "nenhum item lido"
        linhas.append([f"<b>{pasta.name[:2]}</b> {desc}", tipo, f"<b>{r['status'].replace('_COM_', '_COM_<br/>')}</b>", itens,
                       str(len(r["pendencias"]))])
    return linhas


def ler_execucao_real():
    arq = EVID / "execucao_inmet_real.log"
    if not arq.exists():
        return None
    log = arq.read_text(encoding="utf-8")
    m_feed = re.search(r"(\d+) aviso\(s\) no feed", log)
    m_fim = re.search(r"status (\w+) · itens (\{.*?\}).*?· ([\d.]+) s", log)
    return {
        "quando": log[:16],
        "feed": m_feed.group(1) if m_feed else "?",
        "status": m_fim.group(1) if m_fim else "?",
        "itens": m_fim.group(2) if m_fim else "?",
        "duracao": m_fim.group(3) if m_fim else "?",
        "piloto": len(re.findall(r"aviso_cap\s+\| ok", log)),
        "fora": log.count("nenhum município piloto atingido"),
        "cancel": log.count("Cancel de "),
        "trecho": "\n".join(l for l in log.splitlines()
                             if any(k in l for k in ("| feed ", "56383", "56447", "56355 ", "56448", "comparacao", "| fim "))),
    }


def partes_bpmn():
    img = PILImage.open(DOCS / "belka_avisos_bpmn.png")
    cortes = [0, 2050, 4200, img.height]
    saida = []
    for i in range(3):
        destino = DOCS / f"_bpmn_parte{i + 1}.png"
        parte = img.crop((0, cortes[i], img.width, cortes[i + 1]))
        caixa = PILImage.eval(parte.convert("L"), lambda v: 255 if v < 245 else 0).getbbox()
        if caixa:
            parte = parte.crop((max(caixa[0] - 20, 0), max(caixa[1] - 10, 0),
                                min(caixa[2] + 20, parte.width), min(caixa[3] + 10, parte.height)))
        parte.save(destino)
        saida.append(destino)
    return saida


# ----------------------------------------------------------------------- conteúdo
def conteudo():
    st = []
    st.append(NextPageTemplate("normal"))
    st.append(PageBreak())

    # 1 visão geral
    st += [P("RESUMO", "rotulo"), P("O componente de automação da Belka", "h1"),
           P("O MVP da Belka avisa o cidadão que os níveis calculados pela Belka são indicadores experimentais e "
             "não substituem os avisos oficiais. Para mostrar esses avisos e conferir o modelo, alguém da equipe "
             "teria que abrir o portal do INMET todos os dias, procurar os municípios piloto em dezenas de avisos, "
             "traduzir a severidade, copiar para o MVP e comparar com a Belka."),
           P("Este robô em Python faz isso de ponta a ponta, sem intervenção humana: lê o feed oficial de avisos do "
             "INMET no padrão internacional CAP 1.2, decide aviso por aviso o que fazer, publica um arquivo "
             "estruturado que o MVP consome e aponta à equipe onde o modelo da Belka ficou abaixo do aviso oficial. "
             "Tudo com log, trilha de auditoria e tratamento de falhas."),
           Spacer(1, 4), P("Onde cada etapa obrigatória do desafio é atendida", "h2"),
           tabela(["Etapa obrigatória", "Como o robô atende", "Seção"], [
               ["01 Mapeamento do processo", "Fluxo BPMN 2.0 (arquivo .bpmn editável e imagem) com início, entradas, decisões, repetição, exceções e saídas", "3"],
               ["02 Desenvolvimento", "Python 3.10+, versionado no GitHub, executável por linha de comando ou agendador", "2, 10"],
               ["03 Lógica de negócio e lote", "Laço sobre todos os avisos do feed; 9 pontos de decisão (cancelamento, atualização, área, severidade...)", "4"],
               ["04 Exceções e resiliência", "Novas tentativas, base anterior, quarentena, pendências refeitas, arquivo do MVP preservado", "5"],
               ["05 Logs e auditoria", "Log legível, eventos JSON, relatório por execução e histórico no banco, com dados sensíveis mascarados", "6"],
               ["06 Integração com o MVP", "saida/avisos_oficiais.json (arquivo estruturado) e SQLite consumidos pelo MVP e pelo Belka AI", "7"],
               ["07 Testes e validação", "51 testes automatizados, 5 cenários com evidências e execução contra o feed real", "8"],
               ["08 Documentação e publicação", "Repositório público com README, este PDF e o vídeo", "10"],
           ], [43 * mm, 109 * mm, 18 * mm])]

    # 2 problema e solução
    st += [PageBreak(), P("O PROBLEMA E A SOLUÇÃO", "rotulo"), P("Do processo manual ao robô", "h1"),
           P("Processo manual (antes)", "h2"),
           tabela(["#", "Tarefa manual", "Risco"], [
               ["1", "Abrir o portal do INMET e procurar os 5 municípios piloto em dezenas de avisos", "Aviso esquecido; a área vem por mesorregião e é fácil confundir"],
               ["2", "Abrir cada aviso, ver severidade, início e fim, e copiar para o MVP", "Erro de digitação; aviso cancelado ou atualizado continua no ar"],
               ["3", "Traduzir Perigo Potencial, Perigo e Grande Perigo para os níveis da Belka", "Cada pessoa interpreta de um jeito"],
               ["4", "Comparar com o nível calculado pela Belka e avisar a equipe", "Ninguém faz; o modelo não é recalibrado"],
           ], [8 * mm, 85 * mm, 77 * mm]),
           P("Processo automatizado (depois)", "h2"),
           codigo("Feed RSS do INMET → para cada aviso: baixar o CAP → validar → cancelamento / atualização / novo?\n"
                  "   → atinge município piloto? (código IBGE) → severidade → nível Belka → banco SQLite\n"
                  "   → comparação com belka_mvp.json → saida/avisos_oficiais.json (MVP) → divergencias.csv\n"
                  "   → aviso grave → equipe (webhook) → relatório, log e auditoria"),
           Spacer(1, 6), P("Fonte de dados", "h2"),
           P("<b>INMET · avisos meteorológicos</b>, em <font color='#2F5FD0'>https://apiprevmet3.inmet.gov.br/avisos/rss</font>. "
             "O feed RSS lista os avisos atuais; cada item aponta para um documento <b>CAP 1.2</b> (Common Alerting "
             "Protocol, padrão OASIS) com identificador, tipo da mensagem (Alert, Update, Cancel), evento, severidade, "
             "início, fim, cor do aviso e a lista de municípios no formato <i>São Paulo - SP (3550308)</i>. A fonte é "
             "pública, não exige chave e não contém dado pessoal."),
           P("Tecnologia", "h2"),
           tabela(["Item", "Escolha"], [
               ["Linguagem", "Python 3.10+ (requests, defusedxml, tzdata; pytest para os testes)"],
               ["Banco operacional", "SQLite (saida/belka_avisos.db), sem servidor"],
               ["Agendamento", "Airflow 3 (DAG em agendamento/), cron ou Agendador de Tarefas do Windows, todo dia às 06:45"],
               ["Fluxo", "BPMN 2.0 gerado a partir da mesma definição do código (docs/gerar_bpmn.py)"],
           ], [38 * mm, 132 * mm])]

    # 3 BPMN
    partes = partes_bpmn()
    tamanhos = [PILImage.open(parte).size for parte in partes]
    escala = min(min(LARG / w, (222 * mm if i == 0 else 238 * mm) / h) for i, (w, h) in enumerate(tamanhos))
    for i, parte in enumerate(partes):
        w, h = tamanhos[i]
        larg_img, alt = w * escala, h * escala
        st.append(PageBreak())
        if i == 0:
            st += [P("01 · MAPEAMENTO DO PROCESSO", "rotulo"), P("Fluxo BPMN", "h1"),
                   P("O BPMN editável está em docs/belka_avisos.bpmn (abre no bpmn.io e no Camunda Modeler). "
                     "Legenda: ↻ repetição · ⚙ chamada externa · ✉ envio · losango = decisão.", "legenda"),
                   Spacer(1, 4)]
        else:
            st.append(P(f"Fluxo BPMN · parte {i + 1} de 3", "rotulo"))
        st.append(Image(str(parte), width=larg_img, height=alt))

    # 4 regras
    st += [PageBreak(), P("03 · LÓGICA DE NEGÓCIO E LOTE", "rotulo"), P("Regras, decisões e repetição", "h1"),
           P("<b>Repetição:</b> o robô percorre todos os itens do feed, do mais antigo para o mais novo, para que "
             "cancelamentos e atualizações cheguem depois do aviso original (65 avisos no feed real). "
             "<b>Decisões</b>, na ordem em que acontecem:"),
           tabela(["Decisão", "Se sim", "Se não"], [
               ["Configuração válida?", "Segue", "FALHA, nada publicado"],
               ["Feed lido?", "Processa os avisos", "Com leitura anterior, publica da base (fonte desatualizada); sem, FALHA"],
               ["Aviso já processado?", "Pula sem baixar de novo (idempotência)", "Baixa o documento CAP"],
               ["Baixou o CAP?", "Valida", "Pendência; refeito na próxima execução"],
               ["CAP válido?", "Segue", "Quarentena com o motivo"],
               ["Aviso real e inédito?", "Segue", "Exercício, teste ou duplicado: ignora e registra"],
               ["Tipo da mensagem", "Cancel: cancela o aviso citado · Update: substitui o anterior", "Alert: aviso novo"],
               ["Atinge município piloto?", "Converte e grava", "Ignora: fora da área"],
               ["Contrato do arquivo íntegro?", "Publica para o MVP", "FALHA, arquivo anterior mantido"],
               ["Aviso Grande Perigo ainda não avisado?", "Notifica a equipe (uma vez só)", "Segue"],
           ], [45 * mm, 62 * mm, 63 * mm]),
           P("Severidade oficial e nível da Belka", "h2"),
           P("Segue o manual de marca (campo equivalente_inmet do MVP). O robô usa três sinais do aviso: severity, "
             "cor e grau no título. Se discordarem, vale o mais grave; nenhum sinal reconhecido leva à quarentena."),
           tabela(["INMET (grau)", "CAP severity", "Cor", "Nível Belka"], [
               ["Perigo Potencial", "Moderate", "amarelo", selo(1, "1 · Fique de olho")],
               ["Perigo", "Severe", "laranja", selo(2, "2 · Prepare-se")],
               ["Grande Perigo", "Extreme", "vermelho", selo(3, "3 · Aja agora")],
           ], [42 * mm, 35 * mm, 30 * mm, 63 * mm]),
           KeepTogether([P("Evento do INMET e riscos da Belka", "h2"),
                         tabela(["Evento do INMET", "Riscos da Belka"], [
                             ["Tempestade", "enchente, vento forte"],
                             ["Chuvas Intensas, Acumulado de Chuva", "enchente, deslizamento"],
                             ["Vendaval, Ventos Costeiros", "vento forte"],
                             ["Baixa Umidade · Onda de Calor", "tempo seco · calor extremo"],
                             ["outros (geada, frio, ressaca...)", "outro"],
                         ], [80 * mm, 90 * mm])]),
           Spacer(1, 2),
           P("<b>Área:</b> código IBGE da lista do CAP (ou a mesorregião, se a lista faltar). <b>Situação:</b> vigente, "
             "próximo (até 3 dias) ou expirado. <b>Comparação:</b> concorda, belka_abaixo ou belka_acima. "
             "Tudo configurável em config/config_avisos.json.")]

    # 5 exceções
    st += [PageBreak(), P("04 · EXCEÇÕES E RESILIÊNCIA", "rotulo"), P("Nenhuma falha é silenciosa", "h1"),
           P("Toda situação abaixo vira evento de auditoria, entra no relatório e define o status final da execução: "
             "<b>SUCESSO</b>, <b>SUCESSO_COM_PENDENCIAS</b> ou <b>FALHA</b> (código de saída 2)."),
           tabela(["Situação", "O que o robô faz"], [
               ["Feed do INMET fora do ar (API indisponível)", "3 tentativas com espera crescente (2 s, 4 s); com base anterior, publica marcando fonte.desatualizada; sem base, FALHA sem publicar"],
               ["Feed vazio, página de manutenção ou XML quebrado", "Tratado como feed indisponível (mesma decisão)"],
               ["Um documento CAP não baixa", "Pendência; o item é refeito na próxima execução e os outros seguem"],
               ["CAP corrompido, sem campo obrigatório ou com datas incoerentes (arquivo inválido)", "Quarentena em saida/quarentena/ com o XML e o motivo"],
               ["XML com entidades externas (ataque XXE)", "Recusado pelo defusedxml e enviado para a quarentena"],
               ["Severidade não reconhecida", "Quarentena"],
               ["Sinais de severidade em conflito (dado inconsistente)", "Usa o mais grave e registra no log"],
               ["Município fora do padrão na lista", "Descartado e contado no log"],
               ["Mesmo aviso em dois itens do feed (dado duplicado)", "Ignorado pelo identificador"],
               ["Cancelamento que chega antes do aviso", "Guardado e aplicado quando o aviso chegar"],
               ["Robô rodando de novo", "Itens já processados nem são baixados; nada duplica"],
               ["belka_mvp.json ausente ou inválido", "Publica os avisos sem comparação e registra pendência"],
               ["Arquivo do MVP reprovado na validação", "FALHA; o arquivo anterior continua publicado (escrita atômica)"],
               ["Erro inesperado num aviso", "Registrado com o tipo do erro; o lote continua"],
           ], [72 * mm, 98 * mm])]

    # 6 logs
    st += [PageBreak(), P("05 · LOGS E AUDITORIA", "rotulo"), P("Registros de cada execução", "h1"),
           tabela(["Arquivo", "Conteúdo"], [
               ["logs/belka_avisos_&lt;execução&gt;.log", "Data/hora, nível, etapa, resultado, item e mensagem"],
               ["logs/auditoria.jsonl", "Um evento JSON por linha, acumulado entre execuções"],
               ["saida/relatorios/relatorio_&lt;execução&gt;.json", "Itens por situação, decisões, comparação, publicação, notificações, pendências e duração"],
               ["saida/ultima_execucao.json", "Cópia do último relatório, para monitoramento"],
               ["tabela execucoes (SQLite)", "Histórico de todas as execuções com status"],
           ], [62 * mm, 108 * mm]),
           Spacer(1, 6),
           P("Antes de gravar, todo texto passa por uma máscara que esconde tokens, senhas, e-mails, telefones, URLs "
             "com credenciais e caminhos de webhook. Há teste automatizado garantindo isso."),
           P("Trecho do log · cenário 01 (feed de exemplo)", "h2")]
    log01 = (EVID / "cenarios" / "01_sucesso_e_decisoes" / "execucao.log").read_text(encoding="utf-8").splitlines()
    sel = [l for l in log01 if any(k in l for k in ("| feed ", "55902", "55906", "55909", "55903", "comparacao",
                                                    "divergencia", "publicacao", "| fim "))]
    st.append(codigo("\n".join(linha_log(l) for l in sel)))

    # 7 integração
    s = json.loads((EVID / "cenarios" / "01_sucesso_e_decisoes" / "avisos_oficiais.json").read_text(encoding="utf-8"))
    ssb = next(m for m in s["municipios"] if m["municipio_id"] == 3550704)
    av = ssb["avisos_vigentes"][0]
    exemplo = {"municipio_id": ssb["municipio_id"], "municipio_nome": ssb["municipio_nome"],
               "nivel_oficial_agora": ssb["nivel_oficial_agora"], "nivel_nome": ssb["nivel_nome"],
               "grau_inmet": ssb["grau_inmet"],
               "avisos_vigentes": [{k: av[k] for k in ("evento", "situacao", "nivel_nome", "grau_inmet", "riscos",
                                                       "inicio", "fim", "link", "criterio_area")}]}
    comp = next(c for c in s["comparacao_belka"]["municipios"] if c["municipio_id"] == 3550704)
    st += [PageBreak(), P("06 · INTEGRAÇÃO COM O MVP", "rotulo"), P("O que o MVP recebe", "h1"),
           tabela(["Saída", "Quem consome", "Conteúdo"], [
               ["saida/avisos_oficiais.json", "Tela do cidadão (MVP)", "Por município: nível oficial agora, avisos vigentes e próximos (título, descrição, instrução, link do INMET), comparação com a Belka e situação da fonte"],
               ["saida/belka_avisos.db (SQLite)", "Assistente Belka AI, painel da Defesa Civil", "Tabelas avisos, aviso_municipio, itens_rss, execucoes, notificacoes"],
               ["saida/divergencias.csv", "Equipe de dados da Belka", "Onde o modelo ficou abaixo ou acima do aviso oficial"],
           ], [48 * mm, 42 * mm, 80 * mm]),
           Spacer(1, 4),
           P("A entrada vinda do pipeline de dados é entrada/belka_mvp.json, o mesmo snapshot que o MVP já usa. "
             "O arquivo é gravado de forma atômica (o MVP nunca lê um arquivo pela metade) e a versão anterior fica "
             "em avisos_oficiais.anterior.json."),
           P("Exemplo · São Sebastião no cenário 01", "h2"),
           codigo(json.dumps(exemplo, ensure_ascii=False, indent=2)),
           Spacer(1, 4),
           codigo('"comparacao_belka": ' + json.dumps({k: comp[k] for k in ("municipio_nome", "nivel_belka_nome",
                                                                             "nivel_oficial_nome", "resultado")},
                                                      ensure_ascii=False, indent=2)),
           Spacer(1, 4),
           P("Na tela, o MVP mostra o selo do aviso oficial ao lado do nível da Belka, os cartões com o texto do "
             "INMET e um aviso quando a fonte estiver desatualizada.")]

    # 8 testes
    real = ler_execucao_real()
    st += [PageBreak(), P("07 · TESTES E VALIDAÇÃO", "rotulo"), P("Sucesso, decisão e falha", "h1"),
           P("<b>51 testes automatizados</b> (python -m pytest -v) cobrem as regras isoladas e o robô inteiro de ponta "
             "a ponta, com rede simulada. A saída completa está em evidencias/testes_pytest.txt. Os 5 cenários abaixo "
             "são executados por python demo_cenarios.py, que guarda log, relatório e saídas de cada um em "
             "evidencias/cenarios/."),
           tabela(["Cenário", "Tipo", "Status", "Itens", "Pend"], ler_cenarios(),
                  [48 * mm, 25 * mm, 40 * mm, 45 * mm, 12 * mm]),
           Spacer(1, 4),
           *balas(["<b>01</b>: São Sebastião em Prepare-se (Chuvas Intensas), Vendaval cancelado, Onda de Calor "
                   "atualizada para Prepare-se, exercício e aviso de Goiás e Tocantins ignorados, divergência apontada.",
                   "<b>02</b>: os 10 itens são reconhecidos como já processados; nada é baixado nem duplicado.",
                   "<b>03</b>: 3 tentativas registradas; o MVP recebe os avisos da base com fonte.desatualizada = true.",
                   "<b>04</b>: 2 avisos na quarentena com o motivo, 1 pendência para refazer e os demais publicados.",
                   "<b>05</b>: sem base anterior, FALHA com código de saída 2 e nenhum arquivo publicado."])]
    if real:
        st += [CondPageBreak(70 * mm), P("Execução contra o feed real do INMET", "h2"),
               P(f"Em {real['quando']}, o robô leu o feed oficial: <b>{real['feed']} avisos</b> processados em "
                 f"<b>{real['duracao']} s</b>, status <b>{real['status']}</b>. <b>{real['piloto']}</b> avisos de "
                 f"Tempestade atingiam os municípios piloto (Perigo Potencial → Fique de olho, confirmado por "
                 f"severidade e cor), <b>{real['fora']}</b> foram ignorados por estarem fora da área e "
                 f"<b>{real['cancel']}</b> cancelamentos citavam avisos que já tinham saído do feed. A comparação "
                 "saiu como indisponível, porque o snapshot da Belka ia até 07/11: o robô registra isso em vez de "
                 "inventar um resultado. Log completo em evidencias/execucao_inmet_real.log."),
               codigo("\n".join(linha_log(l) for l in real["trecho"].splitlines()))]

    # 9 segurança
    st += [PageBreak(), P("SEGURANÇA E LGPD", "rotulo"), P("Boas práticas", "h1"),
           *balas(["A fonte é pública e não tem dado pessoal. O robô trabalha <b>por município</b>: não lê nem grava "
                   "nome, telefone ou e-mail de cidadão.",
                   "A URL do webhook vem só de variável de ambiente (.env, fora do Git). Não há chave nem senha no "
                   "repositório.",
                   "Todo texto que vai para o log passa por uma máscara de tokens, senhas, e-mails, telefones, URLs "
                   "com credenciais e webhooks.",
                   "O XML externo é lido com defusedxml (bloqueia XXE e bomba de entidades) e respostas acima de 5 MB "
                   "são recusadas.",
                   "O arquivo do MVP é gravado de forma atômica, validado contra o contrato antes de publicar, e a "
                   "versão anterior é preservada.",
                   "Os avisos do INMET são reproduzidos sem alteração e o MVP mantém o aviso legal com Defesa Civil "
                   "(199) e Corpo de Bombeiros (193)."])]

    # 10 como executar
    st += [Spacer(1, 10), P("08 · DOCUMENTAÇÃO E PUBLICAÇÃO", "rotulo"), P("Como executar", "h1"),
           codigo("pip install -r requirements.txt\n\n"
                  "python -m belka_avisos                       # produção: lê o feed do INMET agora\n"
                  "python -m belka_avisos --local exemplos/feed_2026-11-07 --agora 2026-11-07T15:00:00-03:00\n"
                  "                                             # demonstração offline\n"
                  "python -m belka_avisos --estrito             # código 1 se houver pendências\n\n"
                  "python -m pytest -v                          # 51 testes\n"
                  "python demo_cenarios.py                      # 5 cenários com evidências"),
           Spacer(1, 6),
           P("Códigos de saída: 0 sucesso (com ou sem pendências), 1 pendências em modo estrito, 2 falha. "
             "Agendamento diário às 06:45 pelo Airflow (agendamento/belka_avisos_dag.py), cron ou Agendador de "
             "Tarefas do Windows."),
           P("Estrutura do repositório", "h2"),
           codigo("belka_avisos/   robo.py (E1–E8) · fonte.py · cap.py · regras.py · banco.py · publicacao.py · auditoria.py\n"
                  "config/         config_avisos.json (regras de negócio)\n"
                  "entrada/        belka_mvp.json (snapshot da Belka, vindo do pipeline de dados)\n"
                  "exemplos/       feed de exemplo no formato do INMET\n"
                  "tests/          51 testes automatizados\n"
                  "docs/           BPMN (.bpmn, .png, .svg) e geradores\n"
                  "evidencias/     logs, relatórios e saídas dos cenários e da execução real\n"
                  "agendamento/    DAG do Airflow"),
           P("Fontes", "h2"),
           *balas(["INMET, Avisos meteorológicos: https://apiprevmet3.inmet.gov.br/avisos/rss",
                   "OASIS, Common Alerting Protocol 1.2: https://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2-os.html",
                   "Belka, Manual de marca (cores, escala de alerta e equivalência com o INMET)"])]
    return st


class Documento(BaseDocTemplate):
    def __init__(self, arquivo, links):
        super().__init__(str(arquivo), pagesize=A4, leftMargin=MARGEM, rightMargin=MARGEM, topMargin=20 * mm,
                         bottomMargin=20 * mm, title="Belka · RPA · Avisos oficiais do INMET",
                         author="Equipe Belka", subject="Global Solution 2026.2 · Robotic Process Automation")
        self.links = links
        quadro = Frame(MARGEM, 20 * mm, LARG, ALT_PAG - 40 * mm, id="corpo")
        self.addPageTemplates([PageTemplate("capa", [Frame(0, 0, LARG_PAG, ALT_PAG)], onPage=capa),
                               PageTemplate("normal", [quadro], onPage=rodape)])


def main():
    p = argparse.ArgumentParser(description="Gera docs/Belka_RPA_Documentacao.pdf")
    p.add_argument("--github", default="(adicionar o link do repositório)")
    p.add_argument("--video", default="(adicionar o link do vídeo)")
    p.add_argument("--saida", default=str(DOCS / "Belka_RPA_Documentacao.pdf"))
    a = p.parse_args()
    doc = Documento(a.saida, {"github": a.github, "video": a.video})
    doc.build(conteudo())
    for parte in DOCS.glob("_bpmn_parte*.png"):
        parte.unlink()
    print("PDF gerado:", a.saida)


if __name__ == "__main__":
    main()
