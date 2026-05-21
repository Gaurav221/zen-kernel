/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        fio:  { DEFAULT: "#3b82f6", light: "#93c5fd", dark: "#1d4ed8" },
        log:  { DEFAULT: "#10b981", light: "#6ee7b7", dark: "#047857" },
        cmd:  { DEFAULT: "#f59e0b", light: "#fcd34d", dark: "#b45309" },
      },
    },
  },
  plugins: [],
};
