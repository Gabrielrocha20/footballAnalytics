import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ChevronLeft } from 'lucide-react'
import { api } from '../lib/api.js'
import { SOURCE_NAMES, formatDate } from '../lib/format.js'
import { Loading, ErrorCard, Metric } from '../components/Ui.jsx'
import { Standings } from '../components/Standings.jsx'
import { MatchCard } from '../components/MatchCard.jsx'

export function LeaguePage() {
  const { routeSource, leagueId } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [tab, setTab] = useState('standings')

  useEffect(() => {
    setData(null)
    setError(null)
    setTab('standings')
    api.league(routeSource, leagueId).then(setData).catch(setError)
  }, [routeSource, leagueId])

  if (error) return <main><ErrorCard error={error} /></main>
  if (!data) return <main><Loading label="Abrindo liga" /></main>

  const played = data.stats.played || 0
  const total = data.stats.matches || 0
  const progress = total ? Math.round((played / total) * 100) : 0

  return (
    <main>
      <Link className="back-link" to="/ligas">
        <ChevronLeft size={14} /> Voltar às ligas
      </Link>
      <section className="page-title">
        <span className="eyebrow">{data.league.country || SOURCE_NAMES[routeSource]}</span>
        <h1>{data.league.name}</h1>
        {data.league.season && <p className="muted">Temporada {data.league.season}</p>}
      </section>

      <div className="metrics-row">
        <Metric label="Partidas" value={total} />
        <Metric label="Disputadas" value={`${played} (${progress}%)`} />
        <Metric label="Gols" value={data.stats.goals} />
        <Metric label="Média por jogo" value={data.stats.goals_per_match} accent />
      </div>

      <div className="tab-row">
        <button className={tab === 'standings' ? 'active' : ''} onClick={() => setTab('standings')}>
          Classificação
        </button>
        <button className={tab === 'upcoming' ? 'active' : ''} onClick={() => setTab('upcoming')}>
          Próximos jogos ({data.upcoming?.length || 0})
        </button>
        <button className={tab === 'recent' ? 'active' : ''} onClick={() => setTab('recent')}>
          Resultados recentes ({data.recent?.length || 0})
        </button>
      </div>

      {tab === 'standings' && (
        <section className="panel">
          <div className="panel-title">
            <h2>Classificação</h2>
            <span>{data.standings?.length || 0} times</span>
          </div>
          <Standings rows={data.standings} />
        </section>
      )}

      {tab === 'upcoming' && (
        <section className="panel">
          <div className="panel-title">
            <h2>Próximos jogos</h2>
          </div>
          {data.upcoming?.length ? (
            <div className="stacked-matches">
              {data.upcoming.map((match) => (
                <MatchCard key={match.id_api} match={match} source={routeSource} compact />
              ))}
            </div>
          ) : (
            <p className="muted">Sem jogos futuros cadastrados.</p>
          )}
        </section>
      )}

      {tab === 'recent' && (
        <section className="panel">
          <div className="panel-title">
            <h2>Resultados recentes</h2>
          </div>
          {data.recent?.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Data</th>
                    <th>Mandante</th>
                    <th>Placar</th>
                    <th>Visitante</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent.map((match) => (
                    <tr key={match.id_api}>
                      <td>{formatDate(match.data_partida, false)}</td>
                      <td>
                        <Link to={`/partidas/${routeSource}/${match.id_api}`}>{match.time_casa}</Link>
                      </td>
                      <td className="points">
                        {match.gols_casa} × {match.gols_fora}
                      </td>
                      <td>
                        <Link to={`/partidas/${routeSource}/${match.id_api}`}>{match.time_fora}</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">Sem resultados recentes cadastrados.</p>
          )}
        </section>
      )}
    </main>
  )
}
