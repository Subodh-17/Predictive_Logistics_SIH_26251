/** @type {import('tailwindcss').Config} */
// Colours are CSS variables (see src/index.css) so the same classes serve the Dark (default) and Light themes.
const v = n => `rgb(var(--${n}) / <alpha-value>)`
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: v('bg'), pn: v('pn'), pn2: v('pn2'), ln: v('ln'), tx: v('tx'), mu: v('mu'), hi: v('hi'),
        ac: v('ac'), act: v('act'), onac: v('onac'), ok: v('ok'), wr: v('wr'), wrf: v('wrf'), cr: v('cr'),
        ins: v('ins'), hov: v('hov'), rowln: v('rowln'), bar: v('bar'), side: v('side'), soft: v('soft'),
        errbg: v('errbg'), errtx: v('errtx'), warnbg: v('warnbg'), footbg: v('footbg'),
      },
      fontFamily: {
        mono: ['ui-monospace', 'Menlo', 'Consolas', 'monospace'],
        sans: ['system-ui', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
