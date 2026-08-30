/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        cyber: {
          bg: '#0a0d14',          // Deep cyber background
          card: '#111622',        // Glassy dark card
          cardlight: '#182030',   // Active/hover card background
          text: '#e2e8f0',        // Base text
          primary: '#38bdf8',     // Electric blue
          success: '#10b981',     // Terminal green
          warning: '#f59e0b',     // Threat warning yellow
          danger: '#ef4444',      // Threat block red
          border: '#1e293b'       // Card border slate
        }
      },
      fontFamily: {
        mono: ['Fira Code', 'Courier New', 'Courier', 'monospace'],
        sans: ['Outfit', 'Inter', 'system-ui', 'sans-serif']
      }
    },
  },
  plugins: [],
}
