import { useState } from 'react'
import { KeyRound, ShieldAlert, Loader2 } from 'lucide-react'
import { useAuth } from '../context/AuthContext.jsx'

export function Login() {
  const { login } = useAuth()
  const [token, setTokenValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function submit(event) {
    event.preventDefault()
    if (!token.trim()) return
    setBusy(true)
    setError(null)
    const result = await login(token)
    setBusy(false)
    if (!result.ok) setError(result.message)
  }

  return (
    <div className="boot login-screen">
      <div className="login-card">
        <div className="login-mark">
          <span>TF</span>
        </div>
        <h1>Acesso ao TradeFot</h1>
        <p>Informe o token de acesso gerado no servidor para consultar ligas, partidas e análises.</p>
        <form onSubmit={submit}>
          <label>
            Token de acesso
            <div className="token-field">
              <KeyRound size={16} />
              <input
                type="password"
                autoFocus
                value={token}
                onChange={(event) => setTokenValue(event.target.value)}
                placeholder="Cole aqui o token gerado pelo backend"
              />
            </div>
          </label>
          {error && (
            <div className="login-error">
              <ShieldAlert size={15} /> {error}
            </div>
          )}
          <button className="primary-button full" disabled={busy || !token.trim()}>
            {busy ? <Loader2 className="spin-icon" size={16} /> : 'Entrar'}
          </button>
        </form>
        <small className="login-hint">
          O token é gerado com <code>python -m backend.app.auth generate</code> e fica salvo apenas neste
          navegador.
        </small>
      </div>
    </div>
  )
}

export function Unconfigured() {
  return (
    <div className="boot login-screen">
      <div className="login-card">
        <div className="login-mark warn">
          <ShieldAlert size={22} />
        </div>
        <h1>Backend sem token configurado</h1>
        <p>
          Gere um token com <code>python -m backend.app.auth generate</code>, defina
          <code>TRADEFOT_ACCESS_TOKEN_HASH</code> no <code>.env</code> e reinicie o servidor para liberar o
          acesso.
        </p>
      </div>
    </div>
  )
}
