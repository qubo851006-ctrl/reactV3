import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        // Split heavy third-party libs into separate vendor chunks so the main
        // app bundle shrinks and rarely-changing libs cache independently.
        // recharts(+d3) and html2canvas are the biggest; react-markdown's
        // dependency tree is broad so match its ecosystem by name fragments.
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('recharts') || id.includes('/d3-') || id.includes('victory')) return 'charts'
          if (id.includes('html2canvas')) return 'html2canvas'
          if (/react-markdown|remark|micromark|mdast|hast|unist|character-entities|property-information|space-separated|comma-separated|trim-lines|decode-named/.test(id)) return 'markdown'
          if (id.includes('react-dom') || id.includes('/scheduler/') || /node_modules\/react\//.test(id)) return 'react-vendor'
          return 'vendor'
        },
      },
    },
  },
})
