# Cloudflare Security Recommendations

The Worker already enforces application-level protection:

- Security headers on static and API responses.
- Same-origin checks for mutating API requests.
- HttpOnly, Secure, SameSite=Lax session cookies.
- D1-backed rate limits for static traffic, login, and authenticated APIs.
- 30-minute D1-backed cooldowns for manual submit and settings changes.
- 15-second upstream Zepp request timeout.
- Optional Cloudflare Turnstile verification on the Zepp login endpoint.

Recommended dashboard rules for `steps.zhhcnl.com`:

1. WAF custom rule:
   - If URI path starts with `/api/`
   - And HTTP method is not one of `GET`, `POST`, `PUT`
   - Then block.

2. Rate limiting rule for `/api/auth/login`:
   - Characteristic: IP
   - Period: 15 minutes
   - Requests: 8
   - Action: block or managed challenge.

3. Rate limiting rule for `/api/submit`:
   - Characteristic: IP
   - Period: 30 minutes
   - Requests: 3
   - Action: block or managed challenge.

4. Rate limiting rule for `/api/settings`:
   - Characteristic: IP
   - Period: 30 minutes
   - Requests: 6
   - Action: block or managed challenge.

5. Bot protection:
   - Create a Cloudflare Turnstile widget for `steps.zhhcnl.com`.
   - Set `TURNSTILE_SITE_KEY` as a Worker variable.
   - Set `TURNSTILE_SECRET_KEY` as a Worker secret.
   - Keep Security Level at least Medium.
