# bubblestone-leximpact

Service legacy hébergé sur BubbleStone servant `leximpact.bubblestone.ai`.

Le **compose** est versionné ici. Le **build context** (Dockerfile + HTML/CSS/JS) vit sur le serveur dans `/opt/bubblestone-leximpact/`. Pas versionné en repo : service statique legacy, contenu rarement modifié.

## Deploy
```bash
cd /opt/bubblestone-leximpact
docker compose -p bubblestone-leximpact up -d
```

Le réseau `bubblestone-net` doit exister (créé par la stack `bubblestone` principale).
