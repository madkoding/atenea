# Atenea Pro

[Español](#espanol) | [English](#english)

---

## Espanol

Atenea Pro es un fork mejorado de [Atenea](https://github.com/madkoding/atenea), orientado a una experiencia mas completa, mantenible y enfocada en uso real diario.

### Que es Atenea Pro

- Workspace de IA self-hosted con chat, agente, documentos, memoria, research, email y calendario.
- Fork activo con cambios funcionales, mejoras de arquitectura y mas control para personalizacion/operacion.
- Rama estable: `main`.

### Mejoras sobre el proyecto original

Estas son las mejoras clave implementadas en este fork (sobre upstream):

- **Bilingue real (UI + comportamiento IA):**
  - Interfaz EN/ES con runtime i18n (`static/js/i18n.js`) y toggle de idioma.
  - Locales extensas (`static/js/locales/en.json`, `static/js/locales/es.json`) con paridad de claves.
  - Prompts y flujos principales adaptados para responder en espanol cuando `ui_language=es` (chat, agent loop, deep research, memory, skills, presets y youtube handler).
- **Arquitectura mas mantenible (reorganizacion por dominios):**
  - Migracion desde un `src/` plano a paquetes por dominio: `src/chat/`, `src/agent/`, `src/research/`, `src/tools/`, `src/runtime/`, `src/vector/`, etc.
  - Menor acoplamiento, mejor separacion de responsabilidades y ubicacion mas predecible del codigo.
  - Compatibilidad preservada en modulos publicos de `src/` para reducir friccion en merges y uso externo.
- **Rendimiento y robustez backend:**
  - Mejoras en fallback/model endpoint y cacheado para reducir consultas repetidas.
  - Integracion de cache por regiones (Dogpile) para DB/LLM/settings/context.
  - Ajustes en timeouts de research para escenarios de carga en frio de modelos locales.
- **UX y personalizacion avanzadas:**
  - Sistema de temas ampliado (fuentes por zona, tamano por zona, fondo custom, control de ajuste/posicion, variantes visuales).
  - Mejoras en paneles internos (calendar, tasks, settings, notes, gallery, cookbook, skills, memory, compare).
- **Nuevas capacidades funcionales:**
  - Integracion/flujo de imagenes (A1111 Stable Diffusion) en stack y herramientas del agente.
  - Incorporacion de mejoras/bugfixes de upstream mediante merges periodicos.
- **Mejor base operativa para colaboracion:**
  - CI y validaciones para sintaxis Python/JS y tests.
  - Documentacion de contribucion y estrategia de ramas orientada a estabilidad (`main`) y desarrollo (`dev`).

### Estructura de codigo (mantenibilidad)

Arquitectura principal en este fork:

```text
app.py                # entrada FastAPI
core/                 # auth, middleware, capa base
routes/               # endpoints HTTP por dominio
services/             # servicios de aplicacion
src/
  chat/               # pipeline de chat
  agent/              # orquestacion del agente
  research/           # deep research + extractores
  tools/              # herramientas y ejecucion
  runtime/            # bootstrap, config, endpoint resolver
  vector/             # embeddings + store vectorial
  memory/             # memoria persistente
  email/ calendar_app/# integraciones funcionales
  ...
static/               # frontend modular (js/css/html)
tests/                # suite de pruebas + estandares
```

Este layout mejora mantenibilidad porque:

- reduce el efecto "archivo gigante en raiz";
- facilita ownership por dominio;
- simplifica refactor y testing aislado;
- hace mas seguros los merges frecuentes con upstream.

### Instalacion rapida

```bash
git clone https://github.com/madkoding/atenea-pro.git
cd atenea-pro
git checkout main
cp .env.example .env
docker compose up -d --build
```

Abrir: `http://localhost:7000`

### Ramas

- `main`: estable (default branch)
- `dev`: integracion y desarrollo

---

## English

Atenea Pro is an improved fork of [Atenea](https://github.com/madkoding/atenea), focused on a more complete, maintainable, and production-minded self-hosted AI workspace.

### What Atenea Pro is

- A self-hosted AI workspace with chat, agent, documents, memory, research, email, and calendar.
- An active fork with functional enhancements, architecture improvements, and stronger operational control.
- Stable branch: `main`.

### Improvements over the original project

Key improvements currently included in this fork:

- **True bilingual behavior (UI + AI behavior):**
  - EN/ES interface with i18n runtime (`static/js/i18n.js`) and language toggle.
  - Large locale dictionaries (`static/js/locales/en.json`, `static/js/locales/es.json`) with key parity.
  - Core prompt flows adapted to answer in Spanish when `ui_language=es` (chat, agent loop, deep research, memory, skills, presets, youtube handler).
- **More maintainable architecture (domain-oriented refactor):**
  - Migration from a flat `src/` layout to domain packages such as `src/chat/`, `src/agent/`, `src/research/`, `src/tools/`, `src/runtime/`, `src/vector/`, etc.
  - Clearer separation of concerns, lower coupling, easier navigation.
  - Public compatibility modules preserved at `src/` root to reduce breakage and ease upstream sync.
- **Backend performance and resilience:**
  - Endpoint fallback improvements and caching to reduce repeated lookups.
  - Dogpile cache regions for DB/LLM/settings/context.
  - Research timeout tuning for local-model cold-start scenarios.
- **Advanced UX and customization:**
  - Extended theme system (per-zone fonts, per-zone font sizes, custom backgrounds, fit/position controls, visual variants).
  - Broader internal panel polish (calendar, tasks, settings, notes, gallery, cookbook, skills, memory, compare).
- **New functional capabilities:**
  - Image-generation tooling path (A1111 Stable Diffusion) integrated with stack and agent tooling.
  - Ongoing upstream bugfix/features periodically merged into this fork.
- **Stronger collaboration baseline:**
  - CI checks for Python/JS syntax and test execution.
  - Branch strategy and contribution guidance oriented to stable releases (`main`) and active development (`dev`).

### Code structure (maintainability)

Current high-level architecture:

```text
app.py                # FastAPI entrypoint
core/                 # auth, middleware, base infrastructure
routes/               # HTTP endpoints by domain
services/             # application services
src/
  chat/               # chat pipeline
  agent/              # agent orchestration
  research/           # deep research + extractors
  tools/              # tool runtime and execution
  runtime/            # bootstrap, config, endpoint resolver
  vector/             # embeddings + vector store
  memory/             # persistent memory
  email/ calendar_app/# functional integrations
  ...
static/               # modular frontend (js/css/html)
tests/                # test suite + testing standards
```

This layout improves maintainability by reducing top-level clutter, making domain ownership explicit, enabling safer refactors/testing, and simplifying frequent upstream merges.

### Quick start

```bash
git clone https://github.com/madkoding/atenea-pro.git
cd atenea-pro
git checkout main
cp .env.example .env
docker compose up -d --build
```

Open: `http://localhost:7000`

### Branches

- `main`: stable (default branch)
- `dev`: integration and development

## License

Same as upstream Atenea. See `LICENSE`.
