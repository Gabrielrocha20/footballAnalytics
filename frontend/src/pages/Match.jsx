import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ChevronLeft } from 'lucide-react'
import { api } from '../lib/api.js'
import { formatDate } from '../lib/format.js'
import { Loading, ErrorCard } from '../components/Ui.jsx'
import { JobStatus } from '../components/SyncPanel.jsx'
import {
  ProbabilityBar,
  LayCard,
  HistoryTable,
  TeamSummary,
  H2H,
} from '../components/MatchAnalysis.jsx'

export function MatchPage() {
  const { routeSource, matchId } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [neural, setNeural] = useState(null)
  const [error, setError] = useState(null)
  const [job, setJob] = useState(null)

  function load() {
    setError(null)
    api.analysis(routeSource, matchId).then(setData).catch(setError)
    api.neuralPrediction(routeSource, matchId).then(setNeural).catch(() => setNeural(null))
  }

  useEffect(load, [routeSource, matchId])

  useEffect(() => {
    if (!job || ['completed', 'failed'].includes(job.status)) return
    const timer = setInterval(async () => {
      const next = await api.job(job.id)
      setJob(next)
      if (next.status === 'completed') load()
    }, 1300)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job])

  async function collectMinutes() {
    setJob(await api.minutes(routeSource, data.lay_01.missing_match_ids))
  }

  if (error)
    return (
      <main>
        <button className="back-link button-link" onClick={() => navigate(-1)}>
          <ChevronLeft size={14} /> Voltar
        </button>
        <ErrorCard error={error} onRetry={load} />
      </main>
    )
  if (!data) return <main><Loading label="Calculando análise" /></main>

  const { match, prediction, lay_01: lay } = data
  const maxProbability = prediction ? Math.max(prediction.home, prediction.draw, prediction.away) : 0
  const collecting = job && !['completed', 'failed'].includes(job.status)

  return (
    <main>
      <button className="back-link button-link" onClick={() => navigate(-1)}>
        <ChevronLeft size={14} /> Voltar
      </button>

      <section className="match-hero">
        <div className="match-context">
          <Link to={`/ligas/${routeSource}/${match.liga_id}`}>{match.liga_nome}</Link>
          <span>{formatDate(match.data_partida)}</span>
          {match.rodada && <span>{match.rodada}</span>}
        </div>
        <div className="fixture">
          <h1>{match.time_casa}</h1>
          <div>
            <span>PRÉ-JOGO</span>
            <strong>×</strong>
          </div>
          <h1>{match.time_fora}</h1>
        </div>
      </section>

      {prediction ? (
        <section className="panel prediction-panel">
          <div className="panel-title">
            <div>
              <span className="eyebrow">Modelo estatístico</span>
              <h2>Probabilidades</h2>
            </div>
            <span>
              Gols esperados {prediction.expected_home_goals} × {prediction.expected_away_goals}
            </span>
          </div>
          <div className="probabilities">
            <ProbabilityBar label={match.time_casa} value={prediction.home} active={prediction.home === maxProbability} />
            <ProbabilityBar label="Empate" value={prediction.draw} active={prediction.draw === maxProbability} />
            <ProbabilityBar label={match.time_fora} value={prediction.away} active={prediction.away === maxProbability} />
          </div>
        </section>
      ) : (
        <div className="state-card">Histórico insuficiente para calcular probabilidades.</div>
      )}

      {neural?.available && (
        <section className="panel prediction-panel neural-panel">
          <div className="panel-title">
            <div>
              <span className="eyebrow">Rede neural · validação cronológica</span>
              <h2>Previsão treinada</h2>
            </div>
            <span>
              Palpite: {neural.predicted_team || 'Empate'} · confiança {neural.confidence === 'high' ? 'alta' : neural.confidence === 'medium' ? 'média' : 'baixa'}
            </span>
          </div>
          <div className="probabilities">
            <ProbabilityBar
              label={match.time_casa}
              value={neural.probabilities.home}
              active={neural.prediction === 'home'}
            />
            <ProbabilityBar
              label="Empate"
              value={neural.probabilities.draw}
              active={neural.prediction === 'draw'}
            />
            <ProbabilityBar
              label={match.time_fora}
              value={neural.probabilities.away}
              active={neural.prediction === 'away'}
            />
          </div>
          <p className="muted">
            Treinado em {neural.history_used.finished_before_match.toLocaleString('pt-BR')} resultados ·
            acerto no teste: {neural.model.test_metrics.accuracy}% · log-loss {neural.model.test_metrics.log_loss}
          </p>
        </section>
      )}

      <LayCard lay={lay} onCollect={collectMinutes} collecting={collecting} />
      <JobStatus job={job} onClose={() => setJob(null)} />

      <div className="summary-grid">
        <TeamSummary name={match.time_casa} data={data.home.summary} />
        <TeamSummary name={match.time_fora} data={data.away.summary} />
      </div>

      <HistoryTable title={`Últimos jogos · ${match.time_casa}`} history={data.home.history} showLay />
      <HistoryTable title={`Últimos jogos · ${match.time_fora}`} history={data.away.history} />
      <H2H matches={data.head_to_head} />

      {data.disclaimer && <p className="disclaimer">{data.disclaimer}</p>}
    </main>
  )
}
