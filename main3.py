"""Coletor incremental do OneFootball para o painel Streamlit.

O coletor usa as rotas JSON públicas do Next.js consumidas pelo próprio site
para catálogo, calendário, resultados, tabela e detalhes de partidas. A Scores
API é mantida como fallback. A primeira execução descobre o catálogo completo;
as seguintes reaproveitam as competições salvas e fazem upsert dos jogos atuais.

Uso:
  python main3.py                         # full se vazio; update se já populado
  python main3.py --full                  # redescobre todo o catálogo
  python main3.py --update                # atualiza as competições do banco
  python main3.py --competition-ids 9,10  # sincroniza somente os IDs informados
  python main3.py --goal-ids 123,456      # salva eventos/minutos desses jogos
"""

from __future__ import annotations

import argparse
import gzip
import html as html_module
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("ONEFOOTBALL_DB_PATH", BASE_DIR / "futebol3.db"))
SITE_URL = "https://onefootball.com"
SCORES_URL = "https://scores-api.onefootball.com"
CATALOG_PATH = "/pt-br/todas-as-competicoes"
DEFAULT_DELAY = 0.20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"
)


class OneFootballError(RuntimeError):
    pass


def _safe_console(value: object) -> str:
    """Evita que respostas binárias de erro derrubem terminais Windows legados."""
    text = str(value)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


class OneFootballClient:
    def __init__(self, delay: float = DEFAULT_DELAY) -> None:
        self.delay = max(delay, 0.0)
        self.build_id: str | None = None
        self.last_request = 0.0

    def _wait(self) -> None:
        elapsed = time.monotonic() - self.last_request
        if self.last_request and elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    def get_text(self, url: str, accept: str = "application/json") -> str:
        last_error: Exception | None = None
        for attempt in range(4):
            self._wait()
            request = Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": accept,
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
                    "Origin": SITE_URL,
                    "Referer": f"{SITE_URL}/pt-br/",
                },
            )
            try:
                with urlopen(request, timeout=35) as response:
                    raw = response.read()
                    if response.headers.get("Content-Encoding", "").casefold() == "gzip":
                        raw = gzip.decompress(raw)
                    charset = response.headers.get_content_charset() or "utf-8"
                    self.last_request = time.monotonic()
                    return raw.decode(charset, errors="replace")
            except HTTPError as exc:
                last_error = exc
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                    detail = exc.read(300).decode("utf-8", errors="replace")
                    raise OneFootballError(f"HTTP {exc.code} em {url}: {detail}") from exc
                retry_after = exc.headers.get("Retry-After")
                time.sleep(float(retry_after) if retry_after else 2 ** (attempt + 1))
            except (URLError, TimeoutError) as exc:
                last_error = exc
                if attempt == 3:
                    break
                time.sleep(2 ** attempt)
        raise OneFootballError(f"Falha ao consultar {url}: {last_error}")

    def get_json(self, url: str) -> dict | list:
        try:
            return json.loads(self.get_text(url))
        except json.JSONDecodeError as exc:
            raise OneFootballError(f"Resposta JSON inválida em {url}: {exc}") from exc

    def page_data(self, path: str) -> dict:
        body = self.get_text(f"{SITE_URL}{path}", "text/html,application/xhtml+xml")
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            body,
            re.DOTALL,
        )
        if not match:
            raise OneFootballError(f"__NEXT_DATA__ não encontrado em {path}")
        data = json.loads(html_module.unescape(match.group(1)))
        if data.get("buildId"):
            self.build_id = str(data["buildId"])
        return data

    def next_data(self, path: str, query: dict[str, str], refresh_path: str) -> dict:
        """Consulta uma rota JSON do Next.js sem fixar o buildId no código."""
        if not self.build_id:
            self.page_data(CATALOG_PATH)
        assert self.build_id

        def request() -> dict:
            url = (
                f"{SITE_URL}/_next/data/{self.build_id}{path}.json?"
                f"{urlencode(query)}"
            )
            payload = self.get_json(url)
            if not isinstance(payload, dict):
                raise OneFootballError(f"Layout Next.js inesperado em {path}")
            return payload

        try:
            return request()
        except OneFootballError as exc:
            if "HTTP 404" not in str(exc):
                raise
            # O buildId muda a cada publicação do site. Atualiza e tenta uma vez.
            self.build_id = None
            self.page_data(refresh_path)
            return request()

    def competition_layout(self, slug: str, entity_page: str) -> dict:
        path = f"/pt-br/competition/{slug}/{entity_page}"
        return self.next_data(
            path,
            {"competition-id": slug, "entity-page": entity_page},
            f"/pt-br/competicao/{slug}/{entity_page}",
        )

    def match_layout(self, match_id: int) -> dict:
        if not self.build_id:
            self.page_data(CATALOG_PATH)
        assert self.build_id
        query = urlencode({"match-slug": str(match_id)})
        url = (
            f"{SITE_URL}/_next/data/{self.build_id}/pt-br/match/{match_id}.json?{query}"
        )
        try:
            data = self.get_json(url)
        except OneFootballError as exc:
            if "HTTP 404" not in str(exc):
                raise
            self.build_id = None
            self.page_data(f"/pt-br/match/{match_id}")
            assert self.build_id
            url = (
                f"{SITE_URL}/_next/data/{self.build_id}/pt-br/match/{match_id}.json?{query}"
            )
            data = self.get_json(url)
        if not isinstance(data, dict):
            raise OneFootballError(f"Layout inesperado para a partida {match_id}")
        return data


def criar_banco(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS competicoes (
            liga_id INTEGER PRIMARY KEY,
            liga_nome TEXT NOT NULL,
            liga_pais TEXT,
            slug TEXT,
            temporada_id INTEGER,
            ativo INTEGER NOT NULL DEFAULT 0,
            ultima_sincronizacao TEXT,
            ultimo_erro TEXT
        );
        CREATE TABLE IF NOT EXISTS partidas (
            id_api INTEGER PRIMARY KEY,
            liga_id INTEGER NOT NULL,
            liga_codigo TEXT NOT NULL,
            liga_nome TEXT NOT NULL,
            liga_pais TEXT,
            temporada_id INTEGER,
            temporada INTEGER,
            rodada TEXT,
            data_partida TEXT NOT NULL,
            status TEXT,
            time_casa_id INTEGER,
            time_casa TEXT,
            time_fora_id INTEGER,
            time_fora TEXT,
            gols_casa INTEGER,
            gols_fora INTEGER,
            vencedor TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_one_partidas_liga_data
            ON partidas(liga_id, data_partida);
        CREATE INDEX IF NOT EXISTS idx_one_partidas_times
            ON partidas(time_casa_id, time_fora_id, data_partida);
        CREATE TABLE IF NOT EXISTS partidas_detalhes (
            id_api INTEGER PRIMARY KEY,
            coletado_em TEXT NOT NULL,
            gols_casa_ate_75 INTEGER NOT NULL,
            gols_fora_ate_75 INTEGER NOT NULL,
            primeiro_gol_casa_minuto INTEGER,
            primeiro_gol_fora_minuto INTEGER,
            total_gols_incidentes INTEGER NOT NULL,
            FOREIGN KEY (id_api) REFERENCES partidas(id_api)
        );
        CREATE TABLE IF NOT EXISTS eventos_partida (
            id_api INTEGER NOT NULL,
            evento_ordem INTEGER NOT NULL,
            minuto INTEGER,
            minuto_texto TEXT,
            lado TEXT,
            tipo TEXT,
            subtipo TEXT,
            jogador TEXT,
            assistente TEXT,
            jogador_entra TEXT,
            jogador_sai TEXT,
            PRIMARY KEY (id_api, evento_ordem),
            FOREIGN KEY (id_api) REFERENCES partidas(id_api)
        );
        CREATE TABLE IF NOT EXISTS classificacao (
            liga_id INTEGER NOT NULL,
            time_id INTEGER NOT NULL,
            posicao INTEGER,
            variacao_posicao INTEGER,
            time_nome TEXT NOT NULL,
            jogos INTEGER,
            vitorias INTEGER,
            empates INTEGER,
            derrotas INTEGER,
            saldo_gols INTEGER,
            pontos INTEGER,
            atualizado_em TEXT NOT NULL,
            PRIMARY KEY (liga_id, time_id)
        );
        CREATE INDEX IF NOT EXISTS idx_one_classificacao_liga_posicao
            ON classificacao(liga_id, posicao);
        CREATE TABLE IF NOT EXISTS coleta_estado (
            chave TEXT PRIMARY KEY,
            valor TEXT,
            atualizado_em TEXT NOT NULL
        );
        """
    )
    conn.commit()


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def extrair_catalogo(page_data: dict) -> tuple[dict[int, dict], list[str]]:
    competitions: dict[int, dict] = {}
    groups: set[str] = set()
    for item in _walk(page_data.get("props", page_data)):
        path = item.get("urlPath")
        if not isinstance(path, str):
            continue
        match = re.search(r"/competicao/[^/?]+-(\d+)$", path)
        if match:
            league_id = int(match.group(1))
            competitions[league_id] = {
                "liga_id": league_id,
                "liga_nome": str(item.get("name") or f"Competição {league_id}"),
                "slug": path,
            }
        elif path.startswith(CATALOG_PATH + "/"):
            groups.add(path)
    return competitions, sorted(groups)


def descobrir_competicoes(
    client: OneFootballClient,
    progresso: Callable[[int, int, str], None] | None = None,
) -> list[dict]:
    root = client.next_data(
        CATALOG_PATH,
        {"directory-entity": "todas-as-competicoes"},
        CATALOG_PATH,
    )
    competitions, group_paths = extrair_catalogo(root)
    # O diretório principal é dividido em duas páginas: A–O e P–Z.
    second_page = client.next_data(
        CATALOG_PATH,
        {"directory-entity": "todas-as-competicoes", "page": "2"},
        f"{CATALOG_PATH}?page=2",
    )
    second_competitions, second_groups = extrair_catalogo(second_page)
    competitions.update(second_competitions)
    group_paths = sorted(set(group_paths) | set(second_groups))
    total = len(group_paths)
    for index, path in enumerate(group_paths, start=1):
        if progresso:
            progresso(index - 1, total, f"Catálogo OneFootball: {path.rsplit('/', 1)[-1].upper()}")
        entity = path.rstrip("/").rsplit("/", 1)[-1]
        page_competitions, _ = extrair_catalogo(
            client.next_data(path, {"directory-entity": entity}, path)
        )
        competitions.update(page_competitions)
    if progresso:
        progresso(total, total, f"Catálogo descoberto: {len(competitions)} competições")
    return sorted(competitions.values(), key=lambda item: item["liga_nome"].casefold())


def _status(period: object) -> tuple[str, bool]:
    if isinstance(period, (int, float)) or str(period or "").isdigit():
        period_number = int(period)
        numeric_status = {
            1: "SCHEDULED",
            2: "CANCELLED",
            3: "POSTPONED",
            4: "IN_PLAY",
            5: "PAUSED",
            6: "SUSPENDED",
            7: "IN_PLAY",
            8: "IN_PLAY",
            9: "IN_PLAY",
            10: "IN_PLAY",
            11: "FINISHED",
            12: "FINISHED",
            13: "FINISHED",
        }
        status = numeric_status.get(period_number, "UNKNOWN")
        return status, status == "FINISHED"
    text = str(period or "").strip()
    normalized = re.sub(r"[^a-z]", "", text.casefold())
    finished = normalized in {
        "fulltime",
        "fulltimepenalties",
        "resultsafterfulltime",
        "afterfulltime",
    }
    if finished:
        return "FINISHED", True
    if normalized in {"prematch", "notstarted", "scheduled", ""}:
        return "SCHEDULED", False
    if "postpon" in normalized:
        return "POSTPONED", False
    if "abandon" in normalized or "cancel" in normalized:
        return "CANCELLED", False
    return text.upper() or "UNKNOWN", False


def _winner(home: int | None, away: int | None) -> str | None:
    if home is None or away is None:
        return None
    if home > away:
        return "HOME_TEAM"
    if away > home:
        return "AWAY_TEAM"
    return "DRAW"


def _season_years(matches: list[dict]) -> dict[int, int]:
    result: dict[int, int] = {}
    for match in matches:
        season_id = int((match.get("season") or {}).get("id") or 0)
        kickoff = str(match.get("kickoff") or "")
        if season_id and len(kickoff) >= 4 and kickoff[:4].isdigit():
            year = int(kickoff[:4])
            result[season_id] = min(result.get(season_id, year), year)
    return result


def _competition_slug(competition: dict) -> str:
    slug = str(competition.get("slug") or "").rstrip("/").rsplit("/", 1)[-1]
    if not slug or slug.casefold() in {"none", "competicao"}:
        raise OneFootballError(
            f"slug ausente para a competição {competition.get('liga_id')}"
        )
    return slug


def _case_payload(layout: dict, case_name: str) -> dict | None:
    for item in _walk(layout.get("pageProps", layout)):
        if item.get("$case") == case_name:
            payload = item.get(case_name)
            return payload if isinstance(payload, dict) else None
    return None


def _tracking_value(item: dict, key: str) -> str | None:
    for event in item.get("trackingEvents") or []:
        parameter = (event.get("typedServerParameter") or {}).get(key) or {}
        value = parameter.get("value")
        if value not in (None, ""):
            return str(value)
    return None


def _id_from_image(team: dict) -> int | None:
    path = str((team.get("imageObject") or {}).get("path") or "")
    match = re.search(r"/(\d+)\.(?:png|jpe?g|webp)(?:\?|$)", path, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _optional_int(value: object) -> int | None:
    try:
        return int(str(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _match_lists(layout: dict) -> tuple[list[dict], str | None]:
    payload = _case_payload(layout, "matchCardsListsAppender") or {}
    lists = payload.get("lists") if isinstance(payload.get("lists"), list) else []
    load_more = payload.get("loadMoreButton") or {}
    return lists, load_more.get("apiUrl")


def _cards_with_round(lists: list[dict]) -> list[tuple[dict, str]]:
    cards: list[tuple[dict, str]] = []
    for group in lists:
        round_name = str((group.get("sectionHeader") or {}).get("subtitle") or "")
        for card in group.get("matchCards") or []:
            if isinstance(card, dict):
                cards.append((card, round_name))
    return cards


def _load_competition_cards(
    client: OneFootballClient, slug: str, entity_page: str
) -> list[tuple[dict, str]]:
    layout = client.competition_layout(slug, entity_page)
    lists, load_more_url = _match_lists(layout)
    all_lists = list(lists)
    if load_more_url:
        extra_url = urljoin("https://api.onefootball.com", str(load_more_url))
        extra = client.get_json(extra_url)
        if isinstance(extra, dict) and isinstance(extra.get("lists"), list):
            all_lists.extend(extra["lists"])
    result: dict[int, tuple[dict, str]] = {}
    for card, round_name in _cards_with_round(all_lists):
        match_id = _optional_int(card.get("matchId") or _tracking_value(card, "match_id"))
        if match_id is not None:
            result[match_id] = (card, round_name)
    return list(result.values())


def _standings_rows(layout: dict, league_id: int) -> list[tuple]:
    payload = _case_payload(layout, "standings") or {}
    now = datetime.now(timezone.utc).isoformat()
    result = []
    for row in payload.get("rows") or []:
        team_path = str(row.get("teamPath") or "")
        team_match = re.search(r"-(\d+)$", team_path)
        team_id = int(team_match.group(1)) if team_match else _id_from_image(row)
        if team_id is None or not row.get("teamName"):
            continue
        result.append(
            (
                league_id,
                team_id,
                _optional_int(row.get("position")),
                _optional_int(row.get("positionChange")),
                str(row["teamName"]),
                _optional_int(row.get("playedMatchesCount")),
                _optional_int(row.get("wonMatchesCount")),
                _optional_int(row.get("drawnMatchesCount")),
                _optional_int(row.get("lostMatchesCount")),
                _optional_int(row.get("goalsDiff")),
                _optional_int(row.get("points")),
                now,
            )
        )
    return result


def _save_standings(conn: sqlite3.Connection, league_id: int, rows: list[tuple]) -> None:
    if not rows:
        return
    conn.execute("DELETE FROM classificacao WHERE liga_id=?", (league_id,))
    conn.executemany(
        """
        INSERT INTO classificacao (
            liga_id, time_id, posicao, variacao_posicao, time_nome, jogos,
            vitorias, empates, derrotas, saldo_gols, pontos, atualizado_em
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _card_row(
    card: dict,
    round_name: str,
    competition: dict,
    season_year: int | None,
) -> tuple | None:
    match_id = _optional_int(card.get("matchId") or _tracking_value(card, "match_id"))
    kickoff = str(card.get("kickoff") or "")
    home = card.get("homeTeam") or {}
    away = card.get("awayTeam") or {}
    if match_id is None or not kickoff or not home.get("name") or not away.get("name"):
        return None
    league_id = int(competition["liga_id"])
    status, finished = _status(card.get("period") or _tracking_value(card, "match_state"))
    home_score = _optional_int(home.get("score")) if finished else None
    away_score = _optional_int(away.get("score")) if finished else None
    return (
        match_id,
        league_id,
        f"ONE_{league_id}",
        str(_tracking_value(card, "competition") or competition.get("liga_nome") or league_id),
        str(competition.get("liga_pais") or ""),
        None,
        season_year,
        round_name,
        kickoff,
        status,
        _optional_int(_tracking_value(card, "home_team_id")) or _id_from_image(home),
        str(home["name"]),
        _optional_int(_tracking_value(card, "away_team_id")) or _id_from_image(away),
        str(away["name"]),
        home_score,
        away_score,
        _winner(home_score, away_score),
    )


def _sincronizar_competicao_next(
    conn: sqlite3.Connection,
    client: OneFootballClient,
    competition: dict,
) -> tuple[int, int, int]:
    league_id = int(competition["liga_id"])
    slug = _competition_slug(competition)
    cards = _load_competition_cards(client, slug, "resultados")
    cards.extend(_load_competition_cards(client, slug, "jogos"))
    deduplicated: dict[int, tuple[dict, str]] = {}
    for card, round_name in cards:
        match_id = _optional_int(card.get("matchId") or _tracking_value(card, "match_id"))
        if match_id is not None:
            deduplicated[match_id] = (card, round_name)
    if not deduplicated:
        raise OneFootballError(f"rotas Next.js sem partidas para {slug}")

    kickoff_years = [
        int(str(card.get("kickoff"))[:4])
        for card, _ in deduplicated.values()
        if len(str(card.get("kickoff") or "")) >= 4
        and str(card.get("kickoff"))[:4].isdigit()
    ]
    season_year = min(kickoff_years) if kickoff_years else None
    rows = [
        row
        for card, round_name in deduplicated.values()
        if (row := _card_row(card, round_name, competition, season_year)) is not None
    ]
    ids = [row[0] for row in rows]
    existing: set[int] = set()
    for start in range(0, len(ids), 800):
        block = ids[start : start + 800]
        marks = ",".join("?" for _ in block)
        existing.update(
            row[0]
            for row in conn.execute(
                f"SELECT id_api FROM partidas WHERE id_api IN ({marks})", block
            )
        )

    conn.executemany(
        """
        INSERT INTO partidas (
            id_api, liga_id, liga_codigo, liga_nome, liga_pais,
            temporada_id, temporada, rodada, data_partida, status,
            time_casa_id, time_casa, time_fora_id, time_fora,
            gols_casa, gols_fora, vencedor
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id_api) DO UPDATE SET
            liga_id=excluded.liga_id,
            liga_codigo=excluded.liga_codigo,
            liga_nome=excluded.liga_nome,
            liga_pais=COALESCE(NULLIF(excluded.liga_pais, ''), partidas.liga_pais),
            temporada_id=COALESCE(excluded.temporada_id, partidas.temporada_id),
            temporada=COALESCE(excluded.temporada, partidas.temporada),
            rodada=COALESCE(NULLIF(excluded.rodada, ''), partidas.rodada),
            data_partida=excluded.data_partida,
            status=excluded.status,
            time_casa_id=COALESCE(excluded.time_casa_id, partidas.time_casa_id),
            time_casa=excluded.time_casa,
            time_fora_id=COALESCE(excluded.time_fora_id, partidas.time_fora_id),
            time_fora=excluded.time_fora,
            gols_casa=COALESCE(excluded.gols_casa, partidas.gols_casa),
            gols_fora=COALESCE(excluded.gols_fora, partidas.gols_fora),
            vencedor=COALESCE(excluded.vencedor, partidas.vencedor)
        """,
        rows,
    )

    try:
        table_layout = client.competition_layout(slug, "tabela")
        _save_standings(conn, league_id, _standings_rows(table_layout, league_id))
    except OneFootballError:
        # Copas e torneios eliminatórios podem não ter uma tabela.
        pass

    now = datetime.now(timezone.utc).isoformat()
    league_name = rows[0][3] if rows else str(competition.get("liga_nome") or league_id)
    conn.execute(
        """
        INSERT INTO competicoes (
            liga_id, liga_nome, liga_pais, slug, temporada_id, ativo,
            ultima_sincronizacao, ultimo_erro
        ) VALUES (?, ?, ?, ?, NULL, 1, ?, NULL)
        ON CONFLICT(liga_id) DO UPDATE SET
            liga_nome=excluded.liga_nome,
            slug=excluded.slug,
            ativo=1,
            ultima_sincronizacao=excluded.ultima_sincronizacao,
            ultimo_erro=NULL
        """,
        (league_id, league_name, str(competition.get("liga_pais") or ""), competition.get("slug"), now),
    )
    conn.commit()
    new_count = len(set(ids) - existing)
    return len(rows), new_count, len(rows) - new_count


def sincronizar_competicao(
    conn: sqlite3.Connection,
    client: OneFootballClient,
    competition: dict,
    previous_matchdays: int = 80,
    next_matchdays: int = 40,
) -> tuple[int, int, int]:
    """Usa as rotas Next.js; recorre à Scores API somente se elas falharem."""
    try:
        return _sincronizar_competicao_next(conn, client, competition)
    except OneFootballError as next_error:
        try:
            return _sincronizar_competicao_scores(
                conn,
                client,
                competition,
                previous_matchdays=previous_matchdays,
                next_matchdays=next_matchdays,
            )
        except OneFootballError as scores_error:
            raise OneFootballError(
                f"Next.js falhou ({next_error}); fallback Scores API falhou ({scores_error})"
            ) from scores_error


def _sincronizar_competicao_scores(
    conn: sqlite3.Connection,
    client: OneFootballClient,
    competition: dict,
    previous_matchdays: int = 80,
    next_matchdays: int = 40,
) -> tuple[int, int, int]:
    league_id = int(competition["liga_id"])
    info = client.get_json(f"{SCORES_URL}/v1/en/competitions/{league_id}")
    info_item = info[0] if isinstance(info, list) and info else {}
    league_name = str(info_item.get("name") or competition.get("liga_nome") or league_id)
    country = str((info_item.get("country") or {}).get("name") or "")
    params = urlencode(
        {"number_next": next_matchdays, "number_previous": previous_matchdays}
    )
    payload = client.get_json(
        f"{SCORES_URL}/v1/en/competitions/{league_id}/matches?{params}"
    )
    matches = payload if isinstance(payload, list) else []
    season_years = _season_years(matches)
    ids = [int(match["id"]) for match in matches if match.get("id") is not None]
    existing: set[int] = set()
    for start in range(0, len(ids), 800):
        block = ids[start : start + 800]
        if block:
            marks = ",".join("?" for _ in block)
            existing.update(
                row[0]
                for row in conn.execute(
                    f"SELECT id_api FROM partidas WHERE id_api IN ({marks})", block
                )
            )

    rows = []
    season_ids: set[int] = set()
    for match in matches:
        match_id = match.get("id")
        home = match.get("team_home") or {}
        away = match.get("team_away") or {}
        if match_id is None or not home or not away or not match.get("kickoff"):
            continue
        season_id = int((match.get("season") or {}).get("id") or 0)
        if season_id:
            season_ids.add(season_id)
        status, finished = _status(match.get("period"))
        home_score = match.get("score_home") if finished else None
        away_score = match.get("score_away") if finished else None
        rows.append(
            (
                int(match_id),
                league_id,
                f"ONE_{league_id}",
                league_name,
                country,
                season_id or None,
                season_years.get(season_id),
                str((match.get("matchday") or {}).get("name") or match.get("group_name") or ""),
                str(match["kickoff"]),
                status,
                home.get("id"),
                home.get("name"),
                away.get("id"),
                away.get("name"),
                home_score,
                away_score,
                _winner(home_score, away_score),
            )
        )

    conn.executemany(
        """
        INSERT INTO partidas (
            id_api, liga_id, liga_codigo, liga_nome, liga_pais,
            temporada_id, temporada, rodada, data_partida, status,
            time_casa_id, time_casa, time_fora_id, time_fora,
            gols_casa, gols_fora, vencedor
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id_api) DO UPDATE SET
            liga_id=excluded.liga_id,
            liga_codigo=excluded.liga_codigo,
            liga_nome=excluded.liga_nome,
            liga_pais=excluded.liga_pais,
            temporada_id=excluded.temporada_id,
            temporada=excluded.temporada,
            rodada=excluded.rodada,
            data_partida=excluded.data_partida,
            status=excluded.status,
            time_casa_id=excluded.time_casa_id,
            time_casa=excluded.time_casa,
            time_fora_id=excluded.time_fora_id,
            time_fora=excluded.time_fora,
            gols_casa=COALESCE(excluded.gols_casa, partidas.gols_casa),
            gols_fora=COALESCE(excluded.gols_fora, partidas.gols_fora),
            vencedor=COALESCE(excluded.vencedor, partidas.vencedor)
        """,
        rows,
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO competicoes (
            liga_id, liga_nome, liga_pais, slug, temporada_id, ativo,
            ultima_sincronizacao, ultimo_erro
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(liga_id) DO UPDATE SET
            liga_nome=excluded.liga_nome,
            liga_pais=excluded.liga_pais,
            slug=COALESCE(excluded.slug, competicoes.slug),
            temporada_id=COALESCE(excluded.temporada_id, competicoes.temporada_id),
            ativo=excluded.ativo,
            ultima_sincronizacao=excluded.ultima_sincronizacao,
            ultimo_erro=NULL
        """,
        (
            league_id,
            league_name,
            country,
            competition.get("slug"),
            max(season_ids) if season_ids else None,
            1 if rows else 0,
            now,
        ),
    )
    conn.commit()
    new_count = len(set(ids) - existing)
    return len(rows), new_count, len(rows) - new_count


def _registrar_catalogo(conn: sqlite3.Connection, competitions: Iterable[dict]) -> None:
    conn.executemany(
        """
        INSERT INTO competicoes (liga_id, liga_nome, slug)
        VALUES (?, ?, ?)
        ON CONFLICT(liga_id) DO UPDATE SET
            liga_nome=excluded.liga_nome,
            slug=excluded.slug
        """,
        [
            (int(item["liga_id"]), str(item["liga_nome"]), item.get("slug"))
            for item in competitions
        ],
    )
    conn.commit()


def atualizar_dados(
    db_path: str | Path = DB_PATH,
    progresso: Callable[[int, int, str], None] | None = None,
    full: bool = False,
    competition_ids: Iterable[int] | None = None,
    intervalo: float = DEFAULT_DELAY,
) -> dict:
    client = OneFootballClient(intervalo)
    conn = sqlite3.connect(str(db_path), timeout=30)
    criar_banco(conn)
    errors: list[str] = []
    try:
        requested_ids = [int(value) for value in competition_ids or []]
        if requested_ids:
            known = {
                row[0]: {"liga_id": row[0], "liga_nome": row[1], "slug": row[2]}
                for row in conn.execute(
                    f"SELECT liga_id, liga_nome, slug FROM competicoes WHERE liga_id IN ({','.join('?' for _ in requested_ids)})",
                    requested_ids,
                )
            }
            competitions = [
                known.get(value, {"liga_id": value, "liga_nome": f"Competição {value}", "slug": None})
                for value in requested_ids
            ]
        else:
            has_catalog = conn.execute("SELECT 1 FROM competicoes LIMIT 1").fetchone()
            if full or not has_catalog:
                if progresso:
                    progresso(0, 1, "Descobrindo catálogo completo do OneFootball")
                competitions = descobrir_competicoes(client, progresso)
                _registrar_catalogo(conn, competitions)
            else:
                competitions = [
                    {"liga_id": row[0], "liga_nome": row[1], "slug": row[2]}
                    for row in conn.execute(
                        """
                        SELECT liga_id, liga_nome, slug
                        FROM competicoes
                        WHERE ultima_sincronizacao IS NULL
                           OR (
                               ativo=1
                               AND (
                                   datetime(ultima_sincronizacao) < datetime('now', '-7 days')
                                   OR EXISTS (
                                       SELECT 1
                                       FROM partidas p
                                       WHERE p.liga_id=competicoes.liga_id
                                         AND datetime(p.data_partida)
                                             BETWEEN datetime('now', '-2 days')
                                                 AND datetime('now', '+21 days')
                                   )
                               )
                           )
                        ORDER BY ativo DESC, liga_nome
                        """
                    )
                ]

        summary = {
            "consultas": len(competitions),
            "concluidas": 0,
            "recebidas": 0,
            "inseridas": 0,
            "atualizadas": 0,
            "erros": errors,
        }
        for index, competition in enumerate(competitions, start=1):
            message = f"{competition['liga_nome']} (ID {competition['liga_id']})"
            if progresso:
                progresso(index - 1, len(competitions), message)
            try:
                received, inserted, updated = sincronizar_competicao(
                    conn, client, competition
                )
                summary["concluidas"] += 1
                summary["recebidas"] += received
                summary["inseridas"] += inserted
                summary["atualizadas"] += updated
            except (OneFootballError, ValueError, KeyError, sqlite3.Error) as exc:
                detail = f"{message}: {exc}"
                errors.append(detail)
                conn.execute(
                    "UPDATE competicoes SET ultimo_erro=? WHERE liga_id=?",
                    (str(exc)[:500], competition["liga_id"]),
                )
                conn.commit()
                print(_safe_console(f"ERRO {detail}"), flush=True)
        if progresso:
            progresso(len(competitions), len(competitions), "Sincronização OneFootball concluída")
        conn.execute(
            """
            INSERT INTO coleta_estado (chave, valor, atualizado_em)
            VALUES ('ultima_sincronizacao', ?, ?)
            ON CONFLICT(chave) DO UPDATE SET
                valor=excluded.valor, atualizado_em=excluded.atualizado_em
            """,
            (json.dumps(summary, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return summary
    finally:
        conn.close()


def _find_match_events(layout: dict) -> list[dict] | None:
    for item in _walk(layout):
        if item.get("$case") == "matchEvents":
            events = (item.get("matchEvents") or {}).get("events")
            return events if isinstance(events, list) else []
    return None


def _minute(value: object) -> int | None:
    match = re.search(r"(\d+)(?:\s*\+\s*(\d+))?", str(value or ""))
    if not match:
        return None
    return int(match.group(1)) + int(match.group(2) or 0)


def _event_row(match_id: int, order: int, event: dict) -> tuple:
    event_type = event.get("type") or {}
    case = str(event_type.get("$case") or "unknown")
    payload = event_type.get(case) or {}
    side_value = event.get("teamSide")
    side = "HOME" if side_value == 0 else ("AWAY" if side_value == 1 else None)
    player = payload.get("scorer") or payload.get("player") or {}
    assistant = payload.get("assistant") or {}
    player_in = payload.get("playerIn") or {}
    player_out = payload.get("playerOut") or {}
    return (
        match_id,
        order,
        _minute(event.get("timeline")),
        str(event.get("timeline") or ""),
        side,
        case,
        str(payload.get("type") if payload.get("type") is not None else ""),
        player.get("name"),
        assistant.get("name"),
        player_in.get("name"),
        player_out.get("name"),
    )


def salvar_eventos_partida(
    conn: sqlite3.Connection, match_id: int, events: list[dict]
) -> None:
    rows = [_event_row(match_id, index, event) for index, event in enumerate(events)]
    valid_goals = []
    for event, row in zip(events, rows):
        event_type = event.get("type") or {}
        goal = event_type.get("goal") or {}
        # 0 normal, 1 contra e 2 pênalti. 3 anulado e 4 perdido não contam.
        if event_type.get("$case") == "goal" and goal.get("type") in (0, 1, 2):
            valid_goals.append(row)
    home_minutes = [row[2] for row in valid_goals if row[4] == "HOME" and row[2] is not None]
    away_minutes = [row[2] for row in valid_goals if row[4] == "AWAY" and row[2] is not None]
    conn.execute("DELETE FROM eventos_partida WHERE id_api=?", (match_id,))
    conn.executemany(
        """
        INSERT INTO eventos_partida (
            id_api, evento_ordem, minuto, minuto_texto, lado, tipo, subtipo,
            jogador, assistente, jogador_entra, jogador_sai
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.execute(
        """
        INSERT INTO partidas_detalhes (
            id_api, coletado_em, gols_casa_ate_75, gols_fora_ate_75,
            primeiro_gol_casa_minuto, primeiro_gol_fora_minuto,
            total_gols_incidentes
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id_api) DO UPDATE SET
            coletado_em=excluded.coletado_em,
            gols_casa_ate_75=excluded.gols_casa_ate_75,
            gols_fora_ate_75=excluded.gols_fora_ate_75,
            primeiro_gol_casa_minuto=excluded.primeiro_gol_casa_minuto,
            primeiro_gol_fora_minuto=excluded.primeiro_gol_fora_minuto,
            total_gols_incidentes=excluded.total_gols_incidentes
        """,
        (
            match_id,
            datetime.now(timezone.utc).isoformat(),
            sum(minute <= 75 for minute in home_minutes),
            sum(minute <= 75 for minute in away_minutes),
            min(home_minutes) if home_minutes else None,
            min(away_minutes) if away_minutes else None,
            len(valid_goals),
        ),
    )
    conn.commit()


def coletar_minutos_gols(
    match_ids: Iterable[int],
    db_path: str | Path = DB_PATH,
    progresso: Callable[[int, int, str], None] | None = None,
    intervalo: float = DEFAULT_DELAY,
) -> dict:
    ids = list(dict.fromkeys(int(value) for value in match_ids))
    client = OneFootballClient(intervalo)
    conn = sqlite3.connect(str(db_path), timeout=30)
    criar_banco(conn)
    completed = 0
    errors: list[str] = []
    try:
        known = {
            row[0]: (row[1], row[2])
            for row in conn.execute(
                f"SELECT id_api, gols_casa, gols_fora FROM partidas WHERE id_api IN ({','.join('?' for _ in ids)})",
                ids,
            )
        } if ids else {}
        for index, match_id in enumerate(ids, start=1):
            message = f"[GOLS {index}/{len(ids)}] Partida {match_id}"
            print(message, flush=True)
            if progresso:
                progresso(index - 1, len(ids), message)
            try:
                events = _find_match_events(client.match_layout(match_id))
                expected_goals = sum(value or 0 for value in known.get(match_id, (None, None)))
                if events is None and expected_goals == 0:
                    events = []
                elif events is None:
                    raise OneFootballError("bloco matchEvents ausente")
                actual_goals = sum(
                    1
                    for event in events
                    if (event.get("type") or {}).get("$case") == "goal"
                    and ((event.get("type") or {}).get("goal") or {}).get("type") in (0, 1, 2)
                )
                if expected_goals and actual_goals < expected_goals:
                    raise OneFootballError(
                        f"eventos incompletos: placar tem {expected_goals} gols, página retornou {actual_goals}"
                    )
                salvar_eventos_partida(conn, match_id, events)
                completed += 1
            except (OneFootballError, ValueError, KeyError, sqlite3.Error) as exc:
                errors.append(f"{match_id}: {exc}")
        if progresso:
            progresso(len(ids), len(ids), "Minutos OneFootball atualizados")
        return {"concluidas": completed, "erros": len(errors), "total": len(ids), "detalhes": errors}
    finally:
        conn.close()


def _parse_ids(value: str | None) -> list[int]:
    if not value:
        return []
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Coletor incremental OneFootball")
    parser.add_argument("--full", action="store_true", help="redescobre todo o catálogo")
    parser.add_argument("--update", action="store_true", help="usa o catálogo salvo")
    parser.add_argument("--competition-ids", help="IDs separados por vírgula")
    parser.add_argument("--goal-ids", help="IDs de partidas separados por vírgula")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    if args.goal_ids:
        result = coletar_minutos_gols(
            _parse_ids(args.goal_ids), intervalo=args.delay
        )
        for error in result.get("detalhes", []):
            print(f"ERRO {error}")
        print(
            "ONEFOOTBALL_GOLS_RESULTADO "
            f"concluidas={result['concluidas']} erros={result['erros']} total={result['total']}"
        )
        return

    def report(current: int, total: int, message: str) -> None:
        print(f"[{current}/{total}] {message}", flush=True)

    db_has_data = DB_PATH.exists() and DB_PATH.stat().st_size > 0
    result = atualizar_dados(
        progresso=report,
        full=args.full or (not args.update and not db_has_data),
        competition_ids=_parse_ids(args.competition_ids),
        intervalo=args.delay,
    )
    print("=" * 64)
    print(
        "ONEFOOTBALL_RESULTADO "
        f"consultas={result['consultas']} concluidas={result['concluidas']} "
        f"recebidas={result['recebidas']} inseridas={result['inseridas']} "
        f"atualizadas={result['atualizadas']} erros={len(result['erros'])}"
    )
    print(f"Banco salvo em {DB_PATH}")


if __name__ == "__main__":
    main()
