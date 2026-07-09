/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        'chat-bg':      '#212121',
        'chat-card':    '#2F2F2F',
        'chat-border':  '#3A3A3A',
        'chat-text':    '#ECECEC',
        'chat-accent':  '#10A37F',
        'chat-sidebar': '#171717',
        'chat-code':    '#1a1a1a',
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
}
