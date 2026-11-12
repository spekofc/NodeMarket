# Security Policy

NodeMarket's threat model is simple: the server operator and the buyer do
not trust each other's infrastructure. The codebase is built so that buyer
delivery data is unreadable at rest even if the database, backups or the
host itself are compromised.

## Supported versions

| Version | Supported |
|---|---|
| 0.4.x (main) | ✅ |
| < 0.4 | ❌ upgrade first |

## Responsible disclosure

- **Do not open a public issue.** Email the maintainer directly or open a
  [GitHub Security Advisory](https://github.com/spekofc/NodeMarket/security/advisories/new)
  (private by default).
- Include: affected endpoint/file, reproduction steps, impact assessment.
- Acknowledgement target: **72 hours**. Fix or mitigation target for
  high-severity issues: **7 days**.
- We credit reporters by handle in the fix commit unless you ask otherwise.
- Please allow a fix to ship before publishing details. Coordinated
  disclosure only — no ransomware-style "pay or publish", no leaks.

## Community Bug Hunt

Any bug from the priority scope below, found and responsibly reported, gets
credited in the fix commit and acknowledged in the release notes. NodeMarket
is a free-software project (AGPL-3.0); the bounty is community credit and
early-access to the fixed version, not cash. Independent projects paying
cash bounties are welcome to point their programs at this scope.

### Priority scope

1. **Plaintext leakage** — any path where buyer delivery details exist
   outside PGP ciphertext: plaintext in the SQLite file/WAL, in logs or
   stdout, in HTTP responses (order page, error re-renders, admin pages),
   or a fail-open path where an unencryptable key produces a 500 instead
   of failing closed.
2. **CAPTCHA / rate-limit bypass** — answer forgery, token replay,
   missing-window enumeration, or reaching a protected write endpoint
   (admin login, checkout POST) without honoring the limits in
   `app/ratelimit.py`.
3. **BIP32 derivation flaws** — wrong child-index math, address reuse
   across orders, collision between concurrent orders, or keys/paths
   leaking in `app/payments/xpub.py` and the BTC provider.
4. **XSS / CSRF** — any injection through product names, descriptions,
   category names, or admin-configured strings; any state-changing form
   accepted cross-origin (the `OriginCheck` middleware is the reference).

### Out of scope

- Attacks requiring control of the server itself (config, `.env`, admin
  password) — that is the operator's machine by definition.
- Plaintext exposure of data the buyer *chose* to submit in BYO PGP mode
  before encryption (the server can only validate, never decrypt).
- Traffic-analysis of Tor users; low-severity missing security headers
  already covered by the default middleware.

## Security architecture invariants (what we defend)

- Buyer data is PGP-encrypted **before** any persistence; the database
  only ever stores ciphertext.
- Every encryption path **fails closed**: missing/garbage/unencryptable
  store key → 400, no row created.
- Zero request logging, zero IP storage; rate-limit buckets live in
  process RAM and evaporate on restart.
- Zero JavaScript: `script-src 'none'`; no inline handlers anywhere.
- Session and order-tracking secrets are `secrets.token_hex(16+)`; the
  order URL token is the only order credential.
