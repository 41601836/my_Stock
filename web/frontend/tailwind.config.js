/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        darkBg: "#0B0F19",
        cardBg: "#151D30",
        borderBg: "#222F4C",
        neonGreen: "#10B981",
        neonRed: "#EF4444",
        neonPurple: "#A855F7"
      }
    },
  },
  plugins: [],
}
