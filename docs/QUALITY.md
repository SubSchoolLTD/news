# SignalDesk verification record

Reviewed on 23 October 2026. The product is deployed at [analytics.subschool.us](https://analytics.subschool.us), with the shared-data [RU mirror](https://analytics.subschool.ru). This is a working, single-host hackathon product; the scope and operational limits are documented in the README.

## Automated checks

| Check | Result | Scope |
|---|---|---|
| Python backend | **30 passed** | Sessions, separate admin realm, tenant and role boundaries, one-time email-bound invitations, profile approval/versioning, SSRF and numeric-IP pinning, origins, credential redaction, retrieval provenance, withheld unsupported events, period windows, citation validation, independent brief schedules, scheduled empty briefs and email language. |
| Vue/TypeScript production build | **Passed** | Type check and Vite build, lazy route chunks. Main bundle approximately 157 kB / 59 kB gzip; charts load separately. |
| Deterministic Playwright | **8 groups passed** | Demo, evidence, bookmarks, notifications, research/trace, RU mobile, onboarding, invites/viewer restrictions, independent operations. Runs in CI without a paid model. |
| Live Playwright | **13 groups passed, 141 seconds** | Approved Qwen, daily/weekly/monthly brief generation, grounded conversation, actual website extraction, live source collection, RAG/interpretation/verification, team UI and operations. No browser runtime errors or horizontal overflow. |
| Public HTTPS smoke | **6 groups passed** | Main and mirror, exact locale rules, equal deployed release, security headers, actual owner and independent admin sign-in, session isolation and Secure/HttpOnly/SameSite cookies. |
| Actual case grounding | **Passed** | Anonymised manufacturing client, actual case bank PDF, selected exact quote and page, explicit unknown debt terms. |

Commands:

```bash
.venv/bin/python -m pytest backend/tests -q
npm run build --prefix frontend
node scripts/e2e.mjs
RUN_LIVE_E2E=true node scripts/e2e.mjs
PYTHONPATH=backend .venv/bin/python scripts/evaluate_case.py
node scripts/smoke_deployed.mjs
```

Live checks consume the supplied gateway budget. The public smoke script checks private sign-ins only when the ignored `.local/ACCESS.md` exists on the owner's machine. It never logs passwords. CI runs a fresh API with email delivery and the worker disabled. One upstream TestClient deprecation warning is present; the tests pass.

The checked source release before the final documentation/localisation update was `0b01babe85e161ed256fd41cdd3b709362b27582`: [CI](https://github.com/SubSchoolLTD/news/actions/runs/39942453526) and [deployment](https://github.com/SubSchoolLTD/news/actions/runs/39942599535) passed. Subsequent commits use the same checks, and deployment runs only after a successful verification of that push. The authoritative current deployment revision is returned by `/api/health` on either domain.

## Analysis reviewed beyond pass/fail assertions

### SubSchool: real website and reporting

The live run read `subschool.us`, then the user-facing flow reviewed industry, priorities, exposures and suggested sources. The final collection retrieved **12 Bank of Russia releases and 12 EdSurge articles**. Three verified signals concerned AI adoption constraints, cost-efficient tutoring after funding changes, and assessment challenges from student AI reliance. Each connected to a concrete SubSchool activity such as lesson generation or grading, rather than merely summarising the article.

The outputs did not assert district contracts or an existing K–12 customer base. They listed those as unknown. No bank excerpt directly supported these education issues, so the event explicitly said that a supporting bank view had not been verified. This is preferable to attaching unrelated macroeconomic analysis. Source availability and each collection error are visible in diagnostics. A regression test also edits source enablement and monitoring preferences while analysis is in progress: the worker now merges only its metadata atomically, preserving those user edits. The open dashboard discovers background runs and refreshes evidence every 30 seconds when idle. Another earlier run exercised rejection/correction and withheld an unsupported draft; deterministic tests verify this behaviour independently of model variability.

### Actual anonymised case client

`scripts/evaluate_case.py` uses the supplied sample client **U_88715**: electrical-equipment manufacturing, Moscow, revenue about RUB 25.46bn, credit and leasing indicators. Evaluation priorities are stated assumptions. The script does not infer a real company identity or claim that the example website belongs to this client.

The approved Qwen produced one supported financing signal. It retrieved **ALFA-Macro_Insights-Policy_Rate_11Sep.pdf**, page 1, and attached an exact quote from the supplied OCR text. The dated bank view reflected the report's expectation of a 14% rate through end-2026. The result preserved fixed/floating terms and actual maturities as unknown. The evaluation script asserts that the cited words exist on the cited page. Historical research is not represented as a fresh October report.

Weak-model testing exposed UUID/reference confusion and rewritten quotes. The implementation now presents short `N1` news and `B1` bank references plus selectable exact quote IDs, then resolves them to persisted IDs itself. Retrieval returns the full relevant page, so conclusions at the bottom of the page are available. Unsupported results remain unpublished after a bounded retrieve/correct/recheck round.

### Briefs

The live replay generated day/week/month briefs from **2 / 5 / 8** in-window events. Dates and references were checked, and the written output was read. The day report prioritised financing and supplier checks; the week connected financing, currency, labour and regulation; the month connected liquidity, supplier resilience, automation and demand scenarios. Actions identify treasury, procurement, sales, legal or finance and include suggested planning horizons. A reader can open the supporting events.

The report states evidence gaps. Quiet periods produce an explicit coverage report without claiming that the market is calm. Generated wording can still sound more urgent than the underlying evidence warrants; the interface identifies it as decision support and exposes the facts, assumptions and sources. These are reviewed examples, not a statistically validated accuracy benchmark or a promise that every future answer is correct.

## Manual interface and design review

The product was walked through in Codex's internal browser on the public deployment: bank entry → overview → event impact → exact bank citation → generated brief → monitoring → model settings → company onboarding. Screenshots were saved before changes and inspected again after fixes. [Design audit and evidence](DESIGN_AUDIT.md).

Separate browser automation checked a 390px Russian mobile viewport, bookmarks, notifications, registration, source setup, an invitation accepted by a second account with viewer restrictions, and separate operations authentication. There were no runtime errors in the successful runs. This is not a full assistive-technology certification or a multi-browser device lab.

## Deployment and email verification

Both HTTPS domains point to the same persisted application through the existing main Caddy and RU Nginx/VPN route. The RU certificate was issued successfully and renewal is configured. A consistent SQLite backup was produced; a daily backup job retains 14 copies. Backups are on the same host/volume, not off-site disaster recovery.

SendPulse OAuth and the configured sender were verified. The owner welcome/verification message was **accepted by SendPulse**, with no retries. Inbox delivery/read status is not claimed. Synthetic recipients are suppressed; business alerts and briefs require a verified account and explicit opt-in. English and Russian authentication email templates, role-matched alerts, and scheduled quiet-period delivery are covered by the backend tests. No test mail was sent to an unrelated person.

## Artifact locations

Local ignored records: `output/playwright/` (screenshots and deterministic/current results), `output/quality/live-e2e.json` (preserved live run), `output/quality/case-grounding.json` (actual case run and evidence), `output/deployed/` (public smoke), and `output/design-audit/` (original browser captures). The selected inspected design screenshots are versioned in `docs/assets/`.

The product key and deployment secrets are in GitHub Actions secrets. Private owner/admin passwords are only in the ignored local handoff and server-side account hashes. They are not in this report, repository history or browser bundles.

## Proposed ongoing quality process

The prototype already records source diagnostics, every agent step, accepted/withheld drafts, model status/tokens/latency and user feedback. Operations exposes usage, failures and feedback. These are observation tools; the example runs above do not establish production-wide precision.

Recommended operating procedure for a rollout:

1. **Each working day:** inspect failed runs, source coverage, outbox failures, gateway consumption and p50/p95 latency. Investigate a sudden increase in source errors, unsupported drafts or empty briefs before lowering a relevance threshold. Separate empty coverage from a quiet market.
2. **Each week:** an analyst and a business-domain reviewer label a sample of fresh, previously unseen news across at least manufacturing, education/services and trade, with CEO/CFO/treasury perspectives. Preserve the reviewed company profile, source text/date, model ID and release. Include ambiguous loan terms, opinion articles, stale bank reports and irrelevant foreign regulation.
3. **Score each output:** factual support, correct company/role connection, honest geography/customer assumptions, bank-attribution accuracy, causal usefulness and actionable specificity, each on a 0–2 rubric. Mark critical factual or bank-attribution errors separately. Report precision@5 for relevance, valid-citation rate, unsupported-claim rate, bank-attribution accuracy, source coverage/age and reviewer agreement. Report both numerator and denominator; do not hide withheld outputs or empty runs.
4. **Connect user feedback:** compare useful/not-relevant ratings by company, industry and decision role, with at least ten labelled items before drawing a segment conclusion. Inspect the reasons with the original evidence; feedback is not permission for a model to invent stronger claims.
5. **Before model/prompt/source changes:** replay a fixed regression set plus a held-out fresh set. Require zero critical invented bank quotes or company facts in that set and compare relevance/utility to the previous release. Keep results and human labels with the release. A model may pass one scenario and fail another, so use the approved case model for this comparison.

Human-labelled precision, utility and reviewer agreement are proposed rollout measurements, not already-populated dashboard statistics. The repository provides reproducible live checks and trace exports to support this process. Distributed load, off-site recovery and a statistically powered content-quality benchmark remain future production work.
