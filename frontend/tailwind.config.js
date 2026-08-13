/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: "rgb(var(--ink) / <alpha-value>)",
        mist: "rgb(var(--mist) / <alpha-value>)",
        pine: "rgb(var(--pine) / <alpha-value>)",
        fern: "rgb(var(--fern) / <alpha-value>)",
        butter: "rgb(var(--butter) / <alpha-value>)",
        clay: "rgb(var(--clay) / <alpha-value>)",
        paper: "rgb(var(--paper) / <alpha-value>)",
        line: "rgb(var(--line) / <alpha-value>)",
      },
      fontFamily: {
        display: ["Bricolage Grotesque", "ui-sans-serif", "sans-serif"],
        sans: ["Figtree", "ui-sans-serif", "sans-serif"],
      },
      boxShadow: {
        soft: "0 1px 0 rgba(20, 36, 28, 0.06), 0 12px 32px rgba(20, 36, 28, 0.08)",
      },
      keyframes: {
        rise: {
          from: { opacity: "0", transform: "translateY(12px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        fade: {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        pulseBar: {
          "0%, 100%": { transform: "scaleX(0.35)", opacity: "0.45" },
          "50%": { transform: "scaleX(1)", opacity: "1" },
        },
      },
      animation: {
        rise: "rise 0.55s ease-out both",
        "rise-delay": "rise 0.55s ease-out 0.08s both",
        "rise-delay-2": "rise 0.55s ease-out 0.16s both",
        fade: "fade 0.4s ease-out both",
        "pulse-bar": "pulseBar 1.1s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
