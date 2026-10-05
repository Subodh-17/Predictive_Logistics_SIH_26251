import { Area, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { dd, fx } from '../format'
import { usePalette } from '../theme'


export interface Pt { date: string; [k: string]: number | string | null | number[] | undefined }

export function LineChartBox({ data, lines, band, height = 250, xFormat = dd, refLine, zoom = false }: {
  data: Pt[]; lines: { key: string; name: string; color: string; dashed?: boolean }[]; band?: { key: string; name: string }; height?: number
  xFormat?: (s: string) => string; refLine?: { y: number; label: string }; zoom?: boolean
}) {
  const pal = usePalette()
  const AX = { stroke: pal.grid, tick: { fill: pal.axis, fontSize: 10 } }
  const TT = { contentStyle: { background: pal.ttBg, border: `1px solid ${pal.ttBorder}`, fontSize: 12, color: pal.tx }, labelStyle: { color: pal.tx }, itemStyle: { color: pal.tx } }
  // zoom: fit the y-axis to the data instead of starting at 0 (used for demand charts where the level is large vs. the variation)
  let domain: [number, number] | undefined
  if (zoom) {
    const vs: number[] = []
    data.forEach(d => Object.values(d).forEach(v => { if (typeof v === 'number') vs.push(v); else if (Array.isArray(v)) vs.push(...v) }))
    if (vs.length) { const lo = Math.min(...vs), hi = Math.max(...vs), pad = (hi - lo) * 0.12 || hi * 0.05; domain = [Math.max(0, Math.floor(lo - pad)), Math.ceil(hi + pad)] }
  }
  return (
    <div style={{ height }} role="img" aria-label="chart">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={pal.grid} strokeOpacity={0.6} vertical={false} />
          <XAxis dataKey="date" tickFormatter={xFormat} {...AX} minTickGap={28} />
          <YAxis tickFormatter={v => fx(v)} {...AX} width={56} domain={domain ?? [0, 'auto']} allowDataOverflow={false} />
          <Tooltip {...TT} formatter={(v: unknown) => Array.isArray(v) ? `${fx(v[0] as number)} – ${fx(v[1] as number)}` : fx(v as number)} labelFormatter={l => xFormat(String(l))} />
          <Legend />
          {band && <Area dataKey={band.key} name={band.name} stroke="none" fill={pal.accent} fillOpacity={0.18} isAnimationActive={false} />}
          {lines.map(l => <Line key={l.key} dataKey={l.key} name={l.name} stroke={l.color} strokeWidth={1.8} dot={false} strokeDasharray={l.dashed ? '5 4' : undefined} connectNulls={false} isAnimationActive={false} />)}
          {refLine && <ReferenceLine y={refLine.y} stroke={pal.danger} strokeDasharray="4 4" label={{ value: refLine.label, fill: pal.danger, fontSize: 10, position: 'insideTopRight' }} />}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
