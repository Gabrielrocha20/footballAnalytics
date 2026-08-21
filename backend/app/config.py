from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")
DATA_DIR = Path(os.getenv("TRADEFOT_DATA_DIR", ROOT_DIR)).resolve()
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class SourceConfig:
    key: str
    name: str
    filename: str
    description: str
    league_column: str
    date_kind: str
    supports_minutes: bool

    @property
    def path(self) -> Path:
        return DATA_DIR / self.filename


SOURCES = {
    "onefootball": SourceConfig(
        "onefootball",
        "OneFootball",
        "futebol3.db",
        "Catálogo amplo, tabela e minutos dos gols",
        "liga_id",
        "iso",
        True,
    ),
    "sofascore": SourceConfig(
        "sofascore",
        "SofaScore",
        "futebol.db",
        "Catálogo amplo coletado pelo scraper",
        "liga_id",
        "epoch",
        True,
    ),
    "football_data": SourceConfig(
        "football_data",
        "football-data.org",
        "futebol2.db",
        "Principais ligas via API oficial",
        "liga_codigo",
        "iso",
        False,
    ),
}


def bootstrap_data() -> None:
    """Copia bancos distribuídos com a aplicação para um volume vazio."""
    if DATA_DIR == ROOT_DIR:
        return
    for source in SOURCES.values():
        seed = ROOT_DIR / source.filename
        if not source.path.exists() and seed.exists():
            shutil.copy2(seed, source.path)


bootstrap_data()
os.environ.setdefault("SOFASCORE_DB_PATH", str(SOURCES["sofascore"].path))
os.environ.setdefault("FOOTBALL_DATA_DB_PATH", str(SOURCES["football_data"].path))
os.environ.setdefault("ONEFOOTBALL_DB_PATH", str(SOURCES["onefootball"].path))
