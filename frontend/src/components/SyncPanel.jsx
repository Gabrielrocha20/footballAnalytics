import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { RefreshCw, X, CheckCircle2, XCircle } from 'lucide-react'
import { api } from '../lib/api.js'

const TERMINAL_JOB_STATUSES = ['completed', 'failed']

function wait(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

function routeData(pathname) {
  const match = pathname.match(/^\/partidas\/([^/]+)\/(\d+)/)
  if (match) {
    return {
      source: decodeURIComponent(match[1]),
      matchId: Number(match[2]),
    }
  }
  const league = pathname.match(/^\/ligas\/([^/]+)\//)
  return { source: league ? decodeURIComponent(league[1]) : null, matchId: null }
}

export function JobStatus({ job, onClose }) {
  if (!job) return null
  const terminal = TERMINAL_JOB_STATUSES.includes(job.status)
  return (
    <aside className={`job-panel ${job.status}`}>
      <div className="job-panel-head">
        <div>
          <span className="eyebrow">Atualização em segundo plano</span>
          <strong>{job.message}</strong>
          <small>
            {job.current || 0}/{job.total || 0} · {job.progress || 0}%
          </small>
        </div>
        {job.status === 'completed' && <CheckCircle2 className="job-icon ok" size={20} />}
        {job.status === 'failed' && <XCircle className="job-icon fail" size={20} />}
      </div>
      <div className="job-progress">
        <span style={{ width: `${job.progress || 0}%` }} />
      </div>
      {job.error && <p className="job-error">{job.error}</p>}
      {terminal && onClose && (
        <button className="text-button" onClick={onClose}>
          <X size={13} /> Fechar
        </button>
      )}
    </aside>
  )
}

export function SyncButton({ source }) {
  const location = useLocation()
  const [job, setJob] = useState(null)
  const [error, setError] = useState(null)
  const [updating, setUpdating] = useState(false)

  async function waitForJob(initialJob) {
    let current = initialJob
    setJob(current)
    while (!TERMINAL_JOB_STATUSES.includes(current.status)) {
      await wait(1300)
      current = await api.job(current.id)
      setJob(current)
    }
    return current
  }

  async function start() {
    if (updating) return
    setUpdating(true)
    setError(null)
    try {
      const context = routeData(location.pathname)
      const activeSource = context.source || source
      const syncJob = await waitForJob(await api.sync(activeSource, 'incremental'))
      if (syncJob.status === 'failed') return

      if (context.matchId) {
        const analysis = await api.analysis(activeSource, context.matchId)
        const minuteCoverage = analysis.insights?.minute_coverage
        const missingIds = new Set([
          ...(minuteCoverage?.missing_match_ids || []),
          ...(analysis.lay_01?.missing_match_ids || []),
        ])
        if (minuteCoverage?.supported && missingIds.size > 0) {
          const minuteJob = await waitForJob(
            await api.minutes(activeSource, [...missingIds]),
          )
          if (minuteJob.status === 'failed') return
        }
      }

      window.location.reload()
    } catch (err) {
      setError(err)
    } finally {
      setUpdating(false)
    }
  }

  return (
    <>
      <button
        className="ghost-button"
        disabled={updating}
        onClick={start}
        title="Atualiza a fonte e completa os dados da partida aberta"
      >
        <RefreshCw className={updating ? 'spin-icon' : ''} size={14} />
        {updating ? 'Atualizando…' : 'Atualizar'}
      </button>
      {error && <div className="toast error">{error.message}</div>}
      <JobStatus job={job} onClose={updating ? null : () => setJob(null)} />
    </>
  )
}
