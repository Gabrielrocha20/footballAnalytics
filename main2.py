"""
Sofascore scraper — selenium + webdriver-manager (headless).

Modos:
  python main2.py          → atualização incremental se o banco já tiver dados
  python main2.py --update → força a atualização incremental
  python main2.py --full   → refaz a descoberta completa de países e torneios
"""

import json
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# Garante que os emojis das mensagens funcionem em terminais Windows legados.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

# ── Config ────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.getenv("SOFASCORE_DB_PATH", os.path.join(BASE_DIR, "futebol.db"))
DELAY      = 0.4
BASE       = "https://www.sofascore.com/api/v1"
ANO_MINIMO = datetime.now().year
MODO_UPDATE = "--update" in sys.argv
MODO_GOLS = "--goal-ids" in sys.argv
MODO_FULL = "--full" in sys.argv


# ── Driver ────────────────────────────────────────────────────
def criar_driver() -> webdriver.Chrome:
    options = Options()
    configured_binary = os.getenv("CHROME_BIN")
    candidates = [configured_binary] if configured_binary else []
    candidates.extend([
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ])
    for p in candidates:
        if os.path.exists(p):
            options.binary_location = p
            break

    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,720")
    options.add_argument("--log-level=3")

    log_path = os.path.join(tempfile.gettempdir(), "chromedriver_sofascore.log")
    driver_path = os.getenv("CHROMEDRIVER") or ChromeDriverManager().install()
    service  = Service(driver_path, log_output=log_path)
    return webdriver.Chrome(service=service, options=options)


def get_json(driver, url: str) -> dict | None:
    try:
        driver.get(url)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        body = driver.find_element(By.TAG_NAME, "body").text.strip()
        if not body or body.startswith("<"):
            return None
        return json.loads(body)
    except Exception as e:
        print(f"\n  ERRO {url[-60:]}: {e}")
        return None


# ── Banco ─────────────────────────────────────────────────────
conn   = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.executescript("""
CREATE TABLE IF NOT EXISTS partidas (
    id_api        INTEGER PRIMARY KEY,
    liga_id       INTEGER,
    liga_nome     TEXT,
    liga_pais     TEXT,
    temporada_id  INTEGER,
    temporada     INTEGER,
    rodada        TEXT,
    data_partida  INTEGER,
    status        TEXT,
    time_casa_id  INTEGER,
    time_casa     TEXT,
    time_fora_id  INTEGER,
    time_fora     TEXT,
    gols_casa     INTEGER,
    gols_fora     INTEGER,
    vencedor      TEXT
);
CREATE TABLE IF NOT EXISTS ligas_coletadas (
    liga_id      INTEGER,
    temporada_id INTEGER,
    PRIMARY KEY (liga_id, temporada_id)
);
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
""")
conn.commit()


def ja_coletado(liga_id, temporada_id):
    cursor.execute(
        "SELECT 1 FROM ligas_coletadas WHERE liga_id=? AND temporada_id=?",
        (liga_id, temporada_id)
    )
    return cursor.fetchone() is not None


def marcar_coletado(liga_id, temporada_id):
    cursor.execute("INSERT OR IGNORE INTO ligas_coletadas VALUES (?,?)", (liga_id, temporada_id))
    conn.commit()


def vencedor(gc, gf):
    if gc is None or gf is None:
        return None
    return "HOME_TEAM" if gc > gf else ("AWAY_TEAM" if gf > gc else "DRAW")


def ano_temporada(season: dict) -> int:
    try:
        return int(season.get("name", "0").split("/")[0])
    except Exception:
        return 0


def salvar_eventos(eventos: list, liga_id, liga_nome, liga_pais, temp_id, temp_ano) -> int:
    registros = []
    for e in eventos:
        gc  = e.get("homeScore", {}).get("current")
        gf_ = e.get("awayScore", {}).get("current")
        registros.append((
            e["id"], liga_id, liga_nome, liga_pais,
            temp_id, temp_ano,
            e.get("roundInfo", {}).get("name", ""),
            e.get("startTimestamp"),
            e.get("status", {}).get("description", ""),
            e["homeTeam"]["id"], e["homeTeam"]["name"],
            e["awayTeam"]["id"], e["awayTeam"]["name"],
            gc, gf_, vencedor(gc, gf_),
        ))
    if registros:
        cursor.executemany("""
        INSERT INTO partidas
            (id_api, liga_id, liga_nome, liga_pais, temporada_id, temporada,
             rodada, data_partida, status, time_casa_id, time_casa,
             time_fora_id, time_fora, gols_casa, gols_fora, vencedor)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id_api) DO UPDATE SET
            liga_id=excluded.liga_id,
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
        """, registros)
        conn.commit()
    return len(registros)


def atualizar_resultado(id_api, gc, gf_, status):
    """Atualiza placar de jogo que já aconteceu."""
    cursor.execute("""
        UPDATE partidas
        SET gols_casa=?, gols_fora=?, vencedor=?, status=?
        WHERE id_api=? AND gols_casa IS NULL
    """, (gc, gf_, vencedor(gc, gf_), status, id_api))
    conn.commit()
    return cursor.rowcount  # 1 se atualizou, 0 se já tinha resultado


def banco_tem_dados():
    cursor.execute("SELECT 1 FROM partidas LIMIT 1")
    return cursor.fetchone() is not None


def coletar_minutos_gols(driver, ids_partidas):
    """Coleta e armazena os gols ocorridos até o minuto 75 de partidas específicas."""
    ids = list(dict.fromkeys(int(match_id) for match_id in ids_partidas))
    total = len(ids)
    concluidas = 0
    erros = 0

    for indice, match_id in enumerate(ids, start=1):
        print(f"[GOLS {indice}/{total}] Partida {match_id}", flush=True)
        data = None
        forbidden = False
        for attempt in range(3):
            candidate = get_json(driver, f"{BASE}/event/{match_id}/incidents")
            if candidate and "incidents" in candidate:
                data = candidate
                break
            if candidate and candidate.get("error"):
                print(f"  Tentativa {attempt + 1}: {candidate['error']}", flush=True)
                forbidden = candidate["error"].get("code") == 403
            driver.get("https://www.sofascore.com/pt/football")
            time.sleep(2 + attempt)
        if not data or "incidents" not in data:
            erros += 1
            if forbidden:
                restantes = total - indice
                erros += restantes
                print(
                    "  SofaScore bloqueou temporariamente os incidentes (HTTP 403). "
                    "Aguarde o coletor principal terminar e tente novamente mais tarde.",
                    flush=True,
                )
                break
            continue

        goals = [
            incident
            for incident in data.get("incidents", [])
            if incident.get("incidentType") == "goal"
            and incident.get("incidentClass") != "missed"
        ]
        goals.sort(key=lambda goal: (int(goal.get("time", 999)), int(goal.get("addedTime") or 0)))

        def goal_minute(goal):
            return int(goal.get("time", 999)) + int(goal.get("addedTime") or 0)

        home_minutes = [
            goal_minute(goal)
            for goal in goals
            if goal.get("isHome") is True and goal_minute(goal) <= 75
        ]
        away_minutes = [
            goal_minute(goal)
            for goal in goals
            if goal.get("isHome") is False and goal_minute(goal) <= 75
        ]
        cursor.execute("DELETE FROM eventos_partida WHERE id_api=?", (match_id,))
        cursor.executemany(
            """
            INSERT INTO eventos_partida (
                id_api, evento_ordem, minuto, minuto_texto, lado, tipo,
                subtipo, jogador, assistente, jogador_entra, jogador_sai
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            """,
            [
                (
                    match_id,
                    order,
                    goal_minute(goal),
                    (
                        f"{int(goal.get('time', 0))}+{int(goal.get('addedTime'))}"
                        if goal.get("addedTime")
                        else str(int(goal.get("time", 0)))
                    ),
                    "HOME" if goal.get("isHome") is True else "AWAY",
                    "goal",
                    str(goal.get("incidentClass") or ""),
                    (goal.get("player") or {}).get("name"),
                    (goal.get("assist1") or {}).get("name"),
                )
                for order, goal in enumerate(goals)
            ],
        )
        cursor.execute(
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
                datetime.now().isoformat(timespec="seconds"),
                len(home_minutes),
                len(away_minutes),
                min(home_minutes) if home_minutes else None,
                min(away_minutes) if away_minutes else None,
                len(goals),
            ),
        )
        conn.commit()
        concluidas += 1
        time.sleep(max(DELAY, 1.0))

    print(
        f"MINUTOS_GOLS_RESULTADO concluidas={concluidas} erros={erros} total={total}",
        flush=True,
    )


# ── Modo atualização ──────────────────────────────────────────
def modo_update(driver):
    """
    Sincronização incremental baseada somente nas ligas/temporadas do banco.

    - atualiza placares que já deveriam ter terminado;
    - atualiza datas/status e inclui novos jogos das ligas com partidas nos
      próximos 21 dias;
    - não refaz a varredura mundial de categorias e torneios.
    """
    agora = int(datetime.now().timestamp())
    horizonte = agora + 21 * 24 * 60 * 60

    cursor.execute("""
        SELECT
            liga_id, temporada_id, liga_nome, liga_pais, temporada,
            MAX(CASE WHEN gols_casa IS NULL AND data_partida < ? THEN 1 ELSE 0 END) AS tem_pendente,
            MAX(CASE WHEN gols_casa IS NULL AND data_partida BETWEEN ? AND ? THEN 1 ELSE 0 END) AS tem_proximo
        FROM partidas
        GROUP BY liga_id, temporada_id, liga_nome, liga_pais, temporada
        HAVING tem_pendente = 1 OR tem_proximo = 1
        ORDER BY tem_pendente DESC, liga_nome
    """, (agora, agora, horizonte))
    ligas_ativas = cursor.fetchall()

    if not ligas_ativas:
        print("✅ Nenhuma liga precisa de sincronização neste momento.")
        return

    print(
        f"🔄 Sincronização incremental de {len(ligas_ativas)} liga/temporada(s).\n"
        "   Nenhuma busca de países ou catálogo completo será feita.\n"
    )
    total_sincronizados = 0
    total_resultados = 0
    falhas = 0

    for indice, (
        liga_id, temp_id, liga_nome, liga_pais, temp_ano, tem_pendente, tem_proximo
    ) in enumerate(ligas_ativas, start=1):
        print(
            f"[{indice}/{len(ligas_ativas)}] {liga_nome} ({liga_pais}) ... ",
            end="",
            flush=True,
        )
        sincronizados = 0
        resultados_antes = conn.total_changes

        if tem_pendente:
            cursor.execute(
                """
                SELECT id_api FROM partidas
                WHERE liga_id=? AND temporada_id=?
                  AND gols_casa IS NULL AND data_partida < ?
                """,
                (liga_id, temp_id, agora),
            )
            pending_ids = {row[0] for row in cursor.fetchall()}

            for pagina in range(20):
                data = get_json(
                    driver,
                    f"{BASE}/unique-tournament/{liga_id}/season/{temp_id}/events/last/{pagina}",
                )
                time.sleep(DELAY)
                if not data or not data.get("events"):
                    if pagina == 0:
                        falhas += 1
                    break

                sincronizados += salvar_eventos(
                    data["events"], liga_id, liga_nome, liga_pais, temp_id, temp_ano
                )
                returned_ids = {event["id"] for event in data["events"]}
                pending_ids -= returned_ids
                if not pending_ids or not data.get("hasNextPage", False):
                    break

        if tem_proximo:
            # A primeira página contém os jogos futuros mais próximos. O upsert
            # corrige adiamentos, horários/status e inclui partidas novas.
            data = get_json(
                driver,
                f"{BASE}/unique-tournament/{liga_id}/season/{temp_id}/events/next/0",
            )
            time.sleep(DELAY)
            if data and data.get("events"):
                sincronizados += salvar_eventos(
                    data["events"], liga_id, liga_nome, liga_pais, temp_id, temp_ano
                )
            else:
                falhas += 1

        changes = conn.total_changes - resultados_antes
        print(f"{sincronizados} recebidos · {changes} registros sincronizados")
        total_sincronizados += sincronizados
        total_resultados += changes

    print()
    print("=" * 60)
    print(f"Ligas/temporadas consultadas : {len(ligas_ativas)}")
    print(f"Eventos recebidos            : {total_sincronizados}")
    print(f"Registros sincronizados      : {total_resultados}")
    print(f"Consultas sem resposta       : {falhas}")
    print("Modo                         : incremental")
    print("=" * 60)
    # Mantém compatibilidade com o resumo lido pelo app.py.
    print(f"Total de resultados atualizados: {total_resultados}")


# ── Coleta inicial ────────────────────────────────────────────
def modo_coleta(driver):
    # Warm-up
    print("[INIT] Carregando sofascore.com para gerar sessão...")
    driver.get("https://www.sofascore.com/pt/football")
    time.sleep(3)
    print("[INIT] Pronto.\n")

    # Teste da API
    print("[TESTE] Verificando API...")
    hoje = datetime.now().strftime("%Y-%m-%d")
    teste = get_json(driver, f"{BASE}/sport/football/scheduled-events/{hoje}")
    if not teste:
        print("❌ API não respondeu. Encerrando.")
        return
    print(f"✅ API OK — {len(teste.get('events', []))} jogos hoje.\n")

    # Categorias
    print("[1/3] Buscando categorias...")
    data = get_json(driver, f"{BASE}/sport/football/categories")
    if not data:
        print("❌ Falha ao buscar categorias.")
        return
    categorias = data.get("categories", [])
    print(f"      {len(categorias)} categorias encontradas.\n")

    # Torneios
    print("[2/3] Buscando torneios...")
    todos_torneios = []
    for idx, cat in enumerate(categorias):
        data = get_json(driver, f"{BASE}/category/{cat['id']}/unique-tournaments")
        time.sleep(DELAY * 0.3)
        if not data:
            continue
        for grupo in data.get("groups", []):
            for t in grupo.get("uniqueTournaments", []):
                todos_torneios.append({
                    "liga_id":   t["id"],
                    "liga_nome": t.get("name", "?"),
                    "liga_pais": cat.get("name", "?"),
                })
        if (idx + 1) % 20 == 0:
            print(f"      {idx+1}/{len(categorias)} países — {len(todos_torneios)} torneios...")
    print(f"      Total: {len(todos_torneios)} torneios.\n")

    # Jogos
    print("[3/3] Coletando jogos...")
    print("-" * 60)

    total_jogos = 0
    coletados   = 0
    pulados     = 0

    for i, torneio in enumerate(todos_torneios):
        liga_id   = torneio["liga_id"]
        liga_nome = torneio["liga_nome"]
        liga_pais = torneio["liga_pais"]

        data = get_json(driver, f"{BASE}/unique-tournament/{liga_id}/seasons")
        time.sleep(DELAY)
        if not data or not data.get("seasons"):
            continue

        season   = data["seasons"][0]
        temp_id  = season["id"]
        temp_ano = ano_temporada(season)
        temp_str = season.get("name", "?")

        if temp_ano < ANO_MINIMO:
            continue

        if ja_coletado(liga_id, temp_id):
            pulados += 1
            continue

        print(f"[{i+1}/{len(todos_torneios)}] {liga_nome} ({liga_pais}) {temp_str}", end=" ... ", flush=True)

        n_jogos = 0

        for pagina in range(50):
            data = get_json(
                driver,
                f"{BASE}/unique-tournament/{liga_id}/season/{temp_id}/events/last/{pagina}"
            )
            time.sleep(DELAY)
            if not data or not data.get("events"):
                break
            n_jogos += salvar_eventos(
                data["events"], liga_id, liga_nome, liga_pais, temp_id, temp_ano
            )
            if not data.get("hasNextPage", False):
                break

        for pagina in range(20):
            data = get_json(
                driver,
                f"{BASE}/unique-tournament/{liga_id}/season/{temp_id}/events/next/{pagina}"
            )
            time.sleep(DELAY)
            if not data or not data.get("events"):
                break
            n_jogos += salvar_eventos(
                data["events"], liga_id, liga_nome, liga_pais, temp_id, temp_ano
            )
            if not data.get("hasNextPage", False):
                break

        print(f"{n_jogos} jogos ✅" if n_jogos else "sem jogos")
        total_jogos += n_jogos
        coletados   += 1
        marcar_coletado(liga_id, temp_id)

    print()
    print("=" * 60)
    print(f"Ligas coletadas : {coletados}")
    print(f"Ligas puladas   : {pulados} (já no banco)")
    print(f"Total de jogos  : {total_jogos:,}")
    print(f"Banco           : {DB_PATH}")
    print("=" * 60)


# ── Entry point ───────────────────────────────────────────────
if __name__ == "__main__":
    usar_coleta_completa = MODO_FULL or not banco_tem_dados()
    if MODO_GOLS:
        modo_nome = "MINUTOS DOS GOLS"
    elif usar_coleta_completa:
        modo_nome = "COLETA COMPLETA"
    else:
        modo_nome = "ATUALIZAÇÃO INCREMENTAL"
    print("=" * 60)
    print("SOFASCORE SCRAPER —", modo_nome)
    print("=" * 60)

    print("\n[INIT] Iniciando Chrome headless...")
    driver = criar_driver()
    print("[INIT] Chrome iniciado!\n")

    try:
        if MODO_GOLS:
            try:
                position = sys.argv.index("--goal-ids")
                ids_argument = sys.argv[position + 1]
                ids_partidas = [value for value in ids_argument.split(",") if value.strip()]
            except (ValueError, IndexError):
                raise SystemExit("Informe --goal-ids ID1,ID2,...")
            driver.get("https://www.sofascore.com/pt/football")
            time.sleep(2)
            coletar_minutos_gols(driver, ids_partidas)
        elif not usar_coleta_completa:
            # Warm-up rápido antes do update
            driver.get("https://www.sofascore.com/pt/football")
            time.sleep(2)
            modo_update(driver)
        else:
            modo_coleta(driver)
    finally:
        driver.quit()
        cursor.close()
        conn.close()
