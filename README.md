# Evolum Studio

A working film production platform. Development, funding, casting, and distribution
in one app — the software that runs [evolumstudio.com](https://evolumstudio.com).

Flask. 14,000 lines of Python. 73 routes. SQLite by default.

**No AI. Not "AI optional" — none.** The script analyzer is a deterministic engine,
not a language model. There is no LLM in the request path, no API key to buy, no
per-call cost, no rate limit, and no vendor who can change the terms on you. Feed
it the same screenplay twice and you get the same analysis twice.

It runs on a laptop, offline, forever.

Apache 2.0. Take it, change it, sell it, run your own. You don't owe me anything.

## What it does

Four kinds of people use it, and each gets their own way in:

- **Filmmakers** — project workspace, script analysis, pitch deck builder, sizzle
  reel assembly, festival calendar, deliverables
- **Actors** — casting listings, audition prep, self-tape room, booked-role packets
- **Investors** — deal room, project catalog, slate view
- **Supporters** — supporter feed, sponsorship, rewards

Plus the parts every real product needs and most demos skip: sign-in, billing,
pricing tiers, terms, privacy, acceptable-use, and an audit trail.

## Running it

```bash
git clone https://github.com/madbradsmith/evolum-studio.git
cd evolum-studio
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then edit it — see below
python app.py
```

Open <http://localhost:7000>.

### Configuration

Everything is optional except `SECRET_KEY`. The app starts and runs without any
of the rest; the features that need a given service are simply inactive until you
supply a key.

| Variable | Needed for | Required? |
|---|---|---|
| `SECRET_KEY` | Session signing | **Yes** — any long random string |
| `DATABASE_PATH` | SQLite location | No, defaults to `./evolum.db` |
| `STRIPE_SECRET_KEY` + `STRIPE_PRICE_*` | Paid tiers and checkout | No |
| `STRIPE_WEBHOOK_SECRET` | Subscription webhooks | No |
| `TMDB_API_TOKEN` | Comparable-films enrichment | No |
| `FAL_API_KEY` | Image generation | No |
| `SMTP_*` | Outbound email | No |

Bring your own keys. None are included and none are needed to start.

## What is deliberately not in this repo

This is a real product, so the working directory it came from also held things
that aren't mine to give away or aren't yours to want:

- Screenplays and film IP — my own titles, and third-party scripts that were
  sitting in there as test fixtures
- Poster art, music libraries, pitch decks
- The production database, credentials, and logs

You get the whole application. You don't get my movies. Point it at your own.

## Using it in your own work

Apache 2.0 means commercial use, modification, distribution, private use, and a
patent grant. Keep `LICENSE` and `NOTICE` with anything you redistribute, and note
what you changed. That's the whole obligation.

**If you deploy this**, change the contact details first. The legal templates in
`templates/` — terms, privacy, acceptable use, FAQ — carry my email address,
because they're the real ones from the live site. They should carry yours.

## Contributing

Pull requests welcome, and they arrive under Apache 2.0 (license section 5). No CLA.

No roadmap, no support commitment. Given away as-is — which is what the warranty
disclaimer means in plain language: if it breaks, it's yours to fix.

## License

Apache License 2.0 — see [LICENSE](LICENSE).

Copyright 2026 Brad Smith
