import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [
    sveltekit({
      adapter: adapter({
        // The Cloudflare Worker serves this folder as static assets next to the /api routes.
        pages: '../worker/public',
        assets: '../worker/public',
        fallback: 'index.html',
        precompress: false,
        strict: false
      }),
      files: { assets: 'public' }
    })
  ],
  server: {
    proxy: { '/api': { target: 'http://127.0.0.1:8787', changeOrigin: false } }
  }
});
