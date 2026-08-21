import os
import math
import re
import sqlite3
import subprocess
import sys
import unicodedata

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from main import atualizar_dados as atualizar_football_data

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Football Analytics",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:wght@300;400;500;700&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

/* Dark pitch theme */
.stApp {
    background-color: #0d1117;
    color: #e6edf3;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0d1f0d 0%, #0d1117 100%);
    border-right: 1px solid #1f6b1f44;
}
[data-testid="stSidebar"] .stSelectbox label,
[data-testid="stSidebar"] .stRadio label,
[data-testid="stSidebar"] p {
    color: #88c988 !important;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}

/* Headers */
h1 { font-family: 'Bebas Neue', sans-serif !important; letter-spacing: 0.05em; color: #4ade80 !important; font-size: 3rem !important; }
h2 { font-family: 'Bebas Neue', sans-serif !important; color: #86efac !important; letter-spacing: 0.04em; }
h3 { font-family: 'Bebas Neue', sans-serif !important; color: #bbf7d0 !important; }

/* Metric cards */
[data-testid="metric-container"] {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 8px;
    padding: 1rem;
    border-left: 3px solid #4ade80;
}
[data-testid="metric-container"] label { color: #8b949e !important; font-size: 0.72rem !important; text-transform: uppercase; letter-spacing: 0.06em; }
[data-testid="metric-container"] [data-testid="stMetricValue"] { color: #4ade80 !important; font-family: 'Bebas Neue', sans-serif !important; font-size: 2.2rem !important; }
[data-testid="metric-container"] [data-testid="stMetricDelta"] { color: #86efac !important; }

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    background: #161b22;
    border-radius: 8px;
    gap: 4px;
    padding: 4px;
}
.stTabs [data-baseweb="tab"] {
    color: #8b949e !important;
    font-family: 'DM Sans', sans-serif;
    font-weight: 500;
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    border-radius: 6px;
}
.stTabs [aria-selected="true"] {
    background: #4ade80 !important;
    color: #0d1117 !important;
}

/* Dataframe */
[data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }

/* Divider */
hr { border-color: #21262d; }

/* Selectbox */
.stSelectbox > div > div {
    background: #161b22 !important;
    border: 1px solid #30363d !important;
    color: #e6edf3 !important;
}

/* Pills / badges */
.badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.badge-win  { background: #14532d; color: #4ade80; }
.badge-draw { background: #1c1917; color: #fbbf24; }
.badge-loss { background: #450a0a; color: #f87171; }
</style>
""", unsafe_allow_html=True)

# ── DB helper ─────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_SOURCES = {
    "football_data": {
        "nome": "football-data.org",
        "arquivo": "futebol2.db",
        "descricao": "6 grandes ligas · temporadas configuradas no main.py",
    },
    "sofascore": {
        "nome": "SofaScore",
        "arquivo": "futebol.db",
        "descricao": "Catálogo amplo de ligas · coletado pelo main2.py",
    },
    "onefootball": {
        "nome": "OneFootball",
        "arquivo": "futebol3.db",
        "descricao": "429 competições · calendário, resultados, tabela e minutos",
    },
}

@st.cache_data(ttl=60)
def load_data(db_path):
    if not os.path.exists(db_path):
        return pd.DataFrame()
    with sqlite3.connect(db_path, timeout=30) as conn:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='partidas'"
        ).fetchone()
        if not table_exists:
            return pd.DataFrame()
        details_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='partidas_detalhes'"
        ).fetchone()
        if details_exists:
            df = pd.read_sql(
                """
                SELECT p.*, d.gols_casa_ate_75, d.gols_fora_ate_75,
                       d.primeiro_gol_casa_minuto, d.primeiro_gol_fora_minuto,
                       d.coletado_em AS minutos_coletados_em
                FROM partidas p
                LEFT JOIN partidas_detalhes d ON d.id_api = p.id_api
                """,
                conn,
            )
        else:
            df = pd.read_sql("SELECT * FROM partidas", conn)

    if "liga_codigo" not in df.columns:
        df["liga_codigo"] = "SOFA_" + df["liga_id"].astype("Int64").astype(str)
    if "liga_pais" not in df.columns:
        df["liga_pais"] = ""

    if pd.api.types.is_numeric_dtype(df["data_partida"]):
        df["data_partida"] = pd.to_datetime(
            df["data_partida"], unit="s", errors="coerce", utc=True
        )
    else:
        df["data_partida"] = pd.to_datetime(
            df["data_partida"], errors="coerce", utc=True
        )
    df["mes"] = df["data_partida"].dt.tz_localize(None).dt.to_period("M").astype(str)
    if "rodada" not in df.columns:
        df["rodada"] = ""
    return df


@st.cache_data(ttl=60)
def load_official_standings(db_path, league_id):
    if not os.path.exists(db_path):
        return pd.DataFrame()
    with sqlite3.connect(db_path, timeout=30) as conn:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='classificacao'"
        ).fetchone()
        if not table_exists:
            return pd.DataFrame()
        return pd.read_sql(
            """
            SELECT posicao AS Pos, time_nome AS Time, jogos AS J,
                   vitorias AS V, empates AS E, derrotas AS D,
                   saldo_gols AS SG, pontos AS Pts
            FROM classificacao
            WHERE liga_id=?
            ORDER BY posicao, time_nome
            """,
            conn,
            params=(int(league_id),),
        ).set_index("Pos")


def database_label(source_key):
    source = DB_SOURCES[source_key]
    return f"{source['nome']} — {source['arquivo']}"


def atualizar_sofascore(progresso=None):
    """Executa o modo de atualização do main2.py e adapta o retorno para o painel."""
    sofa_db_path = os.path.join(BASE_DIR, DB_SOURCES["sofascore"]["arquivo"])
    has_data = False
    if os.path.exists(sofa_db_path):
        try:
            with sqlite3.connect(sofa_db_path, timeout=2) as conn:
                has_data = conn.execute("SELECT COUNT(*) FROM partidas").fetchone()[0] > 0
        except sqlite3.Error:
            pass
    command = [sys.executable, "-u", os.path.join(BASE_DIR, "main2.py")]
    if has_data:
        command.append("--update")
    process = subprocess.Popen(
        command,
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output_lines = []
    if process.stdout:
        for line in process.stdout:
            clean_line = line.strip()
            if clean_line:
                output_lines.append(clean_line)
                if progresso:
                    progresso(0, 1, clean_line[-120:])
    return_code = process.wait()
    output = "\n".join(output_lines)
    if return_code != 0:
        detail = "\n".join(output_lines[-8:]) or "O main2.py terminou sem mensagem."
        raise RuntimeError(f"Falha ao atualizar pelo SofaScore:\n{detail}")

    match = re.search(r"Total de resultados atualizados:\s*([\d.,]+)", output)
    updated = int(match.group(1).replace(".", "").replace(",", "")) if match else 0
    if progresso:
        progresso(1, 1, "Atualização do SofaScore concluída")
    return {
        "consultas": 1,
        "concluidas": 1,
        "recebidas": updated,
        "inseridas": 0,
        "atualizadas": updated,
        "erros": [],
        "detalhes": output_lines[-8:],
    }


def atualizar_onefootball(progresso=None, full=False):
    """Executa o coletor OneFootball sem bloquear a atualização visual do app."""
    db_path = os.path.join(BASE_DIR, DB_SOURCES["onefootball"]["arquivo"])
    has_data = False
    if os.path.exists(db_path):
        try:
            with sqlite3.connect(db_path, timeout=2) as conn:
                has_data = conn.execute(
                    "SELECT COUNT(*) FROM partidas"
                ).fetchone()[0] > 0
        except sqlite3.Error:
            pass

    command = [sys.executable, "-u", os.path.join(BASE_DIR, "main3.py")]
    command.append("--full" if full or not has_data else "--update")
    process = subprocess.Popen(
        command,
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output_lines = []
    if process.stdout:
        for line in process.stdout:
            clean_line = line.strip()
            if not clean_line:
                continue
            output_lines.append(clean_line)
            match = re.search(r"\[(\d+)/(\d+)\]\s*(.+)", clean_line)
            if match and progresso:
                progresso(int(match.group(1)), int(match.group(2)), match.group(3)[-120:])
    return_code = process.wait()
    output = "\n".join(output_lines)
    if return_code != 0:
        detail = "\n".join(output_lines[-8:]) or "O main3.py terminou sem mensagem."
        raise RuntimeError(f"Falha ao atualizar pelo OneFootball:\n{detail}")

    result_match = re.search(
        r"ONEFOOTBALL_RESULTADO consultas=(\d+) concluidas=(\d+) "
        r"recebidas=(\d+) inseridas=(\d+) atualizadas=(\d+) erros=(\d+)",
        output,
    )
    if not result_match:
        raise RuntimeError("O coletor OneFootball não retornou um resumo válido.")
    consultas, concluidas, recebidas, inseridas, atualizadas, erros = map(
        int, result_match.groups()
    )
    if progresso:
        progresso(consultas, consultas, "Sincronização OneFootball concluída")
    error_lines = [line.removeprefix("ERRO ") for line in output_lines if line.startswith("ERRO ")]
    return {
        "consultas": consultas,
        "concluidas": concluidas,
        "recebidas": recebidas,
        "inseridas": inseridas,
        "atualizadas": atualizadas,
        "erros": error_lines or ([f"{erros} consulta(s) falharam"] if erros else []),
        "detalhes": output_lines[-8:],
    }


def coletar_minutos_sofascore(match_ids, progresso=None):
    ids = list(dict.fromkeys(int(match_id) for match_id in match_ids))
    if not ids:
        return {"concluidas": 0, "erros": 0, "total": 0}
    command = [
        sys.executable,
        "-u",
        os.path.join(BASE_DIR, "main2.py"),
        "--goal-ids",
        ",".join(map(str, ids)),
    ]
    process = subprocess.Popen(
        command,
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output_lines = []
    if process.stdout:
        for line in process.stdout:
            clean_line = line.strip()
            if not clean_line:
                continue
            output_lines.append(clean_line)
            match = re.search(r"\[GOLS\s+(\d+)/(\d+)\]", clean_line)
            if match and progresso:
                progresso(int(match.group(1)) - 1, int(match.group(2)), clean_line)
    return_code = process.wait()
    output = "\n".join(output_lines)
    if return_code != 0:
        detail = "\n".join(output_lines[-8:]) or "O coletor terminou sem mensagem."
        raise RuntimeError(f"Falha ao coletar os minutos dos gols:\n{detail}")
    result_match = re.search(
        r"MINUTOS_GOLS_RESULTADO concluidas=(\d+) erros=(\d+) total=(\d+)", output
    )
    if not result_match:
        raise RuntimeError("O coletor não retornou o resumo dos minutos dos gols.")
    result = {
        "concluidas": int(result_match.group(1)),
        "erros": int(result_match.group(2)),
        "total": int(result_match.group(3)),
    }
    if progresso:
        progresso(result["total"], result["total"], "Minutos dos gols atualizados")
    return result


def coletar_minutos_onefootball(match_ids, progresso=None):
    ids = list(dict.fromkeys(int(match_id) for match_id in match_ids))
    if not ids:
        return {"concluidas": 0, "erros": 0, "total": 0}
    command = [
        sys.executable,
        "-u",
        os.path.join(BASE_DIR, "main3.py"),
        "--goal-ids",
        ",".join(map(str, ids)),
    ]
    process = subprocess.Popen(
        command,
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output_lines = []
    if process.stdout:
        for line in process.stdout:
            clean_line = line.strip()
            if not clean_line:
                continue
            output_lines.append(clean_line)
            match = re.search(r"\[GOLS\s+(\d+)/(\d+)\]", clean_line)
            if match and progresso:
                progresso(int(match.group(1)) - 1, int(match.group(2)), clean_line)
    return_code = process.wait()
    output = "\n".join(output_lines)
    if return_code != 0:
        detail = "\n".join(output_lines[-8:]) or "O main3.py terminou sem mensagem."
        raise RuntimeError(f"Falha ao coletar os minutos no OneFootball:\n{detail}")
    result_match = re.search(
        r"ONEFOOTBALL_GOLS_RESULTADO concluidas=(\d+) erros=(\d+) total=(\d+)",
        output,
    )
    if not result_match:
        raise RuntimeError("O coletor OneFootball não retornou o resumo dos minutos.")
    result = {
        "concluidas": int(result_match.group(1)),
        "erros": int(result_match.group(2)),
        "total": int(result_match.group(3)),
    }
    if progresso:
        progresso(result["total"], result["total"], "Minutos OneFootball atualizados")
    return result


def normalize_search(value):
    text = unicodedata.normalize("NFKD", str(value))
    return "".join(char for char in text if not unicodedata.combining(char)).casefold()


def change_page(page_key, page):
    st.session_state[page_key] = page


def back_to_home(source_key):
    st.session_state[f"view_{source_key}"] = "🏠 Início"
    st.session_state.pop(f"analysis_match_{source_key}", None)

LIGA_NAMES = {
    "BSA": "🇧🇷 Brasileirão Série A",
    "PL":  "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League",
    "PD":  "🇪🇸 La Liga",
    "SA":  "🇮🇹 Serie A",
    "BL1": "🇩🇪 Bundesliga",
    "FL1": "🇫🇷 Ligue 1",
}

PLOTLY_THEME = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(22,27,34,0.8)",
    font=dict(color="#8b949e", family="DM Sans"),
    xaxis=dict(gridcolor="#21262d", zerolinecolor="#21262d"),
    yaxis=dict(gridcolor="#21262d", zerolinecolor="#21262d"),
    margin=dict(l=10, r=10, t=40, b=10),
)

def team_stats(df, team):
    home = df[df["time_casa"] == team].copy()
    away = df[df["time_fora"] == team].copy()

    home["resultado"] = home["vencedor"].map({"HOME_TEAM": "V", "AWAY_TEAM": "D", "DRAW": "E"})
    away["resultado"] = away["vencedor"].map({"AWAY_TEAM": "V", "HOME_TEAM": "D", "DRAW": "E"})
    home["gols_pro"]    = home["gols_casa"];   home["gols_contra"] = home["gols_fora"]
    away["gols_pro"]    = away["gols_fora"];   away["gols_contra"] = away["gols_casa"]

    all_games = pd.concat([home, away]).sort_values("data_partida")
    played = all_games[all_games["resultado"].notna()]

    wins   = (played["resultado"] == "V").sum()
    draws  = (played["resultado"] == "E").sum()
    losses = (played["resultado"] == "D").sum()
    gf     = played["gols_pro"].sum()
    ga     = played["gols_contra"].sum()
    pts    = wins * 3 + draws

    return dict(played=len(played), wins=wins, draws=draws, losses=losses,
                gf=int(gf), ga=int(ga), gd=int(gf - ga), pts=int(pts))

def build_standings(df):
    columns = ["Time", "PJ", "V", "E", "D", "GP", "GC", "SG", "Pts"]
    if df.empty:
        return pd.DataFrame(columns=columns)
    teams = pd.unique(pd.concat([df["time_casa"], df["time_fora"]]))
    rows = []
    for t in teams:
        s = team_stats(df, t)
        rows.append({"Time": t, "PJ": s["played"], "V": s["wins"],
                     "E": s["draws"], "D": s["losses"],
                     "GP": s["gf"], "GC": s["ga"], "SG": s["gd"], "Pts": s["pts"]})
    tbl = pd.DataFrame(rows, columns=columns).sort_values("Pts", ascending=False).reset_index(drop=True)
    tbl.index += 1
    return tbl


def team_game_history(data, team_id, before_date=None, limit=10):
    """Retorna jogos disputados na perspectiva de um time, do mais novo ao antigo."""
    games = data[
        data["gols_casa"].notna()
        & ((data["time_casa_id"] == team_id) | (data["time_fora_id"] == team_id))
    ].copy()
    if before_date is not None:
        games = games[games["data_partida"] < before_date]

    games["local"] = games["time_casa_id"].eq(team_id).map({True: "Casa", False: "Fora"})
    games["oponente"] = games["time_fora"].where(
        games["time_casa_id"].eq(team_id), games["time_casa"]
    )
    games["gols_pro"] = games["gols_casa"].where(
        games["time_casa_id"].eq(team_id), games["gols_fora"]
    )
    games["gols_contra"] = games["gols_fora"].where(
        games["time_casa_id"].eq(team_id), games["gols_casa"]
    )
    games["resultado"] = "E"
    games.loc[games["gols_pro"] > games["gols_contra"], "resultado"] = "V"
    games.loc[games["gols_pro"] < games["gols_contra"], "resultado"] = "D"
    games = games.sort_values("data_partida", ascending=False)
    return games.head(limit) if limit else games


def history_summary(games):
    total = len(games)
    wins = int(games["resultado"].eq("V").sum()) if total else 0
    draws = int(games["resultado"].eq("E").sum()) if total else 0
    losses = int(games["resultado"].eq("D").sum()) if total else 0
    gf = int(games["gols_pro"].sum()) if total else 0
    ga = int(games["gols_contra"].sum()) if total else 0
    return {
        "jogos": total,
        "vitorias": wins,
        "empates": draws,
        "derrotas": losses,
        "gf": gf,
        "ga": ga,
        "media_gf": gf / total if total else 0,
        "media_ga": ga / total if total else 0,
        "ppg": (wins * 3 + draws) / total if total else 0,
        "aproveitamento": (wins * 3 + draws) / (total * 3) * 100 if total else 0,
        "forma": " ".join(games["resultado"].tolist()) if total else "Sem dados",
    }


def poisson_prediction(home_games, away_games, h2h, home_id, away_id):
    """Estimativa simples baseada em forma, gols e um peso pequeno do confronto direto."""
    home = history_summary(home_games)
    away = history_summary(away_games)

    if not home["jogos"] or not away["jogos"]:
        return None

    expected_home = (home["media_gf"] + away["media_ga"]) / 2
    expected_away = (away["media_gf"] + home["media_ga"]) / 2
    form_difference = home["ppg"] - away["ppg"]

    home_h2h_wins = 0
    away_h2h_wins = 0
    for _, game in h2h.iterrows():
        winner_id = None
        if game["gols_casa"] > game["gols_fora"]:
            winner_id = game["time_casa_id"]
        elif game["gols_fora"] > game["gols_casa"]:
            winner_id = game["time_fora_id"]
        home_h2h_wins += winner_id == home_id
        away_h2h_wins += winner_id == away_id
    h2h_difference = (
        (home_h2h_wins - away_h2h_wins) / len(h2h) if len(h2h) else 0
    )

    expected_home *= 1.08 + 0.08 * form_difference + 0.06 * h2h_difference
    expected_away *= 0.96 - 0.08 * form_difference - 0.06 * h2h_difference
    expected_home = min(max(expected_home, 0.2), 4.0)
    expected_away = min(max(expected_away, 0.2), 4.0)

    home_probability = draw_probability = away_probability = 0.0
    for home_goals in range(9):
        p_home_goals = (
            math.exp(-expected_home) * expected_home**home_goals / math.factorial(home_goals)
        )
        for away_goals in range(9):
            p_away_goals = (
                math.exp(-expected_away) * expected_away**away_goals / math.factorial(away_goals)
            )
            probability = p_home_goals * p_away_goals
            if home_goals > away_goals:
                home_probability += probability
            elif home_goals == away_goals:
                draw_probability += probability
            else:
                away_probability += probability

    total = home_probability + draw_probability + away_probability
    return {
        "casa": home_probability / total * 100,
        "empate": draw_probability / total * 100,
        "fora": away_probability / total * 100,
        "gols_casa": expected_home,
        "gols_fora": expected_away,
    }


def goal_75_history(team_games, team_id):
    """Lê gols do time até 75' na ordem dos jogos recebidos."""
    records = []
    for _, history_match in team_games.iterrows():
        at_home = history_match["time_casa_id"] == team_id
        goal_column = "gols_casa_ate_75" if at_home else "gols_fora_ate_75"
        minute_column = (
            "primeiro_gol_casa_minuto" if at_home else "primeiro_gol_fora_minuto"
        )
        value = history_match.get(goal_column, pd.NA)
        first_minute = history_match.get(minute_column, pd.NA)
        records.append(
            {
                "id_api": int(history_match["id_api"]),
                "goals": None if pd.isna(value) else int(value),
                "first_minute": None if pd.isna(first_minute) else int(first_minute),
                "match": history_match,
            }
        )
    return records


def build_lay_01_candidates(all_data, league_data):
    """Seleciona mandantes favoritos e mede gols marcados até 75' nos 10 jogos anteriores."""
    now = pd.Timestamp.now(tz="UTC")
    upcoming = league_data[
        league_data["gols_casa"].isna() & (league_data["data_partida"] >= now)
    ].sort_values("data_partida")
    if "status" in upcoming.columns:
        upcoming = upcoming[
            ~upcoming["status"].fillna("").str.casefold().isin(
                ["canceled", "cancelled", "abandoned", "walkover"]
            )
        ]

    rows = []
    for _, match in upcoming.iterrows():
        home_id = match["time_casa_id"]
        away_id = match["time_fora_id"]
        kickoff = match["data_partida"]
        home_games = team_game_history(all_data, home_id, kickoff, 10)
        away_games = team_game_history(all_data, away_id, kickoff, 10)
        if len(home_games) < 10 or not len(away_games):
            continue
        h2h = all_data[
            all_data["gols_casa"].notna()
            & (all_data["data_partida"] < kickoff)
            & (
                ((all_data["time_casa_id"] == home_id) & (all_data["time_fora_id"] == away_id))
                | ((all_data["time_casa_id"] == away_id) & (all_data["time_fora_id"] == home_id))
            )
        ].sort_values("data_partida", ascending=False).head(10)
        prediction = poisson_prediction(home_games, away_games, h2h, home_id, away_id)
        if not prediction or prediction["casa"] <= max(prediction["empate"], prediction["fora"]):
            continue

        goal_records = goal_75_history(home_games, home_id)
        goal_values = [record["goals"] for record in goal_records]
        missing_ids = [
            record["id_api"] for record in goal_records if record["goals"] is None
        ]

        coverage = sum(value is not None for value in goal_values)
        hits = sum(value is not None and value >= 1 for value in goal_values)
        percentage = hits / 10 * 100
        rows.append(
            {
                "id_api": int(match["id_api"]),
                "data_partida": kickoff,
                "favorito": match["time_casa"],
                "zebra": match["time_fora"],
                "prob_favorito": prediction["casa"],
                "acertos": hits,
                "cobertura": coverage,
                "percentual": percentage,
                "classificado": coverage == 10 and percentage > 75,
                "missing_ids": missing_ids,
                "history": home_games,
                "goal_values": goal_values,
            }
        )
    return rows


def render_lay_01(all_data, league_data, source_key):
    st.markdown("# 🎯 Método Lay 0x1 na zebra")
    st.caption(
        "Favorito mandante pelo modelo · últimos 10 jogos do favorito · pelo menos 1 gol marcado entre 0' e 75'."
    )
    st.info(
        "O corte é estritamente maior que 75%: na amostra de 10 jogos, o time precisa cumprir o critério em 8 ou mais. "
        "O favoritismo é uma estimativa estatística, não uma odd de mercado nem garantia de gol."
    )

    if source_key not in ("sofascore", "onefootball"):
        st.warning(
            "A football-data.org não forneceu os minutos dos gols para o token atual. "
            "Selecione **OneFootball — futebol3.db** ou **SofaScore — futebol.db** "
            "para usar este filtro com dados exatos."
        )
        return

    candidates = build_lay_01_candidates(all_data, league_data)
    if not candidates:
        st.info("Nenhum mandante favorito com 10 jogos anteriores foi encontrado nesta liga/temporada.")
        return

    missing_ids = sorted(
        {match_id for candidate in candidates for match_id in candidate["missing_ids"]}
    )
    complete = sum(candidate["cobertura"] == 10 for candidate in candidates)
    c1, c2, c3 = st.columns(3)
    c1.metric("Favoritos mandantes", len(candidates))
    c2.metric("Históricos completos", f"{complete}/{len(candidates)}")
    c3.metric("Partidas sem minutos", len(missing_ids))

    if missing_ids:
        st.caption(
            "A primeira análise da liga precisa consultar os incidentes dos jogos anteriores. "
            f"Depois eles ficam salvos no {DB_SOURCES[source_key]['arquivo']}."
        )
        if st.button(
            f"⏱️ Coletar minutos de {len(missing_ids)} partidas",
            type="primary",
            key=f"collect_goal_minutes_{source_key}_{league_data['liga_codigo'].iloc[0]}",
        ):
            progress = st.progress(0, text=f"Abrindo o {DB_SOURCES[source_key]['nome']}...")

            def goal_progress(current, total, message):
                progress.progress(current / total if total else 0, text=message)

            try:
                if source_key == "onefootball":
                    result = coletar_minutos_onefootball(missing_ids, goal_progress)
                else:
                    result = coletar_minutos_sofascore(missing_ids, goal_progress)
                load_data.clear()
                st.session_state[f"goal_minutes_result_{source_key}"] = result
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    result_key = f"goal_minutes_result_{source_key}"
    if result_key in st.session_state:
        result = st.session_state.pop(result_key)
        message = (
            f"Minutos coletados em {result['concluidas']} partidas; "
            f"{result['erros']} falharam."
        )
        if result["erros"] and source_key == "sofascore":
            st.warning(
                message
                + " Se o SofaScore retornou HTTP 403, aguarde a coleta principal terminar e tente novamente."
            )
        elif result["erros"]:
            st.warning(message + " Alguns jogos podem não ter eventos disponíveis no OneFootball.")
        else:
            st.success(message)

    qualified = [candidate for candidate in candidates if candidate["classificado"]]
    st.markdown(f"### Jogos aprovados no filtro: {len(qualified)}")
    if not qualified:
        if missing_ids:
            st.warning("Complete a coleta dos minutos para liberar o resultado definitivo do filtro.")
        else:
            st.info("Nenhum próximo jogo atingiu mais de 75% nesta liga/temporada.")
    else:
        table = pd.DataFrame(
            [
                {
                    "Data": candidate["data_partida"].tz_convert("America/Sao_Paulo").strftime("%d/%m/%Y %H:%M"),
                    "Favorito em casa": candidate["favorito"],
                    "Zebra": candidate["zebra"],
                    "Prob. favorito": f"{candidate['prob_favorito']:.1f}%",
                    "Gol até 75'": f"{candidate['acertos']}/10",
                    "Percentual": f"{candidate['percentual']:.0f}%",
                }
                for candidate in qualified
            ]
        )
        st.dataframe(table, use_container_width=True, hide_index=True)

    with st.expander("Ver todos os favoritos e a cobertura dos dados"):
        audit_table = pd.DataFrame(
            [
                {
                    "Data": candidate["data_partida"].tz_convert("America/Sao_Paulo").strftime("%d/%m/%Y %H:%M"),
                    "Favorito": candidate["favorito"],
                    "Adversário": candidate["zebra"],
                    "Probabilidade": f"{candidate['prob_favorito']:.1f}%",
                    "Acertos": f"{candidate['acertos']}/10",
                    "Dados coletados": f"{candidate['cobertura']}/10",
                    "Situação": "✅ Aprovado" if candidate["classificado"] else ("⏳ Pendente" if candidate["cobertura"] < 10 else "❌ Abaixo de 75%"),
                }
                for candidate in candidates
            ]
        )
        st.dataframe(audit_table, use_container_width=True, hide_index=True)


def history_table(games):
    if games.empty:
        return pd.DataFrame()
    table = games[
        ["data_partida", "liga_nome", "temporada", "local", "oponente", "gols_pro", "gols_contra", "resultado"]
    ].copy()
    table["data_partida"] = table["data_partida"].dt.tz_convert(
        "America/Sao_Paulo"
    ).dt.strftime("%d/%m/%Y")
    table["Placar"] = (
        table["gols_pro"].astype(int).astype(str)
        + " × "
        + table["gols_contra"].astype(int).astype(str)
    )
    table["resultado"] = table["resultado"].map(
        {"V": "✅ Vitória", "E": "🟡 Empate", "D": "❌ Derrota"}
    )
    table = table[["data_partida", "liga_nome", "temporada", "local", "oponente", "Placar", "resultado"]]
    table.columns = ["Data", "Competição", "Temporada", "Local", "Adversário", "Placar", "Resultado"]
    return table


def render_match_lay_01(match, home_games, prediction, source_key):
    """Mostra o critério Lay 0x1 para a partida aberta pelo usuário."""
    home_id = match["time_casa_id"]
    home_name = match["time_casa"]
    away_name = match["time_fora"]
    match_id = int(match["id_api"])

    st.markdown("### 🎯 Filtro Lay 0x1 na zebra")
    st.caption(
        "Regra: favorito jogando em casa e gol marcado pelo favorito entre 0' e 75' "
        "em mais de 75% dos últimos 10 jogos anteriores."
    )

    if prediction:
        home_is_favorite = prediction["casa"] > max(
            prediction["empate"], prediction["fora"]
        )
        favorite_text = (
            f"Sim · {prediction['casa']:.1f}%"
            if home_is_favorite
            else f"Não · {prediction['casa']:.1f}%"
        )
    else:
        home_is_favorite = False
        favorite_text = "Indefinido"

    if source_key not in ("sofascore", "onefootball"):
        c1, c2 = st.columns(2)
        c1.metric("Favorito mandante", favorite_text)
        c2.metric("Gol até 75'", "Sem dados")
        st.warning(
            "Esta fonte não possui os minutos dos gols. Selecione OneFootball ou "
            "SofaScore para validar este método."
        )
        return

    records = goal_75_history(home_games, home_id)
    coverage = sum(record["goals"] is not None for record in records)
    hits = sum(
        record["goals"] is not None and record["goals"] >= 1
        for record in records
    )
    missing_ids = [
        record["id_api"] for record in records if record["goals"] is None
    ]
    percentage = hits / 10 * 100
    qualified = (
        home_is_favorite
        and len(home_games) == 10
        and coverage == 10
        and percentage > 75
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Favorito mandante", favorite_text)
    c2.metric("Gol até 75'", f"{hits}/10")
    c3.metric("Percentual", f"{percentage:.0f}%" if coverage == 10 else "Pendente")
    c4.metric("Dados disponíveis", f"{coverage}/10")

    result_key = f"lay_match_minutes_result_{source_key}_{match_id}"
    if result_key in st.session_state:
        result = st.session_state.pop(result_key)
        message = (
            f"Minutos coletados em {result['concluidas']} partidas; "
            f"{result['erros']} falharam."
        )
        st.success(message) if not result["erros"] else st.warning(message)

    if missing_ids and home_is_favorite and len(home_games) == 10:
        st.warning(
            f"Faltam os minutos de {len(missing_ids)} dos {len(home_games)} jogos encontrados. "
            "Colete-os para liberar o resultado definitivo."
        )
        if st.button(
            f"⏱️ Coletar minutos que faltam ({len(missing_ids)})",
            type="primary",
            key=f"collect_match_minutes_{source_key}_{match_id}",
        ):
            progress = st.progress(0, text=f"Consultando {DB_SOURCES[source_key]['nome']}...")

            def goal_progress(current, total, message):
                progress.progress(current / total if total else 0, text=message)

            try:
                if source_key == "onefootball":
                    result = coletar_minutos_onefootball(missing_ids, goal_progress)
                else:
                    result = coletar_minutos_sofascore(missing_ids, goal_progress)
                load_data.clear()
                st.session_state[result_key] = result
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    if not prediction:
        st.info("Ainda não há dados suficientes para confirmar quem é o favorito.")
    elif not home_is_favorite:
        st.error(
            f"❌ Fora do método: o modelo não considera {home_name} favorito contra {away_name}."
        )
    elif len(home_games) < 10:
        st.warning(
            f"⏳ Amostra insuficiente: foram encontrados somente {len(home_games)} jogos anteriores."
        )
    elif coverage < 10:
        st.info("⏳ Sinal pendente até completar os minutos dos 10 jogos.")
    elif qualified:
        st.success(
            f"✅ APROVADO: {home_name} marcou até 75' em {hits}/10 jogos "
            f"({percentage:.0f}%), acima do corte de 75%."
        )
    else:
        st.error(
            f"❌ REPROVADO: {home_name} marcou até 75' em {hits}/10 jogos "
            f"({percentage:.0f}%). O mínimo prático é 8/10."
        )

    audit_rows = []
    for record in records:
        game = record["match"]
        goals = record["goals"]
        minute = record["first_minute"]
        if goals is None:
            criterion = "⏳ Sem minutos"
        elif goals >= 1:
            criterion = "✅ Sim"
        else:
            criterion = "❌ Não"
        audit_rows.append(
            {
                "Data": game["data_partida"].tz_convert("America/Sao_Paulo").strftime("%d/%m/%Y"),
                "Local": game["local"],
                "Adversário": game["oponente"],
                "Placar": f"{int(game['gols_pro'])} × {int(game['gols_contra'])}",
                "Gols 0–75'": "—" if goals is None else goals,
                "Primeiro gol": f"{minute}'" if minute is not None else "—",
                "Critério": criterion,
            }
        )
    if audit_rows:
        with st.expander("Ver os 10 jogos usados no cálculo", expanded=True):
            st.dataframe(pd.DataFrame(audit_rows), use_container_width=True, hide_index=True)


def render_match_analysis(match, all_data, source_key):
    home_id = match["time_casa_id"]
    away_id = match["time_fora_id"]
    home_name = match["time_casa"]
    away_name = match["time_fora"]
    kickoff = match["data_partida"]

    home_games = team_game_history(all_data, home_id, kickoff, 10)
    away_games = team_game_history(all_data, away_id, kickoff, 10)
    h2h = all_data[
        all_data["gols_casa"].notna()
        & (all_data["data_partida"] < kickoff)
        & (
            ((all_data["time_casa_id"] == home_id) & (all_data["time_fora_id"] == away_id))
            | ((all_data["time_casa_id"] == away_id) & (all_data["time_fora_id"] == home_id))
        )
    ].sort_values("data_partida", ascending=False).head(10)

    home_stats = history_summary(home_games)
    away_stats = history_summary(away_games)
    prediction = poisson_prediction(home_games, away_games, h2h, home_id, away_id)

    st.markdown("---")
    local_date = kickoff.tz_convert("America/Sao_Paulo").strftime("%d/%m/%Y às %H:%M")
    st.markdown(f"## {home_name} × {away_name}")
    st.caption(f"Análise pré-jogo · {local_date} · últimos jogos anteriores a esta partida")

    if prediction:
        labels = [home_name, "Empate", away_name]
        probabilities = [prediction["casa"], prediction["empate"], prediction["fora"]]
        favorite_index = probabilities.index(max(probabilities))
        st.markdown(f"#### Mais provável pelos dados: **{labels[favorite_index]} ({probabilities[favorite_index]:.1f}%)**")
        p1, p2, p3 = st.columns(3)
        p1.metric(f"Vitória · {home_name}", f"{prediction['casa']:.1f}%")
        p2.metric("Empate", f"{prediction['empate']:.1f}%")
        p3.metric(f"Vitória · {away_name}", f"{prediction['fora']:.1f}%")
        st.progress(prediction["casa"] / 100, text=f"{home_name}: {prediction['casa']:.1f}%")
        st.progress(prediction["empate"] / 100, text=f"Empate: {prediction['empate']:.1f}%")
        st.progress(prediction["fora"] / 100, text=f"{away_name}: {prediction['fora']:.1f}%")
        st.caption(
            f"Gols esperados pelo modelo: {home_name} {prediction['gols_casa']:.2f} × "
            f"{prediction['gols_fora']:.2f} {away_name}. Estimativa estatística, não garantia de resultado."
        )
    else:
        st.info("Ainda não há jogos anteriores suficientes dos dois times para calcular probabilidades.")

    render_match_lay_01(match, home_games, prediction, source_key)

    st.markdown("#### Comparativo da forma recente")
    comparison = pd.DataFrame(
        {
            "Indicador": ["Jogos", "Vitórias", "Empates", "Derrotas", "Gols marcados", "Gols sofridos", "Média de gols", "Aproveitamento", "Forma (mais recente primeiro)"],
            home_name: [home_stats["jogos"], home_stats["vitorias"], home_stats["empates"], home_stats["derrotas"], home_stats["gf"], home_stats["ga"], f"{home_stats['media_gf']:.2f}", f"{home_stats['aproveitamento']:.1f}%", home_stats["forma"]],
            away_name: [away_stats["jogos"], away_stats["vitorias"], away_stats["empates"], away_stats["derrotas"], away_stats["gf"], away_stats["ga"], f"{away_stats['media_gf']:.2f}", f"{away_stats['aproveitamento']:.1f}%", away_stats["forma"]],
        }
    )
    comparison[[home_name, away_name]] = comparison[[home_name, away_name]].astype(str)
    st.dataframe(comparison, use_container_width=True, hide_index=True)

    hist_tab_home, hist_tab_away, h2h_tab = st.tabs(
        [f"Últimos jogos · {home_name}", f"Últimos jogos · {away_name}", "Confrontos diretos"]
    )
    with hist_tab_home:
        table = history_table(home_games)
        if table.empty:
            st.info("Sem histórico disponível.")
        else:
            st.dataframe(table, use_container_width=True, hide_index=True)
    with hist_tab_away:
        table = history_table(away_games)
        if table.empty:
            st.info("Sem histórico disponível.")
        else:
            st.dataframe(table, use_container_width=True, hide_index=True)
    with h2h_tab:
        if h2h.empty:
            st.info("Nenhum confronto direto anterior encontrado no banco.")
        else:
            home_wins = int((((h2h["time_casa_id"] == home_id) & (h2h["gols_casa"] > h2h["gols_fora"])) | ((h2h["time_fora_id"] == home_id) & (h2h["gols_fora"] > h2h["gols_casa"]))).sum())
            away_wins = int((((h2h["time_casa_id"] == away_id) & (h2h["gols_casa"] > h2h["gols_fora"])) | ((h2h["time_fora_id"] == away_id) & (h2h["gols_fora"] > h2h["gols_casa"]))).sum())
            draws = len(h2h) - home_wins - away_wins
            c1, c2, c3 = st.columns(3)
            c1.metric(f"Vitórias · {home_name}", home_wins)
            c2.metric("Empates", draws)
            c3.metric(f"Vitórias · {away_name}", away_wins)
            h2h_table = h2h[["data_partida", "liga_nome", "temporada", "time_casa", "gols_casa", "gols_fora", "time_fora"]].copy()
            h2h_table["data_partida"] = h2h_table["data_partida"].dt.tz_convert("America/Sao_Paulo").dt.strftime("%d/%m/%Y")
            h2h_table["Placar"] = h2h_table["gols_casa"].astype(int).astype(str) + " × " + h2h_table["gols_fora"].astype(int).astype(str)
            h2h_table = h2h_table[["data_partida", "liga_nome", "temporada", "time_casa", "Placar", "time_fora"]]
            h2h_table.columns = ["Data", "Competição", "Temporada", "Mandante", "Placar", "Visitante"]
            st.dataframe(h2h_table, use_container_width=True, hide_index=True)


def render_home(all_data, league_labels, source_key):
    st.markdown("# Próximos jogos")
    st.caption(
        "Todas as ligas da fonte selecionada. Clique em uma partida para abrir a liga e a análise pré-jogo."
    )

    now = pd.Timestamp.now(tz="UTC")
    upcoming_mask = all_data["gols_casa"].isna() & (all_data["data_partida"] >= now)
    if "status" in all_data.columns:
        invalid_status = all_data["status"].fillna("").str.casefold().isin(
            ["canceled", "cancelled", "abandoned", "walkover"]
        )
        upcoming_mask &= ~invalid_status

    upcoming_all = all_data[upcoming_mask].sort_values("data_partida").copy()
    if upcoming_all.empty:
        st.info("Nenhum jogo futuro encontrado neste banco.")
        return

    mode = st.radio(
        "Organização",
        ["Mais próximos por data", "2 próximos de cada liga"],
        horizontal=True,
        key=f"home_mode_{source_key}",
    )
    page_size = st.selectbox(
        "Jogos por página",
        options=[25, 50, 100],
        index=1,
        key=f"home_page_size_{source_key}",
    )
    if mode == "2 próximos de cada liga":
        upcoming_all = (
            upcoming_all.groupby("liga_codigo", sort=False, group_keys=False)
            .head(2)
            .sort_values("data_partida")
        )

    total_matches = len(upcoming_all)
    total_pages = max(1, math.ceil(total_matches / page_size))
    mode_key = "date" if mode == "Mais próximos por data" else "league"
    page_key = f"home_page_{source_key}_{mode_key}"
    current_page = int(st.session_state.get(page_key, 1))
    if current_page < 1 or current_page > total_pages:
        current_page = 1
        st.session_state[page_key] = current_page

    start = (current_page - 1) * page_size
    page_games = upcoming_all.iloc[start : start + page_size].reset_index(drop=True)
    display = page_games[
        ["data_partida", "liga_codigo", "temporada", "time_casa", "time_fora"]
    ].copy()
    display["data_partida"] = display["data_partida"].dt.tz_convert(
        "America/Sao_Paulo"
    ).dt.strftime("%d/%m/%Y %H:%M")
    display["liga_codigo"] = display["liga_codigo"].map(league_labels)
    display.columns = ["Data", "Liga", "Temporada", "Mandante", "Visitante"]

    selected = st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"home_matches_{source_key}_{mode_key}_{page_size}_{current_page}",
    )
    selected_rows = selected.selection.rows
    if selected_rows and 0 <= selected_rows[0] < len(page_games):
        match = page_games.iloc[selected_rows[0]]
        st.session_state["navigation_request"] = {
            "source": source_key,
            "league": match["liga_codigo"],
            "season": int(match["temporada"]),
            "match_id": int(match["id_api"]),
        }
        st.rerun()

    previous_col, page_col, next_col = st.columns([1, 2, 1])
    previous_col.button(
        "← Anterior",
        disabled=current_page <= 1,
        use_container_width=True,
        key=f"home_previous_{source_key}_{mode_key}",
        on_click=change_page,
        args=(page_key, current_page - 1),
    )
    page_col.markdown(
        f"<div style='text-align:center;padding-top:.45rem'>Página {current_page} de {total_pages} · {total_matches:,} jogos</div>",
        unsafe_allow_html=True,
    )
    next_col.button(
        "Próxima →",
        disabled=current_page >= total_pages,
        use_container_width=True,
        key=f"home_next_{source_key}_{mode_key}",
        on_click=change_page,
        args=(page_key, current_page + 1),
    )

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚽ Football Analytics")
    st.markdown("---")

    source_key = st.selectbox(
        "Fonte de dados",
        options=list(DB_SOURCES),
        format_func=database_label,
        key="database_source",
    )
    source = DB_SOURCES[source_key]
    DB_PATH = os.path.join(BASE_DIR, source["arquivo"])

    df_all = load_data(DB_PATH)
    st.caption(f"{source['descricao']} · {len(df_all):,} partidas no banco")

    onefootball_full = False
    if source_key == "onefootball":
        update_scope = st.radio(
            "Escopo da atualização",
            ["Todas as competições", "Incremental rápida"],
            horizontal=True,
            key="onefootball_update_scope",
            help=(
                "Todas as competições percorre novamente as 429 ligas. "
                "Incremental rápida atualiza ligas sem coleta, desatualizadas "
                "ou com partidas próximas."
            ),
        )
        onefootball_full = update_scope == "Todas as competições"

    if st.button(
        (
            "🔄 Atualizar todas as ligas"
            if source_key == "onefootball" and onefootball_full
            else f"🔄 Atualizar {source['nome']}"
        ),
        use_container_width=True,
        type="primary",
        key=f"update_{source_key}",
    ):
        progress_bar = st.progress(0, text="Preparando atualização...")

        def update_progress(current, total, message):
            progress_bar.progress(current / total if total else 0, text=message)

        try:
            with st.spinner(f"Atualizando pelo {source['nome']}..."):
                if source_key == "football_data":
                    update_result = atualizar_football_data(progresso=update_progress)
                elif source_key == "sofascore":
                    update_result = atualizar_sofascore(progresso=update_progress)
                else:
                    update_result = atualizar_onefootball(
                        progresso=update_progress,
                        full=onefootball_full,
                    )
            st.session_state[f"update_result_{source_key}"] = update_result
            load_data.clear()
            load_official_standings.clear()
            st.rerun()
        except Exception as exc:
            st.error(f"Não foi possível atualizar os dados: {exc}")

    result_key = f"update_result_{source_key}"
    if result_key in st.session_state:
        result = st.session_state[result_key]
        if result["erros"]:
            st.warning(
                f"Atualização parcial: {result['concluidas']}/{result['consultas']} consultas concluídas."
            )
            with st.expander("Ver erros da atualização"):
                for error in result["erros"]:
                    st.write(f"• {error}")
        else:
            if source_key == "sofascore":
                st.success(
                    f"Sincronização incremental concluída: "
                    f"{result['atualizadas']} registros sincronizados."
                )
            elif source_key == "onefootball":
                st.success(
                    f"OneFootball sincronizado: {result['concluidas']}/"
                    f"{result['consultas']} ligas concluídas, "
                    f"{result['inseridas']} jogos novos e "
                    f"{result['atualizadas']} revisados."
                )
            else:
                st.success(
                    f"Dados atualizados: {result['inseridas']} novas e "
                    f"{result['atualizadas']} partidas revisadas."
                )

    if os.path.exists(DB_PATH):
        updated_at = pd.Timestamp.fromtimestamp(
            os.path.getmtime(DB_PATH), tz="America/Sao_Paulo"
        ).strftime("%d/%m/%Y às %H:%M")
        st.caption(f"Banco atualizado em {updated_at}")

    st.markdown("---")

    if df_all.empty:
        st.error("Banco de dados vazio. Use o botão **Atualizar dados** acima.")
        st.stop()

    league_info = df_all.drop_duplicates("liga_codigo").set_index("liga_codigo")
    liga_labels = {}
    for code, row in league_info.iterrows():
        if code in LIGA_NAMES:
            liga_labels[code] = LIGA_NAMES[code]
        else:
            country = row.get("liga_pais", "")
            country_suffix = f" · {country}" if pd.notna(country) and country else ""
            liga_labels[code] = f"⚽ {row['liga_nome']}{country_suffix}"
    ligas_disp = sorted(liga_labels, key=lambda code: liga_labels[code].casefold())
    league_team_pairs = pd.concat(
        [
            df_all[["liga_codigo", "time_casa"]].rename(columns={"time_casa": "time"}),
            df_all[["liga_codigo", "time_fora"]].rename(columns={"time_fora": "time"}),
        ],
        ignore_index=True,
    ).dropna().drop_duplicates()
    league_teams = (
        league_team_pairs.groupby("liga_codigo")["time"]
        .agg(lambda teams: " ".join(teams.astype(str)))
        .to_dict()
    )

    navigation = st.session_state.get("navigation_request")
    navigation = navigation if navigation and navigation.get("source") == source_key else None
    search_key = f"league_search_{source_key}"
    league_key = f"league_{source_key}"
    if navigation:
        st.session_state[search_key] = ""
        st.session_state[league_key] = navigation["league"]

    league_search = st.text_input(
        "Pesquisar liga ou time",
        key=search_key,
        placeholder="Digite uma liga, país, time ou código...",
    )
    if league_search.strip():
        search_term = normalize_search(league_search)
        filtered_leagues = [
            code
            for code in ligas_disp
            if search_term
            in normalize_search(f"{liga_labels[code]} {code} {league_teams.get(code, '')}")
        ]
    else:
        filtered_leagues = ligas_disp

    if not filtered_leagues:
        st.warning("Nenhuma liga encontrada. Ajuste o texto da pesquisa.")
        filtered_leagues = ligas_disp
    if st.session_state.get(league_key) not in filtered_leagues:
        st.session_state[league_key] = filtered_leagues[0]

    liga_sel = st.selectbox(
        "Liga",
        options=filtered_leagues,
        format_func=lambda x: liga_labels[x],
        key=league_key,
    )

    temps_disp = sorted(df_all[df_all["liga_codigo"] == liga_sel]["temporada"].unique(), reverse=True)
    season_key = f"season_{source_key}_{liga_sel}"
    if navigation and navigation["season"] in temps_disp:
        st.session_state[season_key] = navigation["season"]
    temp_sel = st.selectbox(
        "Temporada",
        options=temps_disp,
        key=season_key,
    )

    st.markdown("---")
    view_key = f"view_{source_key}"
    if navigation:
        st.session_state[view_key] = "🏆 Liga"
    view = st.radio(
        "Visão",
        ["🏠 Início", "🎯 Lay 0x1", "🏆 Liga", "👕 Time"],
        key=view_key,
    )
    if navigation:
        st.session_state[f"analysis_match_{source_key}"] = navigation["match_id"]
        st.session_state.pop("navigation_request", None)

    if view == "👕 Time":
        df_liga = df_all[(df_all["liga_codigo"] == liga_sel) & (df_all["temporada"] == temp_sel)]
        times_disp = sorted(pd.unique(pd.concat([df_liga["time_casa"], df_liga["time_fora"]])))
        time_sel = st.selectbox(
            "Time",
            times_disp,
            key=f"team_{source_key}_{liga_sel}_{temp_sel}",
        )

    st.markdown("---")
    total_jogos = len(df_all)
    st.metric("Total de partidas no banco", f"{total_jogos:,}")

# ── Filter ────────────────────────────────────────────────────────────────────
df = df_all[(df_all["liga_codigo"] == liga_sel) & (df_all["temporada"] == temp_sel)]
df_played = df[df["gols_casa"].notna()].copy()

liga_full = liga_labels.get(liga_sel, liga_sel)

# ═════════════════════════════════════════════════════════════════════════════
# VIEW: LIGA
# ═════════════════════════════════════════════════════════════════════════════
if view == "🏠 Início":
    render_home(df_all, liga_labels, source_key)

elif view == "🎯 Lay 0x1":
    render_lay_01(df_all, df, source_key)

elif view == "🏆 Liga":
    st.markdown(f"# {liga_full}")
    st.markdown(f"### Temporada {temp_sel}")

    analysis_id = st.session_state.get(f"analysis_match_{source_key}")
    analysis_match = df[df["id_api"].eq(analysis_id)] if analysis_id is not None else df.iloc[0:0]
    if not analysis_match.empty:
        st.button(
            "← Voltar aos próximos jogos",
            key=f"back_home_{source_key}",
            on_click=back_to_home,
            args=(source_key,),
        )
        render_match_analysis(analysis_match.iloc[0], df_all, source_key)

    st.markdown("---")

    # KPIs
    c1, c2, c3, c4, c5 = st.columns(5)
    total    = len(df)
    played   = len(df_played)
    total_gols = int(df_played["gols_casa"].sum() + df_played["gols_fora"].sum())
    media_gols = round(total_gols / played, 2) if played else 0
    home_wins = (df_played["vencedor"] == "HOME_TEAM").sum()
    away_wins = (df_played["vencedor"] == "AWAY_TEAM").sum()
    draws_t   = (df_played["vencedor"] == "DRAW").sum()

    c1.metric("Partidas", total)
    c2.metric("Disputadas", played)
    c3.metric("Gols totais", total_gols)
    c4.metric("Média gols/jogo", media_gols)
    c5.metric("% Vitória mandante", f"{home_wins/played*100:.1f}%" if played else "—")

    st.markdown("---")

    tab1, tab2, tab3 = st.tabs(["📋 Classificação", "📊 Estatísticas", "📅 Calendário"])

    # ── TAB 1: Classificação ──────────────────────────────────────────────────
    with tab1:
        official_standings = pd.DataFrame()
        if source_key == "onefootball" and not df.empty and df["liga_id"].notna().any():
            league_id = int(df.loc[df["liga_id"].notna(), "liga_id"].iloc[0])
            league_seasons = df_all.loc[
                df_all["liga_codigo"].eq(liga_sel), "temporada"
            ].dropna()
            if league_seasons.empty or temp_sel == league_seasons.max():
                official_standings = load_official_standings(DB_PATH, league_id)
        standings = (
            official_standings
            if not official_standings.empty
            else build_standings(df_played)
        )
        if not official_standings.empty:
            st.caption("Classificação oficial atual fornecida pelo OneFootball.")

        # Color rows
        def style_standings(val, col):
            if col == "Pts":
                return "color: #4ade80; font-weight: 700; font-family: 'Bebas Neue', sans-serif; font-size: 1.1rem;"
            if col == "SG":
                if isinstance(val, (int, float)):
                    return "color: #4ade80;" if val > 0 else ("color: #f87171;" if val < 0 else "color: #fbbf24;")
            return ""

        st.dataframe(
            standings.style.map(
                lambda v: style_standings(v, "Pts"), subset=["Pts"]
            ).map(
                lambda v: style_standings(v, "SG"), subset=["SG"]
            ).background_gradient(subset=["Pts"], cmap="Greens")
            .format({"SG": lambda x: f"+{x}" if x > 0 else str(x)}),
            use_container_width=True,
            height=600,
        )

    # ── TAB 2: Estatísticas ───────────────────────────────────────────────────
    with tab2:
        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("#### Distribuição de Resultados")
            labels = ["Vitória Mandante", "Empate", "Vitória Visitante"]
            values = [int(home_wins), int(draws_t), int(away_wins)]
            colors = ["#4ade80", "#fbbf24", "#f87171"]
            fig_pie = go.Figure(go.Pie(
                labels=labels, values=values,
                hole=0.55,
                marker=dict(colors=colors, line=dict(color="#0d1117", width=2)),
                textfont=dict(size=13, family="DM Sans"),
            ))
            fig_pie.update_layout(**PLOTLY_THEME, showlegend=True,
                legend=dict(orientation="h", y=-0.05, font=dict(color="#8b949e")))
            st.plotly_chart(fig_pie, use_container_width=True)

        with col_b:
            st.markdown("#### Gols por Mês")
            gols_mes = df_played.groupby("mes").agg(
                gols=("gols_casa", lambda x: x.sum() + df_played.loc[x.index, "gols_fora"].sum()),
                jogos=("id_api", "count")
            ).reset_index()
            gols_mes["media"] = (gols_mes["gols"] / gols_mes["jogos"]).round(2)
            fig_bar = go.Figure()
            fig_bar.add_bar(x=gols_mes["mes"], y=gols_mes["gols"],
                            marker_color="#4ade80", name="Gols", opacity=0.85)
            fig_bar.add_scatter(x=gols_mes["mes"], y=gols_mes["media"],
                                mode="lines+markers", name="Média/jogo",
                                line=dict(color="#fbbf24", width=2), yaxis="y2",
                                marker=dict(size=6))
            fig_bar.update_layout(**PLOTLY_THEME,
                yaxis2=dict(overlaying="y", side="right", gridcolor="rgba(0,0,0,0)",
                            tickfont=dict(color="#fbbf24")),
                legend=dict(orientation="h", y=1.1, font=dict(color="#8b949e")))
            st.plotly_chart(fig_bar, use_container_width=True)

        # Top scorers (by team proxy — goals scored)
        st.markdown("#### Gols Marcados por Time (Mandante + Visitante)")
        gf_home = df_played.groupby("time_casa")["gols_casa"].sum().reset_index().rename(
            columns={"time_casa": "time", "gols_casa": "gols"})
        gf_away = df_played.groupby("time_fora")["gols_fora"].sum().reset_index().rename(
            columns={"time_fora": "time", "gols_fora": "gols"})
        gf_total = pd.concat([gf_home, gf_away]).groupby("time")["gols"].sum().sort_values(ascending=True).reset_index()

        fig_hbar = go.Figure(go.Bar(
            x=gf_total["gols"], y=gf_total["time"],
            orientation="h",
            marker=dict(
                color=gf_total["gols"],
                colorscale=[[0, "#14532d"], [1, "#4ade80"]],
                showscale=False,
            ),
            text=gf_total["gols"], textposition="outside",
            textfont=dict(color="#4ade80", size=11),
        ))
        fig_hbar.update_layout(**PLOTLY_THEME, height=max(400, len(gf_total) * 28))
        fig_hbar.update_xaxes(gridcolor="#21262d")
        fig_hbar.update_yaxes(gridcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_hbar, use_container_width=True)

    # ── TAB 3: Calendário ─────────────────────────────────────────────────────
    with tab3:
        st.markdown("#### Próximas Partidas")
        now = pd.Timestamp.now(tz="UTC")
        upcoming = (
            df[df["gols_casa"].isna() & (df["data_partida"] >= now)]
            .sort_values("data_partida", ascending=True)
            .head(30)
            .reset_index(drop=True)
        )
        if upcoming.empty:
            st.info("Nenhuma partida futura registrada.")
        else:
            cols_show = ["data_partida", "time_casa", "time_fora"]
            upcoming_disp = upcoming[cols_show].copy()
            upcoming_disp["data_partida"] = upcoming_disp["data_partida"].dt.tz_convert(
                "America/Sao_Paulo"
            ).dt.strftime("%d/%m/%Y %H:%M")
            upcoming_disp.columns = ["Data", "Mandante", "Visitante"]
            st.caption("Ordem: partida mais próxima primeiro. Clique em uma linha para abrir a análise.")
            selected_match = st.dataframe(
                upcoming_disp,
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key=f"upcoming_{source_key}_{liga_sel}_{temp_sel}",
            )
            selected_rows = selected_match.selection.rows
            if selected_rows and 0 <= selected_rows[0] < len(upcoming):
                selected_id = int(upcoming.iloc[selected_rows[0]]["id_api"])
                if st.session_state.get(f"analysis_match_{source_key}") != selected_id:
                    st.session_state[f"analysis_match_{source_key}"] = selected_id
                    st.rerun()

        st.markdown("#### Últimas Partidas Disputadas")
        recent = df_played.sort_values("data_partida", ascending=False).head(20)
        if recent.empty:
            st.info("Nenhuma partida disputada registrada.")
        else:
            recent_disp = recent[["data_partida", "time_casa", "gols_casa", "gols_fora", "time_fora", "vencedor"]].copy()
            recent_disp["data_partida"] = recent_disp["data_partida"].dt.strftime("%d/%m/%Y")
            recent_disp["Placar"] = recent_disp["gols_casa"].astype(int).astype(str) + " × " + recent_disp["gols_fora"].astype(int).astype(str)
            recent_disp["Resultado"] = recent_disp["vencedor"].map({
                "HOME_TEAM": "🟢 Mandante", "AWAY_TEAM": "🔴 Visitante", "DRAW": "🟡 Empate"
            })
            recent_disp = recent_disp[["data_partida", "time_casa", "Placar", "time_fora", "Resultado"]]
            recent_disp.columns = ["Data", "Mandante", "Placar", "Visitante", "Resultado"]
            st.dataframe(recent_disp, use_container_width=True, hide_index=True)


# ═════════════════════════════════════════════════════════════════════════════
# VIEW: TIME
# ═════════════════════════════════════════════════════════════════════════════
else:
    st.markdown(f"# {time_sel}")
    st.markdown(f"#### {liga_full} · Temporada {temp_sel}")
    st.markdown("---")

    s = team_stats(df_played, time_sel)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Jogos",    s["played"])
    c2.metric("Pontos",   s["pts"])
    c3.metric("Vitórias", s["wins"])
    c4.metric("Empates",  s["draws"])
    c5.metric("Derrotas", s["losses"])
    c6.metric("Saldo de Gols", f"{'+' if s['gd']>=0 else ''}{s['gd']}")

    st.markdown("---")

    # Build team game list
    home_g = df_played[df_played["time_casa"] == time_sel].copy()
    away_g = df_played[df_played["time_fora"] == time_sel].copy()
    home_g["local"] = "Casa"
    away_g["local"] = "Fora"
    home_g["oponente"]    = home_g["time_fora"]
    away_g["oponente"]    = away_g["time_casa"]
    home_g["gols_pro"]    = home_g["gols_casa"];   home_g["gols_contra"] = home_g["gols_fora"]
    away_g["gols_pro"]    = away_g["gols_fora"];   away_g["gols_contra"] = away_g["gols_casa"]
    home_g["resultado"]   = home_g["vencedor"].map({"HOME_TEAM":"V","AWAY_TEAM":"D","DRAW":"E"})
    away_g["resultado"]   = away_g["vencedor"].map({"AWAY_TEAM":"V","HOME_TEAM":"D","DRAW":"E"})

    team_games = pd.concat([home_g, away_g]).sort_values("data_partida")
    team_games["pts_jogo"] = team_games["resultado"].map({"V": 3, "E": 1, "D": 0})
    team_games["pts_acum"] = team_games["pts_jogo"].cumsum()
    team_games["jogo_num"] = range(1, len(team_games) + 1)

    tab1, tab2, tab3 = st.tabs(["📈 Desempenho", "⚽ Gols", "📋 Jogos"])

    # ── TAB 1: Desempenho ─────────────────────────────────────────────────────
    with tab1:
        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("#### Evolução de Pontos")
            color_map = {"V": "#4ade80", "E": "#fbbf24", "D": "#f87171"}
            fig_pts = go.Figure()
            fig_pts.add_scatter(
                x=team_games["jogo_num"], y=team_games["pts_acum"],
                mode="lines", fill="tozeroy",
                line=dict(color="#4ade80", width=2),
                fillcolor="rgba(74,222,128,0.08)",
                name="Pontos acumulados",
            )
            for _, row in team_games.iterrows():
                fig_pts.add_scatter(
                    x=[row["jogo_num"]], y=[row["pts_acum"]],
                    mode="markers",
                    marker=dict(color=color_map.get(row["resultado"], "#888"), size=9, line=dict(color="#0d1117", width=1)),
                    showlegend=False,
                    hovertext=f"{row['oponente']} ({row['local']})<br>{int(row['gols_pro'])}×{int(row['gols_contra'])} — {row['resultado']}",
                    hoverinfo="text",
                )
            fig_pts.update_layout(**PLOTLY_THEME,
                xaxis_title="Jogo", yaxis_title="Pontos",
                height=300)
            st.plotly_chart(fig_pts, use_container_width=True)

        with col_b:
            st.markdown("#### Resultado por Jogo")
            result_colors = [color_map.get(r, "#888") for r in team_games["resultado"]]
            fig_res = go.Figure(go.Bar(
                x=team_games["jogo_num"],
                y=team_games["pts_jogo"],
                marker_color=result_colors,
                text=team_games["resultado"],
                textposition="outside",
                textfont=dict(size=10),
                hovertext=team_games.apply(
                    lambda r: f"{r['oponente']} ({r['local']})<br>{int(r['gols_pro'])}×{int(r['gols_contra'])}", axis=1
                ),
                hoverinfo="text",
            ))
            fig_res.update_layout(**PLOTLY_THEME, xaxis_title="Jogo", yaxis_title="Pts", height=300)
            fig_res.update_yaxes(range=[0, 4], tickvals=[0,1,3])
            st.plotly_chart(fig_res, use_container_width=True)

        # Win rate casa vs fora
        st.markdown("#### Casa vs Fora")
        local_stats = team_games.groupby(["local", "resultado"]).size().unstack(fill_value=0).reset_index()
        for col in ["V", "E", "D"]:
            if col not in local_stats.columns:
                local_stats[col] = 0

        fig_loc = go.Figure()
        fig_loc.add_bar(name="Vitória",  x=local_stats["local"], y=local_stats["V"],  marker_color="#4ade80")
        fig_loc.add_bar(name="Empate",   x=local_stats["local"], y=local_stats["E"],  marker_color="#fbbf24")
        fig_loc.add_bar(name="Derrota",  x=local_stats["local"], y=local_stats["D"],  marker_color="#f87171")
        fig_loc.update_layout(**PLOTLY_THEME, barmode="group", height=280,
            legend=dict(orientation="h", y=1.1, font=dict(color="#8b949e")))
        st.plotly_chart(fig_loc, use_container_width=True)

    # ── TAB 2: Gols ───────────────────────────────────────────────────────────
    with tab2:
        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("#### Gols Marcados vs Sofridos por Jogo")
            fig_gols = go.Figure()
            fig_gols.add_scatter(
                x=team_games["jogo_num"], y=team_games["gols_pro"],
                mode="lines+markers", name="Marcados",
                line=dict(color="#4ade80", width=2), marker=dict(size=6),
            )
            fig_gols.add_scatter(
                x=team_games["jogo_num"], y=team_games["gols_contra"],
                mode="lines+markers", name="Sofridos",
                line=dict(color="#f87171", width=2), marker=dict(size=6),
            )
            fig_gols.update_layout(**PLOTLY_THEME, height=300,
                legend=dict(orientation="h", y=1.1, font=dict(color="#8b949e")))
            st.plotly_chart(fig_gols, use_container_width=True)

        with col_b:
            st.markdown("#### Gols Acumulados")
            team_games["gols_pro_acum"]    = team_games["gols_pro"].cumsum()
            team_games["gols_contra_acum"] = team_games["gols_contra"].cumsum()
            fig_acum = go.Figure()
            fig_acum.add_scatter(
                x=team_games["jogo_num"], y=team_games["gols_pro_acum"],
                fill="tozeroy", name="Marcados",
                line=dict(color="#4ade80"), fillcolor="rgba(74,222,128,0.1)",
            )
            fig_acum.add_scatter(
                x=team_games["jogo_num"], y=team_games["gols_contra_acum"],
                fill="tozeroy", name="Sofridos",
                line=dict(color="#f87171"), fillcolor="rgba(248,113,113,0.08)",
            )
            fig_acum.update_layout(**PLOTLY_THEME, height=300,
                legend=dict(orientation="h", y=1.1, font=dict(color="#8b949e")))
            st.plotly_chart(fig_acum, use_container_width=True)

        # Scoreline frequency
        st.markdown("#### Placares Mais Frequentes")
        team_games["placar"] = (
            team_games["gols_pro"].astype(int).astype(str) + "×" +
            team_games["gols_contra"].astype(int).astype(str)
        )
        placar_freq = team_games["placar"].value_counts().head(10).reset_index()
        placar_freq.columns = ["Placar", "Frequência"]
        fig_placar = go.Figure(go.Bar(
            x=placar_freq["Placar"], y=placar_freq["Frequência"],
            marker_color="#4ade80", opacity=0.85,
            text=placar_freq["Frequência"], textposition="outside",
        ))
        fig_placar.update_layout(**PLOTLY_THEME, height=260)
        st.plotly_chart(fig_placar, use_container_width=True)

    # ── TAB 3: Jogos ─────────────────────────────────────────────────────────
    with tab3:
        st.markdown("#### Todos os Jogos")
        show = team_games[["data_partida", "local", "oponente", "gols_pro", "gols_contra", "resultado", "pts_acum"]].copy()
        show["data_partida"] = show["data_partida"].dt.strftime("%d/%m/%Y")
        show["Placar"] = show["gols_pro"].astype(int).astype(str) + " × " + show["gols_contra"].astype(int).astype(str)
        show["Res"] = show["resultado"].map({"V": "✅ Vitória", "E": "🟡 Empate", "D": "❌ Derrota"})
        show = show[["data_partida", "local", "oponente", "Placar", "Res", "pts_acum"]]
        show.columns = ["Data", "Local", "Oponente", "Placar", "Resultado", "Pts Acum."]
        st.dataframe(show, use_container_width=True, hide_index=True, height=500)
