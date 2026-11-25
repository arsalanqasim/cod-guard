# Security Policy

## Reporting a vulnerability

Please do not open public GitHub issues for security vulnerabilities, credential leaks, or PII handling bugs. Report them privately to the repository maintainer via GitHub private vulnerability reporting or direct contact.

## Operational security notes

- **Authentication & secrets:** Inject `COD_GUARD_OPERATORS`, connector secrets (`COD_GUARD_SHOPIFY`, `COD_GUARD_WOOCOMMERCE`, `COD_GUARD_WHATSAPP`), and `COD_GUARD_NETWORK_KEY` from your host secret store. Never commit `.env` files.
- **PII & phone masking:** List and detail endpoints mask buyer phone numbers by default (`?reveal_phone=true` logs a `phone_read` audit event). Responses set `Cache-Control: no-store`.
- **Single-host pilot boundary:** The current pilot storage layer uses SQLite in WAL mode with plaintext customer fields (`customer_name`, `phone`, `city`). Run behind an HTTPS reverse proxy with restricted host/volume access and review [docs/HOSTING.md](docs/HOSTING.md) and [docs/ROADMAP_POST_AUDIT.md](docs/ROADMAP_POST_AUDIT.md) before multi-merchant production hosting.
