from __future__ import annotations

import math
import re
from typing import Any

from . import database


def _perspective(matches: list[dict], team_id: int) -> list[dict]:
    result = []
    for match in matches:
        at_home = match["time_casa_id"] == team_id
        goals_for = match["gols_casa"] if at_home else match["gols_fora"]
        goals_against = match["gols_fora"] if at_home else match["gols_casa"]
        if goals_for > goals_against:
            outcome = "W"
        elif goals_for < goals_against:
            outcome = "L"
        else:
            outcome = "D"
        goal_75_key = "gols_casa_ate_75" if at_home else "gols_fora_ate_75"
        minute_key = (
            "primeiro_gol_casa_minuto" if at_home else "primeiro_gol_fora_minuto"
        )
        result.append(
            {
                **match,
                "venue": "home" if at_home else "away",
                "opponent": match["time_fora"] if at_home else match["time_casa"],
                "goals_for": goals_for,
                "goals_against": goals_against,
                "result": outcome,
                "goals_until_75": match.get(goal_75_key),
                "first_goal_minute": match.get(minute_key),
            }
        )
    return result


def _summary(matches: list[dict]) -> dict:
    total = len(matches)
    wins = sum(match["result"] == "W" for match in matches)
    draws = sum(match["result"] == "D" for match in matches)
    losses = sum(match["result"] == "L" for match in matches)
    goals_for = sum(int(match["goals_for"]) for match in matches)
    goals_against = sum(int(match["goals_against"]) for match in matches)
    return {
        "matches": total,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "goals_for_average": round(goals_for / total, 2) if total else 0,
        "goals_against_average": round(goals_against / total, 2) if total else 0,
        "points_per_game": round((wins * 3 + draws) / total, 2) if total else 0,
        "performance": round((wins * 3 + draws) / (total * 3) * 100, 1) if total else 0,
        "form": [match["result"] for match in matches],
    }


def _poisson(
    home_matches: list[dict],
    away_matches: list[dict],
    h2h: list[dict],
    home_id: int,
    away_id: int,
) -> dict | None:
    home = _summary(home_matches)
    away = _summary(away_matches)
    if not home["matches"] or not away["matches"]:
        return None

    expected_home = (home["goals_for_average"] + away["goals_against_average"]) / 2
    expected_away = (away["goals_for_average"] + home["goals_against_average"]) / 2
    form_difference = home["points_per_game"] - away["points_per_game"]
    home_h2h_wins = away_h2h_wins = 0
    for match in h2h:
        if match["gols_casa"] > match["gols_fora"]:
            winner = match["time_casa_id"]
        elif match["gols_fora"] > match["gols_casa"]:
            winner = match["time_fora_id"]
        else:
            winner = None
        home_h2h_wins += winner == home_id
        away_h2h_wins += winner == away_id
    h2h_difference = (
        (home_h2h_wins - away_h2h_wins) / len(h2h) if h2h else 0
    )

    expected_home *= 1.08 + 0.08 * form_difference + 0.06 * h2h_difference
    expected_away *= 0.96 - 0.08 * form_difference - 0.06 * h2h_difference
    expected_home = min(max(expected_home, 0.2), 4.0)
    expected_away = min(max(expected_away, 0.2), 4.0)
    probabilities = []
    for home_goals in range(13):
        p_home = math.exp(-expected_home) * expected_home**home_goals / math.factorial(home_goals)
        for away_goals in range(13):
            p_away = math.exp(-expected_away) * expected_away**away_goals / math.factorial(away_goals)
            probabilities.append(
                {
                    "home_goals": home_goals,
                    "away_goals": away_goals,
                    "raw_probability": p_home * p_away,
                }
            )
    total = sum(item["raw_probability"] for item in probabilities)
    for item in probabilities:
        item["probability"] = item["raw_probability"] / total

    def chance(predicate) -> float:
        return sum(item["probability"] for item in probabilities if predicate(item))

    def priced(probability: float) -> dict:
        percentage = probability * 100
        return {
            "probability": round(percentage, 2),
            "fair_odds": round(1 / probability, 3) if probability > 0 else None,
        }

    home_probability = chance(lambda item: item["home_goals"] > item["away_goals"])
    draw_probability = chance(lambda item: item["home_goals"] == item["away_goals"])
    away_probability = chance(lambda item: item["home_goals"] < item["away_goals"])
    score_matrix = [
        {
            "home_goals": item["home_goals"],
            "away_goals": item["away_goals"],
            **priced(item["probability"]),
        }
        for item in probabilities
        if item["home_goals"] <= 8 and item["away_goals"] <= 8
    ]
    top_scorelines = sorted(
        score_matrix, key=lambda item: item["probability"], reverse=True
    )[:10]
    totals = {}
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        minimum = math.floor(line) + 1
        over = chance(lambda item, minimum=minimum: item["home_goals"] + item["away_goals"] >= minimum)
        totals[str(line)] = {"over": priced(over), "under": priced(1 - over)}
    btts_yes = chance(lambda item: item["home_goals"] > 0 and item["away_goals"] > 0)
    return {
        "home": round(home_probability * 100, 1),
        "draw": round(draw_probability * 100, 1),
        "away": round(away_probability * 100, 1),
        "expected_home_goals": round(expected_home, 2),
        "expected_away_goals": round(expected_away, 2),
        "markets": {
            "match_odds": {
                "home": priced(home_probability),
                "draw": priced(draw_probability),
                "away": priced(away_probability),
            },
            "total_goals": totals,
            "btts": {"yes": priced(btts_yes), "no": priced(1 - btts_yes)},
            "clean_sheet": {
                "home": priced(chance(lambda item: item["away_goals"] == 0)),
                "away": priced(chance(lambda item: item["home_goals"] == 0)),
            },
            "team_to_score": {
                "home": priced(chance(lambda item: item["home_goals"] >= 1)),
                "away": priced(chance(lambda item: item["away_goals"] >= 1)),
            },
        },
        "top_scorelines": top_scorelines,
        "score_matrix": score_matrix,
        "model": {
            "distribution": "independent_poisson",
            "max_goals_calculated": 12,
            "max_goals_returned_in_matrix": 8,
            "fair_odds_include_margin": False,
        },
    }


def _lay_analysis(
    prediction: dict | None,
    home_history: list[dict],
    supports_minutes: bool,
) -> dict:
    home_favorite = bool(
        prediction
        and prediction["home"] > max(prediction["draw"], prediction["away"])
    )
    values = [match.get("goals_until_75") for match in home_history]
    coverage = sum(value is not None for value in values)
    hits = sum(value is not None and int(value) >= 1 for value in values)
    percentage = hits / 10 * 100
    missing_ids = [
        match["id_api"]
        for match in home_history
        if match.get("goals_until_75") is None
    ]
    if not supports_minutes:
        status = "unsupported"
    elif not prediction:
        status = "insufficient_history"
    elif not home_favorite:
        status = "not_home_favorite"
    elif len(home_history) < 10:
        status = "insufficient_history"
    elif coverage < 10:
        status = "pending_minutes"
    elif percentage > 75:
        status = "approved"
    else:
        status = "rejected"
    return {
        "status": status,
        "home_favorite": home_favorite,
        "favorite_probability": prediction["home"] if prediction else None,
        "sample_size": len(home_history),
        "coverage": coverage,
        "hits": hits,
        "percentage": round(percentage, 1),
        "threshold": 75,
        "minimum_hits": 8,
        "missing_match_ids": missing_ids,
        "history": home_history,
    }


TIME_BINS = ("0-15", "16-30", "31-45+", "46-60", "61-75", "76-90+")


def _base_minute(event: dict) -> int | None:
    match = re.search(r"(\d+)", str(event.get("minuto_texto") or ""))
    if match:
        return int(match.group(1))
    minute = event.get("minuto")
    return int(minute) if minute is not None else None


def _time_bin(event: dict) -> str | None:
    minute = _base_minute(event)
    if minute is None:
        return None
    if minute <= 15:
        return "0-15"
    if minute <= 30:
        return "16-30"
    if minute <= 45:
        return "31-45+"
    if minute <= 60:
        return "46-60"
    if minute <= 75:
        return "61-75"
    return "76-90+"


def _events_by_match(timeline: dict) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = {}
    for event in timeline["events"]:
        result.setdefault(int(event["id_api"]), []).append(event)
    for events in result.values():
        events.sort(
            key=lambda event: (
                event.get("minuto") if event.get("minuto") is not None else 999,
                event.get("evento_ordem") if event.get("evento_ordem") is not None else 999,
            )
        )
    return result


def _temporal_profile(
    history: list[dict], team_id: int, timeline: dict
) -> dict:
    covered_ids = set(timeline["covered_match_ids"])
    events_by_match = _events_by_match(timeline)
    scored = {label: 0 for label in TIME_BINS}
    conceded = {label: 0 for label in TIME_BINS}
    scored_matches = {label: set() for label in TIME_BINS}
    conceded_matches = {label: set() for label in TIME_BINS}
    first_goal_minutes = []
    covered_matches = 0

    for match in history:
        match_id = int(match["id_api"])
        if match_id not in covered_ids:
            continue
        covered_matches += 1
        team_side = "HOME" if match["time_casa_id"] == team_id else "AWAY"
        events = events_by_match.get(match_id, [])
        valid_minutes = [
            int(event["minuto"])
            for event in events
            if event.get("minuto") is not None
        ]
        if valid_minutes:
            first_goal_minutes.append(min(valid_minutes))
        for event in events:
            bucket = _time_bin(event)
            if bucket is None:
                continue
            if event.get("lado") == team_side:
                scored[bucket] += 1
                scored_matches[bucket].add(match_id)
            else:
                conceded[bucket] += 1
                conceded_matches[bucket].add(match_id)

    total_scored = sum(scored.values())
    total_conceded = sum(conceded.values())
    bins = []
    for label in TIME_BINS:
        bins.append(
            {
                "period": label,
                "scored": scored[label],
                "conceded": conceded[label],
                "scored_share": round(scored[label] / total_scored * 100, 1) if total_scored else 0,
                "conceded_share": round(conceded[label] / total_conceded * 100, 1) if total_conceded else 0,
                "matches_scored": len(scored_matches[label]),
                "matches_conceded": len(conceded_matches[label]),
                "scored_match_rate": round(len(scored_matches[label]) / covered_matches * 100, 1) if covered_matches else 0,
                "conceded_match_rate": round(len(conceded_matches[label]) / covered_matches * 100, 1) if covered_matches else 0,
            }
        )
    first_half_goal_matches = set().union(
        *(scored_matches[label] | conceded_matches[label] for label in TIME_BINS[:3])
    )
    return {
        "available": covered_matches > 0,
        "sample_matches": len(history),
        "covered_matches": covered_matches,
        "coverage": round(covered_matches / len(history) * 100, 1) if history else 0,
        "total_goals_scored": total_scored,
        "total_goals_conceded": total_conceded,
        "average_first_goal_minute": round(sum(first_goal_minutes) / len(first_goal_minutes), 1) if first_goal_minutes else None,
        "first_half_any_goal_rate": round(len(first_half_goal_matches) / covered_matches * 100, 1) if covered_matches else 0,
        "after_75": {
            "goals_scored": scored["76-90+"],
            "goals_conceded": conceded["76-90+"],
            "matches_scored": len(scored_matches["76-90+"]),
            "matches_conceded": len(conceded_matches["76-90+"]),
            "scored_match_rate": round(len(scored_matches["76-90+"]) / covered_matches * 100, 1) if covered_matches else 0,
            "conceded_match_rate": round(len(conceded_matches["76-90+"]) / covered_matches * 100, 1) if covered_matches else 0,
        },
        "bins": bins,
    }


def _first_goal_impact(
    history: list[dict], team_id: int, timeline: dict
) -> dict:
    covered_ids = set(timeline["covered_match_ids"])
    events_by_match = _events_by_match(timeline)
    scored_first = won_after_scoring = 0
    conceded_first = recovered_after_conceding = 0
    matches_with_first_goal = 0
    for match in history:
        match_id = int(match["id_api"])
        if match_id not in covered_ids:
            continue
        events = events_by_match.get(match_id, [])
        if not events:
            continue
        matches_with_first_goal += 1
        team_side = "HOME" if match["time_casa_id"] == team_id else "AWAY"
        if events[0].get("lado") == team_side:
            scored_first += 1
            won_after_scoring += match["result"] == "W"
        else:
            conceded_first += 1
            recovered_after_conceding += match["result"] in {"W", "D"}
    return {
        "available": matches_with_first_goal > 0,
        "sample_matches": len(history),
        "covered_matches": len(set(int(match["id_api"]) for match in history) & covered_ids),
        "matches_with_first_goal": matches_with_first_goal,
        "scored_first": scored_first,
        "wins_after_scoring_first": won_after_scoring,
        "conservation_rate": round(won_after_scoring / scored_first * 100, 1) if scored_first else None,
        "conceded_first": conceded_first,
        "draws_or_wins_after_conceding_first": recovered_after_conceding,
        "comeback_rate": round(recovered_after_conceding / conceded_first * 100, 1) if conceded_first else None,
    }


def _clean_sheet_split(history: list[dict], venue: str | None = None) -> dict:
    matches = [match for match in history if venue is None or match["venue"] == venue]
    clean_sheets = sum(int(match["goals_against"]) == 0 for match in matches)
    return {
        "matches": len(matches),
        "clean_sheets": clean_sheets,
        "percentage": round(clean_sheets / len(matches) * 100, 1) if matches else None,
    }


def _trading_metrics(history: list[dict], temporal: dict) -> dict:
    btts = sum(
        int(match["goals_for"]) > 0 and int(match["goals_against"]) > 0
        for match in history
    )
    failed_to_score = sum(int(match["goals_for"]) == 0 for match in history)
    return {
        "sample_matches": len(history),
        "btts": {
            "matches": btts,
            "percentage": round(btts / len(history) * 100, 1) if history else None,
        },
        "failed_to_score": {
            "matches": failed_to_score,
            "percentage": round(failed_to_score / len(history) * 100, 1) if history else None,
        },
        "clean_sheet": {
            "overall": _clean_sheet_split(history),
            "home": _clean_sheet_split(history, "home"),
            "away": _clean_sheet_split(history, "away"),
        },
        "average_first_goal_minute": temporal["average_first_goal_minute"],
        "first_half_any_goal_rate": temporal["first_half_any_goal_rate"],
        "goals_after_75": temporal["after_75"],
        "temporal_data_coverage": temporal["coverage"],
    }


def _standing_for(standings: list[dict], team_id: int) -> dict | None:
    for row in standings:
        value = row.get("time_id")
        if value is not None and int(value) == team_id:
            return {
                "position": row.get("position"),
                "played": row.get("played"),
                "points": row.get("points"),
                "goal_difference": row.get("goal_difference"),
            }
    return None


def _intelligent_insights(
    match: dict,
    prediction: dict | None,
    home_history: list[dict],
    away_history: list[dict],
    home_venue_history: list[dict],
    away_venue_history: list[dict],
    home_temporal: dict,
    away_temporal: dict,
    home_first_goal: dict,
    away_first_goal: dict,
    standings: list[dict],
    covered_match_ids: list[int],
    supports_minutes: bool,
) -> dict:
    home_id = int(match["time_casa_id"])
    away_id = int(match["time_fora_id"])
    home_standing = _standing_for(standings, home_id)
    away_standing = _standing_for(standings, away_id)

    favorite_side = None
    if prediction:
        favorite_side = "home" if prediction["home"] >= prediction["away"] else "away"
    favorite_name = match[f"time_{'casa' if favorite_side == 'home' else 'fora'}"] if favorite_side else None
    favorite_probability = prediction[favorite_side] if prediction and favorite_side else None
    favorite_history = home_history if favorite_side == "home" else away_history
    favorite_temporal = home_temporal if favorite_side == "home" else away_temporal
    favorite_first_goal = home_first_goal if favorite_side == "home" else away_first_goal
    covered_ids = set(covered_match_ids)
    missing_match_ids = [
        int(item["id_api"])
        for item in favorite_history
        if int(item["id_api"]) not in covered_ids
    ] if favorite_side else []

    items = []
    first_goal_total = favorite_first_goal["matches_with_first_goal"] if favorite_side else 0
    if first_goal_total:
        first_goal_rate = round(favorite_first_goal["scored_first"] / first_goal_total * 100, 1)
        if first_goal_rate >= 65:
            tone, title = "positive", "Boa frequência de abrir o placar"
        elif first_goal_rate >= 40:
            tone, title = "warning", "Primeiro gol sem vantagem clara"
        else:
            tone, title = "negative", "Baixa frequência de abrir o placar"
        items.append({
            "id": "first_goal",
            "tone": tone,
            "title": title,
            "detail": (
                f"{favorite_name} marcou primeiro em {favorite_first_goal['scored_first']} "
                f"de {first_goal_total} jogos com gol e eventos completos."
            ),
            "value": first_goal_rate,
            "unit": "%",
            "sample_size": first_goal_total,
            "available": True,
        })
    else:
        items.append({
            "id": "first_goal",
            "tone": "neutral",
            "title": "Primeiro gol ainda sem cobertura" if supports_minutes else "Primeiro gol indisponível nesta fonte",
            "detail": (
                "Colete os minutos dos jogos anteriores para medir quem costuma abrir o placar."
                if supports_minutes
                else "A fonte selecionada não fornece eventos de gol por minuto."
            ),
            "value": None,
            "unit": "%",
            "sample_size": 0,
            "available": False,
        })

    conceded_first = favorite_first_goal["conceded_first"] if favorite_side else 0
    comeback_rate = favorite_first_goal.get("comeback_rate") if favorite_side else None
    if conceded_first and comeback_rate is not None:
        if comeback_rate >= 60:
            tone, title = "positive", "Boa reação quando sai perdendo"
        elif comeback_rate >= 35:
            tone, title = "warning", "Reação moderada ao sofrer primeiro"
        else:
            tone, title = "negative", "Dificuldade para reagir ao primeiro gol"
        recovered = favorite_first_goal["draws_or_wins_after_conceding_first"]
        items.append({
            "id": "comeback",
            "tone": tone,
            "title": title,
            "detail": f"{favorite_name} evitou a derrota em {recovered} de {conceded_first} jogos após sofrer o primeiro gol.",
            "value": comeback_rate,
            "unit": "%",
            "sample_size": conceded_first,
            "available": True,
        })
    else:
        items.append({
            "id": "comeback",
            "tone": "neutral",
            "title": "Reação sem amostra suficiente",
            "detail": "Não há jogos cobertos suficientes em que o favorito tenha sofrido o primeiro gol.",
            "value": None,
            "unit": "%",
            "sample_size": conceded_first,
            "available": False,
        })

    late = favorite_temporal.get("after_75", {}) if favorite_side else {}
    late_rate = late.get("scored_match_rate")
    covered_matches = favorite_temporal.get("covered_matches", 0) if favorite_side else 0
    if covered_matches:
        if late_rate >= 40:
            tone, title = "positive", "Forte tendência de gol no fim"
        elif late_rate >= 20:
            tone, title = "warning", "Atenção aos gols depois dos 75 minutos"
        else:
            tone, title = "negative", "Poucos gols do favorito no fim"
        items.append({
            "id": "late_goal",
            "tone": tone,
            "title": title,
            "detail": (
                f"{favorite_name} marcou após os 75 minutos em {late.get('matches_scored', 0)} "
                f"de {covered_matches} jogos com cobertura temporal."
            ),
            "value": late_rate,
            "unit": "%",
            "sample_size": covered_matches,
            "available": True,
        })
    else:
        items.append({
            "id": "late_goal",
            "tone": "neutral",
            "title": "Gols no fim ainda sem cobertura",
            "detail": "Os eventos por minuto dos jogos anteriores ainda não estão completos.",
            "value": None,
            "unit": "%",
            "sample_size": 0,
            "available": False,
        })

    away_venue = _summary(away_venue_history)
    away_position = away_standing.get("position") if away_standing else None
    position_text = f" é o {away_position}º colocado e" if away_position else ""
    if away_venue["matches"] >= 3:
        if away_venue["performance"] >= 60:
            tone = "positive"
        elif away_venue["performance"] >= 40:
            tone = "warning"
        else:
            tone = "negative"
        items.append({
            "id": "away_form",
            "tone": tone,
            "title": f"Visitante{position_text} joga fora de casa" if away_position else "Desempenho recente do visitante fora",
            "detail": (
                f"{match['time_fora']} tem {away_venue['performance']}% de aproveitamento "
                f"nos últimos {away_venue['matches']} jogos como visitante."
            ),
            "value": away_venue["performance"],
            "unit": "%",
            "sample_size": away_venue["matches"],
            "available": True,
        })
    else:
        items.append({
            "id": "away_form",
            "tone": "neutral",
            "title": "Poucos jogos recentes como visitante",
            "detail": f"{match['time_fora']} possui menos de 3 jogos fora antes desta partida.",
            "value": away_venue["performance"] if away_venue["matches"] else None,
            "unit": "%",
            "sample_size": away_venue["matches"],
            "available": False,
        })

    return {
        "method": "rule_based_historical_signals",
        "favorite": {
            "side": favorite_side,
            "team": favorite_name,
            "probability": favorite_probability,
            "sample_size": len(favorite_history) if favorite_side else 0,
        },
        "standings": {
            "season": match.get("temporada"),
            "home": home_standing,
            "away": away_standing,
        },
        "venue_form": {
            "home": _summary(home_venue_history),
            "away": away_venue,
        },
        "minute_coverage": {
            "supported": supports_minutes,
            "covered": len(favorite_history) - len(missing_match_ids) if favorite_side else 0,
            "sample_size": len(favorite_history) if favorite_side else 0,
            "missing_match_ids": missing_match_ids,
        },
        "items": items,
    }


def _xg_window(history: list[dict], team_id: int, xg_map: dict, limit: int) -> dict | None:
    rows = [match for match in history[:limit] if int(match["id_api"]) in xg_map]
    if not rows:
        return None
    actual_for = actual_against = expected_for = expected_against = 0.0
    for match in rows:
        values = xg_map[int(match["id_api"])]
        at_home = match["time_casa_id"] == team_id
        actual_for += int(match["goals_for"])
        actual_against += int(match["goals_against"])
        expected_for += values["home"] if at_home else values["away"]
        expected_against += values["away"] if at_home else values["home"]
    attacking_delta = actual_for - expected_for
    defensive_delta = actual_against - expected_against
    per_match_delta = attacking_delta / len(rows)
    if per_match_delta > 0.35:
        signal = "overperforming"
    elif per_match_delta < -0.35:
        signal = "underperforming"
    else:
        signal = "aligned"
    return {
        "matches": len(rows),
        "requested_matches": min(limit, len(history)),
        "coverage": round(len(rows) / min(limit, len(history)) * 100, 1) if history else 0,
        "goals_scored": actual_for,
        "xg_for": round(expected_for, 2),
        "attacking_delta": round(attacking_delta, 2),
        "goals_conceded": actual_against,
        "xg_against": round(expected_against, 2),
        "defensive_delta": round(defensive_delta, 2),
        "finishing_signal": signal,
    }


def _xg_regression(history: list[dict], team_id: int, xg_map: dict) -> dict:
    last_5 = _xg_window(history, team_id, xg_map, 5)
    last_10 = _xg_window(history, team_id, xg_map, 10)
    if not last_10:
        return {
            "available": False,
            "reason": "A fonte não possui xG real armazenado para estes jogos.",
            "required_fields": ["partidas_metricas.xg_casa", "partidas_metricas.xg_fora"],
        }
    return {"available": True, "last_5": last_5, "last_10": last_10}


def match_analysis(source: str, match_id: int) -> dict[str, Any]:
    match = database.get_match(source, match_id)
    if not match:
        raise database.DataError(f"Partida {match_id} não encontrada")
    if match.get("time_casa_id") is None or match.get("time_fora_id") is None:
        raise database.DataError("Partida sem identificadores dos times")
    home_id = int(match["time_casa_id"])
    away_id = int(match["time_fora_id"])
    kickoff = match["data_partida"]
    home_history = _perspective(
        database.team_history(source, home_id, kickoff, 10), home_id
    )
    away_history = _perspective(
        database.team_history(source, away_id, kickoff, 10), away_id
    )
    home_venue_history = _perspective(
        database.team_history(source, home_id, kickoff, 10, venue="home"), home_id
    )
    away_venue_history = _perspective(
        database.team_history(source, away_id, kickoff, 10, venue="away"), away_id
    )
    h2h = database.head_to_head(source, home_id, away_id, kickoff, 10)
    prediction = _poisson(home_history, away_history, h2h, home_id, away_id)
    config = database.source_config(source)
    history_ids = [
        int(item["id_api"]) for item in [*home_history, *away_history]
    ]
    timeline = database.goal_timeline(source, history_ids)
    xg_map = database.xg_values(source, history_ids)
    home_temporal = _temporal_profile(home_history, home_id, timeline)
    away_temporal = _temporal_profile(away_history, away_id, timeline)
    home_first_goal = _first_goal_impact(home_history, home_id, timeline)
    away_first_goal = _first_goal_impact(away_history, away_id, timeline)
    standings = database.league_standings_before(
        source,
        match["liga_id"],
        kickoff,
        match.get("temporada"),
    )
    return {
        "match": match,
        "prediction": prediction,
        "home": {"summary": _summary(home_history), "history": home_history},
        "away": {"summary": _summary(away_history), "history": away_history},
        "head_to_head": h2h,
        "lay_01": _lay_analysis(prediction, home_history, config.supports_minutes),
        "insights": _intelligent_insights(
            match,
            prediction,
            home_history,
            away_history,
            home_venue_history,
            away_venue_history,
            home_temporal,
            away_temporal,
            home_first_goal,
            away_first_goal,
            standings,
            timeline["covered_match_ids"],
            config.supports_minutes,
        ),
        "advanced": {
            "temporal_goals": {
                "home": home_temporal,
                "away": away_temporal,
            },
            "first_goal_impact": {
                "home": home_first_goal,
                "away": away_first_goal,
            },
            "trading_metrics": {
                "home": _trading_metrics(home_history, home_temporal),
                "away": _trading_metrics(away_history, away_temporal),
            },
            "xg_regression": {
                "home": _xg_regression(home_history, home_id, xg_map),
                "away": _xg_regression(away_history, away_id, xg_map),
            },
        },
        "disclaimer": "Estimativa estatística baseada no histórico disponível; não é garantia de resultado.",
    }


def _market_price(prediction: dict, market: str, selection: str) -> dict:
    market = market.strip().casefold()
    selection = selection.strip().casefold().replace(",", ".")
    markets = prediction["markets"]
    if market in {"match_odds", "btts", "clean_sheet", "team_to_score"}:
        try:
            return markets[market][selection]
        except KeyError as exc:
            raise ValueError(f"Seleção inválida para {market}: {selection}") from exc
    if market == "total_goals":
        match = re.fullmatch(r"(over|under)_([0-4]\.5)", selection)
        if not match:
            raise ValueError(
                "Total inválido. Use, por exemplo, over_2.5 ou under_2.5"
            )
        side, line = match.groups()
        return markets["total_goals"][line][side]
    if market == "exact_score":
        match = re.fullmatch(r"([0-8])[-x:]([0-8])", selection)
        if not match:
            raise ValueError("Placar inválido. Use o formato 1-0, entre 0-0 e 8-8")
        home_goals, away_goals = map(int, match.groups())
        for score in prediction["score_matrix"]:
            if score["home_goals"] == home_goals and score["away_goals"] == away_goals:
                return score
    raise ValueError(f"Mercado não suportado: {market}")


def value_analysis(
    source: str, match_id: int, offers: list[dict]
) -> dict[str, Any]:
    analysis = match_analysis(source, match_id)
    prediction = analysis["prediction"]
    if not prediction:
        raise database.DataError("Histórico insuficiente para precificar a partida")
    results = []
    for offer in offers:
        price = _market_price(
            prediction, str(offer["market"]), str(offer["selection"])
        )
        offered_odds = float(offer["odds"])
        model_probability = float(price["probability"])
        implied_probability = 100 / offered_odds
        expected_value = (model_probability / 100 * offered_odds - 1) * 100
        results.append(
            {
                "market": offer["market"],
                "selection": offer["selection"],
                "offered_odds": offered_odds,
                "fair_odds": price["fair_odds"],
                "model_probability": round(model_probability, 2),
                "implied_probability": round(implied_probability, 2),
                "edge_percentage_points": round(model_probability - implied_probability, 2),
                "expected_value_percentage": round(expected_value, 2),
                "has_value": expected_value > 0,
            }
        )
    return {
        "match": analysis["match"],
        "offers": results,
        "method": "EV = (probabilidade_modelo × odd_oferecida - 1) × 100",
        "disclaimer": (
            "Valor positivo depende da qualidade e cobertura dos dados; "
            "não representa garantia de lucro."
        ),
    }
