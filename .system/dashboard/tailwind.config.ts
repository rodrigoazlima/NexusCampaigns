import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: '#09090b',
          1: '#111113',
          2: '#18181b',
          3: '#27272a',
          4: '#3f3f46',
        },
        primary: '#0C5CAB',
        success: '#10b981',
        warning: '#f59e0b',
        danger: '#ef4444',
        neutral: '#6b7280',
      },
      fontFamily: {
        sans: ['IBM Plex Sans', 'system-ui', 'sans-serif'],
        mono: ['IBM Plex Mono', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
}

export default config
