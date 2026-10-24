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
        sans: ['system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      boxShadow: {
        'bento': '0 2px 8px -1px rgba(0, 0, 0, 0.25), 0 1px 3px -1px rgba(0, 0, 0, 0.2)',
        'bento-accent': '0 0 18px -4px rgba(201, 164, 76, 0.25)',
        'glass-highlight': 'inset 0 1px 0 0 rgba(255, 255, 255, 0.07)',
        'glass-highlight-light': 'inset 0 1px 0 0 rgba(255, 255, 255, 0.75)',
      },
      borderRadius: {
        'sm': '3px',
        'DEFAULT': '4px',
        'md': '6px',
      },
    },
  },
  plugins: [],
}
