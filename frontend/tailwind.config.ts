import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}"
  ],
  theme: {
    extend: {
      // Legacy utility names resolve to the same dark semantic palette as new primitives.
      colors: {
        canvas: '#0b111b', surface: '#121c29', raised: '#1b2939', ink: '#ecf2f8', muted: '#9cacc0', accent: '#5ee0bd',
        white: '#121c29',
        gray: { 50: '#0b111b', 100: '#223145', 200: '#314359', 300: '#8c9eb4', 400: '#9cacc0', 500: '#a6b5c7', 600: '#b5c3d3', 700: '#cbd7e5', 800: '#dce6f0', 900: '#ecf2f8' },
        slate: { 50: '#0e1723', 100: '#223145', 200: '#314359', 300: '#7890a9', 400: '#9cacc0', 500: '#a6b5c7', 600: '#b5c3d3', 700: '#cbd7e5', 800: '#1b2939', 900: '#172537' },
        blue: { 50: '#122f2e', 100: '#1b4540', 200: '#27665c', 300: '#3c9f89', 400: '#4dc6a8', 500: '#5ee0bd', 600: '#207b68', 700: '#8cebd2', 800: '#b1f4e2' },
        indigo: { 50: '#202b43', 100: '#2a3958', 200: '#41567b', 400: '#9eb8f3', 500: '#779be5', 600: '#4564a2', 700: '#b0c8fa', 800: '#d0dfff' },
        emerald: { 50: '#112e29', 100: '#1c483c', 200: '#2b6956', 500: '#54d2a7', 600: '#67dfb8', 700: '#88ebcc', 800: '#296653' },
        amber: { 50: '#30271b', 100: '#514029', 200: '#715832', 600: '#e9bd70', 700: '#f1cc89', 800: '#f1cc89', 900: '#f5d9a7' },
        red: { 50: '#301e28', 100: '#512b38', 200: '#703b49', 400: '#fa9aab', 500: '#f48ca1', 600: '#f7a1b0', 700: '#ffb8c4', 800: '#ffd0d8' },
        orange: { 50: '#30251e', 100: '#51372b', 200: '#6c4a34', 600: '#edb187', 700: '#f6c3a0' }
      },
      borderRadius: { xl: '12px', '2xl': '16px' },
      boxShadow: { panel: '0 8px 28px rgb(0 0 0 / 12%)', float: '0 16px 60px rgb(0 0 0 / 45%)' }
    }
  },
  plugins: []
};

export default config;