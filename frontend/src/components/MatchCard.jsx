import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { formatDate, formatRelativeDay } from '../lib/format.js'
import { api } from '../lib/api.js'

// Cache das previsões por "source:matchId" para não repetir a chamada de análise
// toda vez que o card remonta (paginação, troca de aba, volta pra tela etc.).
const predictionCache = new Map()

// Limita quantas análises são pedidas ao backend ao mesmo tempo: uma página
// pode renderizar dezenas de cards de uma vez e cada um dispara uma consulta
// de análise (Poisson + histórico), então enfileiramos para não sobrecarregar.
const MAX_CONCURRENT = 4
let activeRequests = 0
const requestQueue = []

function runQueue() {
  if (activeRequests >= MAX_CONCURRENT || requestQueue.length === 0) return
  activeRequests += 1
  const job = requestQueue.shift()
  job().finally(() => {
    activeRequests -= 1
    runQueue()
  })
}

function enqueue(task) {
  return new Promise((resolve) => {
    requestQueue.push(() => task().then(resolve, () => resolve(null)))
    runQueue()
  })
}

function getPrediction(source, matchId) {
  const key = `${source}:${matchId}`
  if (!predictionCache.has(key)) {
    predictionCache.set(
      key,
      enqueue(() => api.analysis(source, matchId).then((data) => data?.prediction || null)),
    )
  }
  return predictionCache.get(key)
}

function PredictStrip({ source, matchId }) {
  const [prediction, setPrediction] = useState('loading')

  useEffect(() => {
    let alive = true
    setPrediction('loading')
    getPrediction(source, matchId).then((data) => {
      if (alive) setPrediction(data)
    })
    return () => {
      alive = false
    }
  }, [source, matchId])

  if (prediction === 'loading') {
    return <div className="predict-strip predict-loading">Calculando probabilidades…</div>
  }
  if (!prediction) return null

  const { home, draw, away } = prediction
  const max = Math.max(home, draw, away)

  return (
    <div className="predict-strip">
      <div className="predict-bars">
        <span className={`predict-seg home ${home === max ? 'lead' : ''}`} style={{ flexGrow: home || 0.01 }} />
        <span className={`predict-seg draw ${draw === max ? 'lead' : ''}`} style={{ flexGrow: draw || 0.01 }} />
        <span className={`predict-seg away ${away === max ? 'lead' : ''}`} style={{ flexGrow: away || 0.01 }} />
      </div>
      <div className="predict-labels">
        <span className={home === max ? 'lead' : ''} title="Chance de vitória do mandante">
          <b>1</b> {Math.round(home)}%
        </span>
        <span className={draw === max ? 'lead' : ''} title="Chance de empate">
          <b>X</b> {Math.round(draw)}%
        </span>
        <span className={away === max ? 'lead' : ''} title="Chance de vitória do visitante">
          <b>2</b> {Math.round(away)}%
        </span>
      </div>
    </div>
  )
}

export function MatchCard({ match, source, compact = false }) {
  const hasScore = match.gols_casa !== null && match.gols_casa !== undefined
  return (
    <Link className={`match-card ${compact ? 'compact' : ''}`} to={`/partidas/${source}/${match.id_api}`}>
      <div className="match-meta">
        <span className="match-day">{formatRelativeDay(match.data_partida)}</span>
        <span className="match-round">{match.rodada || match.liga_nome}</span>
      </div>
      <div className="teams">
        <strong>{match.time_casa}</strong>
        {hasScore ? (
          <span className="score">
            {match.gols_casa} <em>×</em> {match.gols_fora}
          </span>
        ) : (
          <span className="versus">{formatDate(match.data_partida).split(', ')[1] || '×'}</span>
        )}
        <strong>{match.time_fora}</strong>
      </div>
      {!hasScore && <PredictStrip source={source} matchId={match.id_api} />}
      <div className="match-footer">
        <span className="league-chip">{match.liga_nome}</span>
        <span className="open-link">
          Analisar <ArrowRight size={13} />
        </span>
      </div>
    </Link>
  )
}
