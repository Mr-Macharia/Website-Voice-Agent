import type { Config } from 'tailwindcss'
import tailwindcssAnimate from 'tailwindcss-animate'

export default {
  darkMode: ['class'],
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}'
  ],
  theme: {
    extend: {
      colors: {
        primary: '#FAFAFA',
        primaryAccent: '#0f172a',
        brand: '#e85d04',
        accentFire: '#dc2f02',
        accentGold: '#f48c06',
        background: {
          DEFAULT: '#0a0f1e',
          secondary: '#0f172a',
          tertiary: '#1e293b'
        },
        secondary: '#f1f5f9',
        border: 'rgba(var(--color-border-default))',
        accent: '#1e293b',
        muted: '#94a3b8',
        destructive: '#dc2f02',
        positive: '#22c55e'
      },
      fontFamily: {
        main: ['Georama', 'sans-serif'],
        large: ['Host Grotesk', 'sans-serif'],
        mono: ['Fira Code', 'monospace'],
        geist: ['Georama', 'sans-serif'],
        dmmono: ['Fira Code', 'monospace']
      },
      borderRadius: {
        xl: '14px',
        '2xl': '20px',
        '3xl': '28px'
      }
    }
  },
  plugins: [tailwindcssAnimate]
} satisfies Config
