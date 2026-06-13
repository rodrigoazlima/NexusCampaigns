import { dirname } from 'path'
import { fileURLToPath } from 'url'
import nextConfig from 'eslint-config-next'

const __dirname = dirname(fileURLToPath(import.meta.url))

export default [
  ...nextConfig,
  {
    languageOptions: {
      parserOptions: {
        project: './tsconfig.json',
        tsconfigRootDir: __dirname,
      },
    },
  },
]
