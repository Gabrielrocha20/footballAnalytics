import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, X, ChevronLeft, ChevronRight, Trophy } from 'lucide-react'
import { api } from '../lib/api.js'
import { SOURCE_NAMES } from '../lib/format.js'
import { MatchCard } from '../components/MatchCard.jsx'
import { PerformancePanel } from '../components/PerformancePanel.jsx'
import { Loading, ErrorCard, EmptyState } from '../components/Ui.jsx'

const PAGE_SIZE = 24

export function Home({ source, sources }) {
  const [input, setInput] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [leagueFilter, setLeagueFilter] = useState(null)
  const [data, setData] = useState(null)
  const [foundLeagues, setFoundLeagues] = useState([])
  const [spotlight, setSpotlight] = useState([])
  const [performance, setPerformance] = useState(null)
  const [error, setError] = useState(null)

  const selectedSource = sources.find((item) => item.key === source)

  useEffect(() => {
    setPage(1)
    setLeagueFilter(null)
    setPerformance(null)
    api
      .leagues(source, '')
      .then((all) => setSpotlight([...all].sort((a, b) => (b.matches || 0) - (a.matches || 0)).slice(0, 8)))
      .catch(() => setSpotlight([]))
    api.performance(source, 7, 12).then(setPerformance).catch(() => setPerformance(null))
  }, [source])

  useEffect(() => {
    setData(null)
    setError(null)
    Promise.all([
      api.upcoming({ source, search, league_id: leagueFilter, page, page_size: PAGE_SIZE }),
      search ? api.leagues(source, search) : Promise.resolve([]),
    ])
      .then(([matches, leagues]) => {
        setData(matches)
        setFoundLeagues(leagues.slice(0, 8))
      })
      .catch(setError)
  }, [source, search, page, leagueFilter])

  function submit(event) {
    event.preventDefault()
    setPage(1)
    setSearch(input.trim())
  }

  function clearSearch() {
    setInput('')
    setSearch('')
    setPage(1)
  }

  function toggleLeague(id) {
    setPage(1)
    setLeagueFilter((current) => (current === id ? null : id))
  }

  const activeLeagueName = useMemo(
    () => spotlight.find((league) => league.id === leagueFilter)?.name,
    [spotlight, leagueFilter],
  )

  return (
    <main>
      <section className="hero">
        <div>
          <span className="eyebrow">Dados antes da entrada</span>
          <h1>
            Encontre o jogo.
            <br />
            <em>Leia o contexto.</em>
          </h1>
          <p>
            Ligas, tabelas, forma recente, confrontos diretos e o filtro Lay 0x1 reunidos em uma tela só,
            direto dos coletores do backend.
          </p>
        </div>
        <div className="source-stat">
          <span>{selectedSource?.name || SOURCE_NAMES[source]}</span>
          <strong>{selectedSource?.matches?.toLocaleString('pt-BR') || '—'}</strong>
          <small>partidas em {selectedSource?.leagues || '—'} ligas</small>
        </div>
      </section>

      <PerformancePanel data={performance} source={source} />

      <form className="search-bar" onSubmit={submit}>
        <Search size={19} />
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Pesquise por time, liga ou país"
        />
        {input && (
          <button type="button" className="clear" onClick={clearSearch}>
            <X size={16} />
          </button>
        )}
        <button className="primary-button">Pesquisar</button>
      </form>

      {foundLeagues.length > 0 && (
        <section className="league-results">
          <span>Ligas encontradas</span>
          <div>
            {foundLeagues.map((league) => (
              <Link key={league.id} to={`/ligas/${source}/${league.id}`}>
                {league.name}
                <small>{league.country}</small>
              </Link>
            ))}
          </div>
        </section>
      )}

      {spotlight.length > 0 && (
        <section className="chip-row">
          <span className="chip-row-label">
            <Trophy size={13} /> Ligas em destaque
          </span>
          <div className="chip-scroll">
            {spotlight.map((league) => (
              <button
                key={league.id}
                className={`chip ${leagueFilter === league.id ? 'active' : ''}`}
                onClick={() => toggleLeague(league.id)}
              >
                {league.name}
              </button>
            ))}
          </div>
          <Link className="chip-see-all" to="/ligas">
            Ver todas →
          </Link>
        </section>
      )}

      <div className="section-heading">
        <div>
          <span className="eyebrow">Calendário</span>
          <h2>
            {activeLeagueName
              ? activeLeagueName
              : search
                ? `Resultados para “${search}”`
                : 'Próximos jogos'}
          </h2>
        </div>
        <div className="section-heading-right">
          {leagueFilter && (
            <button className="text-button" onClick={() => setLeagueFilter(null)}>
              <X size={13} /> limpar filtro
            </button>
          )}
          <span>{data?.total || 0} partidas</span>
        </div>
      </div>

      {error ? (
        <ErrorCard error={error} />
      ) : !data ? (
        <Loading />
      ) : data.items.length === 0 ? (
        <EmptyState>Nenhum próximo jogo encontrado com esses filtros.</EmptyState>
      ) : (
        <div className="matches-grid">
          {data.items.map((match) => (
            <MatchCard key={match.id_api} match={match} source={source} />
          ))}
        </div>
      )}

      {data && data.pages > 1 && (
        <div className="pagination">
          <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            <ChevronLeft size={15} /> Anterior
          </button>
          <span>
            Página {page} de {data.pages}
          </span>
          <button disabled={page >= data.pages} onClick={() => setPage((p) => p + 1)}>
            Próxima <ChevronRight size={15} />
          </button>
        </div>
      )}
    </main>
  )
}
