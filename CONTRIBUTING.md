# Contributing to NodeMarket

Thank you for helping build a store platform that treats buyer privacy as a
design invariant, not a feature flag. This guide covers setup, testing and
the rules of the codebase.

## Philosophy — read before writing code

Three rules define the project. Any change that weakens one of them will be
rejected regardless of its other merits:

1. **Zero JavaScript.** The storefront must work with `script-src 'none'`.
   No bundlers, no CDNs, no inline scripts. Every interaction is plain HTML
   forms and links; any state that JS would hold lives in signed cookies or
   the database.
2. **Zero tracking.** No request logging, no IP storage, no analytics, no
   external calls at runtime. If a change adds any of these, it will not be
   merged.
3. **Buyer data is encrypted at rest or it does not exist.** Delivery
   details must pass through PGP (`app/pgp.py`) before any persistence,
   and every path must fail closed: when encryption is impossible, the
   order is never created — never stored as plaintext, never 500.

## Development setup

```bash
git clone https://github.com/spekofc/NodeMarket.git
cd NodeMarket
python -m venv .venv
# Windows:
.venv\Scripts\pip install -r requirements.txt
# Linux/macOS:
.venv/bin/pip install -r requirements.txt
```

Run the server (binds 127.0.0.1 by default — safe):

```bash
.venv/Scripts/python run.py     # Windows
.venv/bin/python run.py         # Linux/macOS
```

Admin panel: `http://127.0.0.1:8000/admin` (default password
`changeme-admin` from `.env`; set `ADMIN_PASSWORD` for anything real).

## Test suites

All suites are stdlib-only scripts that talk to a live server on
`127.0.0.1:8000`. **Each suite needs a fresh database and a fresh server
process**:

```bash
# 1. kill stale servers, delete the DB
# Windows PowerShell:
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item data/nodemarket.db* -ErrorAction SilentlyContinue

# 2. start the server
.venv/Scripts/python run.py

# 3. run one suite (new terminal), e.g.
.venv/Scripts/python tools/test_v04.py
```

| Suite | Covers |
|---|---|
| `tools/test_privacy.py` | PGP-before-persistence invariants, fail-closed paths |
| `tools/test_v02.py` | Captcha, rate limiting, JS-banner behavior |
| `tools/test_v03.py` | Multi-currency (BTC/XMR), escrow state machine |
| `tools/test_v04.py` | Categories, storefront search, BYO PGP checkout |

Every PR must keep **all four suites green**. New features come with a new
suite or new checks in an existing one — tests are part of the feature.

## Commit style

[Conventional Commits](https://www.conventionalcommits.org), as used in the
history:

```
feat(v0.4): add Docker support, community governance docs, search, categories and client-side PGP
fix(security): fail closed on unencryptable PGP key; document transport security
fix(brand): include 512px icon, drop old svg favicon
```

- `feat` / `fix` / `docs` / `test` / `refactor` / `chore` as types;
  optional scope in parentheses.
- Never force-push; maintainers rebase-merge.

## Pull requests

- Keep the diff focused: one feature or one fix per PR.
- No new dependencies without a strong reason; the stack is intentionally
  small (FastAPI, Jinja2, PGPy, uvicorn). Prefer stdlib.
- No JavaScript, no external asset URLs, no fonts/CDN references.
- Document operator-facing changes in `README.md`.
- Security-relevant changes should also update the relevant section of
  `SECURITY.md`.

## Reporting vulnerabilities

Please do **not** open public issues for security bugs — see
[SECURITY.md](SECURITY.md) for the responsible-disclosure process.
