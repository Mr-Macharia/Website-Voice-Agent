/** @type {import('prettier').Config} */
module.exports = {
  singleQuote: true,
  semi: false,
  trailingComma: 'none',
  plugins: ['prettier-plugin-tailwindcss'],
  tailwindStylesheet: './src/app/globals.css',
  filepath: './src/**/*.{js,ts,jsx,tsx}'
}
