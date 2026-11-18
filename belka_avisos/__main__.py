"""
Uso (na raiz do repositório):

    python -m belka_avisos                                   # lê o feed do INMET agora
    python -m belka_avisos --local exemplos/feed_2026-11-07 \
                           --agora 2026-11-07T15:00:00-03:00 # demonstração offline com a cópia do feed
    python -m belka_avisos --estrito                         # código de saída 1 se houver pendências

Códigos de saída: 0 sucesso (com ou sem pendências), 1 pendências em modo estrito, 2 falha.
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

from .robo import executar


def main() -> int:
    p = argparse.ArgumentParser(prog="belka_avisos", description="Robô Belka: avisos oficiais do INMET -> MVP")
    p.add_argument("--raiz", default=".", help="raiz do repositório (padrão: pasta atual)")
    p.add_argument("--local", help="pasta com uma cópia do feed (rss.xml + cap/<id>.xml) em vez da internet")
    p.add_argument("--agora", help="data/hora de referência ISO 8601 com fuso (padrão: agora)")
    p.add_argument("--config", help="arquivo de configuração (padrão: config/config_avisos.json)")
    p.add_argument("--estrito", action="store_true", help="sai com código 1 se houver pendências")
    a = p.parse_args()

    agora = None
    if a.agora:
        agora = datetime.fromisoformat(a.agora)
        if agora.tzinfo is None:
            p.error("--agora precisa de fuso horário, ex.: 2026-11-07T15:00:00-03:00")

    r = executar(Path(a.raiz), agora=agora, local=Path(a.local) if a.local else None,
                 config=a.config, estrito=a.estrito)
    rel = r.relatorio
    print("\n========== BELKA · AVISOS OFICIAIS ==========")
    print(f"Status ........ {r.status}")
    print(f"Feed .......... {rel.get('feed')}")
    print(f"Itens ......... {rel['itens']}")
    print(f"Decisões ...... {rel['decisoes']}")
    print(f"Publicação .... {rel.get('publicacao') or 'não publicado'}")
    print(f"Comparação .... {rel.get('comparacao')}")
    print(f"Pendências .... {len(rel['pendencias'])}")
    for pend in rel["pendencias"][:10]:
        print(f"   - {pend}")
    if rel["erro"]:
        print(f"Erro .......... {rel['erro']}")
    print(f"Relatório ..... {r.caminho_relatorio}")
    return r.codigo_saida


if __name__ == "__main__":
    sys.exit(main())
