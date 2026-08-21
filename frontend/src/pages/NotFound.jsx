import { Link } from 'react-router-dom'

export function NotFound() {
  return (
    <main>
      <div className="state-card">
        <h2>Página não encontrada</h2>
        <Link to="/">Voltar ao início</Link>
      </div>
    </main>
  )
}
