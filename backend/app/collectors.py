from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

from .config import ROOT_DIR, SOURCES


Progress = Callable[[int, int, str], None]


def _run_subprocess(command: list[str], progress: Progress) -> tuple[list[str], int]:
    env = os.environ.copy()
    env.update(
        {
            "SOFASCORE_DB_PATH": str(SOURCES["sofascore"].path),
            "FOOTBALL_DATA_DB_PATH": str(SOURCES["football_data"].path),
            "ONEFOOTBALL_DB_PATH": str(SOURCES["onefootball"].path),
        }
    )
    process = subprocess.Popen(
        command,
        cwd=str(ROOT_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    lines: list[str] = []
    if process.stdout:
        for raw in process.stdout:
            line = raw.strip()
            if not line:
                continue
            lines.append(line)
            match = re.search(r"\[(\d+)\s*/\s*(\d+)\]\s*(.*)", line)
            if match:
                progress(int(match.group(1)), int(match.group(2)), match.group(3))
            else:
                progress(0, 0, line[-160:])
    return lines, process.wait()


def sync_source(source: str, scope: str, progress: Progress) -> dict:
    if source == "onefootball":
        import main3

        return main3.atualizar_dados(
            db_path=SOURCES[source].path,
            progresso=progress,
            full=scope == "all",
        )
    if source == "football_data":
        import main

        return main.atualizar_dados(
            db_path=SOURCES[source].path,
            progresso=progress,
        )
    if source == "sofascore":
        mode = "--full" if scope == "all" else "--update"
        lines, code = _run_subprocess(
            [sys.executable, "-u", str(ROOT_DIR / "main2.py"), mode], progress
        )
        if code:
            raise RuntimeError("\n".join(lines[-12:]) or "Falha no scraper SofaScore")
        return {
            "consultas": 1,
            "concluidas": 1,
            "recebidas": 0,
            "inseridas": 0,
            "atualizadas": 0,
            "erros": [],
            "log": lines[-20:],
        }
    raise ValueError(f"Fonte desconhecida: {source}")


def sync_and_train(source: str, scope: str, progress: Progress) -> dict:
    """Atualiza a fonte e incorpora resultados novos ao modelo neural."""
    from . import prediction_history

    progress(0, 0, "Congelando análises pré-jogo de hoje")
    try:
        snapshots_before = prediction_history.capture_today(source, progress)
    except Exception as exc:
        snapshots_before = {"captured": 0, "error": str(exc)}

    sync_result = sync_source(source, scope, progress)
    progress(0, 0, "Verificando se o modelo neural precisa ser atualizado")
    try:
        from . import neural_model

        model_result = neural_model.train(source, progress, force=False)
    except Exception as exc:
        # Uma indisponibilidade do modelo não invalida os dados já sincronizados.
        model_result = {"trained": False, "reason": "error", "error": str(exc)}
    progress(0, 0, "Registrando novos jogos pré-jogo de hoje")
    try:
        snapshots_after = prediction_history.capture_today(source, progress)
    except Exception as exc:
        snapshots_after = {"captured": 0, "error": str(exc)}
    return {
        "sync": sync_result,
        "neural_model": model_result,
        "analysis_snapshots": {
            "before_sync": snapshots_before,
            "after_sync": snapshots_after,
        },
    }


def collect_minutes(source: str, match_ids: list[int], progress: Progress) -> dict:
    ids = list(dict.fromkeys(int(value) for value in match_ids))
    if source == "onefootball":
        import main3

        return main3.coletar_minutos_gols(
            ids,
            db_path=SOURCES[source].path,
            progresso=progress,
        )
    if source == "sofascore":
        lines, code = _run_subprocess(
            [
                sys.executable,
                "-u",
                str(ROOT_DIR / "main2.py"),
                "--goal-ids",
                ",".join(map(str, ids)),
            ],
            progress,
        )
        if code:
            raise RuntimeError("\n".join(lines[-12:]) or "Falha ao coletar minutos")
        match = re.search(
            r"MINUTOS_GOLS_RESULTADO concluidas=(\d+) erros=(\d+) total=(\d+)",
            "\n".join(lines),
        )
        return {
            "concluidas": int(match.group(1)) if match else 0,
            "erros": int(match.group(2)) if match else 0,
            "total": int(match.group(3)) if match else len(ids),
            "log": lines[-20:],
        }
    raise ValueError("Esta fonte não fornece minutos dos gols")
