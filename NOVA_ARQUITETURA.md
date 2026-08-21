# TradeFot — React + API

O projeto agora pode rodar como uma única aplicação HTTP:

- `/api/*`: API FastAPI.
- `/api/docs`: documentação interativa.
- `/`: frontend React compilado.
- `backend/`: consultas, análises e execução dos coletores.
- `frontend/`: interface React/Vite.

Documentação detalhada dos endpoints: [`backend/API.md`](backend/API.md).

Os coletores `main.py`, `main2.py` e `main3.py` continuam sendo a fonte das
atualizações. Os bancos atuais não precisam ser convertidos.

## Desenvolvimento local

Instale o backend no ambiente virtual:

```powershell
.\venv\Scripts\pip.exe install -r backend\requirements.txt
```

Terminal 1:

```powershell
.\venv\Scripts\python.exe server.py
```

Terminal 2:

```powershell
cd frontend
npm install
npm run dev
```

O Vite abre `http://localhost:5173` e encaminha `/api` para a porta 8000.

Para testar exatamente como será publicado:

```powershell
cd frontend
npm run build
cd ..
.\venv\Scripts\python.exe server.py
```

Abra `http://localhost:8000`.

## VPS com uma única instância

```bash
docker compose up -d --build
```

A mesma instância entrega frontend e backend em `http://IP_DA_VPS:8000`.
O volume `tradefot-data` mantém os três bancos entre recriações do container.
Na primeira execução, os bancos distribuídos no projeto são copiados para o
volume se ele estiver vazio.

Exemplo de proxy reverso Nginx usando uma única origem:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Use apenas um worker do Uvicorn. A fila de atualização é mantida em memória e
serializa os scrapers para evitar disputa pelos bancos SQLite.

## Variáveis importantes

- `FOOTBALL_DATA_TOKEN` (ou `API`): token do football-data.org.
- `TRADEFOT_DATA_DIR`: diretório persistente dos bancos.
- `TRADEFOT_ACCESS_TOKEN_HASH`: hash do token que protege toda a API.
- `TRADEFOT_COOKIE_SECURE`: use `true` na VPS com HTTPS.
- `TRADEFOT_ML_AUTO_TRAIN`: verifica e treina modelos ao iniciar (padrão `true`).
- `TRADEFOT_ML_MIN_MATCHES`: mínimo de resultados por fonte (padrão `500`).
- `TRADEFOT_ML_EPOCHS`: limite de épocas do treino (padrão `60`).
- `TRADEFOT_MODEL_DIR`: diretório opcional dos modelos; por padrão usa `TRADEFOT_DATA_DIR/models`.
- `PORT`: porta HTTP, padrão `8000`.
- `CHROME_BIN` e `CHROMEDRIVER`: opcionais fora do Docker.

Não publique o arquivo `.env` no repositório ou dentro da imagem.
Use `.env.example` como referência e gere o acesso com
`python -m backend.app.auth generate`. Consulte `backend/API.md` para o fluxo de login.
