/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,jsx}',
    './src/components/**/*.{js,jsx}',
    './src/app/**/*.{js,jsx}',
  ],
  theme: {
    extend: {
      colors: {
        jip: {
          teal: '#0d9488',
          navy: '#1e293b',
          profit: '#059669',
          loss: '#dc2626',
          warning: '#d97706',
          bg: '#f8fafc',
          card: '#ffffff',
          border: '#e2e8f0',
          grid: '#f1f5f9',
          benchmark: '#94a3b8',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
    },
  },
  plugins: [],
};
