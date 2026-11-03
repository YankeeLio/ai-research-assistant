import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#EDEAE1",
        ink: "#191813",
        blueprint: "#1F4E63",
        signal: "#A63C2A",
        graphite: "#2A2B27",
        haze: "#CFCABD",
        mist: "#F7F5EF",
      },
      fontFamily: {
        serif: ["Georgia", "Songti SC", "SimSun", "serif"],
        sans: ["Segoe UI", "Microsoft YaHei", "system-ui", "sans-serif"],
        mono: ["Consolas", "SFMono-Regular", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
