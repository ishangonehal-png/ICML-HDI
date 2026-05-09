import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        shell: {
          bg: "#0b1020",
          panel: "#111831",
          border: "#24325c",
        },
      },
    },
  },
  plugins: [],
};

export default config;
