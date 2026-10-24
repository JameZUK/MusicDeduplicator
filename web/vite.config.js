import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// Built straight into the Python package, so `pip install` ships the dashboard
// and nobody needs Node unless they change the UI.
export default defineConfig({
  plugins: [svelte()],
  base: './',
  build: {
    outDir: '../src/musicdedup/web/static',
    emptyOutDir: true,
    assetsInlineLimit: 0,
  },
  server: {
    // `npm run dev` proxies the API to a running `musicdedup serve`.
    proxy: { '/api': 'http://127.0.0.1:8650' },
  },
});
