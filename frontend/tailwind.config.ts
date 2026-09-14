import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#F7F8F7",
        surface: "#FFFFFF",
        ink: "#1B1F1D",
        muted: "#5B6660",
        border: "#E2E5E2",
        accent: {
          DEFAULT: "#2F6F62",
          soft: "#E6EEEC",
        },
        match: {
          DEFAULT: "#2F6F62",
          soft: "#E6EEEC",
        },
        nomatch: {
          DEFAULT: "#A23B3B",
          soft: "#F5E9E9",
        },
        unclear: {
          DEFAULT: "#93701E",
          soft: "#F5EEDD",
        },
      },
      fontFamily: {
        serif: ["var(--font-source-serif)", "Georgia", "serif"],
        sans: ["var(--font-plex-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-plex-mono)", "ui-monospace", "monospace"],
      },
      maxWidth: {
        reading: "42rem",
      },
    },
  },
  plugins: [],
};

export default config;
