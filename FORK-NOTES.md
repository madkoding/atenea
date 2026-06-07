# Odysseus Spanish Fork — Fork Notes

## Goal

Spanish variant of [Odysseus](https://github.com/pewdiepie-archdaemon/odysseus) (branch `spanish-dev`).
UI in Spanish + AI responses in Spanish across chat, agent, deep research, presets, and skills.
Built as a local-only fork; maintainer rejected i18n upstream (PR #719, 3 jun 2026).

## Branch structure

```
origin  madkoding/odysseus (fork)
  └── spanish-dev   ← our work branch (based on dev at 83b0ab7)
upstream  pewdiepie-archdaemon/odysseus
  └── dev          ← sync target
```

## Sync procedure (upstream → fork)

```bash
git fetch upstream
git checkout dev
git merge upstream/dev
git push origin dev
git checkout spanish-dev
git merge dev
# resolve any conflicts in .html/.js files — keep our i18n data-i18n* markup
git push origin spanish-dev
```

The i18n layer is designed to be re-applied after merges:
1. Merge upstream files as-is (English originals).
2. Our `data-i18n*` attributes and locale JSON keys survive because they are co-located with the strings.
3. Any new strings introduced by upstream get added to `en.json`/`es.json` with the same key path.
4. If upstream renames an element that has `data-i18n`, update the locale key accordingly.

## What's translated

### Fase 1 (commit 58744a4)
- i18n runtime (`static/js/i18n.js`) — `init`, `t`, `tn`, `setLocale`, `getLocale`, `getSupported`, `applyAll`
- Locale files: `en.json`/`es.json` (324 keys at that point)
- Login page: all form labels, buttons, error messages
- Header: welcome message, input placeholder, model picker, send button
- `lang-toggle.js`: EN↔ES toggle with server-side preference sync
- SW cache: v327 → v328

### Fase 2 (commit 5e8f22c)
- `build_context_preface` in `src/chat_processor.py`: appends Spanish directive when `ui_language == "es"`
- `routes/chat_helpers.py`: passes `uprefs.get("ui_language")` to `build_context_preface`
- `static/app.js`: ~50 UI strings via `t()`/`tn()` (incognito, send button, modals, file drop, msg count plural)
- `static/js/chatRenderer.js`: message actions, vision editor, compact context, continue prompt
- `static/js/chat.js`: API key warning, question cards, fork/delete/edit toasts
- SW: v328 → v329

### Fase 3 (commit 2d5ecbd)
- `src/agent_loop.py`: `apply_language` helper suffixes `_ES_AGENT_DIRECTIVE` when `lang == 'es'`
- `_assemble_prompt`, `_build_system_prompt`, `stream_agent_loop` all accept `ui_language` kwarg
- `routes/chat_routes.py`: streams pass `ui_language` from `ctx.uprefs`

### Fase 4 (commit 889af71)
- `src/deep_research.py`: `_localize` helper + `_ES_RESEARCH_DIRECTIVE`, applied to all 6 prompts
- `src/goal_based_extractor.py`: `_ES_EXTRACTOR_DIRECTIVE` + `_localize`
- `src/research_handler.py` + `services/research/research_handler.py`: `call_research_service`/`start_research` forward `ui_language`
- `routes/chat_routes.py`: both call sites read `ui_language` from `ctx.uprefs`

### Fase 5 (commit 410ac87)
- `src/preset_manager.py`: translate `code_analyze`, `brainstorm`, `reason` default presets. "Custom" detector literal unchanged.
- `src/youtube_handler.py` + `services/youtube/youtube_handler.py`: `YOUTUBE_INSTRUCTION_PROMPT` translated
- `routes/chat_routes.py`: research clarification prompt and `/api/rewrite` scaffolding translated
- `routes/memory_routes.py`: `/extract` and document-import prompts translated (JSON field names preserved in English)
- `routes/skills_routes.py`: 6 prompts translated; verdict/confidence/summary keys kept in English

### Fase 6 partial (commit ed9dad3)
- `static/index.html`: `data-i18n-title` on icon rail buttons (calendar, compare, cookbook, research, email, gallery, library, notes, tasks, theme, settings)
- `static/index.html`: `data-i18n` on sidebar tool labels
- `static/index.html`: settings modal nav tabs and shell
- Locale keys added (338/338 parity)
- SW: v329 → v330

### Fase 6 (commit e8bb919)
- `static/index.html`: scroll-bottom button, rename-session modal, custom-preset modal (Inject/Persona/Group tabs, temperature, max tokens), memory modal (all tabs: Browse/Add/Skills/Settings), theme popup (header, Peek, close, Themes/Customize tabs), cookbook modal header/close
- Locale expansion to 436 keys (18 presets.*, 52 memory.*, 6 theme.*, plus app.scroll_bottom, shell.rename_session, etc.)

### Fase 6b (commit a9d7499)
- `static/js/chat.js`: 14 hardcoded English strings replaced with `_t()` calls (import, view thinking, continue, pause, approve/run, open in window, nudge it, stop, cancelled, message interrupted, etc.)
- `static/index.html`: email compose button title (`shell.compose_email`), "new" label (`common.new`)
- Locale expansion to 448 keys

## What's NOT translated (deferred)

- Per-panel JS modules (calendar.js, tasks.js, notes.js, emailInbox.js, emailLibrary.js, gallery.js, document.js, compare/, settings.js, skills.js, memory.js, etc.) — each renders its own HTML via innerHTML
- Backend strings except AI prompts (Fase 3–5)
- Tooltip and title attributes beyond the most visible ones
- Placeholder text on most input fields
- Error messages generated dynamically by JS

These can be addressed in future maintenance sessions using the same `data-i18n*` + `_t()` pattern, or by migrating each module to import i18n and use `element.textContent = _t('key')`.

## Key files

| File | Purpose |
|------|---------|
| `static/js/i18n.js` | Runtime: `t()`, `tn()`, `setLocale`, `getLocale`, `init`, `applyAll` |
| `static/js/lang-toggle.js` | EN↔ES header toggle, reads/writes `/api/prefs/ui_language` |
| `static/js/locales/en.json` | Base locale (448 keys) |
| `static/js/locales/es.json` | Spanish locale (448 keys, parity verified) |
| `static/index.html` | Shell + all modals marked with `data-i18n*` |
| `static/app.js` | Main UI logic, translates ~50 strings via `_t()`/`tn()` |
| `static/js/chat.js` | Chat logic, translates ~15 strings via `_t()` |
| `static/js/chatRenderer.js` | Message rendering, translates actions via `_t()` |
| `static/sw.js` | Service worker, `CACHE_NAME` bumped on each Fase |
| `src/chat_processor.py` | `build_context_preface` appends Spanish directive |
| `src/agent_loop.py` | `apply_language` helper suffixes `_ES_AGENT_DIRECTIVE` |
| `src/deep_research.py` | `_localize` helper + `_ES_RESEARCH_DIRECTIVE` |
| `src/goal_based_extractor.py` | `_ES_EXTRACTOR_DIRECTIVE` + `_localize` |
| `src/preset_manager.py` | Default presets translated; "Custom" detector unchanged |
| `routes/chat_routes.py` | Streams `ui_language` to agent/research calls |

## i18n API

```js
// In HTML: data-i18n="key"  →  element.textContent = t('key')
// In HTML: data-i18n-title="key"  →  element.title = t('key')
// In HTML: data-i18n-aria-label="key"  →  element.setAttribute('aria-label', t('key'))
// In JS:   _t('key', { param: 'value' })   →  translated string with interpolation
// In JS:   _tn('key', n, { n: n })          →  plural-aware translation
```

## Cache busting

After any change to `static/` files, bump `CACHE_NAME` in `static/sw.js` by 1.
Done in every Fase commit (v327 → v330 so far).

## Testing checklist

```bash
# 1. Syntax checks
node --check static/js/i18n.js
node --check static/js/lang-toggle.js
python -m py_compile src/chat_processor.py src/agent_loop.py src/deep_research.py src/goal_based_extractor.py src/preset_manager.py src/youtube_handler.py routes/chat_routes.py routes/memory_routes.py routes/skills_routes.py

# 2. JSON parity
python -c "
import json
with open('static/js/locales/en.json') as f: en = json.load(f)
with open('static/js/locales/es.json') as f: es = json.load(f)
assert set(en.keys()) == set(es.keys()), 'Key mismatch'
print(f'OK: {len(en)} keys')
"

# 3. Load the app in browser, toggle ES, verify:
#    - Header toggle changes UI language
#    - New chat shows Spanish welcome
#    - Agent mode responds in Spanish
#    - Deep research shows Spanish synthesis
#    - Settings panel labels in Spanish
#    - Memory modal tabs/labels in Spanish
```

## Commit history on spanish-dev

| Commit | Fase | Description |
|--------|------|-------------|
| `58744a4` | 1 | i18n runtime, login, shell, CACHE v328 |
| `5e8f22c` | 2 | chat i18n, build_context_preface, CACHE v329 |
| `2d5ecbd` | 3 | agent_loop apply_language |
| `889af71` | 4 | deep_research + goal_based_extractor i18n |
| `410ac87` | 5 | presets, youtube, memory, skills prompts |
| `ed9dad3` | 6 partial | sidebar/rails/settings shell hooks |
| `e8bb919` | 6 | index.html modals + locale to 436 keys |
| `a9d7499` | 6b | chat.js i18n + email compose |