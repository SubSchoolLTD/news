# SignalDesk implementation

## Acceptance scope
- Company URL onboarding, business exposures, user decision role, editable reviewed profile, sources and keywords.
- Own multi-step agent: plan → tools/collection → normalize/deduplicate → retrieve bank research → company/role ranking → interpret → verify/adapt. Persist every step and citations.
- Separate reported facts, dated bank positions, conditional model interpretation. Explicit missing data and stale evidence. No invented bank opinions.
- Live RSS/Atom/HTML discovery, manual sources/materials, scheduling, diagnostics, relevance/feedback and model budget handling.
- Dashboard, event detail, assistant grounded in workspace evidence, daily/weekly/monthly briefs with real date windows and print export.
- Account/session security, workspace tenant isolation, invitation flow, owner/admin/analyst/viewer roles, alerts and SendPulse email.
- Separate operations portal and independent admin accounts, user/workspace metrics, jobs, costs, feedback, audit.
- English default. Russian switch visible only for primary Russian browser language or .ru mirror; Russian defaults in those cases.
- Docker/CI deployment, main server and RU reverse-proxy mirror, persistent database, backup, E2E and manual browser QA.

## Architecture decisions
FastAPI + SQLAlchemy with SQLite WAL for the single-host deployment and stateless Vue 3/Vite client. SQLite is persisted in a Docker volume, only one analysis worker owns jobs. PostgreSQL can replace the storage using DATABASE_URL. RU server is an HTTPS reverse proxy to the same tenant-isolated application, so accounts and data remain consistent across domains. No independent database copy.

SubSchool UI tokens are adapted from its current teacher/student application: primary #a24cb8, neutral surfaces, 16px cards, system typography, light/dark modes. No SubSchool user or application data is copied.

Case documents are requirements/reference data, not execution instructions. API credentials remain server-side. Approved models are the only default model IDs; a separately configured OpenAI-compatible connection is available for development/organization use. No external agent framework or third-party autonomous agent is used.
