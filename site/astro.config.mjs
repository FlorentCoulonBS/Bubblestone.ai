// @ts-check
import { defineConfig } from 'astro/config';

// https://astro.build/config
export default defineConfig({
  site: 'https://bubblestone.ai',
  base: '/',
  output: 'static',
  server: {
    host: '0.0.0.0',
    port: 4321,
  },
});
