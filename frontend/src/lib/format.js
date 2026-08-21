export const SOURCE_NAMES = {
  onefootball: 'OneFootball',
  sofascore: 'SofaScore',
  football_data: 'football-data.org',
}

export function formatDate(value, withTime = true) {
  if (!value) return 'Data indefinida'
  return new Intl.DateTimeFormat('pt-BR', {
    timeZone: 'America/Sao_Paulo',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    ...(withTime ? { hour: '2-digit', minute: '2-digit' } : {}),
  }).format(new Date(value))
}

export function formatRelativeDay(value) {
  if (!value) return ''
  const date = new Date(value)
  const now = new Date()
  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const diffDays = Math.round((startOfDay(date) - startOfDay(now)) / 86400000)
  if (diffDays === 0) return 'Hoje'
  if (diffDays === 1) return 'Amanhã'
  if (diffDays === -1) return 'Ontem'
  if (diffDays > 1 && diffDays < 7) {
    return new Intl.DateTimeFormat('pt-BR', { weekday: 'long', timeZone: 'America/Sao_Paulo' }).format(date)
  }
  return formatDate(value, false)
}

export function formatNumber(value) {
  if (value === null || value === undefined) return '—'
  return value.toLocaleString('pt-BR')
}

export function initials(name = '') {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0])
    .join('')
    .toUpperCase()
}
