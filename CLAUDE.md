# BubbleStone — Conventions projet

## Structure monorepo
```
site/     → site web Astro (bubblestone.ai)
apps/     → applications (555-trend-monitor, linkedin-generator, audit-platform)
infra/    → docker-compose, scripts maintenance, configs
```

## Git workflow (GitHub Flow)
- Branche par defaut : `main` (protegee, jamais de push direct)
- Tout changement passe par une feature branch + Pull Request
- Nommage des branches : `feat/description`, `fix/description`, `refactor/description`
- 1 review approuvee minimum avant merge
- Branches supprimees apres merge

## Deploiement (CI/CD)
- Push sur `main` → GitHub Actions build → deploy staging auto
- Production : `workflow_dispatch` manuel uniquement
- Toute modification site → staging d'abord, validation, puis production

## Conventions
- Commits en anglais, communication en francais
- Les .env et secrets ne sont JAMAIS commites
- Structure des commits : `type(scope): description` (feat, fix, refactor, docs)
