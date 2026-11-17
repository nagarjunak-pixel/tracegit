# Security & Integrity Policy

`tracegit` stores agent execution traces locally inside SQLite with SHA-256 content-addressable Merkle commit roots, avoiding external cloud telemetry exfiltration by default. Never commit raw API credentials into trace argument strings. Report security issues privately to `sendemailtonagarjuna@gmail.com`.
