/**
 * BubbleStone AI — WebMCP Imperative API
 * Exposes structured tools for AI agents via navigator.modelContext
 * 
 * Tools registered:
 * - get_bubblestone_services: List all AI consulting services
 * - get_bubblestone_pricing: Get pricing information  
 * - get_bubblestone_expertise: Get expertise and technology stack
 * - search_bubblestone_blog: Search blog articles
 */

(function() {
  'use strict';

  // Wait for polyfill or native support
  function initWebMCP() {
    if (!navigator.modelContext) return;

    // Tool 1: Services catalog
    navigator.modelContext.registerTool({
      name: 'get_bubblestone_services',
      description: 'Get the full list of AI consulting and automation services offered by BubbleStone AI, a French agency specializing in enterprise AI integration. Services include IT management, process automation, data management, AI/ML, and sales prospection.',
      inputSchema: {
        type: 'object',
        properties: {
          category: {
            type: 'string',
            description: 'Optional filter: pilotage-it, automatisation, data, processus, prospection, ia-ml',
            enum: ['pilotage-it', 'automatisation', 'data', 'processus', 'prospection', 'ia-ml']
          }
        }
      },
      handler: function(params) {
        var services = [
          { id: 'pilotage-it', name: 'Pilotage IT 360°', description: 'Déploiement, monitoring proactif, support réactif, optimisation des coûts, Infrastructure as Code. L\'IA au cœur de votre infrastructure.', technologies: ['Docker', 'Terraform', 'CI/CD', 'Linux', 'Monitoring'] },
          { id: 'automatisation', name: 'Automatisation de processus', description: 'Workflows n8n, intégrations API, MCP (Model Context Protocol), automatisation 24/7. Produire plus, plus vite, sans effort supplémentaire.', technologies: ['n8n', 'API', 'Webhooks', 'MCP', 'Agents IA'] },
          { id: 'data', name: 'Data Management', description: 'Centralisation des données, bases de connaissances, ETL & pipelines, qualité des données. Valoriser le savoir de votre entreprise.', technologies: ['PostgreSQL', 'ETL', 'RAG', 'Embeddings', 'Vector DB'] },
          { id: 'processus', name: 'Processus Métier', description: 'Digitalisation des processus, réduction des erreurs, traçabilité complète, gains de productivité mesurables.', technologies: ['Workflow', 'BPM', 'Automatisation', 'Audit'] },
          { id: 'prospection', name: 'Prospection Commerciale IA', description: 'Enrichissement de leads, scoring prédictif, intégration CRM, veille automatisée. Des équipes Sales augmentées par l\'IA.', technologies: ['CRM', 'Lead scoring', 'Enrichissement', 'Veille'] },
          { id: 'ia-ml', name: 'IA & Machine Learning', description: 'LLM personnalisés, agents autonomes, fine-tuning, RAG & embeddings. Chaque modèle adapté à chaque besoin métier.', technologies: ['LLM', 'Claude', 'Mistral', 'Fine-tuning', 'RAG', 'Agents IA', 'MCP'] }
        ];
        if (params && params.category) {
          services = services.filter(function(s) { return s.id === params.category; });
        }
        return { services: services, contact: 'https://bubblestone.ai/#contact', email: 'florent.coulon@bubblestone.ai' };
      }
    });

    // Tool 2: Pricing
    navigator.modelContext.registerTool({
      name: 'get_bubblestone_pricing',
      description: 'Get pricing information for BubbleStone AI consulting services. Daily rate between 600€ and 800€ depending on project complexity. Based in France.',
      inputSchema: { type: 'object', properties: {} },
      handler: function() {
        return {
          daily_rate: { min: 600, max: 800, currency: 'EUR' },
          pricing_model: 'Journalier (daily rate)',
          note: 'Chaque euro investi doit générer un retour mesurable.',
          process: ['1. Audit de l\'existant', '2. Étude de faisabilité et ROI', '3. PRD (Product Requirements Document)', '4. Implémentation IA', '5. Maintenance & évolution continue'],
          contact: 'https://bubblestone.ai/#contact'
        };
      }
    });

    // Tool 3: Expertise
    navigator.modelContext.registerTool({
      name: 'get_bubblestone_expertise',
      description: 'Get the technical expertise and technology stack of BubbleStone AI founder Florent Coulon. 20+ years IT experience, 100+ AI agents deployed, 130+ automated workflows.',
      inputSchema: { type: 'object', properties: {} },
      handler: function() {
        return {
          founder: { name: 'Florent Coulon', experience: '20+ years IT', linkedin: 'https://www.linkedin.com/in/coulonflorent/' },
          stats: { agents_deployed: '100+', workflows_automated: '130+', years_experience: '20+' },
          stack: {
            ai_ml: ['LLM', 'Claude', 'Mistral', 'RAG', 'Fine-tuning', 'Agents IA', 'MCP', 'Embeddings'],
            infrastructure: ['Docker', 'Terraform', 'CI/CD', 'Linux', 'Nginx', 'PostgreSQL', 'GitHub Actions'],
            automation: ['n8n', 'API', 'Webhooks', 'Workflows', 'CRM', 'ETL', 'Scraping']
          },
          location: 'France',
          website: 'https://bubblestone.ai'
        };
      }
    });

    console.log('[WebMCP] BubbleStone AI tools registered: get_bubblestone_services, get_bubblestone_pricing, get_bubblestone_expertise');
  }

  // Try init immediately, or wait for polyfill
  if (navigator.modelContext) {
    initWebMCP();
  } else {
    // Retry after polyfill loads
    var attempts = 0;
    var interval = setInterval(function() {
      attempts++;
      if (navigator.modelContext) {
        clearInterval(interval);
        initWebMCP();
      } else if (attempts > 20) {
        clearInterval(interval);
      }
    }, 250);
  }
})();
