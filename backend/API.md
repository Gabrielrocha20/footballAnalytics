# TradeFot Backend API

Referência da API HTTP usada pelo frontend React do TradeFot.

## Visão geral

Por padrão, backend e frontend são entregues pela mesma origem:

```text
http://localhost:8000/          Frontend React
http://localhost:8000/api/     API
http://localhost:8000/api/docs Documentação Swagger interativa
```

Todos os corpos e respostas usam JSON. As datas das partidas são retornadas em
ISO 8601 e UTC, por exemplo `2026-08-22T19:00:00Z`. O frontend converte essas
datas para `America/Sao_Paulo`.

A API lê três bancos existentes e normaliza suas diferenças:

| Chave | Coletor | Banco | Minutos dos gols |
|---|---|---|---|
| `onefootball` | `main3.py` | `futebol3.db` | Sim |
| `sofascore` | `main2.py` | `futebol.db` | Sim |
| `football_data` | `main.py` | `futebol2.db` | Não |

As requisições `GET` de dados apenas consultam os bancos. Os scrapers e APIs
externas só são acionados pelos endpoints `POST /api/sync` e
`POST /api/minutes`.

A partir da versão 1.3, o backend também mantém um modelo neural separado para
cada fonte. Os artefatos ficam em `models/` dentro do diretório de dados e são
atualizados automaticamente quando novos resultados entram no banco.

## Autenticação por token

Toda a API de dados é privada. Somente estas rotas são públicas:

- `GET /api/health`
- `GET /api/auth/status`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `/api/docs` e `/api/openapi.json`

Se nenhum token estiver configurado, as rotas protegidas respondem HTTP `503`.
Isso é intencional: a API falha fechada e não expõe os dados por acidente.

### 1. Gerar o token

Na raiz do projeto, execute:

```powershell
.\venv\Scripts\python.exe -m backend.app.auth generate
```

O comando mostra duas informações:

1. O token puro, que deve ser guardado em um gerenciador de senhas.
2. O hash SHA-256 para colocar no `.env` do servidor.

Exemplo de configuração:

```env
TRADEFOT_ACCESS_TOKEN_HASH=hash_de_64_caracteres_gerado_pelo_comando
TRADEFOT_COOKIE_SECURE=false
```

Na VPS com domínio e HTTPS:

```env
TRADEFOT_COOKIE_SECURE=true
```

O token não pode ser recuperado a partir do hash. Se ele for perdido, gere
outro, substitua o hash no `.env` e reinicie o backend.

Também existe a alternativa mais simples, porém menos recomendada:

```env
TRADEFOT_ACCESS_TOKEN=token_puro
```

Não configure o token puro e o hash ao mesmo tempo. Se ambos existirem, o hash
tem prioridade. `TRADEFOT_ADMIN_TOKEN` continua aceito apenas por
compatibilidade com a versão anterior.

### 2. Formas de autenticação

O backend aceita três formas:

1. Cookie `HttpOnly` criado por `POST /api/auth/login`.
2. Header padrão `Authorization: Bearer TOKEN`.
3. Header `X-Access-Token: TOKEN`.

`X-Admin-Token` ainda é reconhecido para compatibilidade com o frontend
anterior, mas novas integrações devem usar cookie ou Bearer.

### 3. Exemplo com Bearer

```powershell
$token = Read-Host "Token TradeFot"
$headers = @{ Authorization = "Bearer $token" }
Invoke-RestMethod http://localhost:8000/api/sources -Headers $headers
```

Nos exemplos protegidos deste documento, considere que `$headers` já foi
definido dessa forma.

### 4. Exemplo com cookie de login

```powershell
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$token = Read-Host "Token TradeFot"
$body = @{ token = $token } | ConvertTo-Json

Invoke-RestMethod `
  -Uri http://localhost:8000/api/auth/login `
  -Method Post `
  -ContentType "application/json" `
  -Body $body `
  -WebSession $session

Invoke-RestMethod `
  -Uri http://localhost:8000/api/sources `
  -WebSession $session
```

## Formato normalizado de uma partida

Os endpoints de calendário e análise usam a seguinte estrutura básica:

```json
{
  "id_api": 2652431,
  "liga_id": "16",
  "liga_codigo": "ONE_16",
  "liga_nome": "Brasileirão Betano",
  "liga_pais": "Brazil",
  "temporada_id": null,
  "temporada": 2026,
  "rodada": "Rodada 24",
  "data_partida": "2026-08-22T19:00:00Z",
  "status": "SCHEDULED",
  "time_casa_id": 1666,
  "time_casa": "Fluminense",
  "time_fora_id": 2673,
  "time_fora": "Remo",
  "gols_casa": null,
  "gols_fora": null,
  "vencedor": null,
  "gols_casa_ate_75": null,
  "gols_fora_ate_75": null,
  "primeiro_gol_casa_minuto": null,
  "primeiro_gol_fora_minuto": null
}
```

Campos indisponíveis em determinada fonte são retornados como `null` ou string
vazia. `liga_id` é sempre serializado como string porque no football-data.org o
identificador é um código como `BSA` ou `PL`.

---

## Saúde da aplicação

### `GET /api/health`

Verifica se o processo HTTP está respondendo.

Resposta:

```json
{
  "status": "ok",
  "service": "tradefot"
}
```

Exemplo:

```powershell
Invoke-RestMethod http://localhost:8000/api/health
```

---

## Sessão e login

### `GET /api/auth/status`

Rota pública usada pela tela de login para saber se o servidor já possui um
token configurado.

```json
{
  "configured": true,
  "methods": ["cookie", "bearer", "x-access-token"]
}
```

Se `configured=false`, gere o token, configure o `.env` e reinicie o servidor.

### `POST /api/auth/login`

Valida o token e cria o cookie `tradefot_session`.

Body:

```json
{
  "token": "token-puro-gerado-pelo-comando"
}
```

O token deve ter entre 16 e 512 caracteres. Resposta:

```json
{
  "authenticated": true,
  "token_type": "bearer"
}
```

O cookie criado possui estas propriedades:

- `HttpOnly`: JavaScript não consegue ler o token.
- `SameSite=Strict`: reduz envio em requisições iniciadas por outros sites.
- validade de 30 dias.
- `Secure` quando `TRADEFOT_COOKIE_SECURE=true`.
- caminho `/`, portanto vale para toda a aplicação na mesma origem.

O frontend deve chamar o login com `credentials: "include"` se estiver sendo
executado em outra origem durante o desenvolvimento:

```javascript
await fetch('/api/auth/login', {
  method: 'POST',
  credentials: 'include',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ token }),
})
```

Nunca grave o token puro em logs ou inclua-o no código-fonte do frontend.

### `GET /api/auth/me`

Rota protegida para conferir se a sessão atual é válida.

```json
{
  "authenticated": true,
  "role": "owner"
}
```

Se o cookie ou Bearer estiver ausente ou incorreto, retorna HTTP `401`.

### `POST /api/auth/logout`

Remove o cookie de sessão. É uma rota pública para permitir limpar cookies
antigos mesmo quando o token foi trocado.

```json
{
  "authenticated": false
}
```

O logout encerra o acesso por cookie. Um token Bearer guardado pelo cliente deve
ser removido pelo próprio frontend.

---

## Fontes disponíveis

### `GET /api/sources`

Retorna os bancos disponíveis e seus totais atuais.

Resposta:

```json
[
  {
    "key": "onefootball",
    "name": "OneFootball",
    "description": "Catálogo amplo, tabela e minutos dos gols",
    "available": true,
    "matches": 65376,
    "leagues": 427,
    "supports_minutes": true
  }
]
```

`available=false` indica que o arquivo do banco ainda não existe.

---

## Ligas

### `GET /api/leagues`

Lista as ligas da fonte selecionada. A pesquisa considera nome da liga, país,
código e nomes dos times. A comparação ignora maiúsculas e acentos.

Parâmetros:

| Nome | Tipo | Padrão | Descrição |
|---|---|---|---|
| `source` | string | `onefootball` | Fonte de dados |
| `search` | string | vazio | Liga, país, código ou time; máximo 100 caracteres |

Exemplo:

```http
GET /api/leagues?source=onefootball&search=brasileirao
```

Resposta:

```json
[
  {
    "id": "16",
    "name": "Brasileirão Betano",
    "country": "Brazil",
    "code": "ONE_16",
    "matches": 380,
    "seasons": [2026]
  }
]
```

Quando `search` contém um time, `matches` representa os registros que
participaram daquela busca, não necessariamente o total completo da liga.

### `GET /api/leagues/{league_id}`

Retorna a visão geral de uma liga: métricas, classificação, próximos jogos e
resultados recentes.

Parâmetros:

| Nome | Local | Tipo | Padrão |
|---|---|---|---|
| `league_id` | rota | string | obrigatório |
| `source` | query | string | `onefootball` |
| `season` | query | inteiro | todas as temporadas no banco |

Exemplos:

```http
GET /api/leagues/16?source=onefootball
GET /api/leagues/BSA?source=football_data&season=2026
```

Resposta resumida:

```json
{
  "league": {
    "id": "16",
    "name": "Brasileirão Betano",
    "country": "Brazil",
    "season": null
  },
  "stats": {
    "matches": 380,
    "played": 230,
    "goals": 580,
    "goals_per_match": 2.52
  },
  "standings": [],
  "upcoming": [],
  "recent": []
}
```

No OneFootball, `standings` usa a classificação oficial armazenada. Nas outras
fontes, a classificação é calculada a partir dos resultados existentes.

---

## Próximas partidas

### `GET /api/matches/upcoming`

Retorna partidas futuras em ordem cronológica, sempre da mais próxima para a
mais distante.

Parâmetros:

| Nome | Tipo | Padrão | Limite/descrição |
|---|---|---|---|
| `source` | string | `onefootball` | Fonte de dados |
| `league_id` | string | vazio | Restringe a uma liga |
| `search` | string | vazio | Liga, mandante ou visitante |
| `page` | inteiro | `1` | Mínimo 1 |
| `page_size` | inteiro | `30` | Entre 1 e 100 |

Exemplo:

```http
GET /api/matches/upcoming?source=onefootball&search=Fluminense&page=1&page_size=30
```

Resposta:

```json
{
  "items": [],
  "page": 1,
  "page_size": 30,
  "total": 18,
  "pages": 1
}
```

Cada item de `items` segue o formato normalizado de partida.

---

## Análise de uma partida

### `GET /api/matches/{match_id}/analysis`

Monta a análise completa usando somente partidas anteriores à data do jogo.

Parâmetros:

| Nome | Local | Tipo | Padrão |
|---|---|---|---|
| `match_id` | rota | inteiro | obrigatório |
| `source` | query | string | `onefootball` |

Exemplo:

```http
GET /api/matches/2652431/analysis?source=onefootball
```

A resposta contém:

| Campo | Conteúdo |
|---|---|
| `match` | Dados normalizados da partida |
| `prediction` | Probabilidades e gols esperados |
| `home` | Resumo e últimos 10 jogos do mandante |
| `away` | Resumo e últimos 10 jogos do visitante |
| `head_to_head` | Até 10 confrontos diretos anteriores |
| `lay_01` | Avaliação do método Lay 0x1 |
| `insights` | Sinais prontos de primeiro gol, reação, gol tardio, mando e classificação |
| `advanced` | Distribuição temporal, primeiro gol, métricas de trading e xG |
| `disclaimer` | Aviso sobre a natureza estatística da estimativa |

Exemplo de previsão:

```json
{
  "prediction": {
    "home": 45.0,
    "draw": 26.8,
    "away": 28.2,
    "expected_home_goals": 1.41,
    "expected_away_goals": 1.05
  }
}
```

O favorito é o resultado com maior probabilidade individual. Isso é uma
estimativa do modelo interno, não uma odd de mercado.

### Análise inteligente

`insights.items` transforma as métricas históricas em quatro leituras prontas
para o frontend:

- frequência com que o favorito do modelo abre o placar;
- capacidade de empatar ou vencer depois de sofrer o primeiro gol;
- frequência de gols do favorito após os 75 minutos;
- aproveitamento recente do visitante fora de casa.

Cada sinal informa `tone`, `title`, `detail`, `value`, `sample_size` e
`available`. O bloco também retorna a posição dos dois times em `standings`,
calculada somente com resultados anteriores ao início da partida e dentro da
mesma temporada. Assim, uma análise histórica não recebe dados do futuro.

Quando faltam eventos por minuto, `minute_coverage.missing_match_ids` lista as
partidas que podem ser enviadas a `POST /api/minutes`. Fontes sem suporte a
minutos retornam `minute_coverage.supported=false`.

### Poisson, placares exatos e odds justas

O modelo calcula o parâmetro esperado de gols (`lambda`) de cada equipe usando
as médias recentes de ataque e defesa, com ajustes de mando, forma e confronto
direto. Para cada quantidade `k` de gols:

```text
P(X = k) = (lambda^k × e^-lambda) / k!
```

O backend calcula de 0 a 12 gols por equipe para precificar os mercados e
normaliza a pequena massa residual. A matriz retornada em `score_matrix` contém
os 81 placares de `0-0` a `8-8`. `top_scorelines` contém os 10 mais prováveis.

Cada preço possui:

```json
{
  "probability": 45.02,
  "fair_odds": 2.221
}
```

A odd justa é calculada sem margem da casa:

```text
odd_justa = 1 / probabilidade_decimal
```

Mercados disponíveis em `prediction.markets`:

- `match_odds`: `home`, `draw`, `away`.
- `total_goals`: Over e Under 0.5, 1.5, 2.5, 3.5 e 4.5.
- `btts`: `yes` e `no`.
- `clean_sheet`: probabilidade de casa ou visitante não sofrer gol.
- `team_to_score`: probabilidade de cada equipe marcar pelo menos um gol.

Exemplo parcial:

```json
{
  "markets": {
    "match_odds": {
      "home": { "probability": 45.02, "fair_odds": 2.221 },
      "draw": { "probability": 26.75, "fair_odds": 3.738 },
      "away": { "probability": 28.23, "fair_odds": 3.543 }
    },
    "btts": {
      "yes": { "probability": 49.15, "fair_odds": 2.035 },
      "no": { "probability": 50.85, "fair_odds": 1.966 }
    }
  }
}
```

### Distribuição temporal de gols

`advanced.temporal_goals.home` e `.away` dividem os gols marcados e sofridos em:

- `0-15`
- `16-30`
- `31-45+`
- `46-60`
- `61-75`
- `76-90+`

Exemplo de um bloco:

```json
{
  "period": "76-90+",
  "scored": 3,
  "conceded": 3,
  "scored_share": 27.3,
  "conceded_share": 33.3,
  "matches_scored": 2,
  "matches_conceded": 3,
  "scored_match_rate": 20.0,
  "conceded_match_rate": 30.0
}
```

O perfil também retorna:

- `coverage`: percentual dos últimos jogos com eventos completos.
- `average_first_goal_minute`: média do primeiro gol da partida.
- `first_half_any_goal_rate`: jogos cobertos com algum gol até 45+.
- `after_75`: gols e frequência de jogos com gol após 75 minutos.

Uma partida só entra na cobertura quando a quantidade de eventos de gol salvos
é igual ou maior que o total de gols informado nos detalhes. Assim, ausência de
coleta não é confundida com ausência de gols.

### Impacto do primeiro gol

`advanced.first_goal_impact.home` e `.away` retornam:

```json
{
  "available": true,
  "sample_matches": 10,
  "covered_matches": 10,
  "matches_with_first_goal": 8,
  "scored_first": 4,
  "wins_after_scoring_first": 1,
  "conservation_rate": 25.0,
  "conceded_first": 4,
  "draws_or_wins_after_conceding_first": 3,
  "comeback_rate": 75.0
}
```

- `conservation_rate`: vitórias divididas pelas partidas em que o time abriu o
  placar.
- `comeback_rate`: empates ou vitórias divididos pelas partidas em que o time
  sofreu o primeiro gol.

Partidas 0-0 ficam na cobertura dos eventos, mas não entram nos denominadores
de primeiro gol.

### Métricas para trading

`advanced.trading_metrics` fornece separadamente para mandante e visitante:

- quantidade e percentual histórico de Ambas Marcam (`btts`);
- frequência de jogos sem marcar (`failed_to_score`);
- clean sheet geral, em casa e fora;
- tempo médio do primeiro gol;
- frequência de algum gol no primeiro tempo;
- gols marcados e sofridos após 75 minutos;
- cobertura dos dados temporais.

Clean sheet e BTTS usam os placares finais e funcionam mesmo sem eventos por
minuto. As métricas temporais devem sempre ser interpretadas junto com
`temporal_data_coverage`.

### Regressão à média por xG

`advanced.xg_regression` compara gols reais e xG nas janelas de 5 e 10 jogos
quando existem dados reais nas colunas:

```text
partidas_metricas.xg_casa
partidas_metricas.xg_fora
```

Resposta quando a fonte não possui xG:

```json
{
  "available": false,
  "reason": "A fonte não possui xG real armazenado para estes jogos.",
  "required_fields": [
    "partidas_metricas.xg_casa",
    "partidas_metricas.xg_fora"
  ]
}
```

O backend não transforma chutes ou gols em “xG estimado”. Ele somente publica
xG quando o provedor fornecer a métrica. Nas respostas verificadas durante a
implementação, OneFootball e SofaScore não entregaram xG para as partidas
testadas.

Quando disponível, `last_5` e `last_10` mostram gols, xG, diferença ofensiva e
defensiva e `finishing_signal`. O sinal é `overperforming` acima de +0,35 gol
por jogo sobre o xG, `underperforming` abaixo de -0,35 e `aligned` no intervalo.
O campo `coverage` informa quantos jogos da janela realmente possuíam xG.

### Histórico na perspectiva do time

Os itens em `home.history` e `away.history` acrescentam:

```json
{
  "venue": "home",
  "opponent": "Palmeiras",
  "goals_for": 2,
  "goals_against": 1,
  "result": "W",
  "goals_until_75": 1,
  "first_goal_minute": 32
}
```

`result` pode ser `W` (vitória), `D` (empate) ou `L` (derrota).

### Regra Lay 0x1

O bloco `lay_01` avalia:

1. O mandante precisa ser o favorito do modelo.
2. Precisam existir 10 jogos anteriores.
3. Os minutos precisam estar coletados nos 10 jogos.
4. O favorito precisa ter marcado entre 0 e 75 minutos em mais de 75% deles.

Com uma amostra de 10 jogos, o mínimo prático é `8/10`.

```json
{
  "lay_01": {
    "status": "approved",
    "home_favorite": true,
    "favorite_probability": 52.4,
    "sample_size": 10,
    "coverage": 10,
    "hits": 8,
    "percentage": 80.0,
    "threshold": 75,
    "minimum_hits": 8,
    "missing_match_ids": [],
    "history": []
  }
}
```

Estados possíveis:

| Estado | Significado |
|---|---|
| `approved` | Favorito em casa e 8/10 ou mais |
| `rejected` | Histórico completo, mas 75% ou menos |
| `pending_minutes` | Existem 10 jogos, mas faltam minutos |
| `not_home_favorite` | O mandante não é favorito |
| `insufficient_history` | Não há histórico suficiente para concluir |
| `unsupported` | A fonte não fornece minutos dos gols |

---

## Desempenho das análises

### `GET /api/performance`

Retorna a auditoria das previsões que foram congeladas antes do início das
partidas. O histórico fica em `TRADEFOT_DATA_DIR/tradefot_history.db` e,
portanto, persiste junto com os demais bancos no Docker.

Parâmetros:

| Nome | Tipo | Padrão | Limite |
|---|---|---|---|
| `source` | string | `onefootball` | fonte cadastrada |
| `days` | inteiro | `7` | entre 1 e 90 |
| `limit` | inteiro | `30` | entre 1 e 100 |

Cada partida encerrada avalia separadamente:

- resultado 1X2 mais provável;
- Mais/Menos 2,5 gols;
- Ambas Marcam;
- se o favorito do modelo marcaria;
- Lay 0x1, quando o sinal estava aprovado e o minuto está disponível.

O primeiro acesso à análise de uma partida futura congela sua fotografia. O
fluxo de `POST /api/sync` também registra automaticamente todos os jogos
restantes do dia antes de atualizar os resultados. Depois da sincronização,
o painel pode comparar a fotografia original com o placar novo sem recalcular
o passado.

Resposta resumida:

```json
{
  "summary": {
    "snapshots": 18,
    "evaluated_matches": 12,
    "pending_matches": 6,
    "matches_hit": 8,
    "checks": 48,
    "hits": 33,
    "hit_rate": 68.8
  },
  "items": []
}
```

---

## Comparação com odds da casa

### `POST /api/matches/{match_id}/value`

Recebe odds oferecidas e compara com a precificação do Poisson.

Parâmetros:

| Nome | Local | Tipo | Padrão |
|---|---|---|---|
| `match_id` | rota | inteiro | obrigatório |
| `source` | query | string | `onefootball` |

Body:

```json
{
  "offers": [
    { "market": "match_odds", "selection": "home", "odds": 2.40 },
    { "market": "btts", "selection": "yes", "odds": 2.20 },
    { "market": "total_goals", "selection": "over_2.5", "odds": 2.10 },
    { "market": "exact_score", "selection": "1-1", "odds": 8.50 }
  ]
}
```

São aceitas entre 1 e 30 ofertas. A odd precisa ser maior que 1 e menor ou igual
a 1000.

Mercados e seleções:

| `market` | Seleções aceitas |
|---|---|
| `match_odds` | `home`, `draw`, `away` |
| `btts` | `yes`, `no` |
| `total_goals` | `over_0.5` até `over_4.5` e equivalentes `under` |
| `exact_score` | `0-0` até `8-8` |
| `clean_sheet` | `home`, `away` |
| `team_to_score` | `home`, `away` |

Resposta por oferta:

```json
{
  "market": "match_odds",
  "selection": "home",
  "offered_odds": 2.4,
  "fair_odds": 2.221,
  "model_probability": 45.02,
  "implied_probability": 41.67,
  "edge_percentage_points": 3.35,
  "expected_value_percentage": 8.05,
  "has_value": true
}
```

Fórmula:

```text
EV% = (probabilidade_modelo_decimal × odd_oferecida - 1) × 100
```

`has_value=true` significa apenas que o EV teórico é positivo segundo o modelo.
Não considera limite, liquidez, comissão da exchange, erro da amostra nem mudança
de escalação.

Exemplo PowerShell:

```powershell
$body = @{
  offers = @(
    @{ market = "match_odds"; selection = "home"; odds = 2.40 }
  )
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Uri "http://localhost:8000/api/matches/2652431/value?source=onefootball" `
  -Method Post `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
```

---

## Atualizações em segundo plano

### `POST /api/sync`

Inicia um coletor sem bloquear a requisição HTTP. Requer o token administrativo
quando ele estiver configurado.

Body:

```json
{
  "source": "onefootball",
  "scope": "incremental"
}
```

Valores de `source`:

- `onefootball`
- `sofascore`
- `football_data`

Valores de `scope`:

- `incremental`: atualiza apenas o necessário.
- `all`: percorre o catálogo completo da fonte.

O football-data.org não diferencia os dois escopos e atualiza suas ligas
configuradas. No SofaScore, `all` executa `main2.py --full`. No OneFootball,
`all` redescobre e percorre o catálogo completo.

Depois da coleta, a mesma tarefa verifica os resultados finalizados e retreina
o modelo neural da fonte quando a assinatura mudou. Ao concluir, `result`
contém dois blocos: `sync`, com o resumo do coletor, e `neural_model`, com o
resultado do treino ou `reason="dataset_unchanged"`.

Exemplo PowerShell:

```powershell
$headers = @{ Authorization = "Bearer $token" }
$body = @{ source = "onefootball"; scope = "incremental" } | ConvertTo-Json
$job = Invoke-RestMethod `
  -Uri http://localhost:8000/api/sync `
  -Method Post `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $body
$job.id
```

Resposta HTTP `202`:

```json
{
  "id": "2fd8864a2d8a4b909253381fb01377b3",
  "kind": "sync:onefootball:incremental",
  "status": "queued",
  "progress": 0,
  "current": 0,
  "total": 0,
  "message": "Aguardando execução",
  "result": null,
  "error": null,
  "created_at": "2026-08-20T22:00:00+00:00",
  "updated_at": "2026-08-20T22:00:00+00:00"
}
```

### `POST /api/minutes`

Coleta os eventos/minutos de partidas específicas. Aceita entre 1 e 30 IDs e
está disponível somente para OneFootball e SofaScore.

Body:

```json
{
  "source": "onefootball",
  "match_ids": [2652427, 2652428]
}
```

Também retorna uma tarefa com HTTP `202`. Consulte o progresso pelo endpoint de
tarefas. O frontend usa `lay_01.missing_match_ids` para montar essa requisição.

### `GET /api/jobs/{job_id}`

Consulta uma atualização ou coleta de minutos.

Estados:

| Estado | Significado |
|---|---|
| `queued` | Aguardando outra tarefa terminar |
| `running` | Coletor em execução |
| `completed` | Concluído; resultado disponível em `result` |
| `failed` | Falha; descrição disponível em `error` |

Exemplo de acompanhamento em PowerShell:

```powershell
do {
  $status = Invoke-RestMethod "http://localhost:8000/api/jobs/$($job.id)"
  Write-Host "$($status.progress)% - $($status.message)"
  Start-Sleep -Seconds 2
} while ($status.status -in @("queued", "running"))

$status | ConvertTo-Json -Depth 8
```

As tarefas são serializadas: apenas um scraper é executado por vez para evitar
disputa pelos bancos SQLite. O estado das tarefas fica em memória e é perdido
quando o processo reinicia; os dados já gravados nos bancos permanecem.

---

## Erros HTTP

| Código | Situação comum |
|---|---|
| `400` | Fonte ou parâmetro semanticamente inválido |
| `401` | Token de acesso ausente ou incorreto |
| `404` | Banco, partida, tarefa ou rota não encontrada |
| `422` | Body ou query fora do formato esperado |
| `503` | Token ainda não configurado ou hash inválido no servidor |
| `500` | Falha inesperada no backend |

Formato padrão:

```json
{
  "detail": "Descrição do erro"
}
```

Falhas ocorridas dentro de um scraper não transformam o `POST` inicial em erro
HTTP, porque ele apenas cria a tarefa. Nesse caso, `GET /api/jobs/{job_id}`
retorna `status=failed` e preenche o campo `error`.

## OpenAPI

O contrato gerado automaticamente está disponível em:

```text
GET /api/openapi.json
```

Interfaces interativas:

```text
http://localhost:8000/api/docs
```

No Swagger, clique em **Authorize** e informe o token no esquema Bearer antes de
testar as rotas protegidas.

Para integrações novas, use o OpenAPI como fonte definitiva dos tipos de entrada
e validações, e este documento para as regras de negócio.

---

## Modelo neural e aprendizado automático

O TradeFot treina uma rede neural MLP independente para cada fonte. Ela usa
somente informações existentes antes do início de cada partida:

- forma geral e por mando nos últimos 10 jogos;
- pontos, vitórias, empates, gols, BTTS e clean sheets;
- rating Elo atualizado cronologicamente;
- retrospecto dos últimos cinco confrontos diretos;
- comportamento histórico da liga e intervalo de descanso.

A saída é uma distribuição calibrada entre vitória do mandante, empate e
vitória do visitante. As três probabilidades somam aproximadamente 100%. O
resultado mais provável é um palpite estatístico, não uma garantia.

### Treino e validação

Os dados são ordenados por data e divididos sem embaralhamento: 70% para treino,
15% para validação/calibração e os 15% mais recentes para teste final. Isso
impede que informações do futuro vazem para o treino. A API publica acurácia,
log-loss e Brier Score; nas duas últimas métricas, valores menores são melhores.
O bloco `metrics` também compara a rede com referências de frequência histórica
e Poisson calculadas exclusivamente com informações pré-jogo.

Por padrão, o backend:

1. verifica modelos ausentes ou desatualizados ao iniciar;
2. sincroniza a fonte quando `POST /api/sync` é chamado;
3. calcula uma assinatura dos resultados finalizados;
4. retreina com todo o histórico somente se os resultados mudaram;
5. substitui o modelo anterior de forma atômica após a validação.

Configurações opcionais no `.env`:

```env
TRADEFOT_ML_AUTO_TRAIN=true
TRADEFOT_ML_MIN_MATCHES=500
TRADEFOT_ML_EPOCHS=60
TRADEFOT_MODEL_DIR=/caminho/persistente/models
```

Na VPS, `TRADEFOT_MODEL_DIR` deve apontar para um volume persistente. Definir
`TRADEFOT_ML_AUTO_TRAIN=false` desativa somente a verificação ao iniciar; a
verificação posterior a `POST /api/sync` permanece ativa.

### `GET /api/models/status`

Sem query, retorna os modelos de todas as fontes. Para consultar apenas uma:

```http
GET /api/models/status?source=onefootball
```

Estados possíveis: `not_trained`, `ready` e `stale`. A resposta inclui data do
treino, quantidade de partidas, divisão temporal, época escolhida e métricas.

### `POST /api/models/train`

Agenda o treinamento no gerenciador de tarefas:

```json
{
  "source": "onefootball",
  "force": false
}
```

Com `force=false`, não há novo treino se os resultados não mudaram. Use
`force=true` para reconstruir o modelo. A resposta inicial tem HTTP `202`; o
progresso é consultado em `GET /api/jobs/{job_id}`.

### `GET /api/matches/{match_id}/prediction`

```http
GET /api/matches/2665745/prediction?source=onefootball
```

Resposta resumida:

```json
{
  "available": true,
  "prediction": "home",
  "predicted_team": "Los Angeles Football Club 2",
  "confidence": "medium",
  "probabilities": {
    "home": 54.80,
    "draw": 24.47,
    "away": 20.72
  },
  "fair_odds": {
    "home": 1.825,
    "draw": 4.086,
    "away": 4.825
  },
  "history_used": {
    "home": 10,
    "away": 10,
    "finished_before_match": 28169
  }
}
```

`confidence` combina a maior probabilidade com a cobertura histórica dos dois
times. Equipes com poucos jogos recebem confiança baixa.
