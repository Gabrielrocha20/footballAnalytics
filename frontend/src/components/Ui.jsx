import { AlertTriangle, Loader2, Inbox } from 'lucide-react'

export function Loading({ label = 'Carregando dados' }) {
  return (
    <div className="state-card">
      <Loader2 className="spin-icon" size={18} />
      {label}
    </div>
  )
}

export function ErrorCard({ error, onRetry }) {
  return (
    <div className="state-card error">
      <AlertTriangle size={18} />
      <span>{error?.message || String(error)}</span>
      {onRetry && (
        <button className="text-button" onClick={onRetry}>
          Tentar novamente
        </button>
      )}
    </div>
  )
}

export function EmptyState({ children }) {
  return (
    <div className="state-card">
      <Inbox size={18} />
      {children}
    </div>
  )
}

export function Metric({ label, value, accent = false }) {
  return (
    <div className={`metric ${accent ? 'accent' : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}
