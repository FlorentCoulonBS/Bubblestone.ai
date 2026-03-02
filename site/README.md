# BubbleStone.ai - Site Web

Site web de BubbleStone.ai construit avec [Astro](https://astro.build) v5.

## Prérequis

- Node.js 18+ (recommandé: v20 ou supérieur)
- npm ou pnpm

## Installation

```bash
# Cloner le repository
git clone https://github.com/VOTRE-USERNAME/bubblestone-website.git
cd bubblestone-website

# Installer les dépendances
npm install
```

## Développement

```bash
# Lancer le serveur de développement
npm run dev
```

Le site sera accessible sur `http://localhost:4321`

## Build

```bash
# Générer le site statique
npm run build

# Prévisualiser le build
npm run preview
```

## Déploiement sur GitHub Pages

### 1. Créer le repository GitHub

```bash
# Si ce n'est pas déjà fait, initialiser git
git init

# Configurer le remote
git remote add origin https://github.com/VOTRE-USERNAME/bubblestone-website.git

# Ou si vous utilisez SSH
git remote add origin git@github.com:VOTRE-USERNAME/bubblestone-website.git
```

### 2. Configurer Astro pour GitHub Pages

Modifier `astro.config.mjs` avec vos informations :

```javascript
export default defineConfig({
  site: 'https://VOTRE-USERNAME.github.io',
  base: '/bubblestone-website',  // Nom de votre repo
});
```

**Note**: Si vous utilisez un domaine personnalisé (ex: bubblestone.ai), utilisez :
```javascript
export default defineConfig({
  site: 'https://bubblestone.ai',
  // Pas de base nécessaire avec un domaine personnalisé
});
```

### 3. Créer le workflow GitHub Actions

Créer le fichier `.github/workflows/deploy.yml` :

```yaml
name: Deploy to GitHub Pages

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm

      - name: Install dependencies
        run: npm ci

      - name: Build
        run: npm run build

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: ./dist

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

### 4. Configurer GitHub Pages

1. Aller dans les **Settings** de votre repository
2. Section **Pages** (dans la sidebar)
3. Source : sélectionner **GitHub Actions**

### 5. Pousser et déployer

```bash
# Ajouter tous les fichiers
git add .

# Premier commit
git commit -m "Initial commit - Site BubbleStone.ai avec Astro"

# Pousser sur GitHub
git push -u origin main
```

Le site sera automatiquement déployé à chaque push sur la branche `main`.

### 6. Configurer un domaine personnalisé (optionnel)

1. Dans **Settings > Pages**, ajouter votre domaine dans "Custom domain"
2. Créer un fichier `public/CNAME` contenant votre domaine :
   ```
   bubblestone.ai
   ```
3. Configurer les DNS chez votre registrar :
   - Type A vers les IPs GitHub Pages :
     - 185.199.108.153
     - 185.199.109.153
     - 185.199.110.153
     - 185.199.111.153
   - Ou CNAME vers `VOTRE-USERNAME.github.io`

## Structure du projet

```
/
├── public/
│   └── favicon.svg
├── src/
│   ├── components/
│   │   ├── Header.astro
│   │   ├── Hero.astro
│   │   ├── Services.astro
│   │   ├── About.astro
│   │   ├── Contact.astro
│   │   └── Footer.astro
│   ├── layouts/
│   │   └── Layout.astro
│   ├── pages/
│   │   └── index.astro
│   └── styles/
│       └── global.css
├── astro.config.mjs
├── package.json
└── tsconfig.json
```

## Personnalisation

### Couleurs

Les couleurs sont définies dans `src/styles/global.css` :

```css
:root {
  --color-primary: #020202;     /* Noir principal */
  --color-accent: #1e6aff;      /* Bleu accent */
  --color-white: #ffffff;
  --color-gray-light: #f4f4f4;
  --color-text-secondary: #666666;
}
```

### Contenu

- **Services** : Modifier `src/components/Services.astro`
- **À propos** : Modifier `src/components/About.astro`
- **Contact** : Modifier `src/components/Contact.astro`

## Commandes utiles

| Commande | Action |
|----------|--------|
| `npm run dev` | Démarre le serveur de développement |
| `npm run build` | Build le site pour la production |
| `npm run preview` | Prévisualise le build localement |

## Documentation Astro

- [Documentation officielle](https://docs.astro.build)
- [Guide GitHub Pages](https://docs.astro.build/en/guides/deploy/github/)
