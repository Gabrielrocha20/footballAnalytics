from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from . import database
from .config import DATA_DIR


HISTORY_PATH = DATA_DIR / "tradefot_history.db"
LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(HISTORY_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS analysis_snapshots (
            source TEXT NOT NULL,
            match_id INTEGER NOT NULL,
            kickoff TEXT NOT NULL,
            league_name TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            PRIMARY KEY (source, match_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_snapshots_kickoff ON analysis_snapshots(source, kickoff DESC)"
    )
    return conn


def _is_before_kickoff(match: dict) -> bool:
    if match.get("gols_casa") is not None or not match.get("data_partida"):
        return False
    try:
        kickoff = datetime.fromisoformat(match["data_partida"].replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    return kickoff > datetime.now(timezone.utc)


def save_analysis(analysis: dict) -> bool:
    """Congela a primeira fotografia disponível antes do início do jogo."""
    match = analysis["match"]
    if not _is_before_kickoff(match):
        return False
    payload = {
        "prediction": analysis.get("prediction"),
        "insights": analysis.get("insights"),
        "lay_01": {
            key: analysis.get("lay_01", {}).get(key)
            for key in (
                "status",
                "home_favorite",
                "favorite_probability",
                "sample_size",
                "coverage",
                "hits",
                "percentage",
            )
        },
    }
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO analysis_snapshots (
                source, match_id, kickoff, league_name, home_team, away_team,
                payload_json, captured_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis.get("source") or "",
                int(match["id_api"]),
                match["data_partida"],
                match.get("liga_nome") or "",
                match.get("time_casa") or "",
                match.get("time_fora") or "",
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                now,
            ),
        )
    return cursor.rowcount > 0


def save_source_analysis(source: str, analysis: dict) -> bool:
    analysis = {**analysis, "source": source}
    return save_analysis(analysis)


def _existing_match_ids(source: str, match_ids: list[int]) -> set[int]:
    if not match_ids:
        return set()
    marks = ",".join("?" for _ in match_ids)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT match_id FROM analysis_snapshots WHERE source=? AND match_id IN ({marks})",
            (source, *match_ids),
        ).fetchall()
    return {int(row["match_id"]) for row in rows}


def capture_today(
    source: str,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    """Registra as análises dos jogos restantes do dia no horário de São Paulo."""
    today = datetime.now(LOCAL_TIMEZONE).date()
    candidates = []
    page = 1
    while True:
        result = database.list_upcoming(source, page=page, page_size=100)
        for match in result["items"]:
            kickoff = datetime.fromisoformat(match["data_partida"].replace("Z", "+00:00"))
            local_date = kickoff.astimezone(LOCAL_TIMEZONE).date()
            if local_date == today:
                candidates.append(match)
        if page >= result["pages"]:
            break
        last = result["items"][-1] if result["items"] else None
        if last:
            last_date = datetime.fromisoformat(last["data_partida"].replace("Z", "+00:00"))
            if last_date.astimezone(LOCAL_TIMEZONE).date() > today:
                break
        page += 1

    scheduled = len(candidates)
    existing_ids = _existing_match_ids(
        source, [int(match["id_api"]) for match in candidates]
    )
    candidates = [
        match for match in candidates if int(match["id_api"]) not in existing_ids
    ]
    captured = 0
    errors = []
    if candidates:
        from . import analytics

        for index, match in enumerate(candidates, start=1):
            if progress:
                progress(index, len(candidates), f"Salvando análise pré-jogo: {match['time_casa']} x {match['time_fora']}")
            try:
                analysis = analytics.match_analysis(source, int(match["id_api"]))
                captured += save_source_analysis(source, analysis)
            except Exception as exc:
                errors.append({"match_id": match["id_api"], "error": str(exc)})
    return {
        "date": today.isoformat(),
        "scheduled": scheduled,
        "candidates": len(candidates),
        "captured": captured,
        "errors": errors,
    }


def _priced_pick(market: dict, first: str, second: str) -> str:
    return (
        first
        if float(market[first]["probability"]) >= float(market[second]["probability"])
        else second
    )


def _check(check_id: str, label: str, selection: str, hit: bool) -> dict:
    return {
        "id": check_id,
        "label": label,
        "selection": selection,
        "hit": bool(hit),
    }


def _evaluate(snapshot: sqlite3.Row, match: dict) -> dict:
    payload = json.loads(snapshot["payload_json"])
    prediction = payload.get("prediction")
    checks = []
    home_goals = int(match["gols_casa"])
    away_goals = int(match["gols_fora"])
    actual_result = "home" if home_goals > away_goals else "away" if away_goals > home_goals else "draw"

    if prediction:
        result_labels = {"home": "Casa", "draw": "Empate", "away": "Fora"}
        result_pick = max(("home", "draw", "away"), key=lambda key: prediction[key])
        checks.append(
            _check("result", "Resultado 1X2", result_labels[result_pick], result_pick == actual_result)
        )

        total_market = prediction["markets"]["total_goals"]["2.5"]
        total_pick = _priced_pick(total_market, "over", "under")
        total_goals = home_goals + away_goals
        checks.append(
            _check(
                "total_25",
                "Total de gols",
                "Mais de 2,5" if total_pick == "over" else "Menos de 2,5",
                (total_goals > 2.5) == (total_pick == "over"),
            )
        )

        btts_market = prediction["markets"]["btts"]
        btts_pick = _priced_pick(btts_market, "yes", "no")
        both_scored = home_goals > 0 and away_goals > 0
        checks.append(
            _check(
                "btts",
                "Ambas marcam",
                "Sim" if btts_pick == "yes" else "Não",
                both_scored == (btts_pick == "yes"),
            )
        )

        favorite_side = payload.get("insights", {}).get("favorite", {}).get("side")
        if favorite_side in {"home", "away"}:
            score_market = prediction["markets"]["team_to_score"][favorite_side]
            predicts_score = float(score_market["probability"]) >= 50
            favorite_goals = home_goals if favorite_side == "home" else away_goals
            checks.append(
                _check(
                    "favorite_scores",
                    "Favorito marca",
                    "Sim" if predicts_score else "Não",
                    (favorite_goals > 0) == predicts_score,
                )
            )

    lay = payload.get("lay_01") or {}
    if lay.get("status") == "approved" and match.get("gols_casa_ate_75") is not None:
        checks.append(
            _check(
                "lay_01",
                "Lay 0x1",
                "Gol do favorito até 75′",
                int(match["gols_casa_ate_75"]) >= 1,
            )
        )

    hits = sum(item["hit"] for item in checks)
    hit_rate = round(hits / len(checks) * 100, 1) if checks else None
    return {
        "source": snapshot["source"],
        "match_id": int(snapshot["match_id"]),
        "kickoff": snapshot["kickoff"],
        "league_name": snapshot["league_name"],
        "home_team": snapshot["home_team"],
        "away_team": snapshot["away_team"],
        "home_goals": home_goals,
        "away_goals": away_goals,
        "captured_at": snapshot["captured_at"],
        "status": "evaluated" if checks else "ungraded",
        "hits": hits,
        "checks_count": len(checks),
        "hit_rate": hit_rate,
        "verdict": "hit" if hit_rate is not None and hit_rate >= 60 else "miss",
        "checks": checks,
    }


def performance(source: str, days: int = 7, limit: int = 30) -> dict:
    database.source_config(source)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM analysis_snapshots
            WHERE source=? AND kickoff>=?
            ORDER BY kickoff DESC
            LIMIT ?
            """,
            (source, since, max(limit * 4, 100)),
        ).fetchall()

    evaluated = []
    pending = 0
    for row in rows:
        match = database.get_match(source, int(row["match_id"]))
        if not match or match.get("gols_casa") is None or match.get("gols_fora") is None:
            pending += 1
            continue
        evaluated.append(_evaluate(row, match))

    visible = evaluated[:limit]
    total_checks = sum(item["checks_count"] for item in evaluated)
    total_hits = sum(item["hits"] for item in evaluated)
    return {
        "source": source,
        "period_days": days,
        "summary": {
            "snapshots": len(rows),
            "evaluated_matches": len(evaluated),
            "pending_matches": pending,
            "matches_hit": sum(item["verdict"] == "hit" for item in evaluated),
            "checks": total_checks,
            "hits": total_hits,
            "hit_rate": round(total_hits / total_checks * 100, 1) if total_checks else None,
        },
        "items": visible,
    }
