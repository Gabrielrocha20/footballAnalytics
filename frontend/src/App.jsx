import { useEffect, useState } from 'react'
import { Routes, Route } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext.jsx'
import { Login, Unconfigured } from './pages/Login.jsx'
import { Layout } from './components/Layout.jsx'
import { Home } from './pages/Home.jsx'
import { Leagues } from './pages/Leagues.jsx'
import { LeaguePage } from './pages/League.jsx'
import { MatchPage } from './pages/Match.jsx'
import { NotFound } from './pages/NotFound.jsx'
import { Loading, ErrorCard } from './components/Ui.jsx'
import { api } from './lib/api.js'

function Gate() {
  const { status, error, retry } = useAuth()

  if (status === 'checking') {
    return (
      <div className="boot">
        <Loading label="Verificando acesso" />
      </div>
    )
  }
  if (status === 'unconfigured') return <Unconfigured />
  if (status === 'anonymous') {
    return (
      <div className="boot">
        {error && <ErrorCard error={error} onRetry={retry} />}
        <Login />
      </div>
    )
  }
  return <Workspace />
}

function Workspace() {
  const [sources, setSources] = useState([])
  const [source, setSource] = useState(localStorage.getItem('tradefot-source') || 'onefootball')
  const [error, setError] = useState(null)

  useEffect(() => {
    api.sources().then(setSources).catch(setError)
  }, [])
  useEffect(() => {
    localStorage.setItem('tradefot-source', source)
  }, [source])

  if (error) return <div className="boot"><ErrorCard error={error} /></div>
  if (!sources.length) return <div className="boot"><Loading label="Iniciando TradeFot" /></div>

  return (
    <Routes>
      <Route element={<Layout source={source} setSource={setSource} sources={sources} />}>
        <Route path="/" element={<Home source={source} sources={sources} />} />
        <Route path="/ligas" element={<Leagues source={source} sources={sources} />} />
        <Route path="/ligas/:routeSource/:leagueId" element={<LeaguePage />} />
        <Route path="/partidas/:routeSource/:matchId" element={<MatchPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  )
}
