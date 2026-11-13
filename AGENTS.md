# AGENTS.md — conventions for AI coding assistants (and humans who read code)

This file tells AI assistants (Copilot, Claude, OpenCode, forks' agents…)
how NodeMarket is built so generated code matches the house style on the
first try. Humans are welcome too.

## What NodeMarket is

A privacy-first, zero-JS e-commerce storefront in Python. Buyers place
orders in BTC/XMR (or a demo provider); delivery details are PGP-encrypted
before touching SQLite. Designed to run behind Tor or TLS as the operator
chooses.

## Hard rules (violations will be reverted)

1. **No JavaScript.** Anywhere. No `<script>`, no `on*=` attributes, no
   bundler, no CDN. All interactions are HTML forms/links; responses are
   full-page renders.
2. **No tracking.** No request/access logging, no IP capture, no analytics,
   no external requests at runtime. `access_log=False` is deliberate.
3. **Buyer plaintext never persists.** Delivery details go through
   `app/pgp.py` (`encrypt_for_store` or validated BYO blocks) before any
   INSERT. Fail closed: if encryption cannot happen, return 400 and create
   nothing. Never 500, never store raw text.
4. **Zero new heavyweight dependencies.** The stack is FastAPI, Jinja2,
   PGPy, uvicorn. Stdlib first.

## Architecture map

```
app/
  config.py       # stdlib .env parser + os.environ, Settings singleton
  db.py           # sqlite3, row_factory=Row, schema + idempotent _MIGRATIONS
  pgp.py          # encrypt_for_store / validate_public_key / validate_pgp_message
  pgp_compat.py   # imghdr shim for PGPy on py3.13+; import before PGPy
  security.py     # signed cookie cart, admin session, OriginCheck, CSRF posture
  captcha.py      # SVG math captcha, in-memory single-use tokens
  ratelimit.py    # in-memory sliding window: admin_login 5/min, checkout 10/min, captcha 30/min
  templating.py   # Jinja2 env + money filter; injects `settings`/`store_name` for every template
  main.py         # app assembly, security headers (script-src 'none'), middleware
  routers/
    catalog.py    # storefront (?q=&category=slug), product detail, cart
    checkout.py   # THE buyer-data entry point: captcha → PGP → INSERT
    admin.py      # login/orders/products/categories/settings
    customize.py  # v0.7 visual customizer: theme, layout, identity, nav, custom pages
    public_pages.py # /page/<slug> renderer for customizer pages
    account.py    # (if present) order tracking by token
  payments/
    providers.py  # demo/btc/xmr provider selection
    xpub.py       # BIP32 xpub derivation (per-order child addresses)
    core_rpc.py   # Bitcoin Core RPC via urllib
    monero_rpc.py # monero-wallet-rpc via urllib
    escrow.py     # state machine: TRANSITIONS, buyer release, dispute flow
static/           # only local files: css, favicon package, webmanifest
tools/            # test suites (stdlib-only, hit http://127.0.0.1:8000)
```

## Style

- Python 3.12+. Type hints on public functions. 4-space indent.
- `snake_case` functions/variables; SQL in lowercase keywords, uppercase
  types as here.
- DB access through `app.db.query` / `app.db.execute` (sqlite3, Row dicts).
  No ORM. Add schema changes to BOTH the CREATE TABLE block and
  `_MIGRATIONS` in `app/db.py` (old databases upgrade in place).
- Templates: Jinja2, extend `base.html` (storefront) or `admin/base.html`.
  Never invent template globals; `settings` (the `store_settings` row) and
  `store_name` are injected automatically by `app/templating.py`
  (`NodeMarketTemplates`), so `base.html` can always read them — do not
  re-pass them per route.
- Error handling: return rendered error pages with proper status codes;
  never let exceptions carry buyer text.

## Testing discipline

- Every suite in `tools/test_*.py` expects a **fresh** DB and a **fresh**
  server on `127.0.0.1:8000`; they are run one at a time.
- Tests are stdlib-only (`urllib`, `http.cookiejar`, `sqlite3`) — no pytest.
  Output convention: `OK`/`FAIL name` lines and an `n/m checks passed`
  summary; exit 1 on any failure.
- Captcha is solved by parsing the SVG `<text>` nodes (`^(\d+)\s*([+\-])\s*(\d+)$`).
- Admin test password: `changeme-admin`.
- Watch rate limits when writing new tests: POST `/checkout` 10/min,
  POST `/admin/login` 5/min.

## pgpy gotchas (learned the hard way)

- `PGPMessage.new(armored_string)` treats the armor as **literal payload**.
  To parse ciphertext: `msg = PGPMessage(); msg.parse(ct)`.
- `encrypt_for_store` raises on keys without an encryption subkey —
  checkout wraps it and fails closed with 400.
- BYO blocks must be `is_encrypted` (signed-only blocks are rejected).

## Commits

Conventional Commits (`feat|fix|docs|test|refactor|chore(scope): summary`).
Never force-push. PRs keep all `tools/test_*.py` suites green.
