import type { Config } from 'tailwindcss'

const config: Config = {
  darkMode: 'class',
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['IBM Plex Sans', 'system-ui', 'sans-serif'],
        mono: ['IBM Plex Mono', 'monospace'],
      },
      colors: {
        surface: {
          DEFAULT: '#09090b',
          1: '#111113',
          2: '#18181b',
          3: '#27272a',
          4: '#3f3f46',
        },
        primary: {
          DEFAULT: '#0C5CAB',
          hover: '#0a4a8a',
          light: '#1d7ad4',
          muted: '#0C5CAB33',
        },
        success: { DEFAULT: '#10b981', muted: '#10b98120' },
        warning: { DEFAULT: '#f59e0b', muted: '#f59e0b20' },
        danger:  { DEFAULT: '#ef4444', muted: '#ef444420' },
        neutral: { DEFAULT: '#6b7280', light: '#9ca3af' },
      },
      borderRadius: { sm: '4px', DEFAULT: '6px', md: '8px', lg: '12px', xl: '16px' },
      boxShadow: {
        card: '0 1px 3px rgba(0,0,0,0.4), 0 1px 2px rgba(0,0,0,0.3)',
        glow: '0 0 0 1px rgba(12,92,171,0.4)',
      },
      keyframes: {
        pulse_dot: { '0%,100%': { opacity: '1' }, '50%': { opacity: '0.3' } },
        slide_in: { from: { opacity: '0', transform: 'translateY(8px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
      },
      animation: {
        pulse_dot: 'pulse_dot 1.5s ease-in-out infinite',
        slide_in: 'slide_in 0.2s ease-out',
      },
    },
  },
  plugins: [],
}
export default config
