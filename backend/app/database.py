from __future__ import annotations

import math
import sqlite3
import unicodedata
from datetime import datetime, timezone
from typing import Any

from .config import SOURCES, SourceConfig


CANONICAL_COLUMNS = (
    "id_api",
    "liga_id",
    "liga_codigo",
    "liga_nome",
    "liga_pais",
    "temporada_id",
    "temporada",
    "rodada",
    "data_partida",
    "status",
    "time_casa_id",
    "time_casa",
    "time_fora_id",
    "time_fora",
    "gols_casa",
    "gols_fora",
    "vencedor",
)


class DataError(RuntimeError):
    pass


def source_config(source: str) -> SourceConfig:
    try:
        return SOURCES[source]
    except KeyError as exc:
        raise DataError(f"Fonte desconhecida: {source}") from exc


def connect(source: str) -> sqlite3.Connection:
    config = source_config(source)
    if not config.path.exists():
        raise DataError(f"Banco ainda não existe: {config.filename}")
    conn = sqlite3.connect(str(config.path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.create_function("normalize", 1, _normalize, deterministic=True)
    return conn


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in text if not unicodedata.combining(char)).casefold()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _match_select(conn: sqlite3.Connection) -> str:
    columns = _columns(conn, "partidas")
    selected = []
    for column in CANONICAL_COLUMNS:
        if column in columns:
            selected.append(f"p.{column} AS {column}")
        elif column == "liga_id" and "liga_codigo" in columns:
            selected.append("p.liga_codigo AS liga_id")
        elif column == "liga_codigo" and "liga_id" in columns:
            selected.append("'SOFA_' || p.liga_id AS liga_codigo")
        elif column == "status":
            selected.append(
                "CASE WHEN p.gols_casa IS NULL THEN 'SCHEDULED' ELSE 'FINISHED' END AS status"
            )
        elif column == "liga_pais":
            selected.append("'' AS liga_pais")
        elif column == "rodada":
            selected.append("'' AS rodada")
        else:
            selected.append(f"NULL AS {column}")

    if _table_exists(conn, "partidas_detalhes"):
        detail_columns = _columns(conn, "partidas_detalhes")
        for column in (
            "gols_casa_ate_75",
            "gols_fora_ate_75",
            "primeiro_gol_casa_minuto",
            "primeiro_gol_fora_minuto",
        ):
            selected.append(
                f"d.{column} AS {column}" if column in detail_columns else f"NULL AS {column}"
            )
    else:
        selected.extend(
            f"NULL AS {column}"
            for column in (
                "gols_casa_ate_75",
                "gols_fora_ate_75",
                "primeiro_gol_casa_minuto",
                "primeiro_gol_fora_minuto",
            )
        )
    return ", ".join(selected)


def _details_join(conn: sqlite3.Connection) -> str:
    return (
        "LEFT JOIN partidas_detalhes d ON d.id_api=p.id_api"
        if _table_exists(conn, "partidas_detalhes")
        else ""
    )


def _to_iso(value: Any, date_kind: str) -> str | None:
    if value in (None, ""):
        return None
    if date_kind == "epoch":
        return datetime.fromtimestamp(int(value), timezone.utc).isoformat().replace("+00:00", "Z")
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return text


def _clean_number(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def serialize_match(row: sqlite3.Row | dict, source: str) -> dict:
    config = source_config(source)
    item = {key: _clean_number(row[key]) for key in row.keys()}
    item["data_partida"] = _to_iso(item.get("data_partida"), config.date_kind)
    item["liga_id"] = str(item.get("liga_id"))
    item["id_api"] = int(item["id_api"])
    return item


def _is_future_match(match: dict, now: datetime | None = None) -> bool:
    """Considera futura somente uma partida sem placar e com data posterior a agora."""
    if match.get("gols_casa") is not None or match.get("gols_fora") is not None:
        return False
    value = match.get("data_partida")
    if not value:
        return False
    try:
        scheduled_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    return scheduled_at.astimezone(timezone.utc) >= reference.astimezone(timezone.utc)


def source_summary(source: str) -> dict:
    config = source_config(source)
    if not config.path.exists():
        return {
            "key": source,
            "name": config.name,
            "description": config.description,
            "available": False,
            "matches": 0,
            "leagues": 0,
            "supports_minutes": config.supports_minutes,
        }
    with connect(source) as conn:
        matches = conn.execute("SELECT COUNT(*) FROM partidas").fetchone()[0]
        leagues = conn.execute(
            f"SELECT COUNT(DISTINCT {config.league_column}) FROM partidas"
        ).fetchone()[0]
    return {
        "key": source,
        "name": config.name,
        "description": config.description,
        "available": True,
        "matches": matches,
        "leagues": leagues,
        "supports_minutes": config.supports_minutes,
    }


def list_leagues(source: str, search: str = "") -> list[dict]:
    config = source_config(source)
    with connect(source) as conn:
        columns = _columns(conn, "partidas")
        country = "COALESCE(p.liga_pais, '')" if "liga_pais" in columns else "''"
        code = "p.liga_codigo" if "liga_codigo" in columns else "'SOFA_' || p.liga_id"
        where = ""
        params: list[Any] = []
        if search.strip():
            needle = f"%{_normalize(search.strip())}%"
            where = f"""
                WHERE normalize(p.liga_nome) LIKE ?
                   OR normalize({country}) LIKE ?
                   OR normalize(CAST({code} AS TEXT)) LIKE ?
                   OR normalize(COALESCE(p.time_casa, '')) LIKE ?
                   OR normalize(COALESCE(p.time_fora, '')) LIKE ?
            """
            params = [needle] * 5
        rows = conn.execute(
            f"""
            SELECT CAST(p.{config.league_column} AS TEXT) AS id,
                   MAX(p.liga_nome) AS name,
                   MAX({country}) AS country,
                   MAX({code}) AS code,
                   COUNT(*) AS matches,
                   GROUP_CONCAT(DISTINCT p.temporada) AS seasons
            FROM partidas p
            {where}
            GROUP BY p.{config.league_column}
            ORDER BY lower(MAX(p.liga_nome))
            """,
            params,
        ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "country": row["country"] or "",
            "code": row["code"],
            "matches": row["matches"],
            "seasons": sorted(
                [int(value) for value in (row["seasons"] or "").split(",") if value],
                reverse=True,
            ),
        }
        for row in rows
    ]


def _date_filter(config: SourceConfig, operator: str) -> tuple[str, Any]:
    now = datetime.now(timezone.utc)
    if config.date_kind == "epoch":
        return f"p.data_partida {operator} ?", int(now.timestamp())
    return f"datetime(p.data_partida) {operator} datetime(?)", now.isoformat()


def list_upcoming(
    source: str,
    league_id: str | None = None,
    search: str = "",
    page: int = 1,
    page_size: int = 30,
) -> dict:
    config = source_config(source)
    with connect(source) as conn:
        date_sql, date_value = _date_filter(config, ">=")
        clauses = ["p.gols_casa IS NULL", date_sql]
        params: list[Any] = [date_value]
        if league_id is not None:
            clauses.append(f"CAST(p.{config.league_column} AS TEXT)=?")
            params.append(str(league_id))
        if search.strip():
            needle = f"%{_normalize(search.strip())}%"
            clauses.append(
                "(normalize(p.liga_nome) LIKE ? OR normalize(p.time_casa) LIKE ? OR normalize(p.time_fora) LIKE ?)"
            )
            params.extend([needle, needle, needle])
        where = " AND ".join(clauses)
        total = conn.execute(
            f"SELECT COUNT(*) FROM partidas p WHERE {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT {_match_select(conn)}
            FROM partidas p {_details_join(conn)}
            WHERE {where}
            ORDER BY p.data_partida ASC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
    return {
        "items": [serialize_match(row, source) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, math.ceil(total / page_size)),
    }


def get_match(source: str, match_id: int) -> dict | None:
    with connect(source) as conn:
        row = conn.execute(
            f"""
            SELECT {_match_select(conn)}
            FROM partidas p {_details_join(conn)}
            WHERE p.id_api=?
            """,
            (match_id,),
        ).fetchone()
    return serialize_match(row, source) if row else None


def team_history(
    source: str,
    team_id: int,
    before_date: str,
    limit: int = 10,
    venue: str | None = None,
) -> list[dict]:
    config = source_config(source)
    if venue not in {None, "home", "away"}:
        raise ValueError("Mando inválido. Use home ou away")
    with connect(source) as conn:
        if config.date_kind == "epoch":
            before_value: Any = int(
                datetime.fromisoformat(before_date.replace("Z", "+00:00")).timestamp()
            )
            before_sql = "p.data_partida < ?"
        else:
            before_value = before_date
            before_sql = "datetime(p.data_partida) < datetime(?)"
        team_clause = {
            "home": "p.time_casa_id=?",
            "away": "p.time_fora_id=?",
        }.get(venue, "(p.time_casa_id=? OR p.time_fora_id=?)")
        team_params = [team_id] if venue else [team_id, team_id]
        rows = conn.execute(
            f"""
            SELECT {_match_select(conn)}
            FROM partidas p {_details_join(conn)}
            WHERE p.gols_casa IS NOT NULL
              AND {team_clause}
              AND {before_sql}
            ORDER BY p.data_partida DESC
            LIMIT ?
            """,
            (*team_params, before_value, limit),
        ).fetchall()
    return [serialize_match(row, source) for row in rows]


def league_standings_before(
    source: str,
    league_id: str,
    before_date: str,
    season: int | None = None,
) -> list[dict]:
    """Calcula a classificação sem usar resultados posteriores ao jogo."""
    config = source_config(source)
    with connect(source) as conn:
        if config.date_kind == "epoch":
            before_value: Any = int(
                datetime.fromisoformat(before_date.replace("Z", "+00:00")).timestamp()
            )
            before_sql = "p.data_partida < ?"
        else:
            before_value = before_date
            before_sql = "datetime(p.data_partida) < datetime(?)"
        clauses = [
            f"CAST(p.{config.league_column} AS TEXT)=?",
            "p.gols_casa IS NOT NULL",
            before_sql,
        ]
        params: list[Any] = [str(league_id), before_value]
        if season is not None:
            clauses.append("p.temporada=?")
            params.append(season)
        rows = conn.execute(
            f"""
            SELECT {_match_select(conn)}
            FROM partidas p {_details_join(conn)}
            WHERE {' AND '.join(clauses)}
            ORDER BY p.data_partida ASC
            """,
            params,
        ).fetchall()
    return compute_standings([serialize_match(row, source) for row in rows])


def head_to_head(
    source: str, home_id: int, away_id: int, before_date: str, limit: int = 10
) -> list[dict]:
    config = source_config(source)
    with connect(source) as conn:
        if config.date_kind == "epoch":
            before_value: Any = int(
                datetime.fromisoformat(before_date.replace("Z", "+00:00")).timestamp()
            )
            before_sql = "p.data_partida < ?"
        else:
            before_value = before_date
            before_sql = "datetime(p.data_partida) < datetime(?)"
        rows = conn.execute(
            f"""
            SELECT {_match_select(conn)}
            FROM partidas p {_details_join(conn)}
            WHERE p.gols_casa IS NOT NULL AND {before_sql}
              AND ((p.time_casa_id=? AND p.time_fora_id=?)
                OR (p.time_casa_id=? AND p.time_fora_id=?))
            ORDER BY p.data_partida DESC LIMIT ?
            """,
            (before_value, home_id, away_id, away_id, home_id, limit),
        ).fetchall()
    return [serialize_match(row, source) for row in rows]


def goal_timeline(source: str, match_ids: list[int]) -> dict:
    ids = list(dict.fromkeys(int(value) for value in match_ids))
    if not ids:
        return {"covered_match_ids": [], "events": []}
    marks = ",".join("?" for _ in ids)
    with connect(source) as conn:
        expected_goals: dict[int, int] = {}
        if _table_exists(conn, "partidas_detalhes"):
            expected_goals = {
                int(row[0]): int(row[1] or 0)
                for row in conn.execute(
                    f"""
                    SELECT id_api, total_gols_incidentes
                    FROM partidas_detalhes WHERE id_api IN ({marks})
                    """,
                    ids,
                )
            }
        events = []
        if _table_exists(conn, "eventos_partida"):
            rows = conn.execute(
                f"""
                SELECT id_api, evento_ordem, minuto, minuto_texto, lado,
                       tipo, subtipo, jogador, assistente
                FROM eventos_partida
                WHERE id_api IN ({marks}) AND lower(tipo)='goal'
                ORDER BY id_api, evento_ordem
                """,
                ids,
            ).fetchall()
            for row in rows:
                item = dict(row)
                subtype = str(item.get("subtipo") or "").strip()
                # OneFootball: 3=anulado e 4=pênalti perdido.
                if subtype in {"3", "4", "cancelled", "missed"}:
                    continue
                item["id_api"] = int(item["id_api"])
                events.append(item)
    event_counts: dict[int, int] = {}
    for event in events:
        event_counts[event["id_api"]] = event_counts.get(event["id_api"], 0) + 1
    covered = [
        match_id
        for match_id, expected in expected_goals.items()
        if expected == 0 or event_counts.get(match_id, 0) >= expected
    ]
    return {"covered_match_ids": covered, "events": events}


def xg_values(source: str, match_ids: list[int]) -> dict[int, dict]:
    """Lê xG real se um coletor futuro preencher partidas_metricas."""
    ids = list(dict.fromkeys(int(value) for value in match_ids))
    if not ids:
        return {}
    with connect(source) as conn:
        if not _table_exists(conn, "partidas_metricas"):
            return {}
        columns = _columns(conn, "partidas_metricas")
        if not {"id_api", "xg_casa", "xg_fora"}.issubset(columns):
            return {}
        marks = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"""
            SELECT id_api, xg_casa, xg_fora
            FROM partidas_metricas
            WHERE id_api IN ({marks})
              AND xg_casa IS NOT NULL AND xg_fora IS NOT NULL
            """,
            ids,
        ).fetchall()
    return {
        int(row["id_api"]): {
            "home": float(row["xg_casa"]),
            "away": float(row["xg_fora"]),
        }
        for row in rows
    }


def league_overview(source: str, league_id: str, season: int | None = None) -> dict:
    config = source_config(source)
    with connect(source) as conn:
        clauses = [f"CAST(p.{config.league_column} AS TEXT)=?"]
        params: list[Any] = [str(league_id)]
        if season is not None:
            clauses.append("p.temporada=?")
            params.append(season)
        where = " AND ".join(clauses)
        rows = conn.execute(
            f"""
            SELECT {_match_select(conn)} FROM partidas p {_details_join(conn)}
            WHERE {where} ORDER BY p.data_partida DESC
            """,
            params,
        ).fetchall()
        matches = [serialize_match(row, source) for row in rows]
        official = []
        if source == "onefootball" and _table_exists(conn, "classificacao"):
            official = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT posicao AS position, time_id, time_nome AS team,
                           jogos AS played, vitorias AS wins, empates AS draws,
                           derrotas AS losses, saldo_gols AS goal_difference,
                           pontos AS points
                    FROM classificacao WHERE liga_id=? ORDER BY posicao
                    """,
                    (int(league_id),),
                )
            ]
    played = [match for match in matches if match["gols_casa"] is not None]
    now = datetime.now(timezone.utc)
    upcoming = sorted(
        [match for match in matches if _is_future_match(match, now)],
        key=lambda item: item["data_partida"] or "",
    )[:30]
    recent = sorted(
        played, key=lambda item: item["data_partida"] or "", reverse=True
    )[:30]
    goals = sum((match["gols_casa"] or 0) + (match["gols_fora"] or 0) for match in played)
    return {
        "league": {
            "id": str(league_id),
            "name": matches[0]["liga_nome"] if matches else str(league_id),
            "country": matches[0]["liga_pais"] if matches else "",
            "season": season,
        },
        "stats": {
            "matches": len(matches),
            "played": len(played),
            "goals": goals,
            "goals_per_match": round(goals / len(played), 2) if played else 0,
        },
        "standings": official or compute_standings(played),
        "upcoming": upcoming,
        "recent": recent,
    }


def compute_standings(matches: list[dict]) -> list[dict]:
    table: dict[int, dict] = {}
    for match in matches:
        for side in ("casa", "fora"):
            team_id = int(match[f"time_{side}_id"])
            table.setdefault(
                team_id,
                {
                    "time_id": team_id,
                    "team": match[f"time_{side}"],
                    "played": 0,
                    "wins": 0,
                    "draws": 0,
                    "losses": 0,
                    "goals_for": 0,
                    "goals_against": 0,
                    "points": 0,
                },
            )
        home = table[int(match["time_casa_id"])]
        away = table[int(match["time_fora_id"])]
        hg, ag = int(match["gols_casa"]), int(match["gols_fora"])
        home["played"] += 1
        away["played"] += 1
        home["goals_for"] += hg
        home["goals_against"] += ag
        away["goals_for"] += ag
        away["goals_against"] += hg
        if hg > ag:
            home["wins"] += 1
            home["points"] += 3
            away["losses"] += 1
        elif ag > hg:
            away["wins"] += 1
            away["points"] += 3
            home["losses"] += 1
        else:
            home["draws"] += 1
            away["draws"] += 1
            home["points"] += 1
            away["points"] += 1
    result = list(table.values())
    for row in result:
        row["goal_difference"] = row["goals_for"] - row["goals_against"]
    result.sort(key=lambda row: (row["points"], row["goal_difference"], row["goals_for"]), reverse=True)
    for index, row in enumerate(result, start=1):
        row["position"] = index
    return result
