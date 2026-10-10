# Lumen Atlas — website setup, deployment and updates

Same architecture as Cortex Atlas: **Streamlit app in a Hugging Face Space (Docker)** + **private Hugging Face
Dataset holding `data.duckdb`** + **Supabase for academic accounts**.

| Piece | Name |
|---|---|
| Space (the website) | `alialawiehlab/lumen-atlas` → https://alialawiehlab-lumen-atlas.hf.space |
| Dataset (the database, private) | `alialawiehlab/lumen-atlas-data` |
| Supabase project | `Lumen Atlas` (new project, recommended) |
| Code | `neurointerventional-network\webapp\` |

Already done (by Claude): `preprocess.py` (builds `data.duckdb`, ~540 MB), `app.py`, `auth.py`, `Dockerfile`,
`requirements.txt`, `.streamlit/config.toml`, `verify_db.py`, `deploy.py`, `BUILD_AND_DEPLOY.ps1`. All 8 pages
pass an automated render test against the current database.

---
## ★ FREE hosting (use this): Streamlit Community Cloud + private HF Dataset
Since 2026 Hugging Face requires PRO ($9/mo) or billing for *new* Docker/Gradio Spaces on CPU basic (only static
Spaces stay free). Cortex's existing Space is unaffected. Lumen therefore runs the same app on **Streamlit Community
Cloud** (free: up to ~2.7 GB RAM, 50 GB disk, sleeps after 12 h without visitors). The database still lives in the
private HF Dataset `alialawiehlab/lumen-atlas-data` (free); only the app host changes. Tested: home page peaks at
~230 MB RAM with DuckDB capped at 1 GB.

**One-time setup (~15 min)**
1. GitHub: create an **empty private** repo `alialawiehlab/lumen-atlas-app` (no README, no .gitignore).
2. Hugging Face: create a **Write** token and a **Read** token (Settings → Access Tokens).
3. PowerShell in `webapp\`:
   ```powershell
   $env:HF_TOKEN = "hf_..."   # WRITE token
   powershell -ExecutionPolicy Bypass -File .\PUBLISH_FREE.ps1
   ```
   → builds `data.duckdb`, uploads it to the private dataset, pushes the code (not the DB) to GitHub.
4. share.streamlit.io → sign in with GitHub → **Create app → Deploy a public app from GitHub**:
   repo `alialawiehlab/lumen-atlas-app`, branch `main`, file `app.py`, App URL `lumen-atlas`
   (→ https://lumen-atlas.streamlit.app). **Advanced settings**: Python **3.12**; **Secrets**: paste the contents of
   `.streamlit/secrets.toml.example` with your **Read** token in `HF_TOKEN`. Deploy.
   If Streamlit asks for access to private repos, allow it. App visibility: **public** (sign-in is done by Supabase
   inside the app).
5. Supabase → Authentication → URL Configuration: Site URL `https://lumen-atlas.streamlit.app`; Redirect URLs add
   `https://lumen-atlas.streamlit.app` and `http://localhost:8501`. (If you choose another subdomain, use it here and in
   the `SUPABASE_REDIRECT_URL` secret.)

**Updates**
- Code/logo change: `.\PUBLISH_FREE.ps1 -AppOnly` (Streamlit redeploys on push automatically).
- New data after your author review: `.\PUBLISH_FREE.ps1`, then share.streamlit.io → app → ⋮ → **Reboot app**
  (`LUMEN_SYNC_DB=1` makes it fetch the new database at start).

Sections B and D below describe the original HF Docker route; use them only if you take HF PRO.

---
## A. Supabase (accounts) — project already created
Project URL `https://sdlpxxnkuacgapjxbjma.supabase.co`; publishable key pre-filled in `BUILD_AND_DEPLOY.ps1`
(publishable keys are meant to be public; never share or paste the **secret / service_role** key).
Remaining clicks in the Supabase dashboard:
1. **Authentication → Sign In / Providers → Email**: enabled, **Confirm email ON**, minimum password length 8.
   Leave other providers (Google, GitHub…) off — the app only implements e-mail + password.
2. **Authentication → URL Configuration**: **Site URL** = your app URL (free route: `https://lumen-atlas.streamlit.app`; HF route: `https://alialawiehlab-lumen-atlas.hf.space`);
   **Redirect URLs**: add `https://alialawiehlab-lumen-atlas.hf.space` and `http://localhost:8501`.
3. **Authentication → Emails → Templates**: *Confirm signup* subject `Confirm your Lumen Atlas account`, body
   "Welcome to Lumen Atlas, the neurointerventional co-authorship atlas. Confirm your address: {{ .ConfirmationURL }}".
   Same for *Reset password*.
4. **Authentication → Emails → SMTP settings** (before announcing): custom SMTP. Supabase's built-in sender allows
   only a few e-mails per hour. Gmail: host `smtp.gmail.com`, port 465, user = the Gmail address, password = a Google
   *app password*, sender name `Lumen Atlas`.
5. **Authentication → Rate limits**: defaults are fine.
6. After you sign up on the live site, make yourself admin (**SQL editor**):
   `update auth.users set raw_user_meta_data = raw_user_meta_data || '{"role":"admin"}' where email = 'you@emory.edu';`
   Guest single-use accounts work as in Cortex (`{"single_use": true}` in the user's metadata).

Sign-up is limited to academic domains (.edu, .ac.xx, .edu.xx), exactly like Cortex (`ACADEMIC_DOMAIN_RE` in `auth.py`).

## B. Hugging Face Docker Space (only with HF PRO) — tokens and settings
**Tokens** (huggingface.co → Settings → Access Tokens → *Create new token*):
- `lumen-deploy`: type **Write**. Used only on your PC by `deploy.py`.
- `lumen-space-read`: type **Read** (or *Fine-grained* with "Read access to contents of selected repos" on
  `alialawiehlab/lumen-atlas-data`). Stored in the Space so the app can download the private database.

**You do not need to create the Space or the Dataset by hand** — `deploy.py` creates them with the settings below. If
you prefer to create them in the web UI, use exactly these:

| Setting | Space `alialawiehlab/lumen-atlas` | Dataset `alialawiehlab/lumen-atlas-data` |
|---|---|---|
| SDK / type | **Docker → Blank** (not Streamlit, not Gradio) | Dataset |
| Hardware | **CPU basic — 2 vCPU · 16 GB · free** (enough; DB is ~0.5 GB) | — |
| Visibility | **Public** (the app has its own Supabase sign-in; a private Space would block everyone else) | **Private** |
| License | `other` (code is PolyForm Noncommercial, like Cortex) | `other` |
| Persistent storage | None (the DB is re-downloaded at each restart) | — |
| Sleep time (Settings) | Default (free tier sleeps after 48 h idle; first visit then takes ~1–2 min) | — |

**Space → Settings → Variables and secrets** (set automatically by `deploy.py`; check they are there):
`HF_TOKEN` = the *read* token · `SUPABASE_URL` · `SUPABASE_ANON_KEY` · `SUPABASE_REDIRECT_URL` · `LUMEN_ATLAS_CONTACT_EMAIL`.
All as **Secrets** (not public Variables).

After every database update use **Settings → Factory rebuild** (`deploy.py` does this); a plain *Restart* keeps the
old cached database.

## C. Logo (optional now, easy later)
Save your logo as `webapp\assets\lumen_atlas_logo.png` (transparent PNG, ~1200 px wide). Until then the site shows a
text title. To add it later: `.\BUILD_AND_DEPLOY.ps1 -AppOnly`.

## D. Build and deploy — one command, ~10 min
```powershell
cd "C:\Users\alial\OneDrive - Emory\neurointerventional-network\webapp"
$env:HF_TOKEN = "hf_..."            # write token
$env:HF_READ_TOKEN = "hf_..."       # read token
# Supabase URL / publishable key / redirect URL / contact e-mail are pre-filled in the script
powershell -ExecutionPolicy Bypass -File .\BUILD_AND_DEPLOY.ps1
```
This builds `data.duckdb`, runs the pre-flight check, creates the private dataset and the Docker Space, uploads both,
stores the five secrets in the Space, and triggers a factory rebuild. Open the Space after ~5 minutes; the first
visit downloads the database (~1 min).

Test locally first if you like: `pip install -r requirements.txt` then `streamlit run app.py`
(without Supabase variables the app falls back to the local password `lumen-atlas-2026`).

## E. Updating after your manual author review (repeat every round)
1. Apply your decisions in the pipeline (review workbook → overrides / merges), then rebuild authors and network:
   `scripts\04_author_table.py` → `05_merge_name_variants.py` → `04_author_table.py` → `06_build_network.py` →
   `07_richclub_preview.py --budget 0 --nulls 10` (or simply `RUN_CORTEX_SYNC.ps1` from the project folder, which runs
   the whole chain including the Cortex identity sync).
2. `cd webapp` and `powershell -ExecutionPolicy Bypass -File .\BUILD_AND_DEPLOY.ps1` (rebuilds the DB from the new
   parquets and redeploys). Code-only changes: `-AppOnly`.
3. The Space factory-rebuilds automatically; a plain restart would keep the old cached database.

## F. What is new compared with Cortex Atlas
- **Parent specialty** on every profile (ENS / IN / INR / joint department), colour-coded throughout, plus the
  author's own affiliation composition and whether the specialty was confirmed by manual review.
- **Interdisciplinarity**: collaborator mix by specialty, cross-specialty share, partner diversity (Blau index), and
  percentile among clinical neurointerventionalists; specialty-coloured ego networks; "Most cross-specialty" sidebar
  ranking and a specialty filter on every leaderboard.
- **🧭 Specialty landscape** page: specialty share of the literature over time, observed/expected collaboration
  heatmap by era, within-specialty preference trend, and the top bridges in each specialty.
- **Subspecialty hierarchy**: 9 domains → 25 subdomains (`common/hierarchy.py`); domain- or subdomain-level
  leaderboards; sunburst on each profile.
- **📈 Eras & milestones** page: subject composition with era boundaries, and milestone diffusion curves.
- **Top papers** tab with OpenAlex links.
- CAPI is not included yet (Lumen Paper 20 analogue not built).

## G. Rich-club threshold (decided 2026-10-10)
Step `07b_richclub_full.py` computes ρ(k) at every integer k against 20 degree-preserving null graphs.
ρ(k) rises steadily, **peaks at 1.86 at degree 864** (217 authors), and declines slowly afterwards (1.69 at k = 1,500):
a broad plateau (ρ ≥ 1.83 for k ≈ 700–1,000) rather than a sharp peak. Persistence thresholds:

| τ (ρ ≥ τ thereafter) | k* | authors above k* |
|---|---|---|
| 1.20 (Cortex rule) | 35 | 21,636 |
| 1.30 | 61 | 13,833 |
| 1.40 | 113 | 6,327 |
| **1.50 (site default)** | **192** | **3,141** |
| ≥ 1.60 | undefined (ρ falls back below 1.6 in the extreme tail) | — |

The site uses **τ = 1.50 → k* = 192**, the strictest persistence threshold that is defined. Change with
`python preprocess.py --fresh --tau 1.4` or a fixed `--kstar 864` (ρ peak).
