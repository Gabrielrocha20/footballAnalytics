import { Link } from 'react-router-dom'
import { Check, Clock3, Target, X } from 'lucide-react'
import { formatDate } from '../lib/format.js'

export function PerformancePanel({ data, source }) {
  if (!data?.summary?.snapshots) return null
  const { summary, items } = data
  return (
    <section className="performance-panel">
      <div className="performance-head">
        <div>
          <span className="eyebrow"><Target size={14} /> Auditoria das análises</span>
          <h2>Quais previsões bateram?</h2>
          <p>Comparação das análises congeladas antes do jogo com os resultados atualizados.</p>
        </div>
        <div className="performance-summary">
          <strong>{summary.hit_rate == null ? '—' : `${summary.hit_rate}%`}</strong>
          <span>{summary.hits}/{summary.checks} sinais corretos</span>
          {summary.pending_matches > 0 && (
            <small><Clock3 size={12} /> {summary.pending_matches} aguardando resultado</small>
          )}
        </div>
      </div>

      {items.length > 0 ? (
        <div className="performance-games">
          {items.map((item) => (
            <Link
              className={`performance-game ${item.verdict}`}
              key={`${item.source}:${item.match_id}`}
              to={`/partidas/${source}/${item.match_id}`}
            >
              <div className="performance-game-head">
                <span>{formatDate(item.kickoff, false)} · {item.league_name}</span>
                <b>{item.hits}/{item.checks_count} bateram</b>
              </div>
              <div className="performance-score">
                <strong>{item.home_team}</strong>
                <b>{item.home_goals} × {item.away_goals}</b>
                <strong>{item.away_team}</strong>
              </div>
              <div className="performance-checks">
                {item.checks.map((check) => (
                  <span className={check.hit ? 'hit' : 'miss'} key={check.id} title={`${check.label}: ${check.selection}`}>
                    {check.hit ? <Check size={11} /> : <X size={11} />}
                    {check.label}
                  </span>
                ))}
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="performance-awaiting">
          <Clock3 size={18} /> As análises estão salvas e aparecerão aqui quando os jogos terminarem.
        </div>
      )}
    </section>
  )
}
