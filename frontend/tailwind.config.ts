import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#080f16",
        panel: "#0e1822",
        accent: "#5ad1ff",
        accentDim: "#3fb8ea",
        ok: "#3ddc97",
        warn: "#ffb547",
        danger: "#ff5d6c",
        steel: "#8fa5b6",
      },
      fontFamily: {
        display: ['"Barlow Condensed"', "system-ui", "sans-serif"],
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;