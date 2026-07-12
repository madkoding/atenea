# Atenea — Code Audit Report

_Generated 2026-07-12 · full-repo safety / performance / security audit_

## Scope & method

- **253 source files** audited (every non-test `.py`, ~100k LOC). No file skipped.
- **Deterministic static routing** (no LLM gate): 50 high-stakes files → `fable`, 159 → `sonnet`, 44 tiny files batched on `sonnet`. Sonnet was the floor — nothing was dropped by a model's guess.
- Every **HIGH/CRITICAL** finding was **cross-model verified** (the model that didn't find it was asked to refute it). Unverified high-severity claims were dropped.
- 6 domain leads deduplicated + grouped findings by root cause.
- Cost: **375 agents, ~14.4M tokens**, 0 agent errors.

## Findings at a glance

| Severity | Count |
|---|---|
| 🔴 Critical | 4 |
| 🟠 High | 119 |
| 🟡 Medium | 223 |
| 🔵 Low | 168 |
| ⚪ Info | 2 |
| **Total** | **516** |

| Domain | Findings |
|---|---|
| Performance | 160 |
| Correctness | 129 |
| Security | 81 |
| Concurrency | 74 |
| Resource Leaks | 65 |
| Memory Safety | 7 |

**155 of 253 files** had at least one finding.

---

## 🔴 Critical findings — fix first

### C1. Cross-request race on module-global active document/model pointer
**`src/chat/agent_loop.py`:735** · _concurrency_

_build_system_prompt calls set_active_model(model) (line 715), set_active_document(active_document.id) (line 735) and set_active_document(None) (line 847). These write plain module globals (_active_document_id/_active_model in src/tools/implementations.py:72-85, confirmed no lock, no contextvar). stream_agent_loop then executes tool rounds across MANY awaits (LLM streaming, tool execution). Concrete failure: user A opens doc X and asks 'fix this'; while A's round-1 LLM stream is in flight, user B (or A's second tab) starts a request with no open document, which runs set_active_document(None) — or worse, doc Y. When A's edit_document/update_document block finally executes, it resolves the active document via get_active_document() and edits the WRONG document (B's doc Y) or fails with no active doc. This is cross-user/cross-session data corruption on any concurrently-used server.

**Fix:** Stop using process-wide globals for per-request state: pass the active doc id explicitly into execute_tool_block (it already receives session_id/owner/workspace), or replace _active_document_id/_active_model with contextvars.ContextVar so each asyncio task sees its own value.

### C2. Check-in digest queries calendar events with no owner scoping — cross-tenant data leak
**`src/scheduling/task_scheduler.py`:1128** · _security_

_execute_checkin pulls calendar events with `_db.query(_CE).filter(_CE.dtstart >= _s, _CE.dtstart <= _e, _CE.status != 'cancelled')` — no filter on the owning calendar. CalendarEvent has no owner column; ownership is via calendar_id -> calendars.owner (verified in core/database.py:1506), and the query joins/filters on neither. Failure scenario: in a multi-user deploy, user B's medical appointments, meeting summaries and locations are embedded in user A's check-in data dump, handed to the LLM, and delivered to user A's session/email/notification.

**Fix:** Join through CalendarCal and filter by owner: `_db.query(_CE).join(_CE.calendar).filter(CalendarCal.owner == task.owner, _CE.dtstart >= _s, ...)` (matching the owner scoping already used for notes on line 1160).

### C3. CPU-bound ML inference and PIL processing run directly inside async handlers, freezing the event loop
**`routes/gallery_routes.py`:1467** · _performance_

Multiple 'async def' endpoints do heavy synchronous CPU work with zero offloading: Real-ESRGAN inference in denoise_image (line 1467 'upsampler.enhance') and upscale_image_local (line 1514), rembg / transformers segmentation in remove_background (lines 1580, 1584-1585), GFPGAN restoration in enhance_face (line 1651), PIL UnsharpMask in sharpen_image (line 1419), and PIL rotate+re-encode plus disk write in gallery_rotate (lines 297-313). Real-ESRGAN on a large image takes tens of seconds of pure CPU (tile=400, half=False). Because these run on the event loop thread, EVERY other request on the server (chat, SSE streams, auth) is completely stalled until inference finishes. Concrete scenario: one user clicks 'AI Upscale 4x' on a 4K photo -> the whole FastAPI app is unresponsive for 30-120s; health checks time out. Blocking file I/O compounds this: gallery_upload writes up to 100MB with img_path.write_bytes (line 161), gallery_replace (line 219), and ai_tag_image reads the whole file with read_bytes (line 1805), all on the loop.

**Fix:** Run inference and large file I/O off the loop: 'await asyncio.get_running_loop().run_in_executor(None, _do_denoise, arr)' (or anyio.to_thread.run_sync), or declare these handlers as plain 'def' so FastAPI runs them in its threadpool. For file writes/reads use run_in_executor or aiofiles.

### C4. Corrupt/unreadable auth.json fails open into first-run setup, allowing unauthenticated admin takeover
**`core/auth.py`:118** · _security_

_load() catches every exception (JSON decode error, permission error, transient I/O error) and sets self._config = {}. That makes is_configured return False, which re-arms setup() (line 200): the first-run path only requires that no users exist. Failure scenario: auth.json is corrupted by a crash mid-manual-edit or a disk error; on next process start the app silently reverts to 'first-run setup required' and ANY unauthenticated visitor can call setup() to create a brand-new admin account. The first subsequent _save() then overwrites the original auth.json, permanently destroying all real accounts. A parse error must not be treated the same as 'file does not exist'.

**Fix:** Fail closed: only fall back to self._config = {} when the file does not exist. If the file exists but cannot be read/parsed, set a self._load_failed flag (or re-raise to abort startup) and make is_configured / setup() refuse while that flag is set, e.g. `except Exception: logger.critical(...); self._load_failed = True; raise` or have setup() return False when _load_failed.

---

# Detailed findings by domain

# Atenea Security Audit — Master Report: Consolidated Findings

**Scope:** 79 distinct verified findings (after collapsing the two byte-identical copies of the Codex `atenea_api.py` traversal bug into one). Severity spread: **2 critical, 22 high, ~34 medium, ~20 low, 1 info.**

The findings collapse into **9 root-cause families**. Nearly every high/critical issue is an instance of one of the first four. Groups and findings within them are ranked most-severe first.

---

## R1 — Missing tenant/owner scoping (the dominant root cause)

Ownership is enforced *ad hoc* per call site instead of at the data layer, so any code path that forgets the `owner` filter (or is handed a falsy owner) reads, mutates, or leaks across tenants. This family contains a critical and several highs and is the single largest source of risk.

- **`src/scheduling/task_scheduler.py:1128` [CRITICAL]** — `_execute_checkin` queries `CalendarEvent` with no calendar-owner join; one user's appointments/locations land in another user's digest and delivery. **Fix:** `.join(_CE.calendar).filter(CalendarCal.owner == task.owner, ...)`, matching the notes query at :1160.
- **`routes/email_routes.py:1618` (and :1645) [HIGH]** — `attachment_as_doc` runs an **unscoped** `Document.is_active=False` sweep across the entire table; one user's attachment import blanks every other user's doc list. New docs also created with no `owner`. **Fix:** scope the update to `owner==caller OR session_id==caller`, stamp `owner`.
- **`src/chat/agent_loop.py:1131` [HIGH]** — Level-0 skill index built with `owner=None`, returning all users' skill names/descriptions into every prompt; the matched-skills path correctly uses `owner=owner` (:956). **Fix:** plumb `owner` into `_build_base_prompt` / `index_for`.
- **`services/memory/service.py:111` [HIGH]** — `MemoryService` never accepts or passes `owner`: `recall`/`get_all`/`delete` span all tenants (uses `load_all()`); any caller can read or delete another user's memory by id. **Fix:** thread `owner` through all four methods; use `provider.delete(id, owner)` which already enforces ownership.
- **`services/memory/memory_extractor.py:386` [MEDIUM]** — owner-less session triggers `audit_memories(owner=None)`, serializing all tenants' memories into one prompt and letting the LLM output replace the whole store. **Fix:** refuse audit / scope dedup when `_owner is None`.
- **`src/runtime/endpoint_resolver.py:282` (and :334) [MEDIUM]** — `if owner:` treats empty-string owner as system context and skips the filter, returning any user's endpoint **with its API key baked into headers**. **Fix:** require an explicit system sentinel; reject empty-string owner.
- **`routes/chat_helpers.py:36` [MEDIUM]** — `_cached_enabled_endpoints` caches every endpoint's plaintext `api_key` under one global dogpile key. **Fix:** drop `api_key` from the cached payload or make the key owner-scoped.
- **`src/actions/builtin.py:599` [MEDIUM]** — `action_classify_events` loads/mutates all users' events using the triggering owner's private memory context. **Fix:** apply the `CalendarCal` owner join used by `action_daily_brief` (:1014).
- **`src/actions/builtin.py:810` (and :894, :1037) [MEDIUM]** — `learn_sender_signatures`/`daily_brief` call `_imap_connect(None)` (global default mailbox) with no owner check; contrast `check_email_urgency` (:1505). **Fix:** resolve the account by `owner`.
- **`routes/email_helpers.py:505` / :566 [MEDIUM]** — `email_boundaries` and `sender_signatures` caches keyed by global Message-ID / from-address with no owner column, despite the file's own stated invariant. **Fix:** migrate to composite `(key, owner)` PKs.
- **`src/scheduling/task_scheduler.py:1867` [MEDIUM]** — `_deliver_via_mcp` calls `_get_email_config()` with no owner, emailing user B's task output to the global default account. **Fix:** pass `owner=task.owner`.
- **`src/scheduling/task_scheduler.py:1243` / :1207 [MEDIUM]** — MCP-snapshot and Miniflux TTL cache keys omit owner; A's email snapshot served into B's digest within the 3-min TTL. **Fix:** add `task.owner` to every cache key.
- **`src/agent/ai_interaction.py:555` [MEDIUM]** — `send_to_session` guard `if owner and sess.owner and ...` skips the check when the target's owner is unset (legacy rows). **Fix:** `if owner and getattr(sess,'owner',None) != owner: deny`.
- **`src/scheduling/task_scheduler.py:334` [LOW]** — `pop_notifications(owner=None)` drains and returns all users' notification bodies. **Fix:** make the unfiltered drain opt-in/restricted.
- **`src/llm_core.py:34` [LOW]** — LLM response cache key omits owner/auth header; B replays A's completion (and quota) on identical prompt. **Fix:** include an identity component in the key.

---

## R2 — Command / argument injection into shells, SSH, and IMAP

Untrusted values (LLM tool args, admin-writable state, inbound email headers) are interpolated into command strings or IMAP protocol commands without correct escaping.

**SSH / shell:**
- **`core/platform_compat.py:381` [HIGH]** — `_ssh_exec_argv` appends the caller-supplied `remote` with no `--` separator; `remote="-oProxyCommand=curl…|sh"` → local RCE. Root of the two findings below. **Fix:** insert `--` before `remote`; reject `^-`; validate port as int.
- **`services/hwfit/hardware.py:34` [HIGH]** — reaches the same `_ssh_exec_argv` sink via the client `host` query param. **Fix:** the platform_compat fix covers it; also validate `host` in `detect_system`.
- **`src/tools/implementations.py:3298` [HIGH]** and **:3592 [HIGH]** — `shlex.quote()` output nested *inside* a hand-written single-quoted string in the tmux kill / adopt SSH commands; LLM-controlled `session_id`/`host` break out → RCE. **Fix:** quote the whole inner command as one word (`inner=…; cmd=f"ssh {quote(host)} {quote(inner)}"`); regex-validate session ids.
- **`routes/codex_routes.py:504` (and :568) [MEDIUM]** — `host`/`ssh_port` from admin-writable cookbook state interpolated unquoted into `create_subprocess_shell`; `adopt` (:727) already quotes correctly. **Fix:** `shlex.quote(host)`, validate port, or use `create_subprocess_exec`.
- **`routes/cookbook_routes.py:2245` [MEDIUM]** — `local_dir`/`repo_id` from admin-writable state interpolated into a remote `ls` over SSH with no validation (the function re-validates other fields for exactly this reason). **Fix:** validate with `_validate_local_dir`/repo-id regex, use `shlex.quote`.
- **`routes/shell_routes.py:79` [MEDIUM]** — `StrictHostKeyChecking=no` on every remote probe/rebuild → MITM of the command stream. **Fix:** `accept-new` (TOFU) with an app-managed `known_hosts`.

**IMAP command/search injection:**
- **`mcp_servers/email_server.py:692` [HIGH]** — `message_id` (echoed from inbound mail, passed back by the LLM) interpolated into `SEARCH` with no escaping; `uid` message-sets and folder names similarly raw — `uid="1:*"` + delete expunges the folder. **Fix:** reject `\r\n`, escape `\`/`"`, validate uids `^\d+$`.
- **`routes/email_helpers.py:1349` (and :1217) [HIGH]** — attacker-controlled `From` address interpolated into `SEARCH (FROM "…")` with no escaping, flipping the cold-sender gate to `is_known=True`; the sibling escape at :1217 handles quotes but not backslashes. **Fix:** escape both `\` and `"`; reject addresses containing either.
- **`routes/email_routes.py:639` [MEDIUM]** — `?from=` and folder params escape `\`/`"` but not CR/LF; imaplib does **not** reject CRLF, so pipelined IMAP commands inject into the pooled connection. **Fix:** reject CR/LF in `from`, `folder`, `dest` and inside `_q()`.

---

## R3 — SSRF (DNS-rebinding TOCTOU + missing URL validation)

**DNS-rebinding TOCTOU — one identical bug in 5 modules.** Each validates a hostname's resolved IPs, then hands the *hostname* (not a pinned IP) to an HTTP client that re-resolves at connect time. Attacker with DNS control serves a public IP at check time, an internal IP at connect time.
- **`src/security/url_safety.py:48` [HIGH]**, **`services/search/content.py:82` [HIGH]**, **`src/calendar_app/sync.py:226` [HIGH]**, **`src/security/url_security.py:92` [MEDIUM]**, **`routes/calendar_routes.py:789` [MEDIUM]**. **Shared fix:** resolve once, validate the IP, and force the client to connect to that pinned IP (custom transport/resolver or connect-to-IP + Host header/SNI). Fix the shared helpers (`url_safety`, `url_security`) and their callers together.

**Missing/bypassed URL validation:**
- **`routes/skills_routes.py:1399` [MEDIUM]** — `test_skill` uses client-supplied `url`/`headers` for server-side calls with no allowlist or admin gate. **Fix:** drop the body fallback or apply `check_outbound_url` + admin gate.
- **`routes/gallery_routes.py:1060` (and :1254) [MEDIUM]** — registered-endpoint restriction gated on `user and not admin`, so anonymous (no-auth) callers reach arbitrary `_endpoint` URLs; `block_private` defaults off. **Fix:** reject whenever no DB endpoint matches and caller isn't admin.
- **`routes/session_routes.py:157` [LOW]** — raw `endpoint_url` accepted when auth disabled (`user is None`). **Fix:** treat no-user as non-admin; block private ranges.

---

## R4 — Fail-open error handling (`except: pass` / swallowed auth)

Broad exception handlers turn transient DB/auth errors (e.g. SQLite lock) into silent security-control bypass.

- **`core/auth.py:118` [CRITICAL]** — corrupt/unreadable `auth.json` caught → `_config={}` → `is_configured` false → **first-run setup re-armed**; any visitor creates a new admin and the next save destroys real accounts. **Fix:** only fall back on file-not-found; set a `_load_failed` flag that makes `setup()` refuse.
- **`app.py:424` [HIGH]** — gallery per-user ownership check wrapped in `except Exception: pass`, falling through to `FileResponse`; a DB lock during lookup serves another user's private image. **Fix:** fail closed — re-raise `HTTPException`, else `raise HTTPException(404)`.
- **`routes/email_helpers.py:671` [MEDIUM]** — `_get_email_config` DB error falls through to unowned legacy credentials; a transient lock makes X's mail run against the admin mailbox. **Fix:** distinguish "no rows" (legacy fallback OK) from "DB error" (raise 503).
- **`routes/chat_helpers.py:104` [MEDIUM]** — `_enforce_chat_privileges` swallows any `get_current_user` exception → `user=None` → skips model-allowlist + daily-cap gates. **Fix:** `except HTTPException: raise`; only no-op on genuine unauthenticated.
- **`routes/research_routes.py:398` [MEDIUM]** — `can_use_research` check for the `X-Atenea-Owner` impersonated user wrapped in `except: pass`, then proceeds. **Fix:** fail closed with 503.
- **`core/database.py:1129` [LOW]** — legacy-owner sweep silently skipped if `auth.json` momentarily unreadable, leaving NULL-owner rows world-visible with no log. **Fix:** log at warning; retry on next tick.

---

## R5 — Secret exposure (env, logs, world-readable files)

**Secrets leaked into subprocesses / logs / temp:**
- **`src/tools/execution.py:715` [HIGH]** — `{**os.environ, …}` passes all API keys/DB creds/webhook tokens into model-controlled subprocesses; `env` exfiltrates everything. Defeats the file's own `.env` deny-list. **Fix:** minimal allowlisted env.
- **`routes/cookbook_routes.py:1033` (and :322/:429/:372/:961) [HIGH]** — raw `HF_TOKEN` written into chmod-0755 runner scripts in `/tmp/atenea-tmux`, never deleted. **Fix:** pass token via env/0600 env-file; chmod 0700; unlink after launch.
- **`routes/mcp_routes.py:200` [HIGH]** — `logger.info(f"…oauth_file={oauth_file!r}")` logs the Google `client_secret` verbatim. **Fix:** log `bool(oauth_file)` / redact.
- **`src/tools/schemas.py:1215` (and :1223) [LOW]** — raw function-call args logged on parse failure; `manage_endpoints`/`manage_mcp` args carry `api_key`/`env`. **Fix:** log name + length, redact known keys.
- **`src/vector/embeddings.py:229` [LOW]** — decrypted `EMBEDDING_API_KEY` written into `os.environ` (whole process, inherited by children). **Fix:** pass into `EmbeddingClient(api_key=…)` directly.

**Secret files created world/group-readable (umask race — same bug, 5 files):**
- **`src/clients/api_key_manager.py:20` [HIGH]** — Fernet **master key** (decrypts all provider keys + webhook secrets) via bare `open('wb')`.
- **`src/security/secret_storage.py:39` [MEDIUM]** — key file `write_bytes` then late `chmod`; readable in the window.
- **`app_setup.py:121` [MEDIUM]** and **`core/atomic_io.py:29` [LOW]** — `auth.json` (bcrypt admin hash) written under default umask; `os.replace` preserves the loose tmp-file mode.
- **`routes/vault_routes.py:74` [LOW]** — `vault.json` (Bitwarden `BW_SESSION`) written before `chmod 0600`.
- **Shared fix:** create atomically with `os.open(path, O_WRONLY|O_CREAT|O_EXCL, 0o600)` (or umask-guarded tmp + `os.rename`); never `write`-then-`chmod`.

---

## R6 — Missing authentication / authorization on routes

- **`routes/document_routes.py:562` [MEDIUM]** — `can_use_documents` enforced on only 2 of ~18 doc routes; a privilege-revoked user still reads/deletes/OCRs and spends LLM/vision tokens (ai-tidy, ai-fill). **Fix:** router-level `require_privilege` dependency.
- **`scripts/diffusion_server.py:71` [MEDIUM]** — no auth on GPU inference; `_compute_allowed_hosts` adds the raw bind host, so `--host 0.0.0.0` + `Host: 0.0.0.0` defeats TrustedHost. **Fix:** skip wildcard binds in the allowlist; add a shared-secret check for non-loopback.
- **`src/scheduling/bg_jobs.py:253` [MEDIUM]** — `get(job_id)` returns any job's command line + output with no session check (48-bit id, leaked in store file). **Fix:** `get(job_id, session_id)` enforcing ownership.
- **`routes/background_routes.py:87` (and :66) [MEDIUM]** — upload/delete background images with no identity/ownership check in a shared namespace (filenames listed by `/list`). **Fix:** require identity; scope per-user.
- **`routes/docker_ollama.py:114` [MEDIUM]** — container start/stop (arbitrary image pull, bind `0.0.0.0`) with no auth dependency. **Fix:** `Depends(require_admin)`.
- **`routes/note_routes.py:597` (all CRUD) [LOW]** — note handlers use `get_current_user` (returns None on middleware bypass) instead of `require_user`; `fire_reminder` (:807) does it right. **Fix:** `require_user` at top of each handler.
- **`routes/model_routes.py:2233` [LOW]** — `GET /api/tools` unauthenticated while `POST` requires admin; leaks tool/capability inventory. **Fix:** add auth gate.

---

## R7 — Path traversal / file-access confinement

- **`mcp_servers/rag_server.py:110` [HIGH]** and **`src/vector/rag_vector.py:404` [HIGH]** — `add_directory` / `index_personal_documents` index any readable path (`/etc`, `~/.ssh`, other tenants) with no root allowlist; unscoped `search()`/keyword fallback then leaks the contents. Same root cause, two layers. **Fix:** validate `directory` against an allowed root via `realpath`+`commonpath` in `index_personal_documents` (data layer), not just callers.
- **`integrations/codex/scripts/atenea_api.py` [HIGH]** and its duplicate **`integrations/claude/skills/atenea/scripts/atenea_api.py:80` [MEDIUM]** (same script, two copies) — UID/session-id segments interpolated into the path without `quote()`; `../../../admin/users` still passes the raw `startswith("/api/codex/")` scope guard. **Fix:** `urllib.parse.quote(v, safe='')` on every segment; check the guard against the normalized path.
- **`src/tools/execution.py:171` [MEDIUM]** — sensitive-path deny-list compared case-sensitively; `.SSH/Authorized_Keys` bypasses on case-insensitive filesystems. **Fix:** `normcase().lower()` before matching.
- **`routes/personal_routes.py:153` [MEDIUM]** — `remove_directory` skips the `_resolve_allowed_personal_dir` containment check that `add_directory` uses. **Fix:** route through the same validator.
- **`routes/personal_routes.py:279` [LOW]** — file-delete containment uses `abspath` not `realpath` → symlink escape before `os.remove`. **Fix:** use `realpath`.
- **`mcp_servers/email_server.py:1108` [LOW]** — attachment dir built from unsanitized `folder`; `../` escapes `MAIL_ATTACHMENTS_DIR`. **Fix:** sanitize folder; verify `is_relative_to`.
- **`src/uploads/handler.py:225` [LOW]** — denylist admits `.html`/`.svg`/`.js`; MIME later re-derived from the user extension → stored XSS if served inline. **Fix:** allowlist inline types; serve others as `octet-stream` + `attachment`.
- **`src/tools/implementations.py:2832` [MEDIUM]** — `do_app_api` blocklist matched on raw path; `/api/cookbook/../admin/…` passes then normalizes to a blocked endpoint. **Fix:** `posixpath.normpath` / reject `..` before matching.

---

## R8 — Info disclosure via raw exception / provider error text

- **`services/search/core.py:300` (and :308) [MEDIUM]** — raw provider exception interpolated into the returned message; `requests`/`httpx` errors stringify the URL including `?key=<secret>` for Serper/Tavily/Google PSE. **Fix:** return `type(e).__name__` only; never format `e` into the response.
- **`routes/history_routes.py:137` (and :216/:375/:464/:517/:661) [LOW]**, **`routes/task_routes.py:1155` [LOW]**, **`services/research/research_handler.py:100` [INFO]** — `str(e)` (SQL fragments, DB paths, internal endpoint URLs) returned verbatim to clients. **Fix:** log server-side, return a generic message.

---

## R9 — Injection into generated output, insecure defaults, CSRF, DoS

- **`routes/mcp_routes.py:489` [MEDIUM]** — legacy Google OAuth callback uses predictable `server_id` as `state`, not session-bound → token-fixation / attacker-mailbox takeover. **Fix:** random per-request `state`, stored server-side, one-time.
- **`scripts/demo_email/seed_demo_emails.py:329` [MEDIUM]** — destructive-wipe guard uses `OR`; a localhost port-forward to a real IMAP server passes and EXPUNGEs everything. **Fix:** require both conditions (`endswith("@atenea.local") AND host in loopback`).
- **`scripts/hf_local_openai_server.py:80` [MEDIUM]** — client `max_tokens` uncapped → resource-exhaustion DoS. **Fix:** clamp to a max (e.g. 1024) via pydantic `Field(ge=1, le=1024)`.
- **`routes/calendar_routes.py:1340` [LOW]** — `rrule` written raw into ICS (unlike escaped SUMMARY/etc.) → CRLF property injection into exported/shared files. **Fix:** validate/strip CR/LF at write and export.
- **`routes/note_routes.py:363` [LOW]** — note title (agent/API-settable) used in SMTP `Subject` with only `.strip()` → header/Bcc injection under compat32. **Fix:** collapse newlines; use `EmailMessage` default policy.
- **`src/research/deep.py:716` (and :520/:746/:777) [MEDIUM]** — web content is wrapped as untrusted for the extractor, but the extracted findings/report re-enter synthesis/stop/query/final prompts as plain interpolation, so surviving injected instructions compound each round. **Fix:** wrap with `untrusted_context_message` at every re-entry point.
- **`src/runtime/config.py:100` [LOW]** — `allowed_origins` defaults to `["*"]`. **Fix:** restrictive default; startup check when `debug=False`.
- **`routes/emoji_routes.py:30` [LOW]** — unbounded codepoint length → oversized-path 500s and unbounded uncached outbound CDN requests. **Fix:** cap segment count/length; wrap `fp.exists()`; cache negatives.
- **`scripts/demo_email/seed_demo_emails.py:59` [LOW]** — STARTTLS without cert verification leaks the IMAP password to an on-path attacker for remote targets. **Fix:** `ssl.create_default_context()` when non-loopback.
- **`scripts/demo_email/demo_account.py:28` [LOW]** — hardcoded `"demodemo"` credential in source. **Fix:** read from env / generate per-install.

---

## Top 3 systemic fixes for this domain

**1. Make tenant isolation a data-layer invariant, not a per-call-site convention (fixes R1 + parts of R4/R6/R7).**
The critical check-in leak, the cross-tenant document wipe, the skill-index leak, and `MemoryService` all exist because `owner` is an optional kwarg that individual queries may forget or receive as `None`/`""`. Introduce a required, non-falsy owner scope (an explicit `SystemScope` sentinel for genuinely global reads) enforced inside the store/manager/resolver layer, so a missing owner *raises* instead of returning all rows. Add a repo-wide lint/grep gate rejecting `load_all()`, `is_active==True` updates, and `if owner:` guards in request paths. This single change closes the largest and highest-severity family.

**2. Centralize and correct every "value → command/URL/protocol" boundary (fixes R2 + R3).**
The SSH `--` omission, the nested-`shlex.quote` pattern, the IMAP CRLF/quote gaps, and the DNS-rebinding TOCTOU are all the *same* class repeated across many files, and correct implementations already exist beside the broken ones (`adopt` quoting, `/search` CRLF guard, `_q` escaping). Provide one audited helper per sink — `run_ssh(argv…)` (always `--`, validated host/port), `imap_arg(v)` (reject CRLF, escape `\`/`"`, validate uid/id patterns), and `connect_pinned(url)` (resolve once, validate IP, connect to that IP) — and route all call sites through them. Ban raw `os.environ` spreading into subprocesses in the same pass.

**3. Fail closed everywhere, and treat secrets as secret end-to-end (fixes R4 + R5 + R8).**
Replace broad `except Exception: pass`/swallow-and-continue around auth, ownership, privilege, and config loading with `except HTTPException: raise` + fail-closed defaults (503/404), so a SQLite lock or corrupt `auth.json` can never *open* a control (the critical `auth.json` first-run takeover is the worst instance). In parallel, adopt a create-with-`O_EXCL|0o600` helper for all secret files, strip secrets from logs and subprocess env, and return only generic messages to clients while logging detail server-side.

---

## Memory Safety — 7 verified findings, 0 duplicates

No true duplicates across the set, but findings MS-1 and MS-3 are the **same defect pattern implemented twice** (truncate-after-buffer subprocess output) and should be fixed with one shared helper. All 7 findings reduce to two root causes.

---

### Root cause A: Size limits enforced *after* unbounded buffering (5 findings)

The dominant pattern in this codebase: a cap exists (`MAX_OUTPUT_CHARS`, `max_output`, `GALLERY_*_MAX_BYTES`), but data is fully materialized in RAM first and the cap applied only to what gets *returned*. The cap bounds the response, never the memory.

**MS-1 — HIGH — Subprocess output buffered unbounded for up to 1 hour**
`src/tools/execution.py:393` — `_run_subprocess_streaming` appends every child stdout/stderr line to `stdout_full`/`stderr_full` (393-394, 405); truncation to `MAX_OUTPUT_CHARS` happens only after exit (743, 770). With `DEFAULT_BASH_TIMEOUT = 3600s`, a model-issued `yes` or `cat /dev/urandom | base64` holds tens of GB in RAM and OOM-kills the FastAPI server; concurrent sessions multiply.
*Fix:* enforce the byte budget inside `_reader` — track cumulative length and stop appending to `full_buf` past `MAX_OUTPUT_CHARS * 2` (keep bounded head + tail deque for progress); discard the rest.

**MS-2 — HIGH — JSON image endpoints accept unbounded base64 payloads**
`routes/gallery_routes.py:1415` — multipart paths use `read_upload_limited`, but every JSON-body endpoint does `await request.json()` + `b64decode` with no cap: `sharpen_image` (1415), `denoise_image` (1448), `upscale_image_local` (1497), `remove_background` (1546), `enhance_face` (1630), `inpaint_proxy` (1085-1086), `harmonize_image`. A 2 GB base64 POST to `/api/image/sharpen` materializes ~2 GB JSON string + ~1.5 GB decoded + a PIL bitmap (PNG-bomb amplified) → OOM.
*Fix:* reject before decoding — check `Content-Length` and `len(image_b64)` against `GALLERY_TRANSFORM_UPLOAD_MAX_BYTES`; set `Image.MAX_IMAGE_PIXELS` / verify `img.size` before processing.

**MS-3 — MEDIUM — Same truncate-after-buffer bug in the "safe" shell service**
`services/shell/service.py:62` — `proc.communicate()` (62-64) reads all output to completion; `self.max_output` is applied afterward (65-66), so it bounds the returned string, not memory.
*Fix:* stream-read with a running byte counter and stop past `max_output` (mirror the existing `stream()` path), or pass `limit=` to `create_subprocess_shell` and read in chunks, discarding once capped. **Extract one bounded-reader helper and use it here and in MS-1.**

**MS-4 — MEDIUM — download-zip builds entire archive in RAM, twice, on the event loop**
`routes/gallery_routes.py:781` — unbounded `ids` array → every file written into an in-memory `io.BytesIO` `ZipFile` (781-797), then copied again via `buf.getvalue()` (802). "Select all" on a 300-item photo/video library = multi-GB RSS spike; the synchronous `zipfile.write` calls also freeze the async event loop for the whole build.
*Fix:* cap id count and total bytes; stream via `StreamingResponse` over a `SpooledTemporaryFile` or streaming-zip library, compression in a thread executor.

**MS-5 — LOW — Process-global `imaplib._MAXLINE = 50_000_000` on every connect**
`routes/email_helpers.py:761` — mutates private module-global state for every imaplib consumer in the process; a hostile or huge server response can force 50 MB per protocol line per connection — pool slots plus background pollers compound to hundreds of MB transient on small deploys. Repeated unsynchronized global write besides.
*Fix:* set once at module import with a lower ceiling (~10 MB), or eliminate the need by paging `UID SEARCH` with ranges instead of `SEARCH ALL`.

---

### Root cause B: Module-global caches/registries with no eviction, TTL, or size cap (2 findings)

**MS-6 — MEDIUM — `_ACCOUNT_CACHE` unbounded, never invalidated, pins decrypted passwords**
`mcp_servers/email_server.py:227` (also 146) — every distinct LLM-supplied selector string becomes a permanent cache key with no size cap; entries never invalidate, so rotated IMAP/SMTP credentials keep failing with AUTHENTICATIONFAILED until restart, and plaintext-decrypted passwords sit in a module-global dict for the process lifetime. Both a leak and a correctness/credential-hygiene issue.
*Fix:* TTL entries (`(expires_at, cfg)`, ~60s) or invalidate on `os.path.getmtime(APP_DB)` change; cache only selectors that resolved to a DB row; stop caching decrypted passwords.

**MS-7 — LOW — `_RUNS` replay buffers pinned forever by hung generators**
`src/agent/runs.py:42` — eviction is armed only in `_drain`'s `finally` (138), i.e. only after the wrapped generator terminates or is `stop()`ed. A hung upstream LLM call pins the `_Run` and its unbounded `buffer` for the process lifetime; `_RUNS` is a plain dict with no size limit, so stuck sessions accumulate.
*Fix:* hard wall-clock timeout around the `async for ev in agen` loop (`asyncio.wait_for` or watchdog calling `stop(session_id)`), plus a cap on `run.buffer` event count as defense-in-depth.

---

### Top 3 systemic fixes

1. **Enforce byte budgets at read time, everywhere.** Build one shared bounded-reader utility (running byte counter, bounded head+tail) and route all subprocess output (MS-1, MS-3) and all request-body/base64 ingestion (MS-2) through it. Truncation after full materialization is not a memory bound — treat any post-hoc cap as a bug in review.
2. **Ban unbounded module-global dicts.** Adopt a single bounded-cache primitive (max entries + TTL) for every process-lifetime cache/registry (MS-6, MS-7), pair every registration with a guaranteed eviction path (watchdog/timeout), and never store decrypted secrets in long-lived caches.
3. **Stream large outputs and set global input ceilings.** Large responses (zips — MS-4) must stream from spooled/temp storage with CPU work off the event loop; establish process-wide ceilings once at startup — `Content-Length` middleware rejection, `Image.MAX_IMAGE_PIXELS`, a sane `imaplib._MAXLINE` set at import (MS-5) — rather than per-handler or per-connection ad-hoc limits.

---

# Resource Leaks — Audit Section (65 verified findings → 8 root-cause groups after dedup)

**Deduplication notes:** `src/llm_core.py:1389` and `core/cache.py:35` are one defect (the dogpile memory backend never evicts) — merged. `src/research/handler.py:292` and `routes/research_routes.py:453` are one defect (`_active_tasks` has a single pop path the panel never calls) — merged. The two `services/youtube/youtube_handler.py`, two `routes/shell_routes.py`, two `routes/ollama_routes.py`, two `app.py`, two `src/vector/embeddings.py`, and two `mcp_servers/email_server.py` findings are distinct defects in shared files and kept separate. Net: 62 unique defects.

---

## RL-1. Subprocesses never killed/reaped on timeout or cancellation — 10 findings (2 HIGH)

The codebase's dominant subprocess idiom is `await asyncio.wait_for(proc.communicate(), N)` with no `except: proc.kill(); await proc.wait()`. `wait_for` cancels the *coroutine*, not the child. Orphans accumulate as zombies holding PIDs, pipe fds, and remote connections.

- **HIGH — `src/tools/execution.py:439`**: shell spawned without `start_new_session=True`; timeout/cancel kills only `/bin/sh`, all children survive orphaned and hold the stdout pipe open. **Fix:** `start_new_session=True` + `os.killpg(os.getpgid(proc.pid), SIGKILL)` on timeout/cancel.
- **HIGH — `services/shell/service.py:62`**: `execute()`/`stream()` handle only internal `TimeoutError`; external `CancelledError`/`GeneratorExit` (client disconnect) skips cleanup entirely. **Fix:** `try/finally: if proc.returncode is None: proc.kill(); await proc.wait()`.
- **HIGH — `services/youtube/youtube_handler.py:205`**: `wait_for` wraps `create_subprocess_exec` (returns instantly); `proc.communicate()` at L213 is unbounded — the timeout is dead code. **Fix:** move `wait_for` to `communicate()`, kill+wait on timeout.
- **HIGH — `routes/vault_routes.py:107`**: `_run_bw` has no timeout at all; a slow Vaultwarden hangs the request and leaks a `bw` process per call. **Fix:** `wait_for(proc.communicate(...), 30)` + kill/wait (also `_check_bw_installed:233`).
- **MED — `routes/cookbook_routes.py:620`** (also 217, 1347, 1357, 1443, 1827): five timeout sites never kill; lines 1495–1498 show the correct in-repo pattern to copy.
- **MED — `routes/shell_routes.py:1145`** (also 1177, 1402): ssh probes and rebuild_engine leave children alive; probe failures additionally swallowed by bare `except`.
- **MED — `routes/ollama_routes.py:339`** (also 275, 382): timed-out brew/curl installers keep running holding dpkg/brew locks, then block on full pipe buffers.
- **LOW — `routes/codex_routes.py:416`**: kills but never `await proc.wait()` — zombie + unclosed transports. **Fix:** await wait with a 2s cap.
- **LOW — `core/platform_compat.py:122`**: `taskkill` run with no `timeout=`, can wedge the cleanup thread forever. **Fix:** `timeout=10`, catch `TimeoutExpired`, log nonzero rc.

## RL-2. Orphaned async tasks and un-cancelled background loops — 4 findings (1 HIGH)

- **HIGH — `src/chat/agent_loop.py:2451`**: client disconnect raises `GeneratorExit` at the SSE yield; `_tool_task` is never cancelled/awaited, so 60s bash runs and model downloads complete headless every time a tab closes mid-turn. **Fix:** try/finally around the drain: `_tool_task.cancel()` + `await` with `suppress(CancelledError)`; propagate cancellation into `execute_tool_block` (pairs with RL-1's `services/shell/service.py` fix).
- **MED — `app.py:1110`**: `_shutdown_event` cancels only `upload_cleanup_task`; the keepalive/sweep/audit `while True` loops in `_startup_tasks` are never cancelled, and lifespan re-entry (tests) duplicates every loop. **Fix:** cancel+gather all `_startup_tasks` on shutdown; fresh list on startup.
- **MED — `routes/webhook_routes.py:383`** and **LOW — `app.py:347`**: fire-and-forget `create_task` with no strong reference — task can be GC'd mid-flight, exceptions never retrieved. **Fix:** module-level `_bg_tasks` set + `add_done_callback(discard)` (log exceptions in the callback).
- **MED — `src/scheduling/bg_monitor.py:111`**: sequential follow-up drain with no per-job timeout; one wedged LLM call stalls the entire monitor loop. **Fix:** `wait_for(_run_followup(rec), BUDGET)` per job.

## RL-3. DB connections/sessions leaked on exception paths — 9 findings

Same shape everywhere: `conn = connect(); ...; conn.close()` with the close on the success path only, and a swallowing `except`. Because this is SQLite, a leaked write connection also **pins the RESERVED lock until GC**, converting a leak into app-wide `database is locked` cascades.

- **MED — `core/database.py:701`**: ~18 migration functions (L701–1976); a mid-migration lock leaks a handle holding the write lock, so every subsequent migration fails silently and the app boots on a partial schema. Only `_migrate_chat_messages_fts:1772` closes in a finally. **Fix:** one shared helper using `contextlib.closing`.
- **MED — `routes/email_pollers.py:246`** (+ 8 more sites through L1067): runs every 30 min per account. **Fix:** `closing()` everywhere; one connection per pass, not per record.
- **MED — `src/actions/builtin.py:971`** (also 860): up to 20 leaked handles per pass; L1787 in the same file has the correct try/finally to copy.
- **MED — `src/agent/ai_interaction.py:1724`**, **MED — `mcp_servers/image_gen_server.py:134`**: SQLAlchemy sessions leaked on commit failure — each leak permanently consumes a pool slot; after pool_size+overflow, **all** DB access hangs. **Fix:** try/rollback/finally-close.
- **LOW — `mcp_servers/email_server.py:80`** (+424), **LOW — `routes/email_helpers.py:359`** (import-time, can break the next import): same `closing()` fix.
- **Subgroup — sessions held across slow awaits:** **MED — `routes/mcp_routes.py:295`** (also 334, 360, 541–578) and **MED — `src/clients/webhook_manager.py:271`**: pooled connections pinned across MCP handshakes and 10s outbound HTTP; a handful of concurrent calls exhausts the default 5-connection pool. **Fix:** read needed columns, close, await, reopen briefly for the write.

## RL-4. Network clients / OS handles never closed, or leaked by pool races — 11 findings (2 HIGH)

- **HIGH — `src/clients/mcp_manager.py:323-376`**: `_connect_http` never `stack.aclose()`s when `initialize()`/`list_tools()` fails after transport connect — every retry against a flaky HTTP MCP server leaks a live socket. Stdio (L192) and SSE (L253) variants do this correctly. **Fix:** copy their inner try/`aclose()`/re-raise.
- **HIGH — `routes/gallery_routes.py:1459`** (also 1507, 1584, 1641): RealESRGAN/GFPGAN/RMBG constructed **per request** — synchronous multi-hundred-MB downloads in async handlers, and 4 concurrent denoises = multi-GB RSS spike → OOM. **Fix:** lock-guarded lazy module singletons.
- **MED — `routes/email_routes.py:542`**: `_pooled_release` unconditionally overwrites the one pool slot; concurrent releases silently drop a live TLS connection — steady socket leak plus Gmail's 15-connection quota exhaustion. **Fix:** logout the incoming/displaced conn if the slot is occupied.
- **MED — `mcp_servers/email_server.py:956`** (also 1049): `conn.select()` before the try/finally-logout; a BAD response leaks an authenticated IMAP socket (Dovecot default caps at 10/user). **Fix:** move `select` inside the try, as `_bulk_set_flag:978` already does.
- **MED — `routes/docker_ollama.py:68`**: fresh never-closed `docker.from_env()` per `/status` poll → fd exhaustion. **Fix:** module-level client or try/finally close.
- **MED — `src/calendar_app/writeback.py:149`**: DAVClient/requests.Session per writeback, never closed. **Fix:** `finally: client.session.close()`.
- **MED — `src/tools/index.py:535`**: unlocked check-then-act singleton; the losing thread's fully-built ToolIndex (own ChromaDB handles) is discarded unclosed. **Fix:** `threading.Lock` around construction.
- **MED — `src/personal/docs.py:18`** (PdfReader ref-cycle keeps fds until cyclic GC; bulk indexing hits `Too many open files`) and **MED — `routes/upload_routes.py:159`** (PIL `Image.open` never closed). **Fix:** context managers.
- **LOW — `src/vector/embeddings.py:54`** (httpx pool dropped on failed probe), **`:192`** (`open().read()` chain), **LOW — `services/search/providers.py:428`** (DDGS not used as context manager). **Fix:** `with` blocks / explicit close.

## RL-5. Unbounded in-memory caches and job dicts — 15 findings

One systemic disease: module-level dicts that only add. TTLs, where present, gate *reuse*, never *eviction*.

- **MED — `src/llm_core.py:1389` + `core/cache.py:35`** (merged): dogpile memory backend never evicts; llm_region keys hash the full message history (near-zero reuse) → one permanently retained response per prompt → monotonic RSS → OOM. **Fix:** bounded backend (cachetools TTL/LRU) or stop caching conversational calls.
- **MED — `src/research/handler.py:292` + `routes/research_routes.py:453`** (merged): `clear_result` (handler.py:567, the sole pop) is only called from the chat flow; panel/cancelled/errored runs retain multi-MB researcher objects forever. **Fix:** null heavy refs in `_run()`'s finally + TTL sweep of terminal entries.
- **MED — `routes/compare_routes.py:88-236`**: `[CMP]` session ids are never persisted on the Comparison row, so `delete_comparison` *cannot* clean up — DB rows and in-memory sessions (holding copied API keys) grow forever. **Fix:** persist sid_a/sid_b, delete them in `delete_comparison`.
- **MED — externally-driven growth (DoS-adjacent):** `services/hwfit/hardware.py:598` (keyed on client-supplied host/port), `src/chat/helpers.py:84` (keyed on user-set endpoint host:port), `src/misc/rate_limiter.py:20` (unique-key flood keeps every entry "fresh" forever), `services/search/analytics.py:113` (one key per distinct query, full-file rewrite per query). **Fix:** cachetools.TTLCache/LRU caps.
- **MED — `core/session_manager.py:462`** (every opened session hydrated permanently with full history), **`core/auth.py:466`** (expired tokens never swept; re-serialized on every save), **`routes/skills_routes.py:400`** (+488: job dicts with 600–1000 log lines each, never evicted), **`src/runtime/endpoint_resolver.py:92`** (permanent negative DNS entries — also a correctness bug: dead peer cached forever). **Fixes:** LRU/TTL sweeps as detailed per finding.
- **LOW — secret-retention flavor:** `routes/model_routes.py:993` (`_refresh_state` keys embed plaintext API keys, retained after deletion/rotation — visible in heap dumps; fix: prune on delete/PATCH, fingerprint keys), `src/scheduling/task_scheduler.py:26`, `src/chatgpt_subscription.py:32`, `scripts/hf_download.py:17` (`id(self)` as dict key — also aliasing bug on id reuse).

## RL-6. Disk-space leaks: temp files, logs, and index rot — 8 findings (1 HIGH)

- **HIGH — `src/uploads/handler.py:248`**: `cleanup_old_uploads` deletes files but never their `uploads.json` entries, while every upload does a full parse+rewrite+fsync of the whole index under a global lock — dead entries make every upload linearly slower forever. **Fix:** prune the index in cleanup; migrate to SQLite.
- **MED — `routes/document_routes.py:1600`** (also 1341, 1464): any exception between temp-PDF creation and the FileResponse orphans everything in `_to_unlink`; `prepare_signed_reply` has no cleanup at all. **Fix:** try/finally `_cleanup_temps()`, skipping only when the BackgroundTask takes ownership.
- **MED — `services/youtube/youtube_handler.py:196`**: `--write-comments` drops a permanent `.info.json` in cwd per summarized video. **Fix:** `-P <tempdir>` or drop the flag.
- **MED — `services/tts/tts_service.py:88`** (no cap/TTL on cache dir), **`services/search/cache.py:39`** (restart resets the in-memory index; on-disk orphans become invisible to eviction forever — the MAX_ENTRIES cap is illusory), **`core/atomic_io.py:29`** (tmp file orphaned when json.dump raises). **Fixes:** size/age eviction; reconcile dir↔index; unlink tmp in except.
- **LOW — `routes/shell_routes.py:649`** (disconnect — the advertised main use case — skips log cleanup) and **`routes/ollama_routes.py:213`** (per-pull uuid scripts/logs never deleted). **Fix:** startup/periodic sweep of TMUX_LOG_DIR + delete script on failed tmux launch.

## RL-7. Unbounded buffering of external input — 3 findings (1 HIGH)

- **HIGH — `routes/background_routes.py:79`**: whole multipart body buffered before the size check, on an unauthenticated endpoint — trivial OOM. **Fix:** chunked read, abort at MAX_FILE_SIZE.
- **MED — `services/search/content.py:96`**: non-streaming fetch of arbitrary remote URLs, body held 2× (text + pdfminer input). **Fix:** stream with hard byte cap + Content-Length pre-check.
- **LOW — `src/runtime/app_helpers.py:15`**: latent — unbounded read+base64 (currently unused). **Fix:** size check before read.

## RL-8. Non-atomic state-file writes (adjacent: corruption = permanent resource loss) — 2 findings

- **MED — `scripts/add_hwfit_models.py:410`** and **LOW — `scripts/claim_ownerless.py:50`**: direct `open(path,'w')` on live data files; crash mid-write truncates the catalog/memory files. **Fix:** write tmp + `os.replace()` (or reuse `core/atomic_io.py` — after its RL-6 fix).

---

## Top 3 systemic fixes

1. **A single subprocess-execution helper with mandatory reaping.** One `run_subprocess(cmd, timeout, *, shell=False)` utility that always: `start_new_session=True`, wraps `communicate()` (not spawn) in `wait_for`, and on `TimeoutError`/`CancelledError`/`GeneratorExit` does `killpg` → `await proc.wait()` in a `finally`. Then ban raw `create_subprocess_*` via lint. This closes all 10 RL-1 findings and the cancellation half of RL-2 at once — the correct pattern already exists in three places in the repo (`shell_routes._exec_shell:438`, `cookbook_routes:1495`, `execution.py`'s timeout arm); it just isn't shared.

2. **Ban bare `connect()/close()` pairs; mandate `contextlib.closing`/try-finally via one DB helper.** A `scoped_sqlite(path)` context manager plus a SQLAlchemy `session_scope()` would eliminate all 9 RL-3 findings (~30 call sites, including 18 near-identical migration functions) and, critically, kill the second-order failure: leaked SQLite write handles holding locks that manifest as unrelated "database is locked" errors across the app. Add the rule "no `await` while a session is checked out" for the pool-starvation subgroup.

3. **Replace every module-level dict cache with a bounded TTL/LRU primitive.** Adopt `cachetools.TTLCache`/`LRUCache` (or one small in-house wrapper) as the only sanctioned in-process cache, and apply it to the 15 RL-5 sites plus the dogpile memory regions. Rule: eviction must happen on *write*, never only on re-read of the same key. This also fixes the security tail — plaintext API keys (`model_routes._refresh_state`) and email payloads retained in heap long after deletion — and neutralizes the three externally-driven growth vectors (hwfit host cache, LM Studio probe cache, rate limiter) that are user-triggerable DoS today.

---

# Concurrency Findings — Atenea Audit (Master Report Section)

74 verified findings deduplicate to **68 distinct defects** in **8 root-cause groups** (6 findings merged: the active-document global is reported at both its definition and use sites; the cookbook-state race is one shared-file problem reported from three writers; the memory-store RMW is one design flaw surfaced in seven call sites, kept itemized below but counted once systemically). Severity: 1 critical, 13 high, 33 medium, 21 low.

---

## Group 1 — Per-request state stored in module globals (CRITICAL)

The worst class: process-wide mutable globals used as if they were request-scoped.

- **CRITICAL** `src/chat/agent_loop.py:735` (+ `src/tools/implementations.py:72` — same defect, definition site). `set_active_document()`/`set_active_model()` write bare module globals; the agent loop then crosses many awaits (LLM streaming) before tools read them back. Any concurrent request repoints the global mid-flight → **edit_document writes to the wrong user's document** (cross-session data corruption). *Fix:* pass the active doc id explicitly into `execute_tool_block`, or use `contextvars.ContextVar`. Merges the medium at `implementations.py:341/405` (same-user cross-tab clobber is the mild variant).
- **HIGH** `services/hwfit/hardware.py:630`. `_remote_host/_remote_port` globals mutated per call; a concurrent local `detect_system` resets them mid-probe → remote query returns **and permanently caches the local box's hardware under the remote host's key**. *Fix:* thread a context dataclass through `_run`/`_detect_*` (interim: module lock around `detect_system`).
- **MED** `src/clients/mcp_oauth.py:174`. `_auth_urls` keyed by server_id only; two concurrent flows for one server cross-wire state/futures — wrong caller's future resolved or a 300s hang. *Fix:* key by per-flow `state`, or serialize flows per server.
- **MED** `src/runtime/model_discovery.py:100`. `self._extra_ports` reset/filled as an instance side effect of `_get_hosts()`, read later by `discover_models()` — concurrent discovery silently drops configured non-default ports. *Fix:* return `(hosts, extra_ports)` locally.
- **MED** `src/runtime/model_discovery.py:79`. `discover_tailscale_hosts()` returns the cache list itself; `_get_hosts()` mutates it in place, polluting the TTL cache with env/default hosts. *Fix:* `return list(hosts)`; lock the refresh.
- **LOW** `src/scheduling/task_scheduler.py:713`. `self._last_run_model` shared across concurrent runs → wrong model in the TaskRun audit trail. *Fix:* return the model from the executor instead of stashing on `self`.

## Group 2 — Foundational: the "atomic" write helper isn't (HIGH)

- **HIGH** `core/atomic_io.py:28` (verified). Temp filename is `path.tmp.<pid>` — unique per **process**, not per call. Two async tasks in the same process saving `sessions.json`/`settings.json` truncate each other's temp file mid-write → corrupted JSON or lost update. This undermines every caller that believes `atomic_write_json` is safe. *Fix:* `tempfile.mkstemp(dir=...)` or a `uuid4` suffix; optionally an asyncio.Lock keyed by path.
- **HIGH** `core/auth.py:143` (verified). `_save_sessions` snapshots under `_sessions_lock` but writes **after** releasing it (and several callers save fully unlocked). Stale snapshot ordering **resurrects revoked tokens for deleted users**; combined with the PID-temp bug above, concurrent savers can corrupt `sessions.json` outright. *Fix:* move `_atomic_write_json` inside the `with self._sessions_lock:` block (RLock makes this safe).

## Group 3 — Whole-store load→mutate→save on the memory JSON store (HIGH, one systemic flaw)

`MemoryManager` exposes only `load_all()`/`save(everything)` with no lock; every caller re-implements the same lost-update race. The atomic `os.replace` in `save()` prevents corruption but not clobbering.

- **HIGH** `src/memory/store.py:209` (verified) — root: `increment_uses`, `claim_ownerless`, and the load+append+save idiom all race; second save silently overwrites the first.
- **HIGH** `src/memory/provider.py:161/227` (verified) — `remember()` returns success for a write that a racing `delete()`'s save then erases (or undeletes).
- **HIGH** `src/actions/builtin.py:275` (verified) — `consolidate_memory` snapshots the store, awaits N×120s of LLM calls, then blind-writes the snapshot back: every memory added during the window is destroyed.
- **HIGH** `services/memory/memory_extractor.py:637` (verified) — `audit_memories` same shape (120s window); with `owner=None` it replaces the **entire file** from the stale snapshot, deleting other users' entries, and the vector rebuild at :647 erases them from the index too.
- **HIGH** `routes/backup_routes.py:79` (verified) — import writes back a minutes-old snapshot of memories/settings/presets/features, wiping anything written meanwhile.
- **MED** `src/agent/ai_interaction.py:1015`, **MED** `routes/memory_routes.py:486` — tool-side and API-side add/edit/pin/delete, same race.
- **LOW** `services/memory/memory_extractor.py:60` — tidy-state sidecar: non-atomic `open(w)` write plus per-owner RMW (wasted LLM re-runs, not data loss).

*Group fix:* one lock inside `MemoryManager` (asyncio.Lock in-process + `filelock` cross-process) spanning load→save, plus a delta-apply API (`add/patch/drop by id` against a fresh re-load) so long-await callers never persist pre-await snapshots. Better: per-entry rows in SQLite.

## Group 4 — Stale-snapshot overwrite after long awaits (non-memory)

Same shape as Group 3, different stores: snapshot → await LLM/network → unconditional write-back.

- **HIGH** `routes/session_routes.py:984` (verified). `compact_session` re-checks nothing after a 60s LLM await; `replace_messages` deletes messages the user sent during summarization. *Fix:* re-check `agent_runs.is_active` and re-read history post-await; 409 or merge.
- **MED** `routes/history_routes.py:599` — same bug in the second compact path; also desyncs DB vs in-memory "recent" sets. *Fix:* version-check or per-session lock.
- **MED** `routes/document_routes.py:954` — `ai_tidy` **hard-deletes** docs from pre-await previews; user edits during the 30s await are permanently lost (bypasses soft-delete). *Fix:* re-fetch and compare `updated_at` before delete; use `is_active=False`; per-row commit.
- **HIGH** `src/scheduling/cookbook_serve_lifecycle.py:138` (verified) + **MED** `routes/cookbook_routes.py:2086` + **MED** `src/actions/builtin.py:2151` — three independent writers RMW `cookbook_state.json`; the lifecycle `_tick` comment claims a re-read that doesn't exist. Lost `_scheduledStopAtMs` stamps mean **serves run indefinitely**; the sweep's non-atomic rate limiter (`cookbook_routes.py:2086-2089`) also duplicates adoptions. *Fix:* one file lock shared by all writers of COOKBOOK_STATE_FILE, or a single owning module for mutations; re-read + merge only changed fields before write.

## Group 5 — Duplicate side effects from missing claim/atomic step

- **HIGH** `routes/email_pollers.py:997` (verified). Scheduled emails SELECTed then sent then marked — no claim. Overlapping poller ticks or the documented cron mode → **recipient gets the email twice**; crash between send and mark re-sends on restart. *Fix:* `UPDATE ... SET status='sending' WHERE id=? AND status='pending'`, proceed only on rowcount==1; sweep stale 'sending'.
- **HIGH** `routes/email_pollers.py:84` (verified). `_run_auto_summarize_once` flips five **persisted global settings**, runs, restores. Overlap persists the temporary flags permanently (e.g. `email_auto_spam=True` the user never enabled → background poller moves inbox mail to Spam every 30 min); the poller can also read flipped flags mid-window. *Fix:* pass flags as parameters into the pass functions; never mutate persisted settings as a calling convention.
- **MED** `routes/note_routes.py:177` — dedupe check at :177, write at :518 after a 30s LLM await; the in-file comment names the exact double-email race. *Fix:* write a 'pending' dedupe marker before any await; lock + tmp/rename.
- **MED** `routes/assistant_routes.py:147` — check-then-seed with no unique constraint → duplicate assistants + double-firing check-ins (previously hit in prod per code comments). *Fix:* partial unique index on `(owner, is_default_assistant)`, catch IntegrityError.
- **MED** `src/scheduling/task_scheduler.py:1938` — `stop_task` removes from `_executing` before the coroutine actually stops → scheduler dispatches a second concurrent run (duplicate emails). *Fix:* let `_execute_task`'s finally own the removal.
- **MED** `routes/skills_routes.py:1419` — POST test overwrites a running job; two loops race on `set_audit`/confidence. *Fix:* mirror the audit-all 'running' guard (409).
- **MED** `routes/chat_routes.py:1040` — `_active_streams` clobbered/popped without ownership token; live stream's partial-save record lost. *Fix:* token-conditional pop, or reject second stream per session.

## Group 6 — Unguarded non-thread-safe shared resources

- **HIGH** `scripts/diffusion_server.py:502` (verified). Sync endpoints run on the threadpool; shared diffusers pipelines are not thread-safe → corrupted denoising schedules, CUDA errors, OOM; `_get_inpaint_pipe` (:556-638) double-loads multi-GB pipelines. *Fix:* module lock around every pipeline `__call__` and double-checked lazy init.
- **MED** `scripts/hf_local_openai_server.py:87` — unbounded parallel `model.generate` → CUDA OOM / CPU collapse. *Fix:* lock or Semaphore(k).
- **MED** `src/vector/embedding_lanes.py:184` — unguarded delete→recreate of shared Chroma collections wipes a concurrent rebuild's writes.
- **MED** `src/vector/memory_vector.py:201` — `rebuild()` deletes collections while in-flight `add()` holds references (write logged as warning, silently lost); **MED** `:109` check-then-add duplicates ids (*fix:* `collection.upsert`).
- **MED** `services/search/cache.py:44` + **LOW** `services/search/content.py:240` — shared cache dicts mutated across threads during GIL-releasing unlink/IO. *Fix:* one module lock.
- **MED** `services/search/analytics.py:99` — RMW + non-atomic write on the analytics file. *Fix:* lock + tmp/replace, or SQL counters.

## Group 7 — asyncio/thread lifecycle hazards (hangs, leaks, starvation)

- **HIGH** `src/scheduling/task_scheduler.py:61` (verified). `_cached` cleans up on `except Exception` only — `CancelledError` leaves the pending future unresolved forever; **every later check-in on that cache key awaits a dead future and wedges permanently**. *Fix:* try/finally popping the key and cancelling the future.
- **MED** `src/tools/execution.py:1086` — 30s-abandoned web-fetch threads squat the **default** executor that `asyncio.to_thread` file tools share → whole-agent stall. *Fix:* dedicated bounded executor + hard HTTP timeouts.
- **MED** `src/clients/webhook_manager.py:245` and **MED** `src/scheduling/event_bus.py:40` — fire-and-forget tasks with no strong reference; GC can silently drop webhook deliveries / event triggers. *Fix:* task set + `add_done_callback(discard)`.
- **MED** `src/clients/mcp_manager.py:378-402` — `task.cancel()` never awaited; zombie connect task overwrites the new connection's state. *Fix:* `await task` with `suppress(CancelledError)`.
- **MED** `routes/model_routes.py:1057` — single-flight guard is check-then-set; two refreshers race and the first's finally force-clears the other's inflight flags. *Fix:* `_refresh_lock.acquire(blocking=False)`.
- **LOW** `routes/email_routes.py:517` — IMAP `noop()`/`logout()` inside the single global pool lock; one dead socket stalls the whole app. *Fix:* pop under lock, do network I/O outside.
- **LOW** `routes/ollama_routes.py:223` — `proc.wait()` with PIPEs, no drain, no timeout: the documented asyncio deadlock. *Fix:* `wait_for(proc.communicate(), 15)`.
- **LOW** `routes/shell_routes.py:575` — master fd closed while executor read in flight; reused fd number can steal another connection's bytes. *Fix:* await the reader future before close.
- **MED** `src/scheduling/bg_jobs.py:203` — `echo $? > exit` truncate-then-write window makes successful jobs read as exit 1. *Fix:* write tmp + `mv`, or treat empty file as not-finished.
- **LOW** `src/scheduling/bg_monitor.py:96` — busy-check only before a minutes-long drain; re-check before persisting.

## Group 8 — DB/file check-then-act without constraints or conditional updates

- **MED** `core/database.py:2149` — import-time migrations, no cross-process lock, exceptions swallowed: a losing worker can boot with the `scheduled_tasks` rebuild half-applied (**table missing entirely**). *Fix:* lifespan hook + `BEGIN IMMEDIATE`/flock; destructive steps fail hard.
- **MED** `routes/document_routes.py:598` — duplicate `version_number` rows; restore resurrects arbitrary content. *Fix:* UNIQUE(document_id, version_number) + IntegrityError retry.
- **MED** `core/auth.py:419` — backup-code check outside `_config_lock`, remove inside → HTTP 500 on concurrent replay; **LOW** `:354` — KeyError 500 if user deleted between check and write. *Fix:* validate inside the lock (and hash backup codes).
- **MED** `src/uploads/handler.py:553` — dedupe lookup and insert in separate lock sections (comment claims otherwise); duplicate uploads orphan files. *Fix:* re-check storage_key at insert, delete the loser. **LOW** `:510` — counter re-read outside lock skips cleanup ticks.
- **MED** `src/integrations/registry.py:260` — RMW on integrations file; a mere *read* can resurrect a deleted entry (`load` writes at :217). **MED** `routes/vault_routes.py:63` — racing save_config wipes the just-obtained BW_SESSION. **MED** `core/platform_compat.py:241` — `_BASH_PROBED=True` set *before* the cache is filled → bash silently "missing". *Fix:* value-before-flag or lru_cache.
- **LOW** — same pattern, lower stakes: `routes/gallery_routes.py:1782` (favorite toggle / upload dedupe → SQL `NOT favorite`, unique index), `routes/compare_routes.py` vote TOCTOU (conditional UPDATE), `routes/chat_helpers.py:664` (token undercount → SQL increment; also unlogged bare except), `routes/calendar_routes.py:706` (CalDAV account list), `routes/contacts_routes.py:637` (ETags fetched, never sent as If-Match — lost updates + property destruction), `routes/research_routes.py:337` (non-atomic write can 404 a report forever), `routes/cookbook_routes.py:581` (shared `scan_cache.py` path → uuid temp or stdin), `services/memory/skills.py:488` (rename TOCTOU), `scripts/add_hwfit_models.py:364` (flock the catalog), `src/clients/api_key_manager.py:69/16` and `src/security/secret_storage.py:36` (**key-generation races make secrets permanently undecryptable** — `O_CREAT|O_EXCL` + read-on-EEXIST), `src/runtime/endpoint_resolver.py:97`, `src/vector/chroma_client.py:37`, `src/vector/rag_singleton.py:32` (benign duplicate-init; double-checked locking).

---

## Top 3 systemic fixes

1. **Introduce one blessed concurrency-safe persistence layer and ban ad-hoc JSON RMW.** ~30 findings (Groups 3, 4, 8 and half of the highs) are the same bug: `load whole file → mutate → save whole file` with no lock. Fix `core/atomic_io.py` (per-call unique temp names), add a `locked_json_update(path, mutate_fn)` helper (asyncio.Lock per path + `filelock` for cross-process) and migrate every writer of memory store, cookbook_state, sessions.json, integrations, vault, analytics, dedupe, research, calendar prefs onto it. Longer term, move hot stores (memory, sessions) to SQLite rows with per-row UPDATEs.

2. **Eliminate module-global per-request state; make it a lint rule.** The single critical (active document/model), the hwfit remote-context high, and the OAuth/discovery mediums all stem from process-wide globals holding request-scoped values. Replace with explicit parameters or `contextvars.ContextVar`, and add a CI grep/review checklist item: no `set_active_*`-style global setters in request paths.

3. **Adopt a "revalidate after await" discipline for every long-await write-back, and claim-before-side-effect for every external action.** Any coroutine that snapshots state, awaits an LLM/network call, then writes must re-read and merge (or version-check and abort) — compact_session, ai_tidy, consolidate/audit memories, cookbook _tick. Any externally visible action (email send, webhook, adoption) needs an atomic claim step first (conditional UPDATE / pending marker written before the await). Codify both patterns in CLAUDE.md/dev docs; they would have prevented every duplicate-email and lost-message finding in this audit.

---

# Performance Domain — Audit Section (Atenea)

**Scope:** 160 verified performance reports. After deduplication these collapse to ~145 unique defects: 12 clusters were double/triple-reported at both caller and callee, or in parallel legacy/new module trees (`src/youtube/handler.py` ≡ `services/youtube/youtube_handler.py`; `src/research/handler.py` ≡ `services/research/research_handler.py`; `src/memory/store.py` reported again via `mcp_servers/memory_server.py` and `services/memory/service.py`; `get_context_length` blocking reported at `src/llm_core.py:1336`, `src/chat/model_context.py:233`, and `routes/session_routes.py:1277`; device-flow sync httpx reported at `routes/device_flow.py:152`, `src/clients/copilot.py:149`, `routes/copilot_routes.py:47`, `routes/chatgpt_subscription_routes.py:134`; skill import at `routes/skills_routes.py:1251` + `services/memory/skill_importer.py:228`; preset fsync at `routes/preset_routes.py:35` + `src/preset_manager.py:115`; skills rescan at `services/memory/skills.py:584` + `routes/skills_routes.py:1435`; STT at `services/stt/stt_service.py:144` + `routes/stt_routes.py:41`; web-search preface at `src/chat/processor.py:296` + `routes/chat_helpers.py:612`). Each cluster is counted once below, cited at its root.

**Headline:** this codebase has one dominant disease — **synchronous I/O and CPU work executed directly on the asyncio event loop inside `async def` handlers** (~70% of all findings, across 60+ files). Because FastAPI runs `async def` bodies on the single loop thread, every one of these turns a per-request cost into an app-wide stall: one slow IMAP server, SQLite lock, or GPU inference freezes *every* user's request, SSE stream, and background task. The codebase already knows the cure — `asyncio.to_thread` is used correctly in `routes/email_routes.py` `/list`, `src/chat/agent_loop.py` RAG retrieval, `app.py` `_touch_last_used`, `src/calendar_app/sync.py` — it is just applied inconsistently.

---

## Group 1 — CPU-bound work on the event loop (1 critical, 4 high)

Worst-in-class because no timeout bounds the stall.

| Severity | Location | Defect | Fix |
|---|---|---|---|
| **CRITICAL** | `routes/gallery_routes.py:1467` (also 1514, 1580, 1651, 1419, 297) | Real-ESRGAN / rembg / GFPGAN / PIL inference inline in `async def` — one "AI Upscale 4x" freezes the whole app 30–120s | `run_in_executor`/`to_thread` around inference and `write_bytes`/`read_bytes` |
| HIGH | `app.py:324` | `bcrypt.checkpw` (~100–300ms) inline in AuthMiddleware for **every bearer-token request**; ×N per shared prefix | `await asyncio.to_thread(_bcrypt.checkpw, ...)` |
| HIGH | `routes/document_routes.py:215` (469, 1140, 1211, 1338, 1461, 1600, 1675) | pypdf+vision OCR (minutes on scanned PDFs), PyMuPDF rasterization, IMAP fetch inline in async handlers | to_thread all; timeout on IMAP |
| HIGH | `src/documents/processor.py:119` | `_process_pdf`: unbounded per-page VL/OCR — up to 3 sync 120s LLM calls **per page**, no page cap; reachable from chat preprocess. Single upload = hours-long loop freeze | Cap pages/images per PDF; use `llm_call_async` + bounded semaphore |
| MED | `src/tools/parsing.py:535` | Unbounded-backtracking regexes over full LLM output per round → O(n²) CPU DoS via crafted model output | Cap input size; bounded quantifiers; to_thread |

Also: `routes/auth_routes.py:264,237` (bcrypt regressions — siblings already use to_thread), `routes/auth_routes.py:208` (QR gen).

## Group 2 — Blocking network I/O in async code (~20 high)

The largest high-severity cluster. Canonical instances, ranked by blast radius:

- **`src/llm_core.py:1336,1448` + `src/chat/model_context.py:233`** (HIGH) — `get_context_length()` does sync `httpx.get` probes on the loop **on every chat turn**; local endpoints deliberately bypass the cache, so every stream against Ollama/llama.cpp pays it. *Fix:* `await asyncio.to_thread(get_context_length, url, model)`; add short-TTL cache for local endpoints. Compounds: `model_context.py:32` re-runs the endpoint-table query up to 5× per lookup — compute once and thread through.
- **`routes/chat_routes.py:421,484,237`** (HIGH) — per-send sequential `socket.create_connection` + sync `httpx.get` probes over ALL endpoints; 10 endpoints ≈ 21s frozen loop. *Fix:* to_thread + `asyncio.gather` + few-second reachability cache.
- **`src/chat/processor.py:296`** (HIGH) — `build_context_preface` runs `comprehensive_web_search` + up to 3 sequential 5s `fetch_webpage_content` calls sync from async `build_chat_context` (`routes/chat_helpers.py:612`). *Fix:* make async; gather URL fetches. Same sync-search defect: `routes/search_routes.py:60`, research fallbacks `src/research/handler.py:943` / `services/research/research_handler.py:429` (fires exactly when the system is already degraded).
- **Email**: `routes/email_routes.py:2699` (ai_reply: IMAP mining + PDF parsing on loop, 5–30s), `:2097` (resolve_contact: ~600 sequential per-UID fetches, 12–30s), `:1103` (search), `:1426` et al. (14 endpoints incl. full-RFC822 attachment fetches), `:3159` (test-config, 20–30s against dead hosts — the endpoint *most likely* to be called with dead hosts); `routes/email_pollers.py:320` (auto-summarize: full RFC822 fetch of 20MB messages on the loop every 30 min); `mcp_servers/email_server.py:1376` (entire tool dispatch sync). *Fix:* one pattern — extract `_x_sync()` bodies, `await asyncio.to_thread(...)`; batch UID fetches (the technique already in `_list_emails_sync:806`).
- **DNS `socket.getaddrinfo` on the loop** (5–30s OS resolver timeout): `src/clients/webhook_manager.py:256` (every webhook delivery — user-triggerable DoS), `src/runtime/endpoint_resolver.py:110` (+`tailscale status` subprocess), `routes/calendar_routes.py:639`, `src/security/url_security.py:41`, `src/security/url_safety.py:29`, `src/calendar_app/sync.py:521`. *Fix:* `loop.getaddrinfo(...)` or to_thread.
- **Device-flow cluster** (HIGH, root: `src/clients/copilot.py:149-211` + `src/chatgpt_subscription.py:251`) — sync `httpx.post` with 10–20s timeouts, polled every ~5s for up to 15 min per login; `routes/device_flow.py:152` calls provider callables eagerly so `_maybe_await` never helps. *Fix:* in `device_flow.py`, `iscoroutinefunction` check → `to_thread` for sync providers; migrate clients to `AsyncClient`. Also covers OAuth refresh (20s httpx.post) in `resolve_runtime_credentials`.
- Other confirmed highs, same fix (`to_thread` / `AsyncClient`): `routes/contacts_routes.py:274-666` (all CardDAV), `routes/task_routes.py:768` (cascade delete, 30s+), `routes/cookbook_routes.py:930` (SSH subprocess + port probes), `src/scheduling/task_scheduler.py:1556` (SMTP 30s), `routes/skills_routes.py:1251`/`skill_importer.py:228` (64 sequential GitHub fetches, 20–30s each; also `:169` — new TLS handshake per file), `src/agent/ai_interaction.py:120,1143,1743` (endpoint probes + 60s DALL-E download), `src/youtube/handler.py:101`, `services/tts/tts_service.py:136` (60s) , `services/stt/stt_service.py:144` (+whisper CPU), `routes/docker_ollama.py:105` (`images.pull` = minutes), `src/chat/handler.py:232` (VL call, 120s/candidate — sibling at line 179 does it right), `routes/upload_routes.py:80,227`, `routes/personal_routes.py:128` (directory indexing), `src/tools/index.py:502` via `task_scheduler.py:1371` (embedding+Chroma — agent_loop wraps it, scheduler doesn't). Mediums: `routes/shell_routes.py:1208`, `routes/ollama_routes.py:293`, `mcp_servers/image_gen_server.py:84`, `mcp_servers/rag_server.py:116`, `src/vector/chroma_client.py:25`, `src/vector/rag_singleton.py:46`, `src/runtime/model_discovery.py:249` (uncached 24-port sweep, ~35s worst case).

## Group 3 — Sync DB (SQLAlchemy/sqlite3) on the event loop (~25 findings, mostly medium)

Single shared failure mode: SQLite serializes writers; any handler doing sync DB in `async def` freezes the loop for the busy-timeout when a background writer holds the lock. Highs: `routes/document_routes.py:88` (all ~18 handlers), `routes/history_routes.py:604` (compact: SELECT-all + N deletes + fsync commit), `routes/calendar_routes.py:850` (+10MB iCal parse + RRULE expansion), `core/session_manager.py:407,242` (3 blocking round-trips **per persisted chat message**), `src/misc/cleanup_service.py:55`, `routes/api_token_routes.py:152`. Mediums/lows: `src/actions/builtin.py:1787` (per-email SELECT+UPSERT loop; also delete the dead `.count()` at L413), `src/scheduling/task_scheduler.py:605` (blocking query while holding `_executing_lock` — query first, lock after), `routes/chat_routes.py:869` (commits mid-SSE-stream), `routes/model_routes.py:1282`, `routes/session_routes.py:562`, `routes/note_routes.py:831,871`, `routes/mcp_routes.py:232`, `routes/auth_routes.py:302` (also: `lower(owner)` defeats the index — filter on normalized value), `src/clients/mcp_oauth.py:119`, `src/clients/mcp_manager.py:416`, `routes/memory_routes.py:271`, `src/actions/document.py:66`, plus `assistant/editor_draft/signature/research/backup` routes. **Fix (uniform):** plain `def` handlers where nothing is awaited (FastAPI threadpools them — the cheapest fix, often just replacing `await request.json()` with a Pydantic body), else `to_thread`; long-term, async SQLAlchemy.

## Group 4 — N+1 / per-item round-trips (~18 findings)

- HIGH `routes/contacts_routes.py:569` — CSV import re-downloads the **entire address book per row** (500 rows × 2000-contact REPORT). Fix: build vCard with phone up front; one shared client.
- MED `routes/task_routes.py:935` — `_resolve_run_endpoint` re-scans + re-JSON-parses the full ModelEndpoint table up to 200×/request. Fix: build model→URL dict once.
- MED `routes/session_routes.py:1055` — up to 2000 first-message queries per Tidy click (the adjacent commit fixed the counts but missed this one); same pattern `src/misc/session_actions.py:58,211` (4 queries/session + re-fetch by PK of rows already in identity map).
- MED `routes/calendar_routes.py:1230` — one dedup SELECT per VEVENT (20k imports = 20k queries). Fix: preload `(dtstart, summary)` set.
- MED `scripts/pr_blocker_audit.py:221` — one `gh api` subprocess per PR, up to 1000 sequential. Fix: batched GraphQL.
- MED `scripts/repair_stale_session_endpoints.py:146` — O(sessions×endpoints) socket probes (worst case 26 min). Fix: probe endpoints once, reuse.
- MED `src/misc/cleanup_service.py:132` — per-session COUNT loop → one GROUP BY.
- Lows, same shape: `routes/gallery_routes.py:585` (2–3 queries/album), `routes/email_helpers.py:714` (session-per-account), `src/runtime/endpoint_resolver.py:403` (session-per-chain-entry → `IN(...)`), `src/misc/session_search.py:271` (per-FTS-hit query → `IN(...)`), `routes/cookbook_routes.py:1565` (one SSH per sysfs file per GPU, 50+ sessions → one remote script), `mcp_servers/email_server.py:476` (per-UID FETCH → batched UID list), `src/scheduling/event_bus.py:105` (commit-per-task → one commit), `src/research/topic_analyzer.py:53`.

## Group 5 — Unbounded work: missing caps, O(n²) algorithms, whole-file materialization (~20 findings)

- **HIGH `core/database.py:1758`** — FTS backfill anti-join on an UNINDEXED column = O(n·m) full-FTS-scan per chat row, **on every boot**, holding a write transaction; 200k messages → minutes of startup. Fix: count-compare skip, or external-content FTS keyed by rowid.
- HIGH `scripts/diffusion_server.py:502` — no bounds on `n`/`size`/`steps`: `n=100000` runs diffusion for hours and accumulates tens of GB of base64. Fix: clamp (n≤4, dims 64–2048, steps≤75).
- HIGH `src/scheduling/bg_jobs.py:164` — `read_text()` of a potentially multi-GB job log before truncating to 16KB → OOM-kills uvicorn. Fix: stat + read head/tail bytes only.
- HIGH `src/research/handler.py:394` — `get_avg_duration` re-parses **every** research JSON (never deleted, MBs each) per status poll/SSE tick, monotonically worse forever. Fix: running (count,sum) aggregate or 60s TTL cache. Same shape: `routes/research_routes.py:264` (library listing parses all reports per poll → sidecar metadata index).
- MED `src/chat/agent_loop.py:2011` — doc streaming re-decodes and re-emits the **full** accumulated document per ~20-byte delta → gigabytes of CPU+SSE for one 200KB doc. Fix: emit only the suffix; incremental decode.
- MED `routes/gallery_routes.py:455` — per-page full tag scan + (shuffle) all-IDs fetch; 50k-photo library = quadratic scroll. Fix: cached facets; seeded SQL ordering.
- MED `src/chat/context_compactor.py:284` — O(n²) pop-and-recount trimming → running total.
- MED `routes/shell_routes.py:655` — tmux tail re-reads the whole log every second → byte-offset seek.
- MED `src/integrations/registry.py:419` — buffers unbounded upstream body before 12KB truncation → stream with 64KB cap. Same: `routes/document_routes.py:524` (unbounded export-zip in BytesIO), `src/vector/embedding_lanes.py:159` and `src/vector/rag_vector.py:480,324` (whole Chroma collection into memory; re-embed everything on fingerprint change → paginate/`where`-filter), `src/uploads/handler.py:364` (full os.walk per dangling upload id), `mcp_servers/memory_server.py:88`.
- LOW: `scripts/pr_blocker_audit.py:542` (O(n²) with recomputed keywords → precompute), `src/personal/docs.py:106` (size computed, never used to skip), `services/docs/service.py:74`, `routes/note_routes.py:871` (uncapped `ids`), `src/research/topic_analyzer.py:76`.

## Group 6 — Redundant recomputation / missing caching (~12 findings)

- MED `src/actions/builtin.py:637` — `classify_events` re-LLMs every `importance='normal'` event forever (24×/day/event, unbounded token spend). Fix: skip when both fields set, regardless of value. **Cheapest big win in the whole audit.**
- MED `services/memory/skills.py:584` — full skills-tree walk+parse on **every agent turn** (`index_for` in system prompt) and O(n²) in audit-all (`routes/skills_routes.py:1435`, ~6n loads). Fix: mtime-keyed cache invalidated on write.
- MED `routes/upload_routes.py:133` — uploads.json parsed + linear-scanned per download → mtime cache + dict index.
- LOW: `core/platform_compat.py:299` (`is_wsl` re-reads /proc/version per path → `lru_cache`), `services/search/providers.py:186` and `skill_importer.py:169` (no HTTP client reuse — fresh TLS handshake per call), `src/research/topic_analyzer.py:71` (regex recompile per keyword×message), `routes/model_routes.py:1532,1472` (serial inline pings), `app.py:759` (index.html read per page load).

## Group 7 — Broken async plumbing (1, correctness-adjacent)

- MED `routes/codex_routes.py:273` — throwaway `BackgroundTasks()` means queued email delivery **never executes**: API returns `queued: true`, mail is silently dropped. Fix: accept `BackgroundTasks` as a real handler parameter and pass it through. Flag this to the correctness lead too.

---

## Top 3 systemic fixes

1. **Establish and enforce an off-loop I/O boundary.** Adopt one rule — *no sync network, DB, file, or CPU-heavy call inside `async def` without `asyncio.to_thread`/`run_in_threadpool`* — and apply it mechanically: convert body-only handlers to plain `def` (free threadpool dispatch), wrap the rest, and add a CI lint (custom ruff/AST rule flagging `SessionLocal()`, `httpx.get/post`, `imaplib`, `socket.getaddrinfo`, `open()`, `subprocess.run` inside `async def`). This single change resolves ~100 of the 145 defects, including the critical and most highs.

2. **Shared async-friendly clients with caching for endpoint/reachability probes.** One module owning: a pooled `httpx.AsyncClient`, async DNS/TCP reachability with a few-second TTL cache, and a TTL cache for `get_context_length`/model lists (including local endpoints). Kills the per-chat-turn probe on the hottest path (`llm_core`/`model_context`/`chat_routes`), the device-flow cluster, discovery sweeps, and the handshake-per-request waste — and removes the incentive to re-probe N endpoints per request.

3. **Batch-or-cap discipline for per-item loops and listings.** Codify three patterns: (a) hoist per-row queries into one `IN(...)`/`GROUP BY` (task runs, tidy, cleanup, calendar import, FTS hits, fallback chains); (b) batch protocol round-trips (IMAP `UID FETCH uid1,uid2,...`, one SSH script per host, GraphQL for PR files); (c) never materialize unbounded data — cap client-supplied list/size params at the schema (Pydantic validators), read files by offset/head-tail, paginate vector-store gets, and maintain incremental aggregates/indexes instead of re-parsing whole directories per poll (research stats, skills library, uploads.json).

---

# Correctness — Annotated Findings (Atenea Audit)

**Input:** 129 verified findings → **1 discarded** (placeholder entry "test" against `src/agent/teacher_escalation.py`, no content) → **de-duplicated into 9 root-cause groups.** Notable merges: the research persistence bugs in `src/research/handler.py` and `services/research/research_handler.py` are the same defect in two near-duplicate modules (the module duplication is itself a finding); the swallowed endpoint-config-load pattern is one copy-pasted bug in three files; the fire-and-forget task-GC bug is one pattern at 8+ sites; truncated-UUID primary keys appear twice.

Groups are ranked by worst-case impact. Every HIGH is listed individually; MEDIUM/LOW are rolled up under their root cause with citations.

---

## G1. Irreversible data loss from destroy-before-verify ordering — CRITICAL

The single worst pattern in the codebase: destructive step commits before the step that could still fail, with no compensating rollback.

- **`src/vector/memory_vector.py:201` (HIGH)** — `rebuild()` deletes all three lane collections, *then* calls `build_embedding_lanes()`. If the embedding backend is briefly down, `_lanes == []`, the insert loop is a no-op, and the function logs success. Every stored memory vector is gone, silently. **Fix:** build and populate new lanes first; only delete old collections after verifying the new ones are non-empty; raise if `_lanes` is empty (mirroring `__init__:40`).
- **`src/vector/embedding_lanes.py:184` (HIGH)** — `_get_or_reset_collection` deletes the original collection before the re-embedded write; if the write *and* the in-memory restore both fail (same disk-full/restart cause), the data is unrecoverable and only a warning is logged. **Fix:** write-then-swap (create new collection under a temp name, `os.replace`-style promotion), never delete before the replacement is durable.
- **`routes/auth_routes.py:340` (HIGH)** — `rename_user` commits the owner-column rewrite across every model *before* `auth_manager.rename_user()`, which can still legitimately reject (reserved names, `core/auth.py:283`; races). Result: auth account stays `bob`, all of bob's rows now belong to a nonexistent owner, permanently. **Fix:** run the auth rename (all its validations) first; compensate-rollback the DB rewrite if the second step fails.
- **`scripts/cleanup_stale_model_endpoints.py:56` (HIGH)** — dedup key is URL-only with no owner filter on a multi-tenant table; `--apply` disables *another user's* working endpoint when two tenants point at the same base_url. **Fix:** key on `(ep.owner or "", _canon(base_url))`.
- MEDIUM/LOW same pattern: `routes/gallery_routes.py:911` (unlink before soft-delete commit; mirror bug in upload at :161 — commit first, then unlink); `routes/calendar_routes.py:1006` (CalDAV writeback failure after local commit returns 500 → client retry duplicates the event; same in update :1057/delete :1091 — return `{ok, sync: "pending"}` on push failure); `routes/session_routes.py:236` (incognito purge filters `created_at < 10min` instead of last-activity, and has **no owner filter** — kills live chats cross-tenant; filter on `last_message_at`); `src/research/handler.py:609` + `src/integrations/registry.py:506` + `src/vector/embedding_lanes.py` config (non-atomic `write_text`/`open('w')` — use temp-file + `os.replace`; the codebase already has `core.atomic_io.atomic_write_json`); `src/calendar_app/sync.py:363` (random-UUID fallback for UID-less VEVENTs → new PK every sync, flickering duplicates; derive a stable hash of calendar_id+dtstart+summary).

## G2. Failures reported as success (silent data loss with a 200) — HIGH

Operations that fail, swallow the error, and tell the caller everything worked.

- **`core/session_manager.py:305` (HIGH)** — `_persist_message` catches DB insert failure (e.g. SQLite lock), rolls back, and returns normally; caller returns success; message vanishes on rehydrate. **Fix:** re-raise so callers surface it.
- **`src/uploads/handler.py:664` (HIGH)** — index write failure after upload is logged-and-ignored; client gets a 200 + id that resolves to `info={}`, and the owner check then *permanently denies the owner their own file*. **Fix:** on index-write failure, delete the bytes and raise 500.
- **`routes/admin_wipe_routes.py:46` (HIGH)** — privacy wipe returns `status: deleted` even when the `memory.json` truncate raised `OSError`; old memories reload next request. **Fix:** propagate file-op failure to the endpoint (non-200 or `partial` flag). Same file: `_rmtree_quiet` (:56, MEDIUM — orphaned gallery files still servable) and cache-clear swallow (:83, LOW).
- **`scripts/claim_ownerless.py:89` (HIGH)** — except block prints ERROR but falls through to "Done! All ownerless data now belongs to…" and exits 0. **Fix:** `sys.exit(1)` in the except.
- **`app_setup.py:283` (HIGH)** — Docker first-run generates a random admin password and never prints it (only `_run_host_setup` prints); fresh container installs are locked out. **Fix:** capture `create_default_admin()`'s tuple and print credentials, or refuse to auto-generate without env vars.
- MEDIUM/LOW same pattern: `core/auth.py:271` (token revocation for a deleted user fails silently → deleted user keeps API access; `logger.exception` + propagate); `routes/skills_routes.py:651` et al. (audit says "published" while disk write failed); `src/misc/cleanup_service.py:73/153/256` (DB outage → `{deleted: 0}` 200, indistinguishable from "nothing to clean"); `scripts/demo_email/seed_demo_emails.py:381/318` (imaplib `NO` status discarded — check `typ != "OK"`); `mcp_servers/rag_server.py:138` (remove_directory always claims success; also missing `abspath` normalization vs add's :110); `routes/contacts_routes.py:573` (CSV phone enrichment failure still counts row as imported).

## G3. Code that has never worked as written — HIGH

Bugs where the happy path itself is broken; several imply zero test coverage of the feature.

- **`src/misc/session_search.py:245` (HIGH)** — FTS5 SQL is missing `:fts_query` after `MATCH` and `:limit` after `LIMIT`; the syntax error is caught at DEBUG and every search silently falls back to full-table `LIKE`. The FTS index has never been queried. **Fix:** add the placeholders + a regression test asserting `_search_fts` returns rows.
- **`routes/cookbook_routes.py:1107` (HIGH)** — generated `ollama serve` bash: unclosed `for`, stray `fi`, `${ATENEA_OLLAMA_URL}` used before assignment. Every POSIX serve dies instantly while the API returns `ok=True`. **Fix:** restructure loop/conditional; add a `bash -n` unit test on the generated runner.
- **`routes/cookbook_routes.py:376` (HIGH)** — Windows-remote download `.ps1` written from *plain* strings containing `{{`/`}}` escape syntax → unparseable PowerShell; downloads never start. **Fix:** single braces in the non-f-string `ps_lines` (mirror the correct serve branch at :967-985).
- **`services/search/service.py:45` (HIGH)** — `self.fetch_content = fetch_content` (bool) shadows the `async def fetch_content` method; any call raises `TypeError: 'bool' object is not callable`. **Fix:** rename the flag to `fetch_content_enabled`.
- **`core/database.py:2108` (HIGH)** — `get_session_by_id` returns an expired, detached ORM instance (no `expire_on_commit=False`); any attribute access raises `DetachedInstanceError`. **Fix:** return a dict built inside the with-block. Same file: `bulk_insert_messages:2010` (MEDIUM) omits the required PK — always `IntegrityError`; add `'id': uuid.uuid4().hex`.
- **`scripts/pr_blocker_audit.py:257` (HIGH)** — `gh api --paginate` emits concatenated JSON arrays; single `json.loads` fails past 100 items, so the largest PRs are exactly the ones silently dropped. **Fix:** `--slurp` + flatten, or `raw_decode` loop.
- **`routes/cookbook_routes.py:1263` (MEDIUM)** — `Path.write_text(mode="a")` doesn't exist; warmup logging always raises TypeError, and raising *again inside the except* kills the task. **Fix:** `open(path, 'a')` via `to_thread`; keep the task reference.
- Related dead/duplicate code hiding the real path: `routes/cookbook_helpers.py:245` (MEDIUM — five helpers defined twice with divergent signatures; last-def wins, first contracts are traps → delete one set, enable pyflakes F811); `routes/email_routes.py:1929` (dead `async` `_send_email_sync` with blocking SMTP body); `routes/ollama_routes.py:62` (`_ollama_api_pull` dead but its own test asserts it's wired in); `routes/calendar_routes.py:1148` (duplicate DELETE route; dead handler returns 200-with-error).

## G4. Tenant/identity scoping failures — HIGH-adjacent

- **`src/tools/security.py:169` (HIGH)** — `is_configured == False` (including transient/error states) grants *every* owner the full admin tool set (bash, python, vault_get). **Fix:** explicit deployment-mode flag; never infer open access from an inferable/error-prone predicate.
- **`mcp_servers/email_server.py:905` (MEDIUM)** — after a merged multi-account listing, reply/delete/archive resolve `account=None` to the default account; per-mailbox UIDs then hit the *wrong message in the wrong account* — replies disclosed to the wrong recipient, wrong messages deleted. **Fix:** refuse destructive ops when ≥2 accounts and account unspecified, or encode account id in returned UIDs.
- MEDIUM/LOW: `routes/email_pollers.py:60` (owner-lookup exception falls back to the *unowned* cache scope — propagate instead); `routes/email_helpers.py:639` (explicit-but-missing `account_id` silently falls through to a different account — raise); `src/documents/pdf_form_doc.py:229` (missed session lookup commits an `owner=None` = effectively public document — bail out); `src/runtime/model_discovery.py:254` (host-less dedup key collapses distinct machines, incl. all fresh Ollama installs — include host in key); `routes/session_routes.py:236` cross-tenant purge (also in G1).

## G5. Fire-and-forget asyncio tasks with no strong reference — one pattern, 8+ sites

The event loop holds only weak refs; tasks can be GC'd mid-flight and their exceptions lost.

- **`routes/skills_routes.py:1428` (HIGH)** — skill-test job GC'd → UI polls `status: running` forever, no cancel path (audit job at :1521 does it right).
- `routes/chat_helpers.py:373/962/1001/1014/1021` (MEDIUM) — memory extraction, skill extraction, webhooks, auto-name all droppable. `routes/cookbook_routes.py:1280` (`ensure_future` for warmup). `routes/email_routes.py:1378` (LOW — `_WARMING_READS` keys added *before* `create_task`; on RuntimeError they're stranded forever and permanently block warming).
- **Fix (one helper, everywhere):** `_bg_tasks = set(); def spawn(coro): t = asyncio.create_task(coro); _bg_tasks.add(t); t.add_done_callback(_bg_tasks.discard); t.add_done_callback(_log_if_exception)`.

## G6. The `except Exception: pass` epidemic — ~35 findings, mostly LOW individually, HIGH in aggregate

The dominant defect *count*. Consequences observed: security-relevant failures invisible (`routes/auth_routes.py:391` — stale bearer token keeps authenticating after user deletion; `routes/mcp_routes.py:104` — corrupt `disabled_tools` JSON silently *re-enables* admin-disabled tools), wrong-credential auth (`src/calendar_app/sync.py:513` — decrypt failure passes raw ciphertext as the password), state divergence (`src/agent/ai_interaction.py:996` vector index drift; `routes/embedding_routes.py:308` stale Chroma client after endpoint switch), lost partial responses (`src/agent/runs.py:115`), invisible schema drift (`routes/email_helpers.py:551` migrations), config silently ignored (`src/runtime/model_discovery.py:119`; the endpoint-file loaders in `routes/embedding_routes.py:101` / `src/vector/embeddings.py:195` / `src/vector/embedding_lanes.py:92` — same copy-pasted block), and misleading error mapping (`app.py:356` — auth middleware's try encloses `call_next`, converting every downstream 500 into `401 Invalid API token`; `routes/webhook_routes.py:257`; `src/chat/helpers.py:307`; `src/runtime/endpoint_resolver.py:311`; `src/llm_core.py:1177` — successful responses discarded as 502 when the cache write raises, then double-billed via fallback).

Additional cited sites: `routes/document_routes.py:216`, `src/chat/agent_loop.py:2485`, `src/tools/index.py:260` (also latches the generation as processed — MCP tools permanently unindexed), `src/scheduling/bg_jobs.py:64` (corrupt store → all jobs orphaned *and* the empty store persisted), `src/chat/handler.py:213`, `routes/image_routes.py:95`, `routes/api_token_routes.py:154` (malformed JSON → false-success 200), `companion/pairing.py:117`, `services/memory/skill_importer.py:249`, `services/hwfit/models.py:259`, `src/clients/builtin_mcp.py:115` (catches `BaseException` incl. SystemExit), `src/calendar_app/writeback.py:87`, `src/chat/model_context.py:62`, `routes/docker_ollama.py:81`, `src/runtime/app_helpers.py:10`, `routes/session_routes.py:572`, `mcp_servers/rag_server.py:32` (latches `_initialized=True` on failure — permanent until restart), research readers (`src/research/handler.py:421-628`, `services/research/research_handler.py:128-206` — duplicated module, consolidate), `scripts/diffusion_server.py:727` (TypeError-as-capability-dispatch returns wrong-but-plausible images), `routes/embedding_routes.py`, `src/memory/store.py:149` (`_validate_entries` never guarantees `"text"` → KeyError crashes chat turns).

**Fix:** blanket policy — every except block must either narrow the type, log at ≥WARNING with context, or propagate. Grep-able: ~`except Exception:\s*(pass|continue)` should be lint-banned (see systemic fix #1).

## G7. Contract violations returning 500s / wrong status for bad input — LOW-MEDIUM

`src/tools/schemas.py:1284` (non-dict edit items abort the whole agent stream — mirror the `isinstance` guard at :1292); `src/tools/execution.py:1569` (`result["stderr"]` KeyError on stdout-only MCP results — use `.get`); `routes/shell_routes.py:434` (`timeout=0` documented as "no timeout" kills the command instantly), :667 (partial-line tail drops completed output), :794 (unparseable exit file fabricates exit 0); `routes/session_routes.py:766` (non-latin-1 session names → UnicodeEncodeError 500 in Content-Disposition); `routes/document_routes.py:1167`, `routes/gallery_routes.py:1410`, `routes/note_routes.py:785`, `routes/hwfit_routes.py` gpu_count, `routes/research_routes.py:514`, `scripts/hf_local_openai_server.py:28` (`stream=true` silently ignored — reject with 400), `scripts/diffusion_server.py:481` (errors as HTTP 200 bodies), `routes/contacts_routes.py:786` (**masked `***` password round-trip stored as the real credential** — skip persisting the sentinel) and :795 (`/clear` poisons the CardDAV cache for 60s).

## G8. Process/PID handling on the host — MEDIUM

`core/platform_compat.py:134` (`killpg` can SIGTERM the server's own group — guard `pgid == os.getpgid(0)`); :106 (`pid_alive` returns False on EPERM for a live foreign-uid process → double-spawns); `src/scheduling/bg_jobs.py:212` (timeout reaper can kill an unrelated *recycled* PID after restart — store and verify process start time before killing).

## G9. Low-entropy primary keys — LOW-MEDIUM

`companion/pairing.py:94` and `src/scheduling/task_scheduler.py:2117` both truncate UUID4 to 8 hex chars (32 bits); collisions are realistic at tens of thousands of rows and surface as unhandled `IntegrityError` (pairing) or a silently-rolled-back seed batch (scheduler). **Fix:** full `uuid4().hex` in both.

Remaining singletons, briefly: `src/chat/agent_loop.py:685` (prompt cache key omits `ui_language` + `mcp_disabled_map` — wrong-language prompts served cross-user), :2257 (verifier `continue` drops the assistant's own round from history → duplicated contradictory finals); `routes/model_routes.py:611` (probe omits `verify=llm_verify()` → private-CA endpoints get their entire model list hidden); `src/llm_core.py:1213` (sync path lacks the dead-host cooldown its own docstring claims); `src/settings.py:209` (shallow merge drops new nested default keys like keybinds — deep-merge dict-valued defaults) and the `PermissionError` asymmetry at :240; `src/runtime/config.py:157` (explicit path overrides silently ignored) and :37 (`.py` both allowed and dangerous — pick one); `routes/chat_routes.py:833` (malformed attachments JSON → message sent without files) and :1745 (`/rewrite` overwrites the newest assistant row regardless of target); `services/search/core.py:347` (slice-before-filter drops valid whitelisted results — filter then slice); `services/hwfit/profiles.py:190` (models with ctx < 8192 get zero profiles — floor at `min(model_ctx_max, 8192)`); `src/research/deep.py:308` (continuation branch identical to fresh branch — `prior_report` never threaded into planning); `src/actions/builtin.py:1934` (transient IMAP failure wipes notified-state → duplicate urgent pings — prune only successfully-scanned accounts); `mcp_servers/email_server.py:873` (unguarded `conn.quit()` in finally masks send outcome → duplicate sends); `scripts/demo_email/seed_demo_emails.py:212` (aware/naive datetime mix puts the demo invite on Sunday); `services/research/research_handler.py:314` (Duration key never emitted → always 0.0s); `routes/calendar_routes.py:635` (legacy empty-url POST wipes ALL accounts, not the first); `routes/signature_routes.py` (raw exception text in 500 bodies).

---

## Top 3 systemic fixes

1. **Ban silent exception swallowing via lint + a shared helper.** Add a CI rule (ruff `S110`/`S112` — `try-except-pass`/`try-except-continue` — plus pyflakes `F811` for the duplicate-definition class) and a `swallow(log_ctx)` context-manager for the genuinely-optional cases so every suppression logs at WARNING with context. This single policy addresses ~35 findings in G6 and the "reported success on failure" halves of G2, and would have made the FTS5 bug (G3) visible on day one instead of hiding it at DEBUG as an "expected fallback."

2. **Adopt a durable-write discipline: never destroy before the replacement is durable, never report success before persistence is confirmed.** Concretely: (a) all JSON/state writes go through the existing `core.atomic_io.atomic_write_json` (temp + `os.replace`); (b) all delete-and-rebuild flows (memory_vector, embedding_lanes, rename_user, gallery, wipe endpoints) restructure to build-verify-swap with a compensating rollback; (c) route handlers return non-200 or an explicit `partial`/`sync: pending` field whenever a persistence step failed. Eliminates every finding in G1 and the HIGHs in G2.

3. **Test generated artifacts and never-exercised paths mechanically.** The G3 cluster (bash with unclosed `for`, PowerShell with literal `{{`, SQL missing bind placeholders, `write_text(mode="a")`, a bool shadowing its own method, an INSERT with no PK) shares one property: the code path was never executed once before shipping. Add cheap smoke gates: `bash -n` / `pwsh -NoProfile -Command "[scriptblock]::Create((gc file))"` on every generated runner script, a unit test that executes each raw SQL string against an in-memory SQLite with the real params dict, and one construct-and-call test per service class. Plus the shared `spawn()` helper from G5 for all `create_task` sites, enforced by grepping for bare `asyncio.create_task(`/`ensure_future(` in CI.

---


# Appendix — findings per file

Files ordered by worst severity, then finding count.

| File | 🔴 | 🟠 | 🟡 | 🔵 | ⚪ |
|---|--|--|--|--|--|
| `src/scheduling/task_scheduler.py` | 1 | 2 | 4 | 4 |  |
| `routes/gallery_routes.py` | 1 | 2 | 3 | 4 |  |
| `src/chat/agent_loop.py` | 1 | 2 | 3 | 2 |  |
| `core/auth.py` | 1 | 1 | 3 | 2 |  |
| `routes/email_routes.py` |  | 3 | 5 | 4 |  |
| `routes/cookbook_routes.py` |  | 4 | 5 | 2 |  |
| `mcp_servers/email_server.py` |  | 2 | 4 | 3 |  |
| `routes/document_routes.py` |  | 2 | 4 | 3 |  |
| `routes/calendar_routes.py` |  | 1 | 4 | 4 |  |
| `src/actions/builtin.py` |  | 1 | 6 | 1 |  |
| `routes/email_helpers.py` |  | 1 | 3 | 4 |  |
| `routes/skills_routes.py` |  | 2 | 5 | 1 |  |
| `routes/session_routes.py` |  | 2 | 3 | 3 |  |
| `src/tools/execution.py` |  | 3 | 3 | 1 |  |
| `app.py` |  | 2 | 3 | 2 |  |
| `src/agent/ai_interaction.py` |  | 1 | 3 | 3 |  |
| `routes/chat_helpers.py` |  | 2 | 4 | 1 |  |
| `routes/contacts_routes.py` |  | 2 | 2 | 3 |  |
| `routes/email_pollers.py` |  | 3 | 2 | 1 |  |
| `core/database.py` |  | 2 | 3 | 1 |  |
| `src/llm_core.py` |  | 1 | 2 | 3 |  |
| `routes/chat_routes.py` |  | 2 | 2 | 2 |  |
| `core/platform_compat.py` |  | 1 | 3 | 2 |  |
| `src/runtime/endpoint_resolver.py` |  | 1 | 2 | 3 |  |
| `src/uploads/handler.py` |  | 2 | 2 | 2 |  |
| `src/research/handler.py` |  | 2 | 3 |  |  |
| `routes/mcp_routes.py` |  | 1 | 3 | 1 |  |
| `routes/auth_routes.py` |  | 1 | 2 | 2 |  |
| `services/research/research_handler.py` |  | 1 |  | 2 | 2 |
| `scripts/diffusion_server.py` |  | 2 | 1 | 2 |  |
| `src/scheduling/bg_jobs.py` |  | 1 | 3 | 1 |  |
| `src/tools/implementations.py` |  | 2 | 2 |  |  |
| `scripts/pr_blocker_audit.py` |  | 1 | 1 | 2 |  |
| `services/memory/memory_extractor.py` |  | 2 | 1 | 1 |  |
| `src/calendar_app/sync.py` |  | 2 | 2 |  |  |
| `routes/upload_routes.py` |  | 2 | 2 |  |  |
| `mcp_servers/rag_server.py` |  | 1 | 2 | 1 |  |
| `core/session_manager.py` |  | 2 | 1 | 1 |  |
| `src/vector/embedding_lanes.py` |  | 1 | 2 | 1 |  |
| `routes/docker_ollama.py` |  | 1 | 2 | 1 |  |
| `routes/task_routes.py` |  | 1 | 1 | 1 |  |
| `services/hwfit/hardware.py` |  | 2 | 1 |  |  |
| `src/clients/webhook_manager.py` |  | 1 | 2 |  |  |
| `src/clients/mcp_manager.py` |  | 1 | 2 |  |  |
| `routes/vault_routes.py` |  | 1 | 1 | 1 |  |
| `src/tools/index.py` |  | 1 | 2 |  |  |
| `src/memory/store.py` |  | 1 | 1 | 1 |  |
| `src/chat/model_context.py` |  | 1 | 1 | 1 |  |
| `services/youtube/youtube_handler.py` |  | 1 | 2 |  |  |
| `routes/history_routes.py` |  | 1 | 1 | 1 |  |
| `routes/personal_routes.py` |  | 1 | 1 | 1 |  |
| `core/atomic_io.py` |  | 1 | 1 | 1 |  |
| `services/memory/skill_importer.py` |  | 1 | 1 | 1 |  |
| `routes/admin_wipe_routes.py` |  | 1 | 1 | 1 |  |
| `src/scheduling/bg_monitor.py` |  | 1 | 1 | 1 |  |
| `src/clients/api_key_manager.py` |  | 1 | 1 | 1 |  |
| `services/search/content.py` |  | 1 | 1 | 1 |  |
| `src/misc/cleanup_service.py` |  | 1 | 2 |  |  |
| `routes/background_routes.py` |  | 1 | 1 | 1 |  |
| `src/vector/memory_vector.py` |  | 1 | 2 |  |  |
| `app_setup.py` |  | 1 | 1 |  |  |
| `src/scheduling/cookbook_serve_lifecycle.py` |  | 1 |  | 1 |  |
| `src/chat/handler.py` |  | 1 |  | 1 |  |
| `src/chatgpt_subscription.py` |  | 1 |  | 1 |  |
| `src/misc/session_search.py` |  | 1 |  | 1 |  |
| `src/vector/rag_vector.py` |  | 1 | 1 |  |  |
| `routes/api_token_routes.py` |  | 1 |  | 1 |  |
| `services/shell/service.py` |  | 1 | 1 |  |  |
| `src/documents/processor.py` |  | 2 |  |  |  |
| `services/tts/tts_service.py` |  | 1 | 1 |  |  |
| `services/memory/service.py` |  | 1 | 1 |  |  |
| `scripts/claim_ownerless.py` |  | 1 |  | 1 |  |
| `routes/backup_routes.py` |  | 1 | 1 |  |  |
| `src/security/url_safety.py` |  | 1 | 1 |  |  |
| `routes/device_flow.py` |  | 1 |  |  |  |
| `src/chat/processor.py` |  | 1 |  |  |  |
| `src/youtube/handler.py` |  | 1 |  |  |  |
| `src/clients/copilot.py` |  | 1 |  |  |  |
| `routes/copilot_routes.py` |  | 1 |  |  |  |
| `integrations/codex/scripts/atenea_api.py` |  | 1 |  |  |  |
| `services/stt/stt_service.py` |  | 1 |  |  |  |
| `src/tools/security.py` |  | 1 |  |  |  |
| `routes/chatgpt_subscription_routes.py` |  | 1 |  |  |  |
| `src/memory/provider.py` |  | 1 |  |  |  |
| `services/search/service.py` |  | 1 |  |  |  |
| `scripts/cleanup_stale_model_endpoints.py` |  | 1 |  |  |  |
| `routes/search_routes.py` |  | 1 |  |  |  |
| `routes/stt_routes.py` |  | 1 |  |  |  |
| `routes/shell_routes.py` |  |  | 5 | 5 |  |
| `routes/model_routes.py` |  |  | 3 | 4 |  |
| `routes/note_routes.py` |  |  | 4 | 3 |  |
| `routes/research_routes.py` |  |  | 3 | 3 |  |
| `routes/ollama_routes.py` |  |  | 2 | 3 |  |
| `src/integrations/registry.py` |  |  | 2 | 3 |  |
| `src/runtime/model_discovery.py` |  |  | 4 | 1 |  |
| `scripts/demo_email/seed_demo_emails.py` |  |  | 1 | 3 |  |
| `routes/codex_routes.py` |  |  | 2 | 1 |  |
| `scripts/hf_local_openai_server.py` |  |  | 2 | 1 |  |
| `routes/memory_routes.py` |  |  | 2 | 1 |  |
| `src/runtime/config.py` |  |  | 2 | 1 |  |
| `src/scheduling/event_bus.py` |  |  | 2 | 1 |  |
| `src/research/topic_analyzer.py` |  |  | 1 | 2 |  |
| `src/tools/schemas.py` |  |  | 1 | 1 |  |
| `routes/webhook_routes.py` |  |  | 2 |  |  |
| `routes/embedding_routes.py` |  |  | 1 | 1 |  |
| `mcp_servers/image_gen_server.py` |  |  | 2 |  |  |
| `src/research/deep.py` |  |  | 1 | 1 |  |
| `services/memory/skills.py` |  |  | 1 | 1 |  |
| `services/search/core.py` |  |  | 1 | 1 |  |
| `src/personal/docs.py` |  |  | 1 | 1 |  |
| `scripts/add_hwfit_models.py` |  |  | 1 | 1 |  |
| `src/chat/helpers.py` |  |  | 1 | 1 |  |
| `src/settings.py` |  |  | 1 | 1 |  |
| `src/calendar_app/writeback.py` |  |  | 1 | 1 |  |
| `routes/compare_routes.py` |  |  | 1 | 1 |  |
| `src/clients/mcp_oauth.py` |  |  | 2 |  |  |
| `src/chat/context_compactor.py` |  |  | 1 | 1 |  |
| `companion/pairing.py` |  |  | 1 | 1 |  |
| `src/misc/session_actions.py` |  |  | 1 | 1 |  |
| `src/agent/runs.py` |  |  | 1 | 1 |  |
| `routes/emoji_routes.py` |  |  | 1 | 1 |  |
| `routes/assistant_routes.py` |  |  | 1 | 1 |  |
| `src/security/url_security.py` |  |  | 2 |  |  |
| `src/security/secret_storage.py` |  |  | 1 | 1 |  |
| `services/search/analytics.py` |  |  | 2 |  |  |
| `services/search/cache.py` |  |  | 2 |  |  |
| `src/vector/chroma_client.py` |  |  | 1 | 1 |  |
| `src/vector/rag_singleton.py` |  |  | 1 | 1 |  |
| `routes/cookbook_helpers.py` |  |  | 1 |  |  |
| `src/tools/parsing.py` |  |  | 1 |  |  |
| `src/documents/pdf_form_doc.py` |  |  | 1 |  |  |
| `integrations/claude/skills/atenea/scripts/atenea_api.py` |  |  | 1 |  |  |
| `routes/preset_routes.py` |  |  | 1 |  |  |
| `mcp_servers/memory_server.py` |  |  | 1 |  |  |
| `src/preset_manager.py` |  |  | 1 |  |  |
| `scripts/repair_stale_session_endpoints.py` |  |  | 1 |  |  |
| `routes/prefs_routes.py` |  |  | 1 |  |  |
| `core/cache.py` |  |  | 1 |  |  |
| `services/hwfit/profiles.py` |  |  | 1 |  |  |
| `src/actions/document.py` |  |  | 1 |  |  |
| `src/misc/rate_limiter.py` |  |  | 1 |  |  |
| `src/vector/embeddings.py` |  |  |  | 4 |  |
| `routes/image_routes.py` |  |  |  | 2 |  |
| `services/search/providers.py` |  |  |  | 2 |  |
| `routes/signature_routes.py` |  |  |  | 2 |  |
| `src/runtime/app_helpers.py` |  |  |  | 2 |  |
| `src/agent/teacher_escalation.py` |  |  |  | 1 |  |
| `scripts/demo_email/demo_account.py` |  |  |  | 1 |  |
| `services/hwfit/models.py` |  |  |  | 1 |  |
| `src/clients/builtin_mcp.py` |  |  |  | 1 |  |
| `routes/editor_draft_routes.py` |  |  |  | 1 |  |
| `src/documents/pdf_forms.py` |  |  |  | 1 |  |
| `routes/hwfit_routes.py` |  |  |  | 1 |  |
| `scripts/hf_download.py` |  |  |  | 1 |  |
| `services/docs/service.py` |  |  |  | 1 |  |
