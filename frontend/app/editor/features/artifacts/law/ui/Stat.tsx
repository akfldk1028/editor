interface Props {
  label: string
  value: string
  note?: string | null
  basis?: string | null
  tone?: 'warn'
}

/** One number with its label, a note under it and the article it rests on. */
export function Stat({ label, value, note, basis, tone }: Props) {
  return (
    <div className="law-stat" data-tone={tone}>
      <span>{label}</span>
      <b>{value}</b>
      {note && <small>{note}</small>}
      {basis && <small className="law-basis">{basis}</small>}
    </div>
  )
}
