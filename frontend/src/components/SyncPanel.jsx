import { useEffect, useState } from 'react'
import { RefreshCw, X, CheckCircle2, XCircle } from 'lucide-react'
import { api } from '../lib/api.js'

export function JobStatus({ job, onClose }) {
  if (!job) return null
  const terminal = ['completed', 'failed'].includes(job.status)
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
      {terminal && (
        <button className="text-button" onClick={onClose}>
          <X size={13} /> Fechar
        </button>
      )}
    </aside>
  )
}

export function SyncButton({ source }) {
  const [open, setOpen] = useState(false)
  const [job, setJob] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!job || ['completed', 'failed'].includes(job.status)) return
    const timer = setInterval(async () => {
      try {
        setJob(await api.job(job.id))
      } catch (err) {
        setError(err)
      }
    }, 1500)
    return () => clearInterval(timer)
  }, [job])

  useEffect(() => {
    function closeOnOutsideClick() {
      setOpen(false)
    }
    if (open) {
      document.addEventListener('click', closeOnOutsideClick)
      return () => document.removeEventListener('click', closeOnOutsideClick)
    }
  }, [open])

  async function start(scope) {
    setOpen(false)
    setError(null)
    try {
      setJob(await api.sync(source, scope))
    } catch (err) {
      setError(err)
    }
  }

  return (
    <>
      <div className="sync-wrap" onClick={(e) => e.stopPropagation()}>
        <button className="ghost-button" onClick={() => setOpen(!open)}>
          <RefreshCw size={14} /> Atualizar
        </button>
        {open && (
          <div className="sync-menu">
            <button onClick={() => start('incremental')}>
              <strong>Incremental</strong>
              <small>Somente o necessário para esta fonte</small>
            </button>
            <button onClick={() => start('all')}>
              <strong>Coleta completa</strong>
              <small>Percorre todo o catálogo da fonte</small>
            </button>
          </div>
        )}
      </div>
      {error && <div className="toast error">{error.message}</div>}
      <JobStatus job={job} onClose={() => setJob(null)} />
    </>
  )
}
