import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

function normalizeProxyTarget(rawTarget) {
  if (!rawTarget) return 'http://127.0.0.1:8000'
  try {
    const parsed = new URL(rawTarget)
    if (parsed.hostname === 'localhost' || parsed.hostname === '[::1]' || parsed.hostname === '::1') {
      parsed.hostname = '127.0.0.1'
    }
    return parsed.toString().replace(/\/$/, '')
  } catch {
    return 'http://127.0.0.1:8000'
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = normalizeProxyTarget(env.VITE_API_PROXY_TARGET || env.VITE_API_BASE_URL)

  return {
    plugins: [react()],
    
    server: {
      port: 5173,
      open: true,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
          secure: false,
        }
      }
    },
  
    // Production build configuration
    build: {
      // Disable source maps in production for security
      sourcemap: mode !== 'production',
      
      // Chunk splitting for better caching
      rollupOptions: {
        output: {
          manualChunks: {
            // Vendor chunks for better caching
            'vendor-react': ['react', 'react-dom', 'react-router-dom'],
            'vendor-mui': ['@mui/material', '@mui/icons-material', '@emotion/react', '@emotion/styled'],
          }
        }
      },
      
      // Minification settings
      minify: mode === 'production' ? 'esbuild' : false,
      
      // Target modern browsers for smaller bundles
      target: 'es2020',
    },
    
    // Define global constants
    define: {
      __APP_VERSION__: JSON.stringify(process.env.npm_package_version || '1.0.0'),
      __BUILD_TIME__: JSON.stringify(new Date().toISOString()),
    },
    
    test: {
      globals: true,
      environment: 'jsdom',
      include: ['tests/**/*.spec.ts', 'src/**/*.test.{ts,tsx,js,jsx}', 'src/**/__tests__/*.{js,jsx,ts,tsx}'],
      coverage: {
        provider: 'v8',
        reporter: ['text', 'json', 'html'],
        include: ['src/**/*.{ts,tsx}'],
        exclude: ['src/**/*.d.ts', 'src/types/**'],
      },
    },
  }
})