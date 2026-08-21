export function Standings({ rows }) {
  if (!rows?.length) return <p className="muted">Classificação indisponível para esta liga.</p>
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Time</th>
            <th>J</th>
            <th>V</th>
            <th>E</th>
            <th>D</th>
            <th>SG</th>
            <th>Pts</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.time_id} className={row.position <= 4 ? 'top-row' : ''}>
              <td>{row.position}</td>
              <td>
                <strong>{row.team}</strong>
              </td>
              <td>{row.played}</td>
              <td>{row.wins}</td>
              <td>{row.draws}</td>
              <td>{row.losses}</td>
              <td>
                {row.goal_difference > 0 ? '+' : ''}
                {row.goal_difference}
              </td>
              <td className="points">{row.points}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
