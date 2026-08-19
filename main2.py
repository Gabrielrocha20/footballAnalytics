"""
Sofascore scraper — selenium + webdriver-manager (headless).

Modos:
  python sofascore_scraper.py          → coleta inicial completa
  python sofascore_scraper.py --update → só atualiza resultados de jogos que já aconteceram
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

# ── Config ────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.path.join(BASE_DIR, "futebol.db")
DELAY      = 0.4
BASE       = "https://www.sofascore.com/api/v1"
ANO_MINIMO = datetime.now().year
MODO_UPDATE = "--update" in sys.argv


# ── Driver ────────────────────────────────────────────────────
def criar_driver() -> webdriver.Chrome:
    options = Options()
    for p in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]:
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
    service  = Service(ChromeDriverManager().install(), log_output=log_path)
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
        INSERT OR IGNORE INTO partidas
            (id_api, liga_id, liga_nome, liga_pais, temporada_id, temporada,
             rodada, data_partida, status, time_casa_id, time_casa,
             time_fora_id, time_fora, gols_casa, gols_fora, vencedor)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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


# ── Modo atualização ──────────────────────────────────────────
def modo_update(driver):
    """
    Busca partidas no banco sem resultado (gols_casa IS NULL)
    cujo timestamp já passou, e tenta buscar o resultado via API.
    Agrupa por liga+temporada para minimizar requests.
    """
    agora = int(datetime.now().timestamp())

    cursor.execute("""
        SELECT DISTINCT liga_id, temporada_id, liga_nome, liga_pais
        FROM partidas
        WHERE gols_casa IS NULL AND data_partida < ?
    """, (agora,))
    ligas_pendentes = cursor.fetchall()

    if not ligas_pendentes:
        print("✅ Nenhuma partida pendente de resultado.")
        return

    print(f"🔄 {len(ligas_pendentes)} liga(s) com jogos para atualizar...\n")
    total_atualizados = 0

    for liga_id, temp_id, liga_nome, liga_pais in ligas_pendentes:
        print(f"  Atualizando {liga_nome} ({liga_pais}) ... ", end="", flush=True)
        atualizados = 0

        # Busca páginas de jogos passados até não ter mais pendentes dessa liga
        for pagina in range(50):
            data = get_json(
                driver,
                f"{BASE}/unique-tournament/{liga_id}/season/{temp_id}/events/last/{pagina}"
            )
            time.sleep(DELAY)
            if not data or not data.get("events"):
                break

            for e in data["events"]:
                gc  = e.get("homeScore", {}).get("current")
                gf_ = e.get("awayScore", {}).get("current")
                if gc is None:
                    continue
                status = e.get("status", {}).get("description", "")
                atualizados += atualizar_resultado(e["id"], gc, gf_, status)

            if not data.get("hasNextPage", False):
                break

        print(f"{atualizados} atualizados ✅" if atualizados else "nada novo")
        total_atualizados += atualizados

    print(f"\n✅ Total de resultados atualizados: {total_atualizados}")


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
    print("=" * 60)
    print("SOFASCORE SCRAPER —", "MODO UPDATE" if MODO_UPDATE else "COLETA INICIAL")
    print("=" * 60)

    print("\n[INIT] Iniciando Chrome headless...")
    driver = criar_driver()
    print("[INIT] Chrome iniciado!\n")

    try:
        if MODO_UPDATE:
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
