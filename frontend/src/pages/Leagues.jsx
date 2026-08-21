import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, X, Trophy, Globe2 } from 'lucide-react'
import { api } from '../lib/api.js'
import { SOURCE_NAMES } from '../lib/format.js'
import { Loading, ErrorCard, EmptyState } from '../components/Ui.jsx'

export function Leagues({ source, sources }) {
  const [input, setInput] = useState('')
  const [search, setSearch] = useState('')
  const [leagues, setLeagues] = useState(null)
  const [error, setError] = useState(null)
  const selectedSource = sources.find((item) => item.key === source)

  useEffect(() => {
    setLeagues(null)
    setError(null)
    const timer = setTimeout(() => {
      api.leagues(source, search).then(setLeagues).catch(setError)
    }, search ? 250 : 0)
    return () => clearTimeout(timer)
  }, [source, search])

  function submit(event) {
    event.preventDefault()
    setSearch(input.trim())
  }

  function clear() {
    setInput('')
    setSearch('')
  }

  const { popular, groups, countries } = useMemo(() => {
    if (!leagues) return { popular: [], groups: {}, countries: [] }
    const sorted = [...leagues].sort((a, b) => (b.matches || 0) - (a.matches || 0))
    const byCountry = {}
    for (const league of leagues) {
      const key = league.country || 'Outras ligas'
      if (!byCountry[key]) byCountry[key] = []
      byCountry[key].push(league)
    }
    Object.values(byCountry).forEach((list) => list.sort((a, b) => (b.matches || 0) - (a.matches || 0)))
    const countryNames = Object.keys(byCountry).sort((a, b) => a.localeCompare(b, 'pt-BR'))
    return { popular: sorted.slice(0, 6), groups: byCountry, countries: countryNames }
  }, [leagues])

  return (
    <main>
      <section className="page-title">
        <span className="eyebrow">{selectedSource?.name || SOURCE_NAMES[source]}</span>
        <h1>Ligas disponíveis</h1>
        <p className="muted">
          {selectedSource?.leagues ? `${selectedSource.leagues.toLocaleString('pt-BR')} ligas catalogadas` : ''} ·
          escolha uma para ver tabela, próximos jogos e resultados recentes.
        </p>
      </section>

      <form className="search-bar" onSubmit={submit}>
        <Search size={19} />
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Filtrar por liga, país, código ou time"
        />
        {input && (
          <button type="button" className="clear" onClick={clear}>
            <X size={16} />
          </button>
        )}
        <button className="primary-button">Filtrar</button>
      </form>

      {error ? (
        <ErrorCard error={error} />
      ) : !leagues ? (
        <Loading label="Carregando ligas" />
      ) : leagues.length === 0 ? (
        <EmptyState>Nenhuma liga encontrada para “{search}”.</EmptyState>
      ) : (
        <>
          {!search && popular.length > 0 && (
            <section className="league-section">
              <div className="league-section-title">
                <Trophy size={15} /> <h2>Mais movimentadas</h2>
              </div>
              <div className="league-grid">
                {popular.map((league) => (
                  <LeagueTile key={league.id} league={league} source={source} />
                ))}
              </div>
            </section>
          )}

          {countries.map((country) => (
            <section className="league-section" key={country}>
              <div className="league-section-title">
                <Globe2 size={15} /> <h2>{country}</h2>
                <span>{groups[country].length} liga{groups[country].length > 1 ? 's' : ''}</span>
              </div>
              <div className="league-grid">
                {groups[country].map((league) => (
                  <LeagueTile key={league.id} league={league} source={source} />
                ))}
              </div>
            </section>
          ))}
        </>
      )}
    </main>
  )
}

function LeagueTile({ league, source }) {
  return (
    <Link className="league-tile" to={`/ligas/${source}/${league.id}`}>
      <div className="league-tile-head">
        <strong>{league.name}</strong>
        <span>{league.matches ?? '—'}</span>
      </div>
      <div className="league-tile-foot">
        <span>{league.country || 'Internacional'}</span>
        {league.seasons?.length > 0 && <span>{league.seasons[league.seasons.length - 1]}</span>}
      </div>
    </Link>
  )
}
