/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_DIRECT_URL?: string
  readonly VITE_API_PROXY?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

