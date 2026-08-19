"""
Diagnóstico do Chrome/Selenium — rode antes do scraper.
pip install selenium webdriver-manager
"""

import os
import subprocess
import sys

print("=" * 60)
print("DIAGNÓSTICO CHROME + SELENIUM")
print("=" * 60)

# 1. Versão do Python
print(f"\n[1] Python: {sys.version}")

# 2. Versão do Selenium
try:
    import selenium
    print(f"[2] Selenium: {selenium.__version__}")
except ImportError:
    print("[2] Selenium: NÃO INSTALADO")

# 3. webdriver-manager
try:
    import webdriver_manager
    print(f"[3] webdriver-manager: {webdriver_manager.__version__}")
except ImportError:
    print("[3] webdriver-manager: NÃO INSTALADO")

# 4. Localiza o Chrome instalado
print("\n[4] Procurando Chrome instalado...")
locais_chrome = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
]
chrome_path = None
for p in locais_chrome:
    if os.path.exists(p):
        chrome_path = p
        print(f"    ✅ Encontrado: {p}")
        break
if not chrome_path:
    print("    ❌ Chrome NÃO encontrado nos locais padrão!")
    print("       Instale o Chrome em https://www.google.com/chrome/")

# 5. Versão do Chrome
if chrome_path:
    print("\n[5] Versão do Chrome:")
    try:
        r = subprocess.run(
            [chrome_path, "--version"],
            capture_output=True, text=True, timeout=10
        )
        print(f"    {r.stdout.strip() or r.stderr.strip()}")
    except Exception as e:
        print(f"    Erro ao checar versão: {e}")

# 6. Testa abrir Chrome headless simples
print("\n[6] Teste básico headless (sem Selenium)...")
if chrome_path:
    try:
        r = subprocess.run(
            [chrome_path, "--headless=new", "--no-sandbox",
             "--disable-gpu", "--dump-dom", "about:blank"],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0 or "<html" in r.stdout.lower():
            print("    ✅ Chrome headless funciona!")
        else:
            print(f"    ❌ Chrome retornou código {r.returncode}")
            print(f"    stderr: {r.stderr[:300]}")
    except Exception as e:
        print(f"    ❌ Erro: {e}")

# 7. Baixa ChromeDriver e mostra o caminho
print("\n[7] Baixando ChromeDriver via webdriver-manager...")
try:
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    path = ChromeDriverManager().install()
    print(f"    ✅ ChromeDriver em: {path}")

    # Versão do ChromeDriver
    r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
    print(f"    Versão: {r.stdout.strip()}")
except Exception as e:
    print(f"    ❌ Erro: {e}")

# 8. Tenta abrir Selenium com logs verbose
print("\n[8] Tentando iniciar sessão Selenium com logs...")
try:
    import tempfile

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    log_path = os.path.join(tempfile.gettempdir(), "chromedriver.log")

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,720")
    if chrome_path:
        options.binary_location = chrome_path

    service = Service(
        ChromeDriverManager().install(),
        log_output=log_path
    )

    driver = webdriver.Chrome(service=service, options=options)
    driver.get("https://example.com")
    print(f"    ✅ Selenium OK! Título: {driver.title}")
    driver.quit()

except Exception as e:
    print(f"    ❌ Falha: {e}")
    # Mostra log do ChromeDriver
    try:
        with open(log_path, "r") as f:
            linhas = f.readlines()
        print(f"\n    --- ChromeDriver log ({log_path}) ---")
        for linha in linhas[-30:]:   # últimas 30 linhas
            print(f"    {linha.rstrip()}")
    except Exception:
        print(f"    (log não encontrado em {log_path})")

print("\n" + "=" * 60)
print("Diagnóstico completo. Cole o resultado aqui.")
print("=" * 60)