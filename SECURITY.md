# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.x     | Yes       |

## Reporting a Vulnerability

**Do NOT open a public GitHub issue for security vulnerabilities.**

To report a security vulnerability, use one of these methods:

1. **GitHub Security Advisories** (preferred): Go to the repository's Security tab and click "Report a vulnerability" to create a private advisory.
2. **Email**: Contact the maintainers directly via their GitHub profile.

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

You can expect an initial response within 5 business days. Accepted vulnerabilities will be patched in a follow-up release with a coordinated disclosure timeline.

## Security Considerations

- The `SECRET_KEY` environment variable must be set to a strong random value before deployment. The application will refuse to start if this variable is empty.
- Wildcard CORS origins (`*`) are rejected at startup. Set `ALLOWED_ORIGINS` to explicit origins.
- Swagger and ReDoc are disabled when `APP_ENV=production`.
- All routes under `/api/v1` require a valid JWT bearer token.
- The `/process-emergency` and `/dashboard` endpoints require JWT authentication.
- Twilio webhook requests are validated using the Twilio auth token signature.
- Rate limiting is enforced on all endpoints via SlowAPI (5/min on login, 60/min global).
- HTTP security headers (HSTS, X-Frame-Options, X-Content-Type-Options) are set on all responses.
- Audio uploads are validated for size (25 MB) and MIME type.
- Transcript length is capped at 10,000 characters.
