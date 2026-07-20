/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./*.html"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'sans-serif'],
      },
      colors: {
        page: "#eef2e3",
        app: "#f6f4ec",
        ink: "#22301b",
        muted: "#6d7a63",
        accent: "#3f7d20",
        "accent-dark": "#2c5c14",
        "accent-soft": "#dcedc8",
        card: "#ffffff",
        border: "#e2e1d3",
        warn: "#c1440e",
        caution: "#b8860b",
        "caution-soft": "#faf1d6",
        danger: "#b3261e",
        "danger-soft": "#fbe4e2",
      },
      keyframes: {
        dotPulse: {
          "0%, 80%, 100%": { opacity: "0.25", transform: "scale(0.8)" },
          "40%": { opacity: "1", transform: "scale(1)" },
        },
      },
      animation: {
        "dot-pulse": "dotPulse 1s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
