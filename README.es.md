# Atenea — Versión en Español

Fork personal de [Atenea](https://github.com/pewdiepie-archdaemon/atenea) con la interfaz de usuario y las respuestas de la IA en español.

> **Nota del mantenedor**: El proyecto upstream no acepta contribuciones de internacionalización ([PR #719 cerrado](https://github.com/pewdiepie-archdaemon/atenea/issues/719)). Este fork es exclusivamente local.

## Qué incluye

- **Interfaz en español** — todos los textos visibles del shell, chat, panels de Ajustes, Memoria y más traducidos medianteruntime i18n.
- **IA que responde en español** — el agente, deep research, presets y prompts de habilidades generan respuestas en español cuando el idioma de interfaz está configurado en `ES`.
- **Conmutador EN↔ES** — el botón de idioma en la cabecera sincroniza la preferencia con el servidor y cambia toda la interfaz al instante.
- **Sincronizable con upstream** — el diseño permite hacer `git merge upstream/dev` y re-aplicar las traducciones sobre los nuevos archivos.

## Cambios respecto a upstream

Cada commit de este fork incluye un mensaje descriptivo. Los cambios principales:

| Fase | Archivos modificados |
|------|----------------------|
| 1 | `i18n.js`, `lang-toggle.js`, `en.json`, `es.json`, `login.html`, `index.html`, `sw.js` |
| 2 | `chat_processor.py`, `chat_helpers.py`, `app.js`, `chat.js`, `chatRenderer.js` |
| 3 | `agent_loop.py`, `chat_routes.py` |
| 4 | `deep_research.py`, `goal_based_extractor.py`, `research_handler.py` |
| 5 | `preset_manager.py`, `youtube_handler.py`, `chat_routes.py`, `memory_routes.py`, `skills_routes.py` |
| 6 | `index.html` (modales), locale expansion a 436+ claves |
| 6b | `chat.js` (cadenas dinámicas), `index.html` (botón email) |

## Instalación

```bash
git clone https://github.com/madkoding/atenea.git
cd atenea
git checkout spanish-dev
# Instalar dependencias y ejecutar — igual que upstream
```

## Mantenimiento (sincronizar con upstream)

```bash
git fetch upstream
git checkout dev
git merge upstream/dev
git push origin dev
git checkout spanish-dev
git merge dev
# Resolver conflictos en archivos .html/.js manteniendo el markup data-i18n*
git push origin spanish-dev
```

Véase [FORK-NOTES.md](./FORK-NOTES.md) para el procedimiento completo y la documentación técnica.

## Rama

```
spanish-dev  ← basada en dev (commit 83b0ab7)
```

## Licencia

Igual que el proyecto upstream — véase [LICENSE](LICENSE) de Atenea.