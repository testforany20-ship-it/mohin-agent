# MOHIN's AI Agent — web version

A private, password-protected web chat for MOHIN's personal AI agent — the
same agent that also runs as a Telegram bot (`agent.py` version), ported to
Streamlit: same Gemini agent loop (function calling with a model fallback
list: gemini-3.5-flash → gemini-3.8-flash → gemini-flash-lite-latest), same
rules (`SOUL.md`), same tools:

- current time (Asia/Dhaka)
- persistent memory — `remember` / `recall`
- MOHIN TECH latest posts (top 5 from the blog feed)
- read a web page and summarise it (`fetch_url_text`)
- draft an English article on a topic — **draft only; there is no publishing
  tool, by design**
- reminders (see limits below)

## First visit: claim the app

The site is for MOHIN only, and it starts unclaimed:

1. Open the app. You will see **“Claim this app”**.
2. Enter the one-time **setup code** (given to MOHIN when the app was
   deployed; it lives in the app’s Streamlit secrets as `SETUP_CODE`).
3. Choose your own password and type it twice.
4. The app stores **only a salted SHA-256 hash** of the password
   (`data/auth.json`) — never the password itself. From now on the setup
   code no longer works; the login screen asks for your password.

Wrong setup code or mismatched passwords change nothing.

## Secrets (Streamlit Cloud → app settings → Secrets)

```toml
GEMINI_API_KEY = "..."
SETUP_CODE = "..."
```

No secret is stored in this repository.

## Honest limits

- **Data can reset.** Memory, reminders and even the password hash live in
  `data/` files inside the app. Streamlit Community Cloud can wipe local
  files on a redeploy or a fresh container — if that happens, the app goes
  back to the “Claim this app” screen: claim it again with the same setup
  code and pick a password again. Memory saved before the reset is gone.
- **Reminders cannot push.** A reminder is shown **once, at the top of the
  page, on your next visit after it comes due** — there is no phone
  notification. (The Telegram version can message you; this web one can’t.)
- **Free Gemini tier.** The agent runs on the free Gemini API tier, so heavy
  use can hit rate limits; answers may occasionally fail and ask you to retry.
- **Drafts are drafts.** The agent never publishes or posts anything
  anywhere, on its own or otherwise — that is a hard rule in `SOUL.md`.
- **Sleep.** Free Streamlit apps sleep when idle; the first visit after a
  while can take about a minute to wake.

## Files

- `streamlit_app.py` — password gate + chat UI
- `agent_core.py` — the agent loop and tools (stdlib only, ported from the
  Telegram version)
- `SOUL.md` — the agent’s standing rules/personality
- `requirements.txt` — `streamlit` (+ `tzdata` so Asia/Dhaka always resolves)
