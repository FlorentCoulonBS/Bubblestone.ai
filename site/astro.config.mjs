// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// https://astro.build/config
export default defineConfig({
  site: 'https://bubblestone.ai',
  base: '/',
  output: 'static',
  integrations: [
    sitemap({
      changefreq: 'weekly',
      priority: 0.7,
      lastmod: new Date(),
      filter: (page) => !page.includes('/mentions-legales') && !page.includes('/confidentialite'),
    }),
  ],
  server: {
    host: '0.0.0.0',
    port: 4321,
  },
});
