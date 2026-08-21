from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from . import database
from .config import DATA_DIR, SOURCES


Progress = Callable[[int, int, str], None]
MODEL_DIR = Path(os.getenv("TRADEFOT_MODEL_DIR", DATA_DIR / "models")).resolve()
MODEL_DIR.mkdir(parents=True, exist_ok=True)
FEATURE_VERSION = 1
MIN_MATCHES = max(300, int(os.getenv("TRADEFOT_ML_MIN_MATCHES", "500")))
MAX_EPOCHS = max(10, int(os.getenv("TRADEFOT_ML_EPOCHS", "60")))
SEED = 20260820
LABELS = ("home", "draw", "away")
_locks = defaultdict(threading.RLock)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _paths(source: str) -> tuple[Path, Path]:
    database.source_config(source)
    return MODEL_DIR / f"{source}.npz", MODEL_DIR / f"{source}.json"


def _parse_date(value: Any, date_kind: str) -> datetime:
    if date_kind == "epoch":
        return datetime.fromtimestamp(int(value), timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _finished_rows(source: str, before: datetime | None = None) -> list[dict]:
    config = database.source_config(source)
    cutoff = (before or datetime.now(timezone.utc)).astimezone(timezone.utc)
    with database.connect(source) as conn:
        columns = database._columns(conn, "partidas")
        league_column = config.league_column
        status_filter = ""
        if "status" in columns:
            status_filter = "AND upper(COALESCE(status, '')) NOT IN ('CANCELLED', 'CANCELED')"
        rows = conn.execute(
            f"""
            SELECT id_api, CAST({league_column} AS TEXT) AS league_id,
                   data_partida, time_casa_id, time_fora_id,
                   gols_casa, gols_fora
            FROM partidas
            WHERE gols_casa IS NOT NULL AND gols_fora IS NOT NULL
              AND time_casa_id IS NOT NULL AND time_fora_id IS NOT NULL
              {status_filter}
            ORDER BY data_partida ASC, id_api ASC
            """
        ).fetchall()
    result = []
    for row in rows:
        try:
            played_at = _parse_date(row["data_partida"], config.date_kind)
            home_goals = int(row["gols_casa"])
            away_goals = int(row["gols_fora"])
        except (TypeError, ValueError, OverflowError):
            continue
        if played_at > cutoff or min(home_goals, away_goals) < 0:
            continue
        result.append(
            {
                "id": int(row["id_api"]),
                "league": str(row["league_id"]),
                "date": played_at,
                "home": int(row["time_casa_id"]),
                "away": int(row["time_fora_id"]),
                "hg": home_goals,
                "ag": away_goals,
            }
        )
    result.sort(key=lambda item: (item["date"], item["id"]))
    return result


def _snapshot(rows: list[dict]) -> dict:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(
            f"{row['id']}|{row['date'].isoformat()}|{row['hg']}|{row['ag']};".encode()
        )
    return {
        "finished_matches": len(rows),
        "latest_result_at": rows[-1]["date"].isoformat().replace("+00:00", "Z") if rows else None,
        "goals": sum(row["hg"] + row["ag"] for row in rows),
        "fingerprint": digest.hexdigest(),
    }


def _blank_state() -> dict:
    return {
        "overall": defaultdict(lambda: deque(maxlen=10)),
        "home": defaultdict(lambda: deque(maxlen=10)),
        "away": defaultdict(lambda: deque(maxlen=10)),
        "elo": defaultdict(lambda: 1500.0),
        "last_date": {},
        "league": defaultdict(lambda: {"n": 0, "h": 0, "d": 0, "a": 0, "hg": 0, "ag": 0, "btts": 0}),
        "h2h": defaultdict(lambda: deque(maxlen=5)),
    }


def _record_summary(records: deque, default_gf: float = 1.25, default_ga: float = 1.25) -> list[float]:
    n = len(records)
    if not n:
        return [0.0, 1.0, 0.33, 0.29, default_gf, default_ga, 0.48, 0.28]
    points = sum(item[2] for item in records)
    wins = sum(item[2] == 3 for item in records)
    draws = sum(item[2] == 1 for item in records)
    gf = sum(item[0] for item in records)
    ga = sum(item[1] for item in records)
    return [
        n / 10,
        points / n,
        wins / n,
        draws / n,
        gf / n,
        ga / n,
        sum(item[0] > 0 and item[1] > 0 for item in records) / n,
        sum(item[1] == 0 for item in records) / n,
    ]


def _h2h_summary(records: deque, home_id: int) -> list[float]:
    if not records:
        return [0.0, 1.0, 0.33, 0.29, 1.25, 1.25, 0.48, 0.28]
    viewed = deque(maxlen=10)
    for item in records:
        if item[0] == home_id:
            gf, ga = item[2], item[3]
        else:
            gf, ga = item[3], item[2]
        points = 3 if gf > ga else 1 if gf == ga else 0
        viewed.append((gf, ga, points))
    summary = _record_summary(viewed)
    summary[0] = len(records) / 5
    return summary


def _league_summary(item: dict) -> list[float]:
    n = item["n"]
    if not n:
        return [0.0, 0.43, 0.29, 0.28, 1.45, 1.15, 0.48]
    return [
        min(math.log1p(n) / math.log1p(5000), 1.0),
        item["h"] / n,
        item["d"] / n,
        item["a"] / n,
        item["hg"] / n,
        item["ag"] / n,
        item["btts"] / n,
    ]


def _rest_days(state: dict, team_id: int, played_at: datetime) -> float:
    previous = state["last_date"].get(team_id)
    if previous is None:
        return 14.0
    return min(max((played_at - previous).total_seconds() / 86400, 0), 30)


def _features(state: dict, match: dict) -> np.ndarray:
    home_id, away_id = match["home"], match["away"]
    league = state["league"][match["league"]]
    league_values = _league_summary(league)
    default_home_goals, default_away_goals = league_values[4], league_values[5]
    pair = tuple(sorted((home_id, away_id)))
    elo_home, elo_away = state["elo"][home_id], state["elo"][away_id]
    values = (
        _record_summary(state["overall"][home_id], default_home_goals, default_away_goals)
        + _record_summary(state["home"][home_id], default_home_goals, default_away_goals)
        + _record_summary(state["overall"][away_id], default_away_goals, default_home_goals)
        + _record_summary(state["away"][away_id], default_away_goals, default_home_goals)
        + [elo_home / 2000, elo_away / 2000, (elo_home - elo_away + 80) / 400]
        + _h2h_summary(state["h2h"][pair], home_id)
        + league_values
        + [
            _rest_days(state, home_id, match["date"]) / 30,
            _rest_days(state, away_id, match["date"]) / 30,
        ]
    )
    return np.asarray(values, dtype=np.float64)


def _target(match: dict) -> int:
    return 0 if match["hg"] > match["ag"] else 1 if match["hg"] == match["ag"] else 2


def _update_state(state: dict, match: dict) -> None:
    home_id, away_id = match["home"], match["away"]
    hg, ag = match["hg"], match["ag"]
    home_points = 3 if hg > ag else 1 if hg == ag else 0
    away_points = 3 if ag > hg else 1 if hg == ag else 0
    home_record, away_record = (hg, ag, home_points), (ag, hg, away_points)
    state["overall"][home_id].append(home_record)
    state["overall"][away_id].append(away_record)
    state["home"][home_id].append(home_record)
    state["away"][away_id].append(away_record)

    home_elo, away_elo = state["elo"][home_id], state["elo"][away_id]
    expected = 1 / (1 + 10 ** ((away_elo - home_elo - 80) / 400))
    actual = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
    change = 24 * (actual - expected)
    state["elo"][home_id] = home_elo + change
    state["elo"][away_id] = away_elo - change
    state["last_date"][home_id] = match["date"]
    state["last_date"][away_id] = match["date"]

    league = state["league"][match["league"]]
    league["n"] += 1
    league["h"] += hg > ag
    league["d"] += hg == ag
    league["a"] += ag > hg
    league["hg"] += hg
    league["ag"] += ag
    league["btts"] += hg > 0 and ag > 0
    state["h2h"][tuple(sorted((home_id, away_id)))].append((home_id, away_id, hg, ag))


def _training_matrix(rows: list[dict], progress: Progress | None = None) -> tuple[np.ndarray, np.ndarray]:
    state = _blank_state()
    x, y = [], []
    for index, match in enumerate(rows, start=1):
        x.append(_features(state, match))
        y.append(_target(match))
        _update_state(state, match)
        if progress and index % 5000 == 0:
            progress(1, MAX_EPOCHS + 3, f"Preparando histórico: {index}/{len(rows)}")
    return np.vstack(x), np.asarray(y, dtype=np.int64)


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / np.sum(exp, axis=1, keepdims=True)


def _forward(x: np.ndarray, weights: dict[str, np.ndarray]) -> tuple[np.ndarray, tuple]:
    z1 = x @ weights["w1"] + weights["b1"]
    a1 = np.maximum(z1, 0)
    z2 = a1 @ weights["w2"] + weights["b2"]
    a2 = np.maximum(z2, 0)
    logits = a2 @ weights["w3"] + weights["b3"]
    return logits, (x, z1, a1, z2, a2)


def _log_loss(y: np.ndarray, probabilities: np.ndarray) -> float:
    return float(-np.mean(np.log(np.clip(probabilities[np.arange(len(y)), y], 1e-12, 1))))


def _metrics(y: np.ndarray, probabilities: np.ndarray) -> dict:
    one_hot = np.eye(3)[y]
    return {
        "matches": int(len(y)),
        "accuracy": round(float(np.mean(np.argmax(probabilities, axis=1) == y)) * 100, 2),
        "log_loss": round(_log_loss(y, probabilities), 5),
        "brier_score": round(float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1))), 5),
    }


def _poisson_baseline(features: np.ndarray) -> np.ndarray:
    """Baseline sem vazamento usando médias pré-jogo presentes nas features."""
    result = []
    for row in features:
        expected_home = float(np.clip((row[12] + row[29]) / 2 * 1.08, 0.15, 4.0))
        expected_away = float(np.clip((row[28] + row[13]) / 2 * 0.96, 0.15, 4.0))
        probabilities = np.zeros(3)
        for home_goals in range(11):
            home_probability = math.exp(-expected_home) * expected_home**home_goals / math.factorial(home_goals)
            for away_goals in range(11):
                away_probability = math.exp(-expected_away) * expected_away**away_goals / math.factorial(away_goals)
                outcome = 0 if home_goals > away_goals else 1 if home_goals == away_goals else 2
                probabilities[outcome] += home_probability * away_probability
        result.append(probabilities / probabilities.sum())
    return np.asarray(result)


def _fit_network(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    progress: Progress | None,
) -> tuple[dict[str, np.ndarray], int, float]:
    rng = np.random.default_rng(SEED)
    input_size = x_train.shape[1]
    weights = {
        "w1": rng.normal(0, math.sqrt(2 / input_size), (input_size, 48)),
        "b1": np.zeros(48),
        "w2": rng.normal(0, math.sqrt(2 / 48), (48, 24)),
        "b2": np.zeros(24),
        "w3": rng.normal(0, math.sqrt(2 / 24), (24, 3)),
        "b3": np.zeros(3),
    }
    moments = {name: np.zeros_like(value) for name, value in weights.items()}
    velocities = {name: np.zeros_like(value) for name, value in weights.items()}
    best = {name: value.copy() for name, value in weights.items()}
    best_loss, best_epoch, patience, step = float("inf"), 0, 0, 0
    batch_size, learning_rate = 256, 0.0015

    for epoch in range(1, MAX_EPOCHS + 1):
        for start in range(0, len(x_train), batch_size):
            indices = rng.permutation(len(x_train)) if start == 0 else indices
            batch = indices[start : start + batch_size]
            xb, yb = x_train[batch], y_train[batch]
            logits, cache = _forward(xb, weights)
            probs = _softmax(logits)
            grad_logits = probs
            grad_logits[np.arange(len(yb)), yb] -= 1
            grad_logits /= len(yb)
            x0, z1, a1, z2, a2 = cache
            gradients = {
                "w3": a2.T @ grad_logits + 1e-4 * weights["w3"],
                "b3": np.sum(grad_logits, axis=0),
            }
            grad_a2 = grad_logits @ weights["w3"].T
            grad_z2 = grad_a2 * (z2 > 0)
            gradients["w2"] = a1.T @ grad_z2 + 1e-4 * weights["w2"]
            gradients["b2"] = np.sum(grad_z2, axis=0)
            grad_a1 = grad_z2 @ weights["w2"].T
            grad_z1 = grad_a1 * (z1 > 0)
            gradients["w1"] = x0.T @ grad_z1 + 1e-4 * weights["w1"]
            gradients["b1"] = np.sum(grad_z1, axis=0)
            step += 1
            for name in weights:
                moments[name] = 0.9 * moments[name] + 0.1 * gradients[name]
                velocities[name] = 0.999 * velocities[name] + 0.001 * gradients[name] ** 2
                m_hat = moments[name] / (1 - 0.9**step)
                v_hat = velocities[name] / (1 - 0.999**step)
                weights[name] -= learning_rate * m_hat / (np.sqrt(v_hat) + 1e-8)

        val_loss = _log_loss(y_val, _softmax(_forward(x_val, weights)[0]))
        if progress:
            progress(epoch + 1, MAX_EPOCHS + 3, f"Treinando rede: época {epoch}, validação {val_loss:.4f}")
        if val_loss < best_loss - 1e-4:
            best_loss, best_epoch = val_loss, epoch
            best = {name: value.copy() for name, value in weights.items()}
            patience = 0
        else:
            patience += 1
            if patience >= 10:
                break
    return best, best_epoch, best_loss


def _temperature(logits: np.ndarray, y: np.ndarray) -> float:
    candidates = np.linspace(0.55, 3.0, 99)
    losses = [_log_loss(y, _softmax(logits / value)) for value in candidates]
    return float(candidates[int(np.argmin(losses))])


def _write_model(source: str, weights: dict, mean: np.ndarray, scale: np.ndarray, temperature: float, metadata: dict) -> None:
    model_path, metadata_path = _paths(source)
    model_temp = model_path.with_name(model_path.name + ".tmp.npz")
    metadata_temp = metadata_path.with_name(metadata_path.name + ".tmp")
    np.savez_compressed(
        model_temp,
        **weights,
        mean=mean,
        scale=scale,
        temperature=np.asarray([temperature]),
        feature_version=np.asarray([FEATURE_VERSION]),
    )
    metadata_temp.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(model_temp, model_path)
    os.replace(metadata_temp, metadata_path)


def _read_metadata(source: str) -> dict | None:
    _, path = _paths(source)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def train(source: str, progress: Progress | None = None, force: bool = True) -> dict:
    database.source_config(source)
    with _locks[source]:
        if progress:
            progress(0, MAX_EPOCHS + 3, "Lendo resultados históricos")
        rows = _finished_rows(source)
        snapshot = _snapshot(rows)
        previous = _read_metadata(source)
        if not force and previous and previous.get("dataset", {}).get("fingerprint") == snapshot["fingerprint"]:
            return {"trained": False, "reason": "dataset_unchanged", "model": previous}
        if len(rows) < MIN_MATCHES:
            raise ValueError(f"São necessários ao menos {MIN_MATCHES} resultados; encontrados {len(rows)}")

        x, y = _training_matrix(rows, progress)
        train_end = int(len(x) * 0.70)
        validation_end = int(len(x) * 0.85)
        if min(train_end, validation_end - train_end, len(x) - validation_end) < 50:
            raise ValueError("Histórico insuficiente para divisão temporal de treino, validação e teste")
        mean = x[:train_end].mean(axis=0)
        scale = x[:train_end].std(axis=0)
        scale[scale < 1e-8] = 1
        normalized = (x - mean) / scale
        weights, best_epoch, validation_loss = _fit_network(
            normalized[:train_end], y[:train_end],
            normalized[train_end:validation_end], y[train_end:validation_end], progress,
        )
        validation_logits = _forward(normalized[train_end:validation_end], weights)[0]
        temperature = _temperature(validation_logits, y[train_end:validation_end])
        train_probs = _softmax(_forward(normalized[:train_end], weights)[0] / temperature)
        validation_probs = _softmax(validation_logits / temperature)
        test_probs = _softmax(_forward(normalized[validation_end:], weights)[0] / temperature)
        class_rates = np.bincount(y[:train_end], minlength=3) / train_end
        baseline = np.tile(class_rates, (len(y) - validation_end, 1))
        poisson_baseline = _poisson_baseline(x[validation_end:])
        metadata = {
            "source": source,
            "model_type": "MLP neural network (48x24, ReLU, Softmax)",
            "feature_version": FEATURE_VERSION,
            "features": int(x.shape[1]),
            "trained_at": _now(),
            "best_epoch": best_epoch,
            "temperature": round(temperature, 4),
            "dataset": snapshot,
            "split": {"method": "chronological", "train": train_end, "validation": validation_end - train_end, "test": len(x) - validation_end},
            "metrics": {
                "train": _metrics(y[:train_end], train_probs),
                "validation": _metrics(y[train_end:validation_end], validation_probs),
                "test": _metrics(y[validation_end:], test_probs),
                "test_frequency_baseline": _metrics(y[validation_end:], baseline),
                "test_poisson_baseline": _metrics(y[validation_end:], poisson_baseline),
                "validation_loss_before_calibration": round(validation_loss, 5),
            },
        }
        _write_model(source, weights, mean, scale, temperature, metadata)
        if progress:
            progress(MAX_EPOCHS + 3, MAX_EPOCHS + 3, "Modelo validado e salvo")
        return {"trained": True, "reason": "forced" if force else "new_results", "model": metadata}


def status(source: str) -> dict:
    metadata = _read_metadata(source)
    if not metadata:
        return {"source": source, "status": "not_trained", "minimum_matches": MIN_MATCHES}
    rows = _finished_rows(source)
    current = _snapshot(rows)
    trained = metadata.get("dataset", {})
    return {
        **metadata,
        "status": "ready" if trained.get("fingerprint") == current["fingerprint"] else "stale",
        "current_dataset": current,
    }


def needs_training(source: str) -> bool:
    try:
        return status(source).get("status") != "ready"
    except (database.DataError, OSError, ValueError):
        return False


def _load_model(source: str) -> tuple[dict[str, np.ndarray], np.ndarray, np.ndarray, float, dict]:
    model_path, _ = _paths(source)
    metadata = _read_metadata(source)
    if not metadata or not model_path.exists():
        raise database.DataError("Modelo neural ainda não foi treinado para esta fonte")
    with np.load(model_path, allow_pickle=False) as saved:
        version = int(saved["feature_version"][0])
        if version != FEATURE_VERSION:
            raise database.DataError("Modelo neural incompatível; execute um novo treinamento")
        weights = {name: saved[name] for name in ("w1", "b1", "w2", "b2", "w3", "b3")}
        mean, scale = saved["mean"], saved["scale"]
        temperature = float(saved["temperature"][0])
    return weights, mean, scale, temperature, metadata


def predict(source: str, match_id: int) -> dict:
    match = database.get_match(source, match_id)
    if not match:
        raise database.DataError("Partida não encontrada")
    if not match.get("data_partida"):
        raise database.DataError("Partida sem data válida")
    config = database.source_config(source)
    match_date = _parse_date(match["data_partida"], "iso")
    target = {
        "id": int(match["id_api"]),
        "league": str(match["liga_id"]),
        "date": match_date,
        "home": int(match["time_casa_id"]),
        "away": int(match["time_fora_id"]),
    }
    weights, mean, scale, temperature, metadata = _load_model(source)
    state = _blank_state()
    history = _finished_rows(source, before=match_date)
    for item in history:
        if item["date"] >= match_date or item["id"] == match_id:
            continue
        _update_state(state, item)
    raw_features = _features(state, target)
    logits, _ = _forward(((raw_features - mean) / scale)[None, :], weights)
    probabilities = _softmax(logits / temperature)[0]
    winner = int(np.argmax(probabilities))
    home_history = len(state["overall"][target["home"]])
    away_history = len(state["overall"][target["away"]])
    maximum = float(probabilities[winner])
    confidence = "high" if maximum >= 0.60 and min(home_history, away_history) >= 8 else "medium" if maximum >= 0.45 and min(home_history, away_history) >= 5 else "low"
    return {
        "available": True,
        "match_id": match_id,
        "source": source,
        "prediction": LABELS[winner],
        "predicted_team": match["time_casa"] if winner == 0 else None if winner == 1 else match["time_fora"],
        "confidence": confidence,
        "probabilities": {label: round(float(probabilities[index]) * 100, 2) for index, label in enumerate(LABELS)},
        "fair_odds": {label: round(1 / float(probabilities[index]), 3) for index, label in enumerate(LABELS)},
        "history_used": {"home": home_history, "away": away_history, "finished_before_match": len(history)},
        "model": {"type": metadata["model_type"], "trained_at": metadata["trained_at"], "test_metrics": metadata["metrics"]["test"]},
        "disclaimer": "Probabilidade estatística, não garantia de resultado ou lucro.",
    }


def auto_train_enabled() -> bool:
    return os.getenv("TRADEFOT_ML_AUTO_TRAIN", "true").strip().casefold() in {"1", "true", "yes", "sim"}


def train_stale_models(progress: Progress | None = None) -> dict:
    results = {}
    for source in SOURCES:
        try:
            results[source] = train(source, progress, force=False)
        except Exception as exc:
            results[source] = {"trained": False, "reason": "error", "error": str(exc)}
    return results
