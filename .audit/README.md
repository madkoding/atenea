# Atenea code audit — multi-agent review harness

Cost-aware, file-by-file safety / performance / security audit of the Atenea
source tree (253 non-test `.py` files, ~100k LOC), run by a fleet of LLM agents.

## Files

- **`AUDIT_REPORT.md`** — the audit results: executive summary, the critical
  findings up front, six per-domain sections, and a per-file appendix.
- **`findings.json`** — all verified findings, structured, for drill-down/triage.
- **`audit_triage.json`** — every source file scored on static risk signals
  (SQL, subprocess, `shell=True`, secrets, auth, concurrency, blocking-in-async,
  size). Input manifest for the workflow.
- **`audit_workflow.mjs`** — the multi-agent audit workflow.

## How it runs (deterministic static routing — no LLM gate)

The routing decision is made from static risk signals, not by a cheap model.
A cheap gate's false-negatives would become the audit's blind spots, so instead
**every file is reviewed** and the signals only decide *which* model does it.
Sonnet is the floor — nothing is ever dropped by a model's guess.

```
Review      every file reviewed.
            fable  -> genuine high-stakes surface (SQL f-string, shell,
                      subprocess, eval, big hot paths, blocking-in-async)
            sonnet -> the floor for everything else
            sonnet -> tiny files, batched
   |
Verify      every HIGH/CRITICAL finding re-checked by the OTHER model,
            prompted to refute -> kills false positives
   |
Synthesize  6 domain leads (memory-safety, resource-leak, performance,
            security, concurrency, correctness) dedup + group by root cause
```

## Actual run (2026-07-12)

- 253 files reviewed · 50 fable / 159 sonnet / 44 batched · 0 files dropped
- 375 agents, 0 errors
- ~14.4M tokens
- 516 verified findings: 4 critical, 119 high, 223 medium, 168 low, 2 info

## To re-run

Launched via the Claude Code `Workflow` tool with `scriptPath` pointing at
`audit_workflow.mjs` (the triage manifest is embedded in the script). On-demand
review harness — not wired to CI.
