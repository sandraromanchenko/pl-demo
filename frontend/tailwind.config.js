/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      // Percona Live 2026 deck palette, sampled from the slides.
      colors: {
        brand: {
          bg: "#282727",
          deep: "#1F1E1E",
          panel: "#323131",
          line: "#403F3F",
          muted: "#A3A2A2",
          volt: "#F6FE54",
          grape: "#653DF4",
        },
      },
    },
  },
  plugins: [],
};
