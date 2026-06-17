# Deploying to Streamlit Community Cloud

This app is a Streamlit server, so it deploys on **Streamlit Community Cloud** (free,
purpose-built) — not Vercel/Netlify (those are for static/serverless front-ends).

## One-time deploy (~3 minutes)

1. Go to **https://share.streamlit.io** and **sign in with GitHub** (the account that
   owns this repo).
2. Click **Create app → Deploy a public app from GitHub**, then set:
   - **Repository:** `pranavnair456/panw-fpa-copilot`
   - **Branch:** `main`
   - **Main file path:** `app/dashboard.py`
3. Open **Advanced settings**:
   - **Python version:** 3.12 (or 3.13).
   - **Secrets:** paste this (TOML format — keep the quotes), with your real key:
     ```toml
     ANTHROPIC_API_KEY = "sk-ant-..."
     ```
4. Click **Deploy**. First build takes ~2–3 min. You'll get a public URL like
   `https://panw-fpa-copilot-xxxx.streamlit.app` — that's the link to share.

The app reads the secret automatically (the dashboard bridges `st.secrets` into the
environment the Anthropic SDK uses). Without a secret it runs in deterministic
**offline mode** — every tab still works.

## Notes for a live demo

- The **Signals** tab runs ~21 Claude extractions on first load (~20–30s), then it's
  cached for the session. The **Exec Summary** and **Chat** tabs call Claude on demand.
- **Protect your key:** set a monthly spend cap in the Anthropic console
  (Settings → Limits), and **delete or rotate the key after the interview**.
- To redeploy after code changes: just `git push` — Streamlit Cloud auto-rebuilds.
- Updating the key later: app page → **⋮ → Settings → Secrets**.
