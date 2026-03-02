# BubbleStone.ai — Monorepo

Infrastructure and applications for the BubbleStone server (72.62.190.147).

## Structure

```
site/                   Astro website (bubblestone.ai)
apps/
  555-trend-monitor/    AI Trend Dashboard (Flask/Python)
  linkedin-generator/   LinkedIn post generator (Flask/Python)
  audit-platform/       Web audit platform (Flask/Python)
infra/
  docker-compose.yml    Docker orchestration
  maintenance.sh        Daily maintenance script
  .env.example          Environment variables template
```

## Deployment

- **Site**: push to `main`/`master` → auto-deploy to staging. Manual workflow dispatch for production.
- **Apps**: deployed via Docker on the server. Code changes must be committed here, then deployed manually.

## Rules

- **NEVER** commit `.env` files or secrets
- **ALWAYS** commit and push after every code/config change
- Test on staging before deploying to production
