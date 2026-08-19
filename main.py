"""Coleta e atualiza as partidas usadas pelo painel Streamlit."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Callable

import requests
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "futebol2.db"
API_URL = "https://api.football-data.org/v4"

LIGAS_TEMPORADAS = {
    "BSA": [2025, 2026],
    "PL": [2025, 2026],
    "PD": [2025, 2026],
    "SA": [2025, 2026],
    "BL1": [2025, 2026],
    "FL1": [2025, 2026],
}


def _token_api() -> str:
    load_dotenv(BASE_DIR / ".env")
    token = os.getenv("FOOTBALL_DATA_TOKEN") or os.getenv("API")
    if not token:
        raise RuntimeError(
            "Token da API não encontrado. Defina FOOTBALL_DATA_TOKEN (ou API) no arquivo .env."
        )
    return token


def _criar_tabela(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS partidas (
            id_api INTEGER PRIMARY KEY,
            liga_codigo TEXT,
            liga_nome TEXT,
            temporada INTEGER,
            data_partida TEXT,
            time_casa_id INTEGER,
            time_casa TEXT,
            time_fora_id INTEGER,
            time_fora TEXT,
            gols_casa INTEGER,
            gols_fora INTEGER,
            vencedor TEXT
        )
        """
    )
    conn.commit()


def atualizar_dados(
    db_path: str | Path = DB_PATH,
    progresso: Callable[[int, int, str], None] | None = None,
    intervalo: float = 6.2,
) -> dict:
    """Busca todas as ligas configuradas e insere ou atualiza cada partida.

    ``progresso`` recebe (etapa_atual, total_etapas, mensagem), permitindo que
    o app mostre uma barra sem acoplar este módulo ao Streamlit.
    """
    tarefas = [
        (liga, temporada)
        for liga, temporadas in LIGAS_TEMPORADAS.items()
        for temporada in temporadas
    ]
    resumo = {
        "consultas": len(tarefas),
        "concluidas": 0,
        "recebidas": 0,
        "inseridas": 0,
        "atualizadas": 0,
        "erros": [],
    }

    headers = {"X-Auth-Token": _token_api()}
    conn = sqlite3.connect(str(db_path), timeout=30)
    _criar_tabela(conn)

    try:
        with requests.Session() as session:
            for indice, (liga, temporada) in enumerate(tarefas, start=1):
                mensagem = f"Atualizando {liga} — temporada {temporada}"
                if progresso:
                    progresso(indice - 1, len(tarefas), mensagem)

                try:
                    resposta = session.get(
                        f"{API_URL}/competitions/{liga}/matches",
                        headers=headers,
                        params={"season": temporada},
                        timeout=30,
                    )

                    if resposta.status_code == 429:
                        espera = max(float(resposta.headers.get("Retry-After", 60)), 1)
                        time.sleep(espera)
                        resposta = session.get(
                            f"{API_URL}/competitions/{liga}/matches",
                            headers=headers,
                            params={"season": temporada},
                            timeout=30,
                        )
                    resposta.raise_for_status()

                    partidas = resposta.json().get("matches", [])
                    ids = [partida["id"] for partida in partidas]
                    ids_existentes: set[int] = set()
                    for inicio in range(0, len(ids), 900):
                        bloco = ids[inicio : inicio + 900]
                        if bloco:
                            marcadores = ",".join("?" for _ in bloco)
                            ids_existentes.update(
                                row[0]
                                for row in conn.execute(
                                    f"SELECT id_api FROM partidas WHERE id_api IN ({marcadores})",
                                    bloco,
                                )
                            )

                    registros = [
                        (
                            partida["id"],
                            liga,
                            partida["competition"]["name"],
                            temporada,
                            partida["utcDate"],
                            partida["homeTeam"]["id"],
                            partida["homeTeam"]["name"],
                            partida["awayTeam"]["id"],
                            partida["awayTeam"]["name"],
                            partida["score"]["fullTime"]["home"],
                            partida["score"]["fullTime"]["away"],
                            partida["score"]["winner"],
                        )
                        for partida in partidas
                    ]

                    conn.executemany(
                        """
                        INSERT INTO partidas (
                            id_api, liga_codigo, liga_nome, temporada, data_partida,
                            time_casa_id, time_casa, time_fora_id, time_fora,
                            gols_casa, gols_fora, vencedor
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id_api) DO UPDATE SET
                            liga_codigo = excluded.liga_codigo,
                            liga_nome = excluded.liga_nome,
                            temporada = excluded.temporada,
                            data_partida = excluded.data_partida,
                            time_casa_id = excluded.time_casa_id,
                            time_casa = excluded.time_casa,
                            time_fora_id = excluded.time_fora_id,
                            time_fora = excluded.time_fora,
                            gols_casa = excluded.gols_casa,
                            gols_fora = excluded.gols_fora,
                            vencedor = excluded.vencedor
                        """,
                        registros,
                    )
                    conn.commit()

                    novas = len(set(ids) - ids_existentes)
                    resumo["recebidas"] += len(registros)
                    resumo["inseridas"] += novas
                    resumo["atualizadas"] += len(registros) - novas
                    resumo["concluidas"] += 1
                except (requests.RequestException, ValueError, KeyError) as exc:
                    resumo["erros"].append(f"{liga} {temporada}: {exc}")

                if indice < len(tarefas) and intervalo:
                    time.sleep(intervalo)

        if progresso:
            progresso(len(tarefas), len(tarefas), "Atualização concluída")
        return resumo
    finally:
        conn.close()


def main() -> None:
    def imprimir(atual: int, total: int, mensagem: str) -> None:
        print(f"[{atual}/{total}] {mensagem}")

    resumo = atualizar_dados(progresso=imprimir)
    print("=" * 50)
    print(
        f"Consultas concluídas: {resumo['concluidas']}/{resumo['consultas']} | "
        f"Partidas recebidas: {resumo['recebidas']} | "
        f"Novas: {resumo['inseridas']} | Atualizadas: {resumo['atualizadas']}"
    )
    if resumo["erros"]:
        print("Erros:")
        for erro in resumo["erros"]:
            print(f"- {erro}")
    print(f"Banco salvo em {DB_PATH}")


if __name__ == "__main__":
    main()
