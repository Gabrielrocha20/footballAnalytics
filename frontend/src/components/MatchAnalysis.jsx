import { CheckCircle2, XCircle, Clock, HelpCircle, Ban } from 'lucide-react'
import { formatDate } from '../lib/format.js'
import { Metric } from './Ui.jsx'

const LAY_COPY = {
  approved: {
    title: 'APROVADO',
    text: 'O favorito cumpriu o corte de 8 em 10 jogos anteriores.',
    icon: CheckCircle2,
  },
  rejected: {
    title: 'REPROVADO',
    text: 'A frequência do gol até 75′ ficou em 75% ou menos.',
    icon: XCircle,
  },
  pending_minutes: {
    title: 'PENDENTE',
    text: 'Faltam minutos coletados para concluir a análise.',
    icon: Clock,
  },
  not_home_favorite: {
    title: 'FORA DO MÉTODO',
    text: 'O mandante não é o favorito do modelo estatístico.',
    icon: Ban,
  },
  insufficient_history: {
    title: 'AMOSTRA INSUFICIENTE',
    text: 'Ainda não existem 10 jogos válidos no histórico.',
    icon: HelpCircle,
  },
  unsupported: {
    title: 'SEM MINUTOS',
    text: 'A fonte selecionada não coleta os minutos dos gols.',
    icon: Ban,
  },
}

export function ProbabilityBar({ label, value, active }) {
  return (
    <div className={`probability ${active ? 'active' : ''}`}>
      <div>
        <span>{label}</span>
        <strong>{value?.toFixed(1)}%</strong>
      </div>
      <div className="bar">
        <span style={{ width: `${value || 0}%` }} />
      </div>
    </div>
  )
}

export function LayCard({ lay, onCollect, collecting }) {
  const copy = LAY_COPY[lay.status] || { title: 'INDEFINIDO', text: 'Sem conclusão disponível.' }
  const Icon = copy.icon || HelpCircle
  return (
    <section className={`lay-card ${lay.status}`}>
      <div className="lay-card-head">
        <Icon size={22} />
        <div>
          <span className="eyebrow">Método Lay 0x1 na zebra</span>
          <h2>{copy.title}</h2>
          <p>{copy.text}</p>
        </div>
      </div>
      <div className="lay-score">
        <strong>
          {lay.hits}
          <small>/10</small>
        </strong>
        <span>gol do favorito até 75′</span>
      </div>
      <div className="lay-facts">
        <Metric label="Favorito em casa" value={lay.home_favorite ? 'Sim' : 'Não'} />
        <Metric label="Percentual" value={`${lay.percentage}%`} />
        <Metric label="Cobertura" value={`${lay.coverage}/10`} />
      </div>
      {lay.status === 'pending_minutes' && lay.missing_match_ids?.length > 0 && (
        <button className="primary-button" disabled={collecting} onClick={onCollect}>
          {collecting ? 'Coletando…' : `Coletar ${lay.missing_match_ids.length} partidas pendentes`}
        </button>
      )}
    </section>
  )
}

export function HistoryTable({ title, history, showLay = false }) {
  return (
    <section className="panel history-panel">
      <div className="panel-title">
        <h2>{title}</h2>
        <span>Mais recente primeiro</span>
      </div>
      {history?.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Data</th>
                <th>Local</th>
                <th>Adversário</th>
                <th>Placar</th>
                {showLay && <th>Gol até 75′</th>}
                <th>Resultado</th>
              </tr>
            </thead>
            <tbody>
              {history.map((game) => (
                <tr key={game.id_api}>
                  <td>{formatDate(game.data_partida, false)}</td>
                  <td>{game.venue === 'home' ? 'Casa' : 'Fora'}</td>
                  <td>{game.opponent}</td>
                  <td>
                    <strong>
                      {game.goals_for} × {game.goals_against}
                    </strong>
                  </td>
                  {showLay && (
                    <td>
                      {game.goals_until_75 == null
                        ? 'Pendente'
                        : game.goals_until_75 > 0
                          ? `Sim${game.first_goal_minute != null ? ` · ${game.first_goal_minute}′` : ''}`
                          : 'Não'}
                    </td>
                  )}
                  <td>
                    <span className={`result ${game.result}`}>{game.result}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="muted">Sem histórico suficiente.</p>
      )}
    </section>
  )
}

export function TeamSummary({ name, data }) {
  return (
    <section className="panel team-summary">
      <div className="panel-title">
        <h2>{name}</h2>
        <div className="form">
          {data.form.map((item, index) => (
            <span key={index} className={item}>
              {item}
            </span>
          ))}
        </div>
      </div>
      <div className="summary-values">
        <div>
          <strong>{data.wins}</strong>
          <span>Vitórias</span>
        </div>
        <div>
          <strong>{data.goals_for}</strong>
          <span>Gols marcados</span>
        </div>
        <div>
          <strong>{data.goals_against}</strong>
          <span>Sofridos</span>
        </div>
        <div>
          <strong>{data.performance}%</strong>
          <span>Aproveitamento</span>
        </div>
      </div>
    </section>
  )
}

export function H2H({ matches }) {
  return (
    <section className="panel history-panel">
      <div className="panel-title">
        <h2>Confrontos diretos</h2>
        <span>{matches.length} encontrados</span>
      </div>
      {matches.length ? (
        <div className="h2h-list">
          {matches.map((match) => (
            <div key={match.id_api}>
              <span>{formatDate(match.data_partida, false)}</span>
              <strong>{match.time_casa}</strong>
              <b>
                {match.gols_casa} × {match.gols_fora}
              </b>
              <strong>{match.time_fora}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="muted">Nenhum confronto anterior no banco.</p>
      )}
    </section>
  )
}
