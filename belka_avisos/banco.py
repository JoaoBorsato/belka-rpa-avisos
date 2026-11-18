"""
Banco operacional do robô (SQLite, saida/belka_avisos.db). Também é lido pelo MVP e pelo assistente Belka AI.

  itens_rss            cada item do feed já visto e o que aconteceu com ele (idempotência)
  avisos               avisos oficiais aceitos, com nível Belka, riscos e estado (ativo/cancelado/substituido)
  aviso_municipio      quais municípios piloto cada aviso atinge
  referencias_orfas    cancelamento/atualização que chegou antes do aviso original
  notificacoes         avisos graves já comunicados à equipe (não repete)
  execucoes            histórico de execuções com status e relatório
  controle             chave/valor (ex.: última leitura bem-sucedida do feed)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS itens_rss (
    rss_id TEXT PRIMARY KEY, url TEXT, titulo TEXT, situacao TEXT NOT NULL, motivo TEXT,
    identifier TEXT, tentativas INTEGER NOT NULL DEFAULT 0, primeira_vez TEXT, ultima_vez TEXT, execucao_id TEXT
);
CREATE TABLE IF NOT EXISTS avisos (
    identifier TEXT PRIMARY KEY, rss_id TEXT, sent TEXT, msg_type TEXT, evento TEXT, severidade TEXT, cor TEXT,
    nivel INTEGER NOT NULL, riscos TEXT, onset TEXT, expires TEXT, headline TEXT, descricao TEXT, instrucao TEXT,
    web TEXT, criterio_area TEXT, estado TEXT NOT NULL DEFAULT 'ativo', estado_motivo TEXT,
    registrado_em TEXT, execucao_id TEXT
);
CREATE TABLE IF NOT EXISTS aviso_municipio (
    identifier TEXT NOT NULL, municipio_id INTEGER NOT NULL, PRIMARY KEY (identifier, municipio_id)
);
CREATE TABLE IF NOT EXISTS referencias_orfas (
    ref_identifier TEXT PRIMARY KEY, tipo TEXT NOT NULL, por_identifier TEXT NOT NULL, registrado_em TEXT
);
CREATE TABLE IF NOT EXISTS notificacoes (chave TEXT PRIMARY KEY, enviado_em TEXT);
CREATE TABLE IF NOT EXISTS execucoes (
    execucao_id TEXT PRIMARY KEY, inicio TEXT, fim TEXT, status TEXT, relatorio TEXT
);
CREATE TABLE IF NOT EXISTS controle (chave TEXT PRIMARY KEY, valor TEXT);
"""


class Banco:
    def __init__(self, caminho: Path):
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(caminho)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(ESQUEMA)

    def fechar(self) -> None:
        self.con.close()

    # ------------------------------------------------------------------ execuções e controle
    def abrir_execucao(self, execucao_id: str, inicio: str) -> None:
        with self.con:
            self.con.execute("INSERT INTO execucoes (execucao_id, inicio, status) VALUES (?, ?, 'EM_ANDAMENTO')",
                             (execucao_id, inicio))

    def fechar_execucao(self, execucao_id: str, fim: str, status: str, relatorio: dict) -> None:
        with self.con:
            self.con.execute("UPDATE execucoes SET fim = ?, status = ?, relatorio = ? WHERE execucao_id = ?",
                             (fim, status, json.dumps(relatorio, ensure_ascii=False, default=str), execucao_id))

    def controle(self, chave: str) -> str | None:
        r = self.con.execute("SELECT valor FROM controle WHERE chave = ?", (chave,)).fetchone()
        return r["valor"] if r else None

    def definir_controle(self, chave: str, valor: str) -> None:
        with self.con:
            self.con.execute("INSERT INTO controle VALUES (?, ?) ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
                             (chave, valor))

    # ------------------------------------------------------------------ itens do feed
    def item(self, rss_id: str):
        return self.con.execute("SELECT * FROM itens_rss WHERE rss_id = ?", (rss_id,)).fetchone()

    def registrar_item(self, rss_id: str, url: str, titulo: str, situacao: str, motivo: str | None,
                       identifier: str | None, quando: str, execucao_id: str) -> None:
        with self.con:
            self.con.execute("""
                INSERT INTO itens_rss (rss_id, url, titulo, situacao, motivo, identifier, tentativas,
                                       primeira_vez, ultima_vez, execucao_id)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(rss_id) DO UPDATE SET situacao = excluded.situacao, motivo = excluded.motivo,
                    identifier = excluded.identifier, tentativas = itens_rss.tentativas + 1,
                    ultima_vez = excluded.ultima_vez, execucao_id = excluded.execucao_id
            """, (rss_id, url, titulo, situacao, motivo, identifier, quando, quando, execucao_id))

    # ------------------------------------------------------------------ avisos
    def aviso(self, identifier: str):
        return self.con.execute("SELECT * FROM avisos WHERE identifier = ?", (identifier,)).fetchone()

    def inserir_aviso(self, reg: dict, municipios: set[int]) -> bool:
        """Grava o aviso. Devolve False se o identifier já existia (não duplica)."""
        if self.aviso(reg["identifier"]) is not None:
            return False
        cols = list(reg)
        with self.con:
            self.con.execute(f"INSERT INTO avisos ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                             [reg[c] for c in cols])
            self.con.executemany("INSERT OR IGNORE INTO aviso_municipio VALUES (?, ?)",
                                 [(reg["identifier"], m) for m in sorted(municipios)])
        return True

    def mudar_estado(self, identifier: str, estado: str, motivo: str) -> bool:
        with self.con:
            cur = self.con.execute(
                "UPDATE avisos SET estado = ?, estado_motivo = ? WHERE identifier = ? AND estado = 'ativo'",
                (estado, motivo, identifier))
        return cur.rowcount > 0

    def guardar_referencia_orfa(self, ref: str, tipo: str, por: str, quando: str) -> None:
        with self.con:
            self.con.execute("INSERT OR IGNORE INTO referencias_orfas VALUES (?, ?, ?, ?)", (ref, tipo, por, quando))

    def consumir_referencia_orfa(self, identifier: str):
        r = self.con.execute("SELECT * FROM referencias_orfas WHERE ref_identifier = ?", (identifier,)).fetchone()
        if r is not None:
            with self.con:
                self.con.execute("DELETE FROM referencias_orfas WHERE ref_identifier = ?", (identifier,))
        return r

    def avisos_ativos(self) -> list[dict]:
        linhas = self.con.execute("SELECT * FROM avisos WHERE estado = 'ativo' ORDER BY onset, identifier").fetchall()
        mapa = {}
        for r in self.con.execute("SELECT identifier, municipio_id FROM aviso_municipio"):
            mapa.setdefault(r["identifier"], []).append(r["municipio_id"])
        saida = []
        for r in linhas:
            d = dict(r)
            d["riscos"] = json.loads(d["riscos"] or "[]")
            d["municipios"] = sorted(mapa.get(d["identifier"], []))
            saida.append(d)
        return saida

    def contagem_por_estado(self) -> dict:
        return {r["estado"]: r["n"] for r in self.con.execute("SELECT estado, COUNT(*) n FROM avisos GROUP BY estado")}

    def primeiro_envio(self) -> str | None:
        r = self.con.execute("SELECT MIN(sent) m FROM avisos").fetchone()
        return r["m"] if r else None

    # ------------------------------------------------------------------ notificações
    def ja_notificado(self, chave: str) -> bool:
        return self.con.execute("SELECT 1 FROM notificacoes WHERE chave = ?", (chave,)).fetchone() is not None

    def marcar_notificado(self, chave: str, quando: str) -> None:
        with self.con:
            self.con.execute("INSERT OR IGNORE INTO notificacoes VALUES (?, ?)", (chave, quando))
