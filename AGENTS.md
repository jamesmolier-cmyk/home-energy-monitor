# Home Energy Monitor — Grok rules

When asked for an energy report, optimisation advice, or Octopus/Aira analysis:

## Mandatory first step

**Always run this command before writing any numbers:**

```bash
bash ~/.grok/skills/octopus-energy/scripts/run-daily-report.sh
```

Or:

```bash
cd ~/home-energy-monitor && ./venv/bin/python scripts/daily_report.py
```

## Never

- Do NOT mock, estimate, or invent consumption figures.
- Do NOT say you cannot access accounts — credentials are in `~/.grok/octopus/config.env`.
- Do NOT skip the fetch because APIs are "private" — the scripts handle auth.

## If fetch fails

Report the exact error from the script output. Do not substitute fake data.

## Credentials location

`~/.grok/octopus/config.env` (Octopus API key, MPAN, Aira login). Never print secrets.

## Dig deeper

Read `~/.grok/octopus/history/YYYY-MM-DD.json` for raw half-hourly intervals and tariff rates.