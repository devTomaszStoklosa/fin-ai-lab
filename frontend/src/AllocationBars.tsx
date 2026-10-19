// Same accent shades as the original PortfolioDetail mockup's asset-class
// chart -- cycled by position, not tied to any specific category, so it
// works unchanged for both asset-class and currency allocation.
const BAR_COLORS = ['#2E3A59', '#7C8FB8', '#C9B896', '#D8D2C4', '#A9B4C2', '#8C7A5D']

type Props = {
  title: string
  allocation: Record<string, string>
}

function AllocationBars({ title, allocation }: Props) {
  const entries = Object.entries(allocation).sort((a, b) => Number(b[1]) - Number(a[1]))
  if (entries.length === 0) return null

  return (
    <div className="allocation">
      <h3>{title}</h3>
      <div className="allocation-bars">
        {entries.map(([key, pct], index) => (
          <div className="allocation-row" key={key}>
            <div className="allocation-label">
              <span>{key}</span>
              <span className="mono">{pct}%</span>
            </div>
            <div className="allocation-track">
              <div
                className="allocation-fill"
                style={{ width: `${pct}%`, background: BAR_COLORS[index % BAR_COLORS.length] }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default AllocationBars
