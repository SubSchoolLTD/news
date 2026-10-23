# Third-party notices and data provenance

## Software

Versions and transitive dependencies are fixed in the Python requirements and npm lock file. Upstream license files remain part of the installed packages.

| Component | Role | Upstream / license |
|---|---|---|
| Python | API and worker runtime | https://www.python.org/ · PSF |
| FastAPI / Starlette / Uvicorn | HTTP API and server | https://fastapi.tiangolo.com/ · MIT / BSD |
| SQLAlchemy | Persistence | https://www.sqlalchemy.org/ · MIT |
| SQLite | Single-host persistent database | https://sqlite.org/ · public domain |
| httpx / httpcore | Outbound HTTP and checked network sockets | https://www.python-httpx.org/ · BSD |
| Beautiful Soup / feedparser | HTML and RSS/Atom extraction | https://www.crummy.com/software/BeautifulSoup/ · MIT; https://feedparser.readthedocs.io/ · BSD |
| pypdf | PDF text and source extraction | https://pypdf.readthedocs.io/ · BSD |
| argon2-cffi / cryptography | Password hashing and private-credential encryption | https://argon2-cffi.readthedocs.io/ · MIT; https://cryptography.io/ · Apache-2.0 / BSD |
| Vue / Vue Router / Vite | Product and admin interfaces | https://vuejs.org/ · MIT |
| Chart.js | Calculated visualisations | https://www.chartjs.org/ · MIT |
| Lucide | Interface icons | https://lucide.dev/ · ISC |
| Playwright / pytest | Verification | https://playwright.dev/ · Apache-2.0; https://pytest.org/ · MIT |
| Tesseract / tessdata_fast / Pillow | Offline OCR preparation of the scanned case research | https://github.com/tesseract-ocr · Apache-2.0; https://python-pillow.org/ · HPND |
| Caddy / Nginx / Docker | Deployment and RU proxy | https://caddyserver.com/ · Apache-2.0; https://nginx.org/ · BSD; https://www.docker.com/ |

The visual tokens and product patterns were adapted with the repository owner's authorisation from the SubSchool teacher/student application: purple primary, neutral surfaces, system typography and rounded cards. No SubSchool accounts or application/customer data were copied.

## Models and services

The default model route is the hackathon's provided gateway, using only its approved IDs: `google/gemma-4-26b-a4b-it`, `z-ai/glm-5.3-flash`, `qwen/qwen3.6-35b-a3b`, `deepseek/deepseek-v4.1-flash`, `qwen/qwen3-vl-30b-a3b-instruct`, `moonshotai/kimi-k2.6`. The default generator is Qwen; independent verification uses the approved Gemma 26B-A4B through the same supplied gateway. Model services and licenses are provided through the organiser's gateway; weights are not distributed here.

SendPulse supplies OAuth and transactional email delivery. The main and mirror servers, DNS and existing VPN are supplied by the project owner. The generic private-model form is a configurable HTTP adapter, not an integration with any additional named model provider.

No external autonomous AI service, ready-made agent or multi-agent framework is part of the runtime solution. Planning, tool selection/execution, source processing, BM25 retrieval, relevance scoring, verification and bounded revision are implemented in this repository.

## Case materials

The owner supplied the case PDF and API instructions. The PDF linked these resources:

- Bank research: https://drive.google.com/drive/folders/15xZTLF1lZ65p6o5xpNA_fRbxjoV-UlG1
- Anonymised companies, physical-person links and payments: https://drive.google.com/drive/folders/1Ep8wWoEHTg5Q8kwrLx2j_xFyxGUEVxFq

`data/bank/*.json` preserves each source URL, the original PDF SHA-256, OCR text and page boundaries. The nine provided research files are: Russian steels (15 April 2021), macro statistics 7M26, consumption, the 11 September 2026 policy-rate review, macro statistics 1H26, tactical bond strategy 3Q26, gold digest August 2026, inflation tracker 2 September 2026, and bond brief 14 September 2026. The gold digest is dated to its reporting month, not an asserted publication day.

`data/demo_clients.csv` and `data/demo_payments.csv` are a small subset of the case's anonymised data, retained only to reproduce import and company-feature analysis. Synthetic IDs do not identify a real company or individual. The full downloaded data and original PDFs are not checked into Git.

## Runtime and test boundaries

- The public tour reads actual collected publications and approved-model analyses in owner-selected review workspaces. A password-authenticated jury account accesses the same data with working product permissions.
- Synthetic company/event generators are test fixtures only (`backend/tests/fixtures.py`), excluded from the production image. Earlier release demo records retain their labels in persisted databases; the current tour cannot access those legacy synthetic workspaces.
- `/alfa-business` provides an interactive banking prototype with a persistent shell across company selection, insight feed, research and briefs, using genuine product data. It does not claim bank-account, balance, payment, banking SSO or transaction connectivity.
- Source discovery uses GDELT DOC 2.0 (https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/), DuckDuckGo public HTML search and MediaWiki's public API (https://www.mediawiki.org/wiki/API:Search). Public publisher leads are inspected and verified; no search challenges are bypassed. Publisher robots policies apply. Headlines, dates and original URLs are retained as evidence, not claimed as original reporting by SignalDesk.
- Email delivery is disabled in development/CI and suppressed for synthetic test addresses. Production uses the real SendPulse integration.
- There is no simulated result used as a fallback for a failed live analysis. Failed or unsupported analysis is shown as such.

The owner also supplied the 74-item webinar Q&A Markdown. Its field semantics inform CSV normalization, qualified payment/group context and analysis attribution. It does not supply a numerical scoring rubric. The accompanying video was not separately transcribed.
