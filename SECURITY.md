# Security policy

## Sensitive information

Never commit credentials, access tokens, private keys, one-time passwords, signed storage addresses, personal data, production identifiers or confidential client material. Checked-in configuration files contain examples and Secret Manager resource references only.

If sensitive information is committed, stop distribution, revoke or rotate the affected credential, remove it from Git history and record the incident through the private project channel.

## Reporting a vulnerability

Do not place exploit details, credentials or personal data in a public issue. Use GitHub's private vulnerability-reporting or security-advisory channel for this repository. If that channel is unavailable, contact the repository owner privately before sharing details.

## Supported versions

The repository is currently in Pre-Sprint development and has no supported production release. Security fixes apply to the current default branch until versioned releases are published.
