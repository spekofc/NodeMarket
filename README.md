<img width="738" height="743" alt="{A7551770-6967-49BA-BDA9-DA9A92BAFD79}" src="https://github.com/user-attachments/assets/202ba930-eacb-43d1-9f1b-e7f68c740d74" />


# NodeMarket

A privacy-first, dependency-light e-commerce engine for independent stores.
Runs on Python + FastAPI + SQLite, renders pure HTML5/CSS, and ships with
**zero required JavaScript** on the storefront — everything (catalog, cart,
checkout, account-free ordering) works in the strictest browser security
modes, including Tor Browser at its highest security level.

## Screenshots

<img width="1875" height="947" alt="{D8E89270-A637-4F8B-8D51-160FC8B85DA1}" src="https://github.com/user-attachments/assets/68d77b67-2098-4c30-a3c0-6c708fed6920" />

<img width="1877" height="943" alt="{70584371-D688-4722-8036-C507ECC5E9D3}" src="https://github.com/user-attachments/assets/53ad0e1d-bd01-445c-8e7f-73789c26c0d3" />


## Philosophy

- **Privacy-first, not privacy-decorated.** There is no analytics, no
  external CDN, no Google Fonts, no third-party calls, and no IP logging
  anywhere in the codebase. Access logging is disabled at the server level.
- **Zero-JS storefront.** Navigation, cart (signed HttpOnly cookie) and
  checkout are plain HTML forms with CSS. `script-src 'none'` is declared in
  the CSP so the site states its own no-script policy.
- **Data encrypted at rest by default.** Buyer delivery details are encrypted
  with the store owner's PGP public key *before* being written to the
  database. The server cannot read them — only the owner, with their private
  key, can.
- **Modular payments.** A small provider interface with two built-in
  providers: a clean `demo` mode and a self-contained `xpub` mode that
  derives a unique native-SegWit (P2WPKH/bech32) Bitcoin address per order
  via BIP32 — implemented in pure stdlib, no network calls.
- **Minimal stack.** Python 3.11+, FastAPI, Jinja2, SQLite. One `pip install`,
  one command to run.

## Install & run

```bash
git clone https://github.com/spekofc/NodeMarket
cd NodeMarket

python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows (PowerShell):
#   .venv\Scripts\Activate.ps1

pip install -r requirements.txt

cp .env.example .env
#   edit .env: set SECRET_KEY and ADMIN_PASSWORD

python run.py
```

Open `http://127.0.0.1:8000`.

<img width="1873" height="941" alt="{30858F48-15ED-4F28-B260-E70B08B7399F}" src="https://github.com/user-attachments/assets/f4e3da89-cd0c-4f30-bb1e-7283e323a18c" />


### First run as a store owner

1. Sign in at `/admin` with `ADMIN_PASSWORD`.
2. Go to **Settings**: set the store name, paste your ASCII-armored **PGP
   public key**, and choose the payment provider (`demo` or `xpub` + your
   account-level xpub).
3. Add products under **Products**.
4. At checkout, buyer delivery details are PGP-encrypted automatically. View
   orders in the admin panel as ciphertext and decrypt them locally:

```bash
gpg --decrypt buyer-order.txt
```

## Security model

| Layer | Behavior |
|---|---|
| CSP | `default-src 'self'; script-src 'none'; frame-ancestors 'none'` |
| Referrer | `no-referrer` (header and meta) |
| Framing | `X-Frame-Options: DENY` |
| CSRF | SameSite=Lax cookies + cross-origin POST rejection (Origin check) |
| Sessions | itsdangerous-signed cookies, HttpOnly, SameSite=Lax |
| Admin auth | constant-time password comparison, 12h signed session |
| Captcha | self-hosted, zero-JS SVG challenge on admin login and checkout; answer lives only in process RAM, keyed by a single-use signed token with 5-minute expiry; no database state |
| JS detector | pure-CSS banner visible only when JavaScript is enabled (hidden via `<noscript><style>`), fully compatible with `script-src 'none'` |
| Rate limiting | in-memory sliding window on admin login, checkout and captcha routes; client addresses never touch disk or logs; automatic bucket sweep |
| Buyer data | PGP-encrypted before persistence; fail-closed checkout without a valid key |
| Logging | none — access log disabled, nothing about the requester is stored |

Out of scope by design (documented, not hidden): the CAPTCHA and rate-limit
stores are per-process (single uvicorn process; scale out behind a reverse
proxy if needed), no DDoS protection, no JavaScript-free image handling
beyond static files.

## Attribution / Forks

NodeMarket is AGPL-3.0. Forks and derived storefronts must keep the footer
attribution and preserve the same license. Please keep a visible link back:

```html
Powered by <a href="https://github.com/spekofc/NodeMarket" target="_blank" rel="noopener noreferrer">NodeMarket</a>
```

Badge for your README:

```markdown
[![Based on NodeMarket](https://img.shields.io/badge/based%20on-NodeMarket-0a5d3c)](https://github.com/spekofc/NodeMarket)
```

## Disclaimer

NodeMarket is a neutral, general-purpose software tool for operating an
electronic storefront. It is intended exclusively for lawful e-commerce and
data protection use. The authors are not responsible for how the software is
deployed or used. No party should use it where doing so would violate
applicable law.

## License

AGPL-3.0 — see [LICENSE](LICENSE).
