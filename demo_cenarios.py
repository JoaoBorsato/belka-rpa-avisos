"""
Demonstração dos cenários de teste (para o vídeo e para as evidências da entrega).

Cada cenário roda o robô inteiro numa cópia temporária do repositório e guarda log, relatório e saídas em
evidencias/cenarios/<cenario>/. Nada no repositório real é alterado.

Uso (na raiz do repositório):  python demo_cenarios.py
"""
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
from belka_avisos.robo import executar  # noqa: E402
from exemplos.montar_feed_exemplo import montar  # noqa: E402

EVID = RAIZ / "evidencias" / "cenarios"
AGORA = datetime.fromisoformat("2026-11-07T15:00:00-03:00")


class INMETForaDoAr:
    """Simula o site do INMET fora do ar: toda chamada dá erro de conexão."""
    def get(self, *a, **kw):
        raise requests.ConnectionError("simulação: apiprevmet3.inmet.gov.br fora do ar")

    def post(self, *a, **kw):
        raise requests.ConnectionError("simulação: sem rede")


def preparar(destino: Path) -> Path:
    shutil.copytree(RAIZ / "config", destino / "config")
    shutil.copytree(RAIZ / "entrada", destino / "entrada")
    cfg = json.loads((destino / "config" / "config_avisos.json").read_text(encoding="utf-8"))
    cfg["rede"]["espera_inicial_s"] = 0.2
    (destino / "config" / "config_avisos.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    montar(destino / "feed")
    return destino


def guardar(nome: str, repo: Path, r) -> None:
    dest = EVID / nome
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    shutil.copy(repo / r.relatorio["log"], dest / "execucao.log")
    shutil.copy(r.caminho_relatorio, dest / "relatorio.json")
    for extra in ("avisos_oficiais.json", "divergencias.csv"):
        if (repo / "saida" / extra).exists():
            shutil.copy(repo / "saida" / extra, dest / extra)
    q = repo / "saida" / "quarentena" / r.relatorio["execucao_id"]
    if q.exists():
        shutil.copytree(q, dest / "quarentena")


def cenario(nome: str, descricao: str, preparo=None, **kw):
    print(f"\n{'=' * 78}\nCENÁRIO {nome}\n{descricao}\n{'=' * 78}")
    with tempfile.TemporaryDirectory() as tmp:
        repo = preparar(Path(tmp))
        extra = (preparo(repo) if preparo else None) or {}
        kw = {"agora": AGORA, "local": repo / "feed", **kw, **extra}
        r = executar(repo, **kw)
        guardar(nome, repo, r)
        rel = r.relatorio
        print(f"-> status {r.status} (código de saída {r.codigo_saida}) · itens {rel['itens']}")
        print(f"-> publicação {rel.get('publicacao') or 'não publicado'}")
        for p in rel["pendencias"]:
            print(f"   pendência: {p}")
        if rel["erro"]:
            print(f"   erro: {rel['erro']}")
        return r


def main():
    shutil.rmtree(EVID, ignore_errors=True)

    cenario("01_sucesso_e_decisoes",
            "Feed de 07/11 às 15:00: aviso vigente (Tempestade), aviso laranja em São Sebastião, aviso fora da área, "
            "cancelamento, atualização, exercício e um aviso vermelho para os próximos dias.")

    def ja_rodou(repo):
        executar(repo, agora=AGORA, local=repo / "feed", ecoar_console=False)
    cenario("02_idempotencia", "O robô já rodou com o mesmo feed: a segunda execução não baixa nem duplica nada.",
            ja_rodou)

    def base_e_queda(repo):
        executar(repo, agora=AGORA, local=repo / "feed", ecoar_console=False)
        return {"local": None, "sessao": INMETForaDoAr()}
    cenario("03_inmet_fora_do_ar_com_base",
            "O site do INMET caiu depois de uma leitura bem-sucedida: 3 tentativas, publica a partir da base "
            "e marca a fonte como desatualizada.", base_e_queda)

    def dados_ruins(repo):
        cap = repo / "feed" / "cap"
        (cap / "55901.xml").write_text("<alert><identifier>urn:oid:quebrado", encoding="utf-8")
        xml = (cap / "55902.xml").read_text(encoding="utf-8")
        (cap / "55902.xml").write_text(xml.replace("<severity>Severe</severity>", "<severity>Unknown</severity>")
                                          .replace("#FB9C00", "#123456").replace("Severidade Grau: Perigo", "Aviso"),
                                       encoding="utf-8")
        (cap / "55910.xml").unlink()                         # documento indisponível (como um 404)
    cenario("04_dados_invalidos",
            "CAP 55901 corrompido, CAP 55902 sem severidade reconhecível e CAP 55910 indisponível: "
            "quarentena, pendência para refazer e o resto do feed publicado.", dados_ruins)

    cenario("05_falha_sem_base",
            "Primeira execução com o INMET fora do ar: não há base anterior, o robô termina em FALHA e não publica.",
            local=None, sessao=INMETForaDoAr())

    print(f"\nEvidências salvas em {EVID.relative_to(RAIZ)}/")


if __name__ == "__main__":
    main()
