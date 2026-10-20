export const fx = (v: number | null | undefined, d = 0) =>
  v === null || v === undefined || !Number.isFinite(v) ? '—' : Number(v).toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d })
export const dd = (iso: string) => {
  const d = new Date(iso + (iso.length === 10 ? 'T00:00:00Z' : ''))
  return `${d.getUTCDate()} ${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getUTCMonth()]}`
}
export const statusColor = (s: string | null) => s === 'CRITICAL' ? '#e5534b' : s === 'WARNING' ? '#e0b83a' : '#3fbf7f'
export const riskColor = (r: number) => r < 0.3 ? '#3fbf7f' : r < 0.5 ? '#e0b83a' : '#e5534b'
export const riskLevel = (r: number) => r < 0.3 ? 'LOW' : r < 0.5 ? 'MODERATE' : 'HIGH'
export const weatherLabel = (v: number) => v === 0 ? 'Normal' : v < 0.5 ? 'Elevated' : v < 1 ? 'Heavy' : 'Severe'
export const roadLabel = (v: number) => v === 0 ? 'Good' : v < 0.5 ? 'Fair' : 'Poor'
