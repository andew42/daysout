import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies API, tiles and basemap assets to the Go backend;
// run `go run .` in backend/ alongside `npm start`.
const proxyTarget = 'http://localhost:8080'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'build',
  },
  server: {
    proxy: {
      '/api': proxyTarget,
      '/tiles': proxyTarget,
      '/basemap': proxyTarget,
    },
  },
})
