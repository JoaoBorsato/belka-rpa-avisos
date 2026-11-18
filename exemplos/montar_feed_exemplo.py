"""
Monta exemplos/feed_2026-11-07/: uma cópia do feed de avisos no formato real do INMET (RSS + CAP 1.2),
para demonstrar o robô sem internet com a data de referência 07/11/2026 às 15:00 (o último dia do snapshot
da Belka em entrada/belka_mvp.json).

O conteúdo é ilustrativo: os avisos foram escritos para exercitar todas as regras do robô.
Para dados reais, rode o robô sem --local (ele lê https://apiprevmet3.inmet.gov.br/avisos/rss).

Uso: python exemplos/montar_feed_exemplo.py
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from tests.fabrica import cap_xml, identificador, rss_xml  # noqa: E402

DESTINO = RAIZ / "exemplos" / "feed_2026-11-07"
SP, GRU, FRA, OSA, CPS, JUN, VAL, SSB, CAR, UBA, ILH, STS, RIO, BH, GYN, PMW = (
    3550308, 3518800, 3516408, 3534401, 3509502, 3525904, 3556206, 3550704,
    3510500, 3555406, 3520400, 3548500, 3304557, 3106200, 5208707, 1721000)

# rss_id, evento, severidade, início, fim, municípios, opções extras · o que demonstra
AVISOS = [
    (55880, "Acumulado de Chuva", "Moderate", "2026-11-05T00:00:00-03:00", "2026-11-06T23:59:00-03:00",
     [SP, GRU, FRA, OSA], {}),                                                    # já expirado: só histórico
    (55901, "Tempestade", "Moderate", "2026-11-07T00:00:00-03:00", "2026-11-07T23:59:00-03:00",
     [SP, GRU, FRA, OSA, CPS, JUN, VAL, RIO, BH], {}),                            # vigente, Fique de olho
    (55902, "Chuvas Intensas", "Severe", "2026-11-07T09:00:00-03:00", "2026-11-08T09:00:00-03:00",
     [SSB, CAR, UBA, ILH, STS], {}),                                              # vigente, Prepare-se
    (55903, "Baixa Umidade", "Moderate", "2026-11-07T10:00:00-03:00", "2026-11-08T19:00:00-03:00",
     [GYN, PMW], {}),                                                             # fora da área piloto
    (55905, "Vendaval", "Moderate", "2026-11-08T12:00:00-03:00", "2026-11-08T23:59:00-03:00",
     [GRU, FRA], {"enviado": "2026-11-07T08:00:00-03:00"}),                       # será cancelado
    (55906, "Vendaval", "Moderate", "2026-11-08T12:00:00-03:00", "2026-11-08T23:59:00-03:00",
     [GRU, FRA], {"msg_type": "Cancel", "referencias": [identificador(55905)],
                  "enviado": "2026-11-07T11:00:00-03:00"}),                       # cancela o 55905
    (55907, "Onda de Calor", "Moderate", "2026-11-08T10:00:00-03:00", "2026-11-10T18:00:00-03:00",
     [CPS, VAL], {"enviado": "2026-11-06T10:00:00-03:00"}),                       # será atualizado
    (55908, "Onda de Calor", "Severe", "2026-11-08T10:00:00-03:00", "2026-11-10T18:00:00-03:00",
     [CPS, VAL], {"msg_type": "Update", "referencias": [identificador(55907)],
                  "enviado": "2026-11-07T10:00:00-03:00"}),                       # sobe para Prepare-se
    (55909, "Tempestade", "Severe", "2026-11-07T12:00:00-03:00", "2026-11-07T23:59:00-03:00",
     [SP], {"status": "Exercise"}),                                               # exercício: ignorado
    (55910, "Acumulado de Chuva", "Extreme", "2026-11-09T00:00:00-03:00", "2026-11-10T12:00:00-03:00",
     [SSB, ILH, CAR], {"enviado": "2026-11-07T12:00:00-03:00"}),                  # próximo, Aja agora
]


def montar(destino: Path = DESTINO) -> Path:
    (destino / "cap").mkdir(parents=True, exist_ok=True)
    for rss_id, evento, sev, ini, fim, munis, extra in AVISOS:
        (destino / "cap" / f"{rss_id}.xml").write_text(cap_xml(rss_id, evento, sev, ini, fim, munis, **extra),
                                                       encoding="utf-8")
    itens = [{"rss_id": a[0], "evento": a[1], "severidade": a[2], "inicio": a[3], "fim": a[4], "municipios": a[5]}
             for a in sorted(AVISOS, key=lambda a: -a[0])]
    (destino / "rss.xml").write_text(rss_xml(itens, "2026-11-07T14:30:00-03:00"), encoding="utf-8")
    return destino


if __name__ == "__main__":
    print("Feed de exemplo gravado em", montar().relative_to(RAIZ))
