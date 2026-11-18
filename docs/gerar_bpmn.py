"""
Gera o fluxo do robô a partir de uma única definição (a mesma ordem de etapas de belka_avisos/robo.py):

  docs/belka_avisos.bpmn       BPMN 2.0 com diagrama (abre no https://demo.bpmn.io e no Camunda Modeler)
  docs/belka_avisos_bpmn.png   imagem para o README e o PDF
  docs/belka_avisos_bpmn.svg

O Graphviz (executável 'dot') calcula o layout; as mesmas coordenadas vão para o diagrama BPMN.
Uso: python docs/gerar_bpmn.py
"""
import json
import subprocess
from html import escape
from pathlib import Path

PASTA = Path(__file__).resolve().parent
TAM = {"start": (36, 36), "end": (36, 36), "task": (150, 64), "gw": (50, 50)}

# id: (tipo, rótulo, marcador)   marcador: loop | service | send | script
NOS = {
    "inicio":    ("start", "Início agendado\n(todo dia, 06:45)", ""),
    "t_cfg":     ("task", "Carregar e validar\nconfiguração", "script"),
    "g_cfg":     ("gw", "Configuração\nválida?", ""),
    "t_feed":    ("task", "Ler feed RSS do INMET\n(3 tentativas,\nespera crescente)", "service"),
    "g_feed":    ("gw", "Feed lido?", ""),
    "g_base":    ("gw", "Existe leitura\nanterior na base?", ""),
    "t_desat":   ("task", "Seguir com a base\ne marcar fonte\ndesatualizada", "script"),
    "t_item":    ("task", "Próximo aviso do feed\n(para cada item)", "loop"),
    "g_visto":   ("gw", "Já processado?", ""),
    "t_cap":     ("task", "Baixar documento CAP\n(3 tentativas)", "service"),
    "g_baixou":  ("gw", "Baixou?", ""),
    "t_pend":    ("task", "Registrar pendência\n(refazer na próxima\nexecução)", "script"),
    "t_valida":  ("task", "Validar CAP\n(XML seguro, campos,\ndatas)", "script"),
    "g_valido":  ("gw", "CAP válido?", ""),
    "t_quar":    ("task", "Quarentena\ncom o motivo", "script"),
    "g_real":    ("gw", "Aviso real e inédito?\n(status Actual,\nidentifier novo)", ""),
    "t_ign":     ("task", "Ignorar e registrar\n(exercício ou\nduplicado)", "script"),
    "g_tipo":    ("gw", "Tipo da\nmensagem?", ""),
    "t_cancel":  ("task", "Marcar aviso citado\ncomo cancelado", "script"),
    "t_subst":   ("task", "Marcar aviso anterior\ncomo substituído", "script"),
    "g_area":    ("gw", "Atinge município\npiloto? (código\nIBGE ou mesorregião)", ""),
    "t_fora":    ("task", "Ignorar:\nfora da área piloto", "script"),
    "t_nivel":   ("task", "Converter severidade\nem nível Belka\ne riscos", "script"),
    "t_grava":   ("task", "Gravar aviso\nno banco", "script"),
    "j_item":    ("gw", "", ""),
    "g_mais":    ("gw", "Mais avisos?", ""),
    "t_comp":    ("task", "Comparar com o nível\nda Belka\n(belka_mvp.json)", "script"),
    "t_monta":   ("task", "Montar\navisos_oficiais.json", "script"),
    "g_contr":   ("gw", "Contrato\níntegro?", ""),
    "t_pub":     ("task", "Publicar para o MVP\n(escrita atômica)", "script"),
    "t_div":     ("task", "Exportar\ndivergencias.csv", "script"),
    "g_grave":   ("gw", "Aviso Grande Perigo\nainda não avisado?", ""),
    "t_notif":   ("task", "Notificar equipe\n(webhook)", "send"),
    "j_rel":     ("gw", "", ""),
    "t_rel":     ("task", "Relatório, log\ne auditoria", "script"),
    "g_pend":    ("gw", "Houve\npendência?", ""),
    "t_aviso":   ("task", "Avisar equipe\n(webhook)", "send"),
    "fim_ok":    ("end", "Sucesso", ""),
    "fim_pend":  ("end", "Sucesso com\npendências", ""),
    "t_erro":    ("task", "Registrar erro e\nmanter arquivo\nanterior do MVP", "send"),
    "fim_falha": ("end", "Falha", ""),
}

ARESTAS = [
    ("inicio", "t_cfg", ""), ("t_cfg", "g_cfg", ""), ("g_cfg", "t_feed", "sim"), ("g_cfg", "t_erro", "não"),
    ("t_feed", "g_feed", ""), ("g_feed", "t_item", "sim"), ("g_feed", "g_base", "não"),
    ("g_base", "t_desat", "sim"), ("g_base", "t_erro", "não"), ("t_desat", "t_comp", ""),
    ("t_item", "g_visto", ""), ("g_visto", "j_item", "sim"), ("g_visto", "t_cap", "não"),
    ("t_cap", "g_baixou", ""), ("g_baixou", "t_valida", "sim"), ("g_baixou", "t_pend", "não"),
    ("t_pend", "j_item", ""),
    ("t_valida", "g_valido", ""), ("g_valido", "g_real", "sim"), ("g_valido", "t_quar", "não"), ("t_quar", "j_item", ""),
    ("g_real", "g_tipo", "sim"), ("g_real", "t_ign", "não"), ("t_ign", "j_item", ""),
    ("g_tipo", "t_cancel", "Cancel"), ("g_tipo", "t_subst", "Update"), ("g_tipo", "g_area", "Alert"),
    ("t_cancel", "j_item", ""), ("t_subst", "g_area", ""),
    ("g_area", "t_nivel", "sim"), ("g_area", "t_fora", "não"), ("t_fora", "j_item", ""),
    ("t_nivel", "t_grava", ""), ("t_grava", "j_item", ""),
    ("j_item", "g_mais", ""), ("g_mais", "t_item", "sim"), ("g_mais", "t_comp", "não"),
    ("t_comp", "t_monta", ""), ("t_monta", "g_contr", ""), ("g_contr", "t_pub", "sim"), ("g_contr", "t_erro", "não"),
    ("t_pub", "t_div", ""), ("t_div", "g_grave", ""), ("g_grave", "t_notif", "sim"), ("g_grave", "j_rel", "não"),
    ("t_notif", "j_rel", ""), ("j_rel", "t_rel", ""), ("t_rel", "g_pend", ""),
    ("g_pend", "fim_ok", "não"), ("g_pend", "t_aviso", "sim"), ("t_aviso", "fim_pend", ""),
    ("t_erro", "fim_falha", ""),
]

SIMBOLO = {"loop": "↻ ", "service": "⚙ ", "send": "✉ ", "script": ""}


def _dot() -> str:
    linhas = ['digraph belka_avisos {', 'graph [rankdir=TB, splines=ortho, nodesep=0.5, ranksep=0.42, '
              'fontname="Helvetica", label="Belka · robô de avisos oficiais do INMET (BPMN)\\n'
              '↻ repetição   ⚙ chamada externa   ✉ envio   ◇ decisão", labelloc=t, fontsize=16];',
              'node [fontname="Helvetica", fontsize=11];', 'edge [fontname="Helvetica", fontsize=10, arrowsize=0.7];']
    for nid, (tipo, rot, marca) in NOS.items():
        w, h = TAM[tipo]
        dim = f'width={w / 72:.2f}, height={h / 72:.2f}, fixedsize=true'
        r = rot.replace("\n", "\\n")
        if tipo == "start":
            linhas.append(f'{nid} [shape=circle, style=filled, fillcolor="#E6F4EA", color="#2E7D32", penwidth=2, '
                          f'label="", xlabel="{r}", {dim}];')
        elif tipo == "end":
            cor = "#C62828" if nid == "fim_falha" else "#0B1B34"
            linhas.append(f'{nid} [shape=circle, style=filled, fillcolor="#FDECEA", color="{cor}", penwidth=3.5, '
                          f'label="", xlabel="{r}", {dim}];')
        elif tipo == "gw":
            linhas.append(f'{nid} [shape=diamond, style=filled, fillcolor="#FFF8E1", color="#C49000", '
                          f'label="", xlabel="{r}", {dim}];')
        else:
            linhas.append(f'{nid} [shape=box, style="rounded,filled", fillcolor="#FFFFFF", color="#0B1B34", '
                          f'label="{SIMBOLO[marca]}{r}", {dim}];')
    for a, b, rot in ARESTAS:
        linhas.append(f'{a} -> {b} [xlabel="{rot}"];' if rot else f"{a} -> {b};")
    linhas.append("}")
    return "\n".join(linhas)


def _bpmn(layout: dict) -> str:
    altura = float(layout["bb"].split(",")[3])
    pos = {}
    for o in layout["objects"]:
        if o.get("name") in NOS:
            x, y = map(float, o["pos"].split(","))
            pos[o["name"]] = (x, altura - y)
    tag = {"start": "startEvent", "end": "endEvent", "gw": "exclusiveGateway"}
    tarefa = {"service": "serviceTask", "send": "sendTask", "script": "scriptTask", "loop": "scriptTask"}
    proc, shapes, flows, di_flows = [], [], [], []
    saidas, entradas = {}, {}
    for i, (a, b, _) in enumerate(ARESTAS):
        saidas.setdefault(a, []).append(f"f{i}")
        entradas.setdefault(b, []).append(f"f{i}")
    for nid, (tipo, rot, marca) in NOS.items():
        el = tag.get(tipo) or tarefa[marca]
        corpo = "".join(f"<bpmn:incoming>{f}</bpmn:incoming>" for f in entradas.get(nid, []))
        corpo += "".join(f"<bpmn:outgoing>{f}</bpmn:outgoing>" for f in saidas.get(nid, []))
        if marca == "loop":
            corpo += "<bpmn:standardLoopCharacteristics />"
        proc.append(f'<bpmn:{el} id="{nid}" name="{escape(rot.replace(chr(10), " "))}">{corpo}</bpmn:{el}>')
        w, h = TAM[tipo]
        x, y = pos[nid]
        shapes.append(f'<bpmndi:BPMNShape id="{nid}_di" bpmnElement="{nid}"><dc:Bounds x="{x - w / 2:.0f}" '
                      f'y="{y - h / 2:.0f}" width="{w}" height="{h}" /></bpmndi:BPMNShape>')
    for i, (a, b, rot) in enumerate(ARESTAS):
        nome = f' name="{escape(rot)}"' if rot else ""
        flows.append(f'<bpmn:sequenceFlow id="f{i}" sourceRef="{a}" targetRef="{b}"{nome} />')
        (x1, y1), (x2, y2) = pos[a], pos[b]
        pontos = [(x1, y1), (x1, (y1 + y2) / 2), (x2, (y1 + y2) / 2), (x2, y2)] if x1 != x2 else [(x1, y1), (x2, y2)]
        di_flows.append(f'<bpmndi:BPMNEdge id="f{i}_di" bpmnElement="f{i}">' +
                        "".join(f'<di:waypoint x="{px:.0f}" y="{py:.0f}" />' for px, py in pontos) + "</bpmndi:BPMNEdge>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
        'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
        'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" id="belka_avisos_def" '
        'targetNamespace="https://belka.exemplo.com/rpa" exporter="belka gerar_bpmn.py" exporterVersion="1.0">\n'
        '<bpmn:process id="belka_avisos" name="Belka RPA · avisos oficiais do INMET" isExecutable="false">\n'
        + "\n".join(proc + flows) + "\n</bpmn:process>\n"
        '<bpmndi:BPMNDiagram id="diagrama"><bpmndi:BPMNPlane id="plano" bpmnElement="belka_avisos">\n'
        + "\n".join(shapes + di_flows) + "\n</bpmndi:BPMNPlane></bpmndi:BPMNDiagram>\n</bpmn:definitions>\n"
    )


def main():
    fonte = _dot()
    for fmt in ("png", "svg"):
        args = ["dot", f"-T{fmt}", "-o", str(PASTA / f"belka_avisos_bpmn.{fmt}")] + (["-Gdpi=140"] if fmt == "png" else [])
        subprocess.run(args, input=fonte, text=True, check=True)
    layout = json.loads(subprocess.run(["dot", "-Tjson"], input=fonte, text=True, check=True, capture_output=True).stdout)
    (PASTA / "belka_avisos.bpmn").write_text(_bpmn(layout), encoding="utf-8")
    print("Gerados:", ", ".join(p.name for p in sorted(PASTA.glob("belka_avisos*"))))


if __name__ == "__main__":
    main()
