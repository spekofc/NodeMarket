<p align="center">
  <img src="docs/logo.png" width="180" alt="NodeMarket logo">
</p>

# NodeMarket

A privacy-first, dependency-light e-commerce engine for independent stores.
Runs on Python + FastAPI + SQLite, renders pure HTML5/CSS, and ships with
**zero required JavaScript** on the storefront — everything (catalog, cart,
checkout, account-free ordering) works in the strictest browser security
modes, including Tor Browser at its highest security level.

## Screenshots

**Storefront** — catalog, categories and search, all plain HTML:

<img src="docs/storefront-preview.png" alt="NodeMarket storefront: catalog with product cards, category filters and search" width="900">

**Visual Customizer** — the v0.7 admin panel, five tabs, zero JavaScript:

<img src="docs/customizer-preview.png" alt="NodeMarket Visual Customizer: identity, theme palette, layout, navigation and custom pages tabs" width="900">

Older captures from a populated test store:

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
- **Modular payments.** A small provider interface with built-in providers:
  a clean `demo` mode, self-contained Bitcoin (`btc`) via xpub BIP32
  derivation or Bitcoin Core RPC, Monero (`xmr`) via store addresses or
  monero-wallet-rpc — plus two configurable settlement modes
  (Direct-to-Seller and Temporary Escrow). See [Payments (v0.3)](#payments-v03).
- **Minimal stack.** Python 3.11+, FastAPI, Jinja2, SQLite. One `pip install`,
  one command to run.

## Install & run

### Quick start (one-click)

**Windows:** double-click `run.bat`

**Linux/macOS:** run `./run.sh`

Both scripts automatically:
- Create `.venv` and install dependencies on first run
- Copy `.env.example` → `.env` if missing (edit `SECRET_KEY` and `ADMIN_PASSWORD`)
- Start the server at `http://127.0.0.1:8000`

### Manual setup

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

### First run as a store owner

1. Sign in at `/admin` with `ADMIN_PASSWORD`.
2. Go to **Settings**: set the store name, paste your ASCII-armored **PGP
   public key**, enable the payment methods you accept (Bitcoin, Monero,
   Demo) and pick the **settlement mode** and **listing policy**. See
   [Payments (v0.3)](#payments-v03) and [Vendor Listings (v0.6)](#vendor-listings-v06) below.
3. Add products under **Products** and group them with **Categories** —
   the storefront gets filter links (`/?category=slug`) and a plain-HTML
   search box (`/?q=`) automatically.
4. At checkout, buyer delivery details are PGP-encrypted automatically.
   Privacy purists can instead pre-encrypt their own details with their own
   key ("Bring your own PGP") — the server stores the block unreadable.
5. Buyers and sellers communicate securely on the order page (`/order/<token>/messages`)
   — messages are PGP-encrypted by default, no accounts needed.
6. Shoppers can **Report listing** on any product page — CAPTCHA-protected,
   visible in `/admin/reports` for moderation (archive or deactivate product).
7. Vendors can post listings via **Sell / Post Listing** (`/sell`) — no account,
   just a secure token to manage their listing and view orders.
8. Shape the storefront in **Visual Customizer** (`/admin/customize`) — theme
   colors, logo/banner uploads, layout, navigation menu and custom pages. No
   template editing, no JavaScript. See [Visual Customizer (v0.7)](#visual-customizer-v07).

View orders in the admin panel as ciphertext and decrypt them locally:

```bash
gpg --decrypt buyer-order.txt
```

## Vendor Listings (v0.6)

The **Sell / Post Listing** portal (`/sell`) lets anyone list products without
creating an account:

- **Zero-JS, CAPTCHA-protected** form at `/sell`
- Seller provides title, category, description, price, currency, and optional
  payout address (BTC/XMR for direct-to-seller sales)
- On submit, a **unique seller token** is generated — bookmark it
- Seller dashboard at `/sell/manage/<token>` shows listing status and orders

Admin controls the marketplace policy in **Settings → Public listing policy**:

| Mode | Behavior |
|---|---|
| **Disabled** | Only admin creates products (default for private stores) |
| **Moderated** (recommended) | Vendors submit → `pending_approval` → admin approves/rejects in `/admin/listings` |
| **Open** | Listings go live immediately |

Admin moderation: `/admin/listings` shows all vendor listings with
Approve/Reject/Pause actions. Approved listings appear in the catalog
alongside admin-created products.

## Visual Customizer (v0.7)

`/admin/customize` turns the storefront into a configurable store without
editing a single template. Every form is plain HTML with a CAPTCHA, and
every setting compiles to CSS variables or template variables at render
time — still zero JavaScript, still `script-src 'none'`.

| Tab | What it controls |
|---|---|
| **Identity & Images** | Store name, logo, hero banner image, banner title/subtitle and CTA button |
| **Palette & Typography** | Theme presets, custom background/card/primary/text colors, corner radius, font family |
| **Layout & Grid** | Category placement (top bar, left/right sidebar, hidden), product grid columns (2/3/4), grid vs list view |
| **Menu & Navigation** | Navigation bar as a JSON list: internal links, custom pages, external links (`"external": true`) |
| **Custom Pages** | Create, edit and delete static pages rendered at `/page/<slug>` |

**Theme presets** ship with the install (Tor Dark, light, high-contrast,
green…) and can be overridden color by color; picking a preset then editing
a single color stores the reference preset name plus the custom values.

**Image uploads** (logo, banner) accept PNG/JPG/JPEG/WebP/GIF up to 5 MB.
Uploads are written to `static/uploads/`, renamed to random hex names, and
**EXIF metadata is stripped** (`_strip_exif`) so camera/GPS data never
reaches the filesystem or the served page.

**Custom pages** are stored in the `custom_pages` table, rendered through
the same `base.html`, and linked automatically in the navigation when their
`custom` flag is set. Deleting a page happens from its edit screen, which
carries a working CAPTCHA.

All five customizer forms are CAPTCHA-protected (the same in-memory SVG
challenge used at checkout) and rate-limited at 30 requests/min.

### How the tabs map to the storefront

| Tab | Stored in | Rendered as |
|---|---|---|
| Identity & Images | `store_settings` (`store_name`, `logo_path`, `banner_*`) | header logo, `<section class="hero-banner">` above the catalog, footer |
| Palette & Typography | `store_settings` (`bg_color`, `card_bg_color`, `primary_color`, `text_color`, `border_radius`, `font_family`, `theme_preset`) | `:root { --bg-color: …; --primary: … }` inline CSS block in `base.html` |
| Layout & Grid | `store_settings` (`category_position`, `grid_columns`, `grid_style`) | category bar/sidebar placement, `.product-grid` column count, grid vs list cards |
| Menu & Navigation | `store_settings.nav_items` (JSON) | `nav_items` loop in `base.html`; `custom` and `external` flags preserved |
| Custom Pages | `custom_pages` table | `/page/<slug>` via `public_pages.py`, rendered with `page_custom.html` |

**Sidebar vs top bar:** with `category_position` set to `left` or `right`
the category list moves into a fixed column beside the product grid;
`top` keeps the horizontal bar; `hidden` removes it from the storefront
entirely (the `/?category=` URLs keep working). Grid columns accept 2, 3 or
4, and `grid_style` switches between card grid and list view — all with CSS
only, no layout script.

**Zero-JS guarantee:** the customizer's own tab bar is a list of anchor
links (`#tab-theme`, `#tab-layout`, …), not a scripted tab widget, and all
panels are rendered visible. There is no `<script>`, no `on*=` handler and
no inline event anywhere in the admin templates. The CSP for the whole app
stays `script-src 'none'`, so a browser that blocks scripts entirely — Tor
Browser at "Safest" — can still configure and run the store.

### Custom page routes

| Route | Method | Purpose |
|---|---|---|
| `/admin/customize` | GET | All five tabs on one page |
| `/admin/customize/theme` | POST | Apply preset or custom colors |
| `/admin/customize/layout` | POST | Category placement, columns, grid style |
| `/admin/customize/identity` | POST | Store name, banner text/URL, logo and banner upload |
| `/admin/customize/navigation` | POST | Save the JSON navigation list |
| `/admin/customize/pages/new` | GET/POST | Create a page |
| `/admin/customize/pages/<id>/edit` | GET/POST | Edit a page (delete form lives here too) |
| `/admin/customize/pages/<id>/delete` | POST | Delete a page |
| `/page/<slug>` | GET | Public render of a published page |


## Launcher scripts

`run.bat` (Windows) and `run.sh` (Linux/macOS) bootstrap everything on a
fresh clone: create `.venv`, install `requirements.txt`, copy
`.env.example` to `.env` if absent, and start uvicorn on
`http://127.0.0.1:8000`. No global Python packages are required beyond the
venv.

## Docker deploy

The recommended way to run NodeMarket in production. The image is
`python:3.12-slim`, runs as a non-root user (`nodemarket`), and persists
everything in a volume at `/app/data`.

```bash
# build and run on http://127.0.0.1:8000
docker compose up -d --build

# generate a session secret and set it in docker-compose.yml before exposing anything
docker compose run --rm nodemarket python -c "import secrets; print(secrets.token_hex(32))"

# set the admin password: add ADMIN_PASSWORD to the environment: block, then
docker compose up -d
```

Plain `docker` without compose:

```bash
docker build -t nodemarket .
docker run -d -p 127.0.0.1:8000:8000 -v nodemarket_data:/app/data nodemarket
```

Configuration through environment variables (compose `environment:` block
or `docker run -e`): `SECRET_KEY`, `ADMIN_PASSWORD`, `STORE_NAME`,
`CURRENCY`, `DB_PATH` (keep the default `data/nodemarket.db` — the volume
mounts `/app/data`).

### Running as a Tor hidden service (`.onion`)

Uncomment the commented `tor` service in `docker-compose.yml`, change
`HOST` to `0.0.0.0` (Tor connects over the internal compose network, never
the host), and start:

```bash
docker compose up -d --build
docker compose exec tor cat /var/lib/tor/hidden_service/hostname   # your .onion URL
```

NodeMarket's zero-JS frontend works with Tor Browser at its highest
security level, and the app makes no external calls that would break
onion-service operation. See
[Transport security](#transport-security-read-before-deploying).

## Payments (v0.3)

### Methods (independently enabled in `/admin/settings`)

| Method | Address source (non-custodial) | Address source (custodial, optional) |
|---|---|---|
| **Bitcoin (BTC)** | `xpub` mode: unique P2WPKH (bech32) address derived per order via BIP32 public derivation — pure stdlib, no network calls, the server never sees a private key | `rpc` mode: local Bitcoin Core wallet issues `getnewaddress` per order (credentials in `.env`) |
| **Monero (XMR)** | store main address, or a pasteable list of subaddresses rotated per order (per-order addresses, no server wallet) | local `monero-wallet-rpc` creates a dedicated subaddress per order (credentials in `.env`) |
| **Demo** | no real payment — for testing | — |

Buyers pick a method with plain HTML radio buttons at checkout. No
exchange-rate API is ever contacted: the admin may set a manual
`1 fiat = N coins` rate per method, or show the fiat total only.

### Settlement modes

**Direct-to-Seller (non-custodial, default).** The checkout address belongs
to the seller's external wallet. The server holds no private keys, cannot
spend anything, and status tracking (`pending_payment → paid → completed`)
is manual bookkeeping. You are responsible for watching your own wallet and
marking payments as received.

**Temporary Escrow (custodial).** For storefronts that want to guarantee
delivery: the payment is received in an RPC-connected custodian wallet and
only moves to the seller after the buyer confirms receipt.

```
pending_payment ──> in_escrow ──> completed_released
                        │  ▲
                        ▼  │ (admin resolves)
                     disputed
pending_payment ──> cancelled (either mode, before settlement)
```

- The buyer confirms receipt on the order tracking page
  (`/order/<token>` — **Confirm receipt & release payment**, one click,
  zero JS, CSRF-hardened via the Origin check).
- On release, `EscrowEngine` (`app/payments/escrow.py`) fires an
  auto-payout hook that sweeps the custodian balance to the configured
  payout address via local RPC (`sendall` / `sweep_all`).
- If the RPC is not connected, the hook logs the pending payout in the
  escrow history and the admin pays out manually from the wallet —
  the release itself never depends on RPC availability.

**Security trade-off, stated plainly:** Direct-to-Seller means the server
operator *cannot* steal your funds but also *cannot* refund or guarantee
them. Temporary Escrow means the custodian wallet (your node, your keys)
holds funds for hours-to-days — it can spend them, so it must be yours and
must be kept safe. NodeMarket ships Direct as the default.

### Order tracking

No user accounts exist. At checkout each order gets a 128-bit random
tracking token: the URL `http://your-store/order/<token>` is the only
credential. It shows live status, the escrow history table (when in escrow
mode) and the release button while the order is `in_escrow`.

### Order messaging (v0.5)

Buyers and sellers communicate on the order page without any accounts:
- Visit `/order/<token>/messages` to read and write messages
- Buyer messages are **PGP-encrypted by default** with the store's public key
  (option to send plaintext for non-sensitive info)
- Seller replies from `/admin/orders/<ref>` are stored as plaintext
- Rate-limited and CAPTCHA-protected (SVG math challenge)
- Zero JavaScript, pure HTML forms

### Product reporting (v0.5)

Any shopper can flag a listing via **Report listing** on the product page:
- CAPTCHA-protected form with reason dropdown + optional description
- Reports appear in `/admin/reports` for the store operator
- Actions: **Archive** (dismiss) or **Deactivate product** (one click)
- Zero JavaScript, pure HTML forms

## Transport security (read before deploying)

NodeMarket encrypts buyer delivery data **at rest** (PGP, before the row is
written). It does **not** encrypt the hop between the buyer's browser and
your server — that is the operator's job:

- **HTTPS**: put a TLS-terminating reverse proxy (nginx, Caddy, Traefik…) in
  front of NodeMarket. Without TLS, delivery addresses and the order-tracking
  URL travel in cleartext from the browser to your server, where the PGP
  layer only then encrypts them for storage.
- **Tor hidden service (`.onion`)**: the zero-JS, no-logging design makes
  NodeMarket well suited to onion service deployment — no external calls, no
  CDNs, no analytics to break, and Tor Browser at its highest security level
  is a first-class client.
- Never expose NodeMarket directly over plain HTTP on a public IP. The
  default bind is `127.0.0.1` for exactly this reason; if you set
  `HOST=0.0.0.0`, you must have TLS or an onion service in front.

## Security model

| Layer | Behavior |
|---|---|
| Transport | **operator's responsibility**: serve behind HTTPS (reverse proxy) or as a Tor hidden service (`.onion`) — see [Transport security](#transport-security-read-before-deploying) |
|---|---|
| CSP | `default-src 'self'; script-src 'none'; frame-ancestors 'none'` |
| Referrer | `no-referrer` (header and meta) |
| Framing | `X-Frame-Options: DENY` |
| CSRF | SameSite=Lax cookies + cross-origin POST rejection (Origin check) |
| Sessions | itsdangerous-signed cookies, HttpOnly, SameSite=Lax |
| Admin auth | constant-time password comparison, 12h signed session |
| Captcha | self-hosted, zero-JS SVG challenge on admin login, all admin write endpoints (customizer, pages) and checkout; answer lives only in process RAM, keyed by a single-use signed token with 5-minute expiry; no database state |
| JS detector | pure-CSS banner visible only when JavaScript is enabled (hidden via `<noscript><style>`), fully compatible with `script-src 'none'` |
| Rate limiting | in-memory sliding window: admin login 5/min, checkout 10/min, captcha 30/min; client addresses never touch disk or logs; automatic bucket sweep |
| Uploads | logo/banner images validated by magic bytes, random filenames, EXIF stripped before serving |
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
