/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#f3efe6",
        raised: "#fbf8f3",
        ink: "#1c1915",
        muted: "#4f4a42",
        line: "#e3dcd0",
        copper: "#8f4318",
        sage: "#21593f",
        clay: "#8d3b32",
      },
      fontFamily: {
        display: ["Newsreader", "Iowan Old Style", "Palatino Linotype", "Palatino", "serif"],
        sans: ["IBM Plex Sans", "Segoe UI", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
      },
      boxShadow: {
        sheet: "0 18px 50px rgba(28, 25, 21, 0.06)",
      },
    },
  },
  plugins: [],
};
