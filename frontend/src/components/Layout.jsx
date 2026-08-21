import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { LogOut, ChevronDown } from 'lucide-react'
import { SyncButton } from './SyncPanel.jsx'
import { useAuth } from '../context/AuthContext.jsx'

export function Layout({ source, setSource, sources }) {
  const navigate = useNavigate()
  const { logout } = useAuth()

  function changeSource(event) {
    setSource(event.target.value)
  }

  async function handleLogout() {
    await logout()
    navigate('/')
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <NavLink to="/" className="brand">
          <span>TF</span>
          <div>
            TradeFot
            <small>Match intelligence</small>
          </div>
        </NavLink>
        <nav>
          <NavLink to="/" end>
            Painel
          </NavLink>
          <NavLink to="/ligas">Ligas</NavLink>
          <div className="select-wrap">
            <select value={source} onChange={changeSource} aria-label="Fonte de dados">
              {sources.map((item) => (
                <option key={item.key} value={item.key} disabled={item.available === false}>
                  {item.name}
                  {item.available === false ? ' (indisponível)' : ''}
                </option>
              ))}
            </select>
            <ChevronDown size={14} className="select-caret" />
          </div>
          <SyncButton source={source} />
          <button className="icon-button" title="Sair" onClick={handleLogout}>
            <LogOut size={16} />
          </button>
        </nav>
      </header>
      <Outlet />
      <footer>TradeFot · Estatísticas são estimativas e não garantem resultados.</footer>
    </div>
  )
}
