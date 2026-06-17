# PRODUCTIONIZATION.md — from POC to a scaled, IT-owned system

## The handoff this is built for

This repo is a **proof of concept**, built the way a centralized AI team inside a
CFO organization builds them: prove the FP&A value on real (here, public) data, get
it in front of the user, then hand it to **IT/Data Engineering to scale and operate**.
The builders are internal consultants — the lasting contribution is the *FP&A logic
and the guardrails*, not the plumbing. This document is the handoff note: what
survives the transition unchanged, what IT rebuilds, and the non-negotiables that
must not be lost on the way to production.

The guiding split: **the POC owns the "what fits the FP&A user" — the models, the
decompositions, the anomaly rules, and especially the integrity guardrails. IT owns
the "make it live, secure, and reliable" — data feeds, orchestration, access, and
operations.** Most failures in this kind of handoff come from IT optimizing away a
guardrail it didn't realize was load-bearing; the [Guardrails](#guardrails-that-must-survive)
section exists to prevent that.

## What stays vs. what gets rebuilt

| Layer | In the POC | In production | Verdict |
|---|---|---|---|
| **FP&A logic** | `forecast.py`, `backtest.py`, `variance.py`, `anomaly.py` | Same algorithms, same interpretable models | **Stays** — this is the value |
| **Guardrails** | `verify.py` (no-hallucination gate), no-leakage tests, reconciliation, conformal calibration | Same, promoted to request-path + CI gates | **Stays, hardened** |
| **Data source** | static `earnings_extracted.json` + one-off SEC XBRL pull | scheduled feed from the internal data warehouse / ERP / billing system | **Rebuilt** |
| **Ingestion** | manual extraction with evidence quotes | automated pipeline with data contracts + validation gates | **Rebuilt** |
| **Orchestration** | `make pipeline` / run scripts by hand | scheduled DAG (Airflow/Dagster), event-triggered on close & earnings | **Rebuilt** |
| **Storage** | flat CSV/JSON in the repo | warehouse tables + versioned snapshots (point-in-time correctness) | **Rebuilt** |
| **LLM layer** | Anthropic Claude via a thin client, offline fallback | same, behind a gateway with logging, spend caps, key rotation | **Stays, wrapped** |
| **UI** | Streamlit single-file dashboard | same for the analyst tool; an API/embed for downstream consumers | **Stays + extended** |
| **Auth** | none (single user) | SSO + role-based access, audit logging | **Rebuilt** |

## Live data feeds & pipelines

The POC's honesty about provenance becomes a pipeline contract:

- **Replace the static dataset** with a scheduled pull from the system of record (the
  data warehouse fed by the ERP / billing / CRM), not press releases. This unlocks
  **monthly** actuals and true drivers (bookings, pipeline, renewal rates) instead of
  quarterly published figures — turning the RPO regression we shelved into a genuine
  leading-indicator model.
- **Event triggers, not just cron.** Re-run on month-end close and on earnings release.
  A late-arriving restatement re-triggers the affected downstream steps.
- **Data contracts + validation gates.** The reconciliation checks in `ingest.py` /
  `anomaly.py` (segments tie to total, organic + inorganic = total, independent
  cross-check) become **blocking pipeline gates**: a feed that fails reconciliation is
  quarantined and alerts an owner, never silently flows into a forecast. The "leave
  gaps blank, never interpolate" rule becomes a schema constraint.
- **Point-in-time correctness.** Store versioned snapshots so any forecast or variance
  can be reproduced exactly as it was computed (an auditor will ask). This also makes
  the no-leakage guarantee enforceable on live data, not just in the backtest.

## Where the model retrains

- **Cadence:** re-fit each close on the latest history (the models are cheap — seconds,
  not GPU hours — because they're interpretable by design).
- **Promotion gate, not auto-deploy.** A refit is only promoted if it **passes the same
  walk-forward backtest** (still beats the naive baseline, calibration still ~80%). A
  champion/challenger comparison runs the incumbent vs. the refit; regressions block
  promotion. This is the production form of "validate before you trust."
- **Conformal recalibration.** The prediction-band width is re-derived from a rolling
  window of recent out-of-sample residuals, so the interval tracks the model's *current*
  demonstrated error rather than drifting stale.
- **Drift & anomaly monitoring.** A spike in the *volume* of unexplained anomalies, or a
  run of same-signed residuals, is itself an alert — the model may be missing a regime
  change. Human review decides whether to re-spec.
- **Human-in-the-loop on promotion.** An FP&A owner signs off before a new model or a
  generated brief is published. The system drafts and flags; a person owns the number.

## Security & access

Financial forecasts and pre-release actuals are **material non-public information** —
this is the part IT must not get wrong:

- **Access control.** SSO + role-based access (analyst / reviewer / viewer); every view
  and export audit-logged. MNPI scoping so pre-announcement data is restricted.
- **Secrets.** No keys in code or repo. The `ANTHROPIC_API_KEY` (and warehouse creds)
  live in a managed secret store / vault, rotated regularly. The POC already reads the
  key from the environment and never logs it — keep that.
- **The LLM data boundary.** The model only ever receives **computed facts** (a FACTS
  block / a bounded data context), never raw source systems, and **`verify.py` runs in
  the request path** as a hard gate on every generated answer — not as an afterthought.
  Use a no-retention / zero-data-retention configuration with the LLM provider so MNPI
  isn't stored, and log prompts + outputs for audit. Cost controls (per-key spend caps,
  rate limits) sit at the gateway.
- **No training on the financial data.** The data is used for inference and narration
  only; it is never used to train or fine-tune a third-party model.

## Reliability & observability

- **Lineage / provenance.** The POC ties every figure to a filing; production ties every
  figure to a warehouse row + load timestamp, surfaced on demand ("where did this come
  from?" is the first question in any finance review).
- **Monitoring & alerting** on pipeline freshness, reconciliation failures, calibration
  drift, anomaly volume, and verifier rejections.
- **Reproducibility.** Fixed seeds + versioned data snapshots → any output is
  re-derivable. The existing determinism tests become CI checks.
- **Graceful degradation.** The offline mode that lets the POC run with no API key is
  the same pattern that keeps the tool useful if the LLM gateway is down: the computed
  numbers and a template brief still render; only the conversational polish is lost.

## Guardrails that must survive

These are the load-bearing invariants from the POC. **If a production redesign breaks
one of these, the system is no longer trustworthy around financial numbers** — escalate
rather than ship:

1. **No hallucinated numbers.** Every figure in any generated text is mechanically
   cross-checked against the computed source of truth; unverifiable figures are rejected.
   `verify.py` stays in the request path.
2. **Provenance on every input.** No number without a traceable source.
3. **No leakage.** No future data in any training window — enforced by point-in-time
   snapshots and the no-leakage tests.
4. **Calibrated intervals.** The reported band reflects demonstrated out-of-sample error
   (conformal), not the model's optimistic self-assessment.
5. **Interpretability.** Models small enough that every forecast and every anomaly flag
   can be explained to a CFO. No black boxes in the decision path.
6. **Human in the loop.** The system drafts, flags, and decomposes; a person owns the
   judgment and the published narrative.

## Suggested rollout

1. **Lift-and-shadow.** Wire the live data feed; run the pipeline in parallel with the
   current manual FP&A process for 1–2 closes; reconcile outputs. Trust is earned, not
   assumed.
2. **Analyst tool GA.** Release the dashboard to the FP&A team behind SSO once shadow
   results match; keep human sign-off on every published brief.
3. **Broaden + integrate.** Add an API for downstream consumers, extend the model set
   (monthly drivers, bookings), and extend the verifier to qualitative claims.
4. **Templatize.** Generalize the POC from PANW to the next FP&A team — the data
   contracts, guardrails, and the FP&A-user framing are the reusable core.
