# SignalDesk 1.1 verification record

23 October 2026. Main product: [analytics.subschool.us](https://analytics.subschool.us); shared-data [RU mirror](https://analytics.subschool.ru). [Case criteria and review scenarios](CASE_CRITERIA.md).

## What changed after hands-on feedback

Registration now gates both product routes and workspace APIs until a one-time email confirmation. The inbox screen supports resend, cross-browser confirmation and continuation of an email-bound invitation. Confirmed regions resolve stale geography questions from website extraction.

The public tour uses a separate guest cookie, viewer permissions and explicit register/sign-in actions. It cannot change profiles, sources, roles, invitations, bookmarks or models, spend model tokens, export workspaces or read team emails/raw datasets. Exploring it preserves an existing signed-in product session. The password-authenticated jury account sees the same three genuine review workspaces with full product permissions. Published review spaces are visibly identified; new ordinary workspaces remain private.

Runtime synthetic demo generation and the fixed source-recommendation catalogue were removed. The generator lives only in `backend/tests/fixtures.py`, excluded from the production image. Prior release demo records remain identifiable in an existing database and are inaccessible to the current public tour. Tests use controlled fixtures; live validation uses real websites, publisher feeds, case research and approved models.

## Automated and live evidence

- Backend: **45 passing tests** cover tenant and role boundaries, strict email gate, cross-browser email-bound invitation continuation, separate guest/product/admin sessions, guest mutation/team/dataset restrictions, SSRF and numeric-IP pinning, credential redaction, profile versioning, stale-unknown reconciliation, real-source discovery validation/cache invalidation, stale promotional feed rejection, future-publication exclusion, record-identity protection, source diversity, unsupported event/brief/assistant withholding, bank provenance, reporting windows, schedules and mail language.
- Vue/TypeScript: production type check and Vite build pass. Main bundle is about 160 kB / 60 kB gzip; charts and routes load separately.
- Deterministic browser checks cover the guest/jury boundary, evidence/bookmarks, research and trace, email verification/onboarding, invitation/viewer access, Russian mobile reflow and independent operations.
- A full real-model browser replay passed **14 groups in 250 seconds**, including actual website extraction, publisher discovery, collection, interpretation and all three brief periods, with no browser runtime errors. That baseline used Qwen for generation/checking. The final Qwen + Gemma replay also passed all **14 groups in 293 seconds**. The genuine review-workspace preparation additionally exercised the new checker.
- Public HTTPS smoke: **8 groups passed**, covering both domains, language rules, jury/owner/independent administrator sign-in, shared genuine workspaces, guest mutation restrictions, session preservation, security headers and secure cookies.
- Manual Codex internal-browser review covers the inbox gate/direct-route block, guest restrictions, ordinary jury sign-in, genuine case evidence, EduHub sources/signals/briefs and grounded follow-up questions. Actual screenshots are documented in [DESIGN_AUDIT.md](DESIGN_AUDIT.md).

Reproduce with:

```bash
.venv/bin/python -m pytest backend/tests -q
npm run build --prefix frontend
node scripts/e2e.mjs
RUN_LIVE_E2E=true node scripts/e2e.mjs
PYTHONPATH=backend .venv/bin/python scripts/report_review_quality.py
node scripts/smoke_deployed.mjs
```

Live runs consume the provided gateway allowance. Development/CI mail is disabled and synthetic addresses are suppressed. The upstream Starlette TestClient deprecation warning is non-blocking. Local live QA can use an isolated database and API/Vite ports (`DATABASE_URL`, `PUBLIC_URL`, `ALLOWED_ORIGINS`, `API_PROXY`, `VITE_PORT`, `E2E_URL`) to avoid mixing controlled browser fixtures with genuine review data.

## Source and analysis findings

The source-discovery job builds queries from reviewed industry/markets, attempts actual public indexes, researches publisher websites, discovers advertised feeds, collects sample publications and ranks only verified source IDs. It records provider/query, original page, headlines, verification time and coverage gaps. No named outlet is a universal fallback. GDELT TLS timeouts, challenged web search and publisher robots restrictions occurred during testing and were preserved as diagnostics, never bypassed. Model-proposed homepages remain explicitly labelled unverified leads until actual collection succeeds.

EduHub's reviewed markets are the United States and Australia. The resulting monitoring includes actual US specialist reporting and The Educator K/12's Australian RSS. The latter was found and verified during manual source research and is labelled accordingly; it is not a hardcoded recommendation for new users. Automatic discovery can still report an Australian coverage gap instead of inventing a source. A 2023 promotional/testimonial feed was rejected. Future webinar dates were found in a working publisher RSS and excluded from current-news selection. A diversified batch prevents one high-scoring publisher from occupying every slot when other relevant publishers exist.

A live SubSchool run exposed a schema mismatch: the model returned exact confirmed exposure values while the validator accepted field keys only. Both exact values and keys now resolve to real confirmed fields; invented values still fail. Unconfirmed customer geography caps evidence confidence and adds an explicit applicability check. Loan presence is never proof of floating-rate terms; a rate hold does not itself prove increased debt payments.

The checked current dataset contains **19 CEO signals and 4 CFO signals**: SubSchool 3/3, EduHub 15/0, and the case client 1/1. Source checks returned 12+12 items for SubSchool, 12/10/12/2 for EduHub, and 14 CBR releases for the case client. Day/week/month brief evidence counts are **0/1/3**, **1/6/15**, and **1/1/1** respectively. These are actual observed counts, not fabricated quality scores.

The genuine manufacturing workspace uses client **U_88715**, electrical-equipment manufacturing in Moscow, reported revenue about RUB 25.46bn, credit and leasing indicators from the supplied case subset. The public company identity/website, fixed/floating terms and maturities remain unknown. Its actual collected CBR release and financing analysis cite the original dated Alfa policy-rate report with an exact page-specific quote. Education events explicitly state when no directly supporting bank excerpt was verified.

The approved **Qwen 35B-A3B** generates interpretations. Live review found that its self-checker sometimes rejected honest conditional statements as facts, preventing useful briefs. The independent checker now uses the smaller approved **Gemma 26B-A4B** through the same supplied gateway. Custom private endpoints use their chosen model. Both model IDs, purposes, tokens, latency and status are recorded; retry usage is accumulated. No external named model provider or ready-made autonomous agent was added.

Events retain their original article, reviewed company snapshot/version and decision role. Briefs use 24h/7d/30d publication windows, cite actual event IDs, preserve uncertainty and undergo independent content review plus one bounded correction. Empty windows produce an explicit coverage brief. A new-signal notice identifies an older edition; failed generation unlocks retry instead of leaving the button busy. A successful retry supersedes its old failure banner.

The assistant uses short evidence aliases, resolves citations server-side, checks answers independently and repairs once. The check specifically rejects applying a US-only funding program to Australia without local evidence. Honest coverage gaps and conditional reporting tests remain valid responses. Unsupported answers are withheld rather than saved as established analysis.

## Genuine review dataset and limitations

`prepare_live_review.py` creates actual SubSchool, EduHub and case-client workspaces, including CEO/CFO interpretations where prepared and day/week/month briefs. `report_review_quality.py` inspects current versions, source health, publication windows, exact bank quotes and calibrated summaries. Its ignored report is `output/quality/revision-review.json`; the live browser record is `output/quality/revision-live-e2e.json` and screenshots are under `output/revision-audit/`. The private import bundle and jury password are owner-only local files, never Git contents. Preparation is idempotent; API/network failures do not fabricate replacement events.

These reviewed runs establish reproducibility and expose specific defects; they are not a statistically measured accuracy benchmark. Some publisher access can fail between runs, sparse windows can be empty, OCR can be imperfect and future model outputs can still require correction. The product records those limits and preserves original sources for inspection.

## Deployment and email

Both HTTPS domains use the same persisted application through main Caddy and the RU Nginx/VPN route. CI gates deployment; the deployment script also verifies that test fixtures and the legacy demo generator are absent from the runtime container. Archive-upload residue from the earlier release is explicitly removed. The current revision is returned by `/api/health`. SQLite has daily same-host backups retaining 14 snapshots. Distributed workers, off-site recovery and a device/accessibility lab remain production follow-up work.

The SendPulse sender and OAuth were verified in the original release; an owner verification message was accepted by the service. Inbox delivery/read status is not claimed. Alerts/brief delivery require a verified user and explicit opt-in. No test mail was sent to an unrelated person. The repository remains private without GitHub jury access, as the owner requested after the paid-seat restriction; app jury access is separate.

## Ongoing quality process

Daily: inspect failed/withheld runs, source freshness and coverage, outbox failures, gateway usage and latency. Weekly: a business expert and analyst label fresh held-out news across industries and CEO/CFO/treasury roles. Score factual support, company/role fit, geographic assumptions, bank attribution, causal usefulness and action specificity on a 0–2 rubric; mark invented company facts or bank quotes separately. Track precision@5, valid-citation rate, unsupported-claim rate, coverage/age and reviewer agreement with numerator/denominator, including withheld and empty runs. Compare usefulness feedback to originals. Before model/prompt/source changes, replay fixed regressions plus fresh cases and retain model/release/profile/source records. No fabricated expert-score metric is populated in the dashboard.
