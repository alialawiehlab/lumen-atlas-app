"""
Lumen Atlas — Neurointerventional Co-Authorship Network Explorer
================================================================
Companion to Cortex Atlas (neurosurgery). Streamlit app with author profiles, ego-network views,
rich-club exploration, and two neurointerventional-specific layers:
  * parent specialty (endovascular neurosurgery / interventional neurology / interventional
    neuroradiology) and cross-specialty collaboration, per author and field-wide
  * a two-level subspecialty hierarchy (domain -> subdomain) for profiles and leaderboards
Run locally:  streamlit run app.py      (data.duckdb next to this file, or downloaded from the HF Dataset)
"""
import json, os, tempfile
from pathlib import Path
import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from pyvis.network import Network

import auth

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
LOGO_PATH = ASSETS_DIR / "lumen_atlas_logo.png"
HAS_LOGO = LOGO_PATH.exists()
st.set_page_config(page_title="Lumen Atlas", page_icon=str(LOGO_PATH) if HAS_LOGO else "🩸", layout="wide")
CONTACT_EMAIL = os.environ.get("LUMEN_ATLAS_CONTACT_EMAIL", "cerebracoreconsulting@gmail.com")

if not auth.require_login(logo_path=LOGO_PATH, has_logo=HAS_LOGO):
    st.stop()

# ---------------------------------------------------------------------------------------------- data
DB_PATH = Path(__file__).resolve().parent / "data.duckdb"
DB_DATASET_REPO = os.environ.get("LUMEN_ATLAS_DATA_REPO", "alialawiehlab/lumen-atlas-data")
DB_DATASET_FILE = os.environ.get("LUMEN_ATLAS_DATA_FILE", "data.duckdb")


def _ensure_db_present() -> None:
    # LUMEN_SYNC_DB=1 (Streamlit Community Cloud): re-check the HF dataset at every app start; unchanged file = one
    # quick HEAD request, new data release = fresh download. Without it, a local data.duckdb is used as is.
    sync = os.environ.get("LUMEN_SYNC_DB", "").strip() == "1"
    if DB_PATH.exists() and not sync:
        return
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        st.error("huggingface_hub is required to fetch the network data."); st.stop()
    with st.spinner(f"First-time setup: downloading network data (~0.5 GB) from `{DB_DATASET_REPO}`…"):
        try:
            hf_hub_download(repo_id=DB_DATASET_REPO, filename=DB_DATASET_FILE, repo_type="dataset",
                            local_dir=str(DB_PATH.parent))
        except Exception as e:
            st.error(f"Could not download the network data from `{DB_DATASET_REPO}`. If the dataset is private the "
                     f"Space needs an `HF_TOKEN` secret with read access. Error: {e}"); st.stop()


@st.cache_resource
def get_db():
    _ensure_db_present()
    # Cap DuckDB memory so the app fits small free hosts (Streamlit Community Cloud ~2.7 GB RAM).
    cfg = {"memory_limit": os.environ.get("LUMEN_DUCKDB_MEMORY", "1GB"), "threads": int(os.environ.get("LUMEN_DUCKDB_THREADS", "2"))}
    return duckdb.connect(str(DB_PATH), read_only=True, config=cfg)


con = get_db()
INFO = con.execute("SELECT * FROM build_info").fetch_df().iloc[0].to_dict()
K_STAR = int(INFO["k_star"])
ERA_BREAKS = json.loads(INFO["era_breaks"]) if INFO.get("era_breaks") else []
_end = pd.Timestamp(INFO["analysis_end"]); END_LABEL = f"{_end.day} {_end:%B %Y}"

SPEC = {  # key -> (label, colour)   Okabe-Ito, colour-blind safe
    "ENS": ("Endovascular neurosurgery", "#0072B2"),
    "IN": ("Interventional neurology", "#D55E00"),
    "INR": ("Interventional neuroradiology", "#009E73"),
    "Mixed": ("Joint department", "#CC79A7"),
    "NonNS-unresolved": ("Non-neurosurgeon, unresolved", "#E69F00"),
    "Unassigned": ("Unassigned", "#BBBBBB"),
    "Other": ("Collaborator (not a clinical NI)", "#999999"),
}
RC_RED = "#B00000"
def spec_label(k): return SPEC.get(k, (k or "—", "#999"))[0]
def spec_color(k): return SPEC.get(k, ("", "#999999"))[1]
SPEC_FILTERS = ["All specialties", "ENS", "IN", "INR", "Mixed"]


# ---------------------------------------------------------------------------------------------- queries
@st.cache_data(ttl=3600)
def search_authors(query: str, limit: int = 30) -> pd.DataFrame:
    tokens = [t for t in (query or "").split() if t]
    if not tokens:
        return pd.DataFrame()
    clauses = " AND ".join(["name ILIKE ?"] * len(tokens))
    return con.execute(f"""SELECT author_oa, name, specialty, n_ni_core, degree, k_core, is_clinical_ni, in_rich_club
                           FROM author_search WHERE {clauses} ORDER BY n_ni_core DESC LIMIT ?""",
                       [f"%{t}%" for t in tokens] + [limit]).fetch_df()

@st.cache_data(ttl=3600)
def get_author(oa):
    r = con.execute("""SELECT a.*, i.cross_specialty_share, i.partner_diversity, i.joint_with_specialists,
                              i.w_ens, i.w_in, i.w_inr, i.w_mixed, i.w_other, p.cross_pct
                       FROM authors a LEFT JOIN author_interdisciplinarity i ON i.author = a.author_oa
                       LEFT JOIN cross_pct p ON p.author = a.author_oa WHERE a.author_oa = ?""", [oa]).fetch_df()
    return None if r.empty else r.iloc[0].to_dict()

@st.cache_data(ttl=3600)
def get_rc_entry_year(oa):
    r = con.execute("SELECT rc_entry_year FROM rich_club_entry WHERE author = ?", [oa]).fetchone()
    return int(r[0]) if r and r[0] is not None else None

@st.cache_data(ttl=3600)
def get_yearly(oa):
    return con.execute("""SELECT year, papers_this_year, core_this_year, cum_papers, cum_core, new_partners, cum_partners
                          FROM yearly_stats WHERE author = ? ORDER BY year""", [oa]).fetch_df()

@st.cache_data(ttl=3600)
def get_collaborators(oa):
    return con.execute("""SELECT c.partner AS partner_oa, a.name AS partner_name, c.first_collab_year, c.n_joint AS joint_papers,
                                 a.degree AS partner_degree, a.k_core AS partner_kcore, a.is_clinical_ni AS partner_is_cni,
                                 a.specialty AS partner_specialty, a.in_rich_club AS partner_in_rc, r.rc_entry_year AS partner_rc_entry_year
                          FROM collaborators c JOIN authors a ON c.partner = a.author_oa
                          LEFT JOIN rich_club_entry r ON c.partner = r.author
                          WHERE c.author = ? ORDER BY c.first_collab_year""", [oa]).fetch_df()

@st.cache_data(ttl=3600)
def get_partner_edges(partners: tuple, year: int):
    if not partners:
        return pd.DataFrame(columns=["author", "partner", "n_joint"])
    ph = ",".join(["?"] * len(partners))
    return con.execute(f"""SELECT author, partner, n_joint FROM collaborators
                           WHERE author IN ({ph}) AND partner IN ({ph}) AND first_collab_year <= ? AND author < partner""",
                       list(partners) + list(partners) + [year]).fetch_df()

@st.cache_data(ttl=3600)
def get_subspecialty(oa):
    return con.execute("""SELECT domain, subspecialty, label, share_weight, n_papers FROM subspecialty_share
                          WHERE author = ? ORDER BY share_weight DESC""", [oa]).fetch_df()

@st.cache_data(ttl=3600)
def get_top_papers(oa, limit=25):
    return con.execute("""SELECT p.year, p.title, p.cited_by_count, p.ni_core, ap.position, p.oa_id
                          FROM author_papers ap JOIN papers p USING (oa_id) WHERE ap.author = ?
                          ORDER BY p.cited_by_count DESC NULLS LAST LIMIT ?""", [oa, limit]).fetch_df()

@st.cache_data(ttl=3600)
def get_mentees(oa):
    return con.execute("""SELECT a.name, a.specialty, m.n_papers, m.first_collab_year, a.degree, a.in_rich_club
                          FROM mentor_mentee m JOIN authors a ON m.mentee = a.author_oa WHERE m.mentor = ?
                          ORDER BY m.n_papers DESC LIMIT 50""", [oa]).fetch_df()

@st.cache_data(ttl=3600)
def get_mentors(oa):
    return con.execute("""SELECT a.name, a.specialty, m.n_papers, m.first_collab_year, a.degree, a.in_rich_club
                          FROM mentor_mentee m JOIN authors a ON m.mentor = a.author_oa WHERE m.mentee = ?
                          ORDER BY m.n_papers DESC LIMIT 50""", [oa]).fetch_df()

@st.cache_data(ttl=3600)
def get_hierarchy():
    return con.execute("SELECT domain, subspecialty, label FROM hierarchy").fetch_df()

@st.cache_data(ttl=3600)
def leaderboard(level: str, key: str, spec: str, rc_only: bool, limit: int = 30):
    spec_clause = "" if spec == "All specialties" else "AND a.specialty = ?"
    params = [key] + ([] if spec == "All specialties" else [spec]) + [limit]
    rc_clause = "AND a.in_rich_club" if rc_only else ""
    if level == "domain":
        src, col = "domain_share", "domain"
    else:
        src, col = "subspecialty_share", "subspecialty"
    return con.execute(f"""SELECT a.author_oa, a.name, a.specialty, a.n_ni_core, a.in_rich_club,
                                  s.share_weight, s.n_papers
                           FROM {src} s JOIN authors a ON a.author_oa = s.author
                           WHERE s.{col} = ? AND a.is_clinical_ni AND a.likely_authentic {rc_clause} {spec_clause}
                           ORDER BY s.share_weight DESC LIMIT ?""", params).fetch_df()


def open_author(oa):
    st.session_state["selected_author_oa"] = oa
    st.session_state["page"] = "author"
    st.rerun()


def author_button(r, key_prefix, extra=""):
    star = "⭐ " if r.get("in_rich_club") else ""
    sp = f" · {r['specialty']}" if r.get("specialty") in SPEC else ""
    if st.button(f"{star}{r['name']}{sp}{extra}", key=f"{key_prefix}_{r['author_oa']}", width="stretch"):
        open_author(r["author_oa"])


def render_network_viz(oa, name, year, max_neighbors=120):
    coll = get_collaborators(oa)
    coll = coll[coll["first_collab_year"] <= year].copy()
    if len(coll) > max_neighbors:
        coll = coll.nlargest(max_neighbors, "joint_papers")
    coll["rc_at_year"] = coll["partner_rc_entry_year"].notna() & (coll["partner_rc_entry_year"] <= year)
    ego = get_author(oa)
    ego_rc = get_rc_entry_year(oa)
    ego_rc_now = ego_rc is not None and ego_rc <= year
    net = Network(height="620px", width="100%", bgcolor="#ffffff", font_color="#222", notebook=False)
    net.barnes_hut(gravity=-2000, central_gravity=0.3, spring_length=120, spring_strength=0.04)
    ego_spec = ego["specialty"] if ego and ego["is_clinical_ni"] else "Other"
    net.add_node(oa, label=name, size=35, font={"size": 20, "bold": True},
                 color={"background": spec_color(ego_spec), "border": RC_RED if ego_rc_now else "#333"},
                 borderWidth=5 if ego_rc_now else 1,
                 title=f"<b>{name}</b><br>{spec_label(ego_spec)}<br>{'Rich club' if ego_rc_now else 'Not yet rich club'} at {year}")
    ids = []
    for r in coll.itertuples(index=False):
        grp = r.partner_specialty if (r.partner_is_cni and r.partner_specialty in SPEC) else "Other"
        rc_y = int(r.partner_rc_entry_year) if pd.notna(r.partner_rc_entry_year) else "—"
        net.add_node(r.partner_oa, label=str(r.partner_name)[:25], size=12 + min(20, r.joint_papers),
                     color={"background": spec_color(grp), "border": RC_RED if r.rc_at_year else "#666"},
                     borderWidth=4 if r.rc_at_year else 1,
                     title=(f"<b>{r.partner_name}</b><br>{spec_label(grp)}<br>First collab: {int(r.first_collab_year)}"
                            f"<br>Joint papers: {int(r.joint_papers)}<br>Degree: {int(r.partner_degree)} · k-core {int(r.partner_kcore)}"
                            f"<br>Rich-club entry: {rc_y}"))
        net.add_edge(oa, r.partner_oa, value=min(15, r.joint_papers), color="#cccccc")
        ids.append(r.partner_oa)
    for r in get_partner_edges(tuple(ids), year).itertuples(index=False):
        net.add_edge(r.author, r.partner, value=min(10, r.n_joint), color="#888888")
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        net.write_html(f.name, notebook=False)
        return Path(f.name).read_text(encoding="utf-8")


SPEC_LEGEND = " · ".join(f"<span style='color:{c}'>●</span> {l}" for k, (l, c) in SPEC.items()
                         if k in ("ENS", "IN", "INR", "Mixed", "Other"))
SPEC_LEGEND += f" · <span style='color:{RC_RED}'>◯</span> red ring = rich club at the selected year"

# ---------------------------------------------------------------------------------------------- sidebar
if HAS_LOGO:
    st.sidebar.image(str(LOGO_PATH), width=240)
else:
    st.sidebar.title("Lumen Atlas")
st.sidebar.caption("Neurointerventional Co-Authorship Network")
st.sidebar.markdown("---")
st.session_state.setdefault("selected_author_oa", None)
st.session_state.setdefault("page", "home")

def goto(page):
    st.session_state["page"] = page
    st.session_state["selected_author_oa"] = None
    st.rerun()

st.sidebar.subheader("Navigate")
for label, key in [("🏠 Home", "home"), ("📖 Tutorial", "tutorial"), ("🧭 Specialty landscape", "landscape"),
                   ("🏆 Subspecialty leaderboards", "subspecialty"), ("📈 Eras & milestones", "eras"),
                   ("🔀 Compare authors", "compare"), ("✉️ Contact / Feedback", "contact")]:
    if st.sidebar.button(label, key=f"nav_{key}", width="stretch"):
        goto(key)
st.sidebar.markdown("---")
st.sidebar.subheader("Search author")
q = st.sidebar.text_input("Author name (any part)", value="")
if q:
    res = search_authors(q)
    if len(res):
        for _, r in res.iterrows():
            lab = f"{'⭐ ' if r['in_rich_club'] else ''}{r['name']} · {r['specialty']} · {int(r['n_ni_core'])} NI papers"
            if st.sidebar.button(lab, key=f"sel_{r['author_oa']}", width="stretch"):
                open_author(r["author_oa"])
    else:
        st.sidebar.info("No matches")
st.sidebar.markdown("---")
st.sidebar.subheader("Top of the network")
top_mode = st.sidebar.radio("Browse", ["Top by NI papers", "Top by degree", "Top by k-core", "Most cross-specialty"], index=0)
top_spec = st.sidebar.selectbox("Specialty", SPEC_FILTERS, index=0, key="top_spec")
sc = "" if top_spec == "All specialties" else f"AND a.specialty = '{top_spec}'"
order = {"Top by NI papers": "a.n_ni_core DESC", "Top by degree": "a.degree DESC",
         "Top by k-core": "a.k_core DESC, a.degree DESC", "Most cross-specialty": "i.cross_specialty_share DESC, a.n_ni_core DESC"}[top_mode]
extra = "AND i.joint_with_specialists >= 50" if top_mode == "Most cross-specialty" else ""
top_df = con.execute(f"""SELECT a.author_oa, a.name, a.specialty, a.in_rich_club FROM authors a
                         LEFT JOIN author_interdisciplinarity i ON i.author = a.author_oa
                         WHERE a.is_clinical_ni AND a.likely_authentic {sc} {extra} ORDER BY {order} LIMIT 30""").fetch_df()
for _, r in top_df.iterrows():
    if st.sidebar.button(f"{'⭐ ' if r['in_rich_club'] else ''}{r['name']}", key=f"top_{r['author_oa']}", width="stretch"):
        open_author(r["author_oa"])
auth.render_sidebar_user_card()

sel = st.session_state.get("selected_author_oa")
page = st.session_state.get("page", "home")

# ---------------------------------------------------------------------------------------------- tutorial
if page == "tutorial":
    st.title("📖 Tutorial — using Lumen Atlas")
    st.markdown(f"""
### What is Lumen Atlas?
An interactive explorer of the global **neurointerventional** co-authorship network: every author with at least one
procedural neuroendovascular paper indexed by OpenAlex, through **{END_LABEL}**. It is the companion to
Cortex Atlas (neurosurgery). Neurointervention is practised by three parent specialties, so the field here is defined
by **what a paper is about** (title and abstract), and each author is then assigned a **parent specialty** from their
affiliations.

### Parent specialty
- **ENS** endovascular neurosurgery · **IN** interventional neurology · **INR** interventional neuroradiology ·
  **Joint department** when affiliations are split (e.g. "Neurology & Neurosurgery").
- Assigned from the author's own affiliation strings on their neurointerventional papers, then aligned with the
  manually reviewed Cortex Atlas neurosurgeon list (a reviewed neurosurgeon is ENS; a reviewed non-neurosurgeon is never ENS).
- **Clinical neurointerventionalist (CNI)**: ≥ 5 procedural NI papers, NI papers ≥ 15% of all their papers, and a
  clinical department affiliation — refined by manual review. Leaderboards show CNIs only.

### Interdisciplinarity
- **Cross-specialty share**: of an author's joint papers with CNI collaborators from the three parent specialties,
  the fraction written with a *different* specialty than their own.
- **Partner diversity** (Blau index, 0–0.67): how evenly an author's specialist collaborators spread across ENS, IN and INR.
- **Specialty landscape** page: who writes the field over time, and how strongly each specialty prefers its own
  (observed ÷ expected collaboration; 1 = no preference).

### Subspecialty hierarchy
Papers are tagged with 25 subdomains grouped into 9 domains (e.g. *Ischemic stroke → Thrombectomy, Imaging & selection,
Systems & transfer…*). A paper can carry several tags; each contributes a fractional weight. Leaderboards work at domain
or subdomain level and can be filtered by specialty and rich club.

### Author profile tabs
Career · Network at year (nodes coloured by specialty, red ring = rich club) · Collaborators · Specialty &
interdisciplinarity · Subspecialty (domain → subdomain sunburst) · Mentor/Mentee · Top papers.

### Key concepts
- **Rich club**: degree > **{K_STAR}** — the smallest degree at which the normalised rich-club coefficient
  ρ(k) = φ(k)/φ_rand(k) reaches {INFO.get('tau') or '—'} and stays above it ({int(INFO['n_nulls'])} degree-preserving random
  graphs). ρ(k) peaks at {float(INFO.get('rho_peak') or 0):.2f} around degree {int(INFO.get('rho_peak_k') or 0)}. Cortex Atlas
  uses the same persistence rule with a lower threshold (1.20); neurointerventionalists sit on large trial author lists,
  so a stricter threshold is needed to keep the rich club selective.
- **k-core**: largest subgraph where every author has ≥ k collaborators; a measure of embeddedness.
- **NI papers**: procedural neuroendovascular papers. Neurovascular-disease papers without an explicit procedure
  count toward the network but not toward "NI papers".

### Data and limits
OpenAlex (CC0), queried May–October 2026; analyses include publications through {END_LABEL} (2026 = January–June).
Author identities were consolidated by automated and manual review, but errors remain — use **Contact / Feedback**.
Specialty is inferred from affiliation text and can be wrong for joint departments or unusual department names.
""")
    st.stop()

# ---------------------------------------------------------------------------------------------- contact
if page == "contact":
    st.title("✉️ Contact and feedback")
    st.markdown(f"""Lumen Atlas is a research tool maintained by **Ali M. Alawieh, MD, PhD**, built on public bibliometric
data from OpenAlex (CC0).

**Write to us if** your profile is split or merged incorrectly, your parent specialty is wrong, you want to be excluded,
or you have suggestions or questions about the methods.

📧 **{CONTACT_EMAIL}**

For corrections please include your name as published, ORCID, your OpenAlex ID (e.g. `https://openalex.org/A5…`) and
what should change. We respond within two weeks.

**Citing**: Alawieh AM, et al. Lumen Atlas (in preparation, 2026); data from OpenAlex.""")
    st.stop()

# ---------------------------------------------------------------------------------------------- specialty landscape
if page == "landscape":
    st.title("🧭 Specialty landscape")
    st.markdown("How the three parent specialties share and co-produce the neurointerventional literature.")
    fs = con.execute("SELECT * FROM field_specialty_year ORDER BY period").fetch_df()
    fs = fs[fs.specialty.isin(["ENS", "IN", "INR", "Mixed"])]
    fs["Specialty"] = fs.specialty.map(spec_label)
    fig = px.area(fs, x="period", y="share", color="Specialty",
                  color_discrete_map={spec_label(k): spec_color(k) for k in SPEC})
    fig.update_layout(title="Share of procedural NI authorships by clinical neurointerventionalists, by parent specialty (5-year bins)",
                      xaxis_title="Period start", yaxis_title="Share", yaxis_tickformat=".0%", height=420)
    st.plotly_chart(fig, width="stretch")
    st.caption("The final bin (2025–) covers January 2025 to June 2026.")

    st.subheader("Do specialties collaborate across lines?")
    mx = con.execute("SELECT * FROM field_mixing").fetch_df()
    eras = ["before 2000", "2000-2009", "2010-2014", "2015-2019", "2020-2026"]
    era = st.select_slider("Era (year a collaboration began)", options=eras, value="2020-2026")
    m = mx[mx.era == era].pivot(index="s1", columns="s2", values="obs_exp").reindex(index=["ENS", "IN", "INR"], columns=["ENS", "IN", "INR"])
    fig = go.Figure(go.Heatmap(z=m.values, x=[spec_label(c) for c in m.columns], y=[spec_label(i) for i in m.index],
                               colorscale="RdBu_r", zmid=1, text=[[f"{v:.2f}" for v in row] for row in m.values],
                               texttemplate="%{text}", colorbar=dict(title="obs / exp")))
    fig.update_layout(height=420, title=f"Collaboration intensity, observed ÷ expected ({era})")
    st.plotly_chart(fig, width="stretch")
    trend = mx[mx.s1 == mx.s2].copy(); trend["Specialty"] = trend.s1.map(spec_label)
    trend["era"] = pd.Categorical(trend.era, eras, ordered=True); trend = trend.sort_values("era")
    fig = px.line(trend, x="era", y="obs_exp", color="Specialty", markers=True,
                  color_discrete_map={spec_label(k): spec_color(k) for k in SPEC})
    fig.add_hline(y=1, line_dash="dot")
    fig.update_layout(title="Within-specialty preference over time (1 = no preference)", yaxis_title="obs / exp", height=360)
    st.plotly_chart(fig, width="stretch")
    st.caption("Values above 1 mean a specialty collaborates with itself more than its share of the field predicts. "
               "Joint papers between clinical neurointerventionalists, by the year each collaboration began.")

    st.subheader("Bridges between specialties")
    st.caption("Clinical neurointerventionalists with ≥ 50 joint papers with specialists, ranked by cross-specialty share.")
    bspec = st.selectbox("Own specialty", ["ENS", "IN", "INR"], key="bridge_spec")
    br = con.execute("""SELECT a.author_oa, a.name, a.specialty, a.in_rich_club, i.cross_specialty_share, i.joint_with_specialists
                        FROM authors a JOIN author_interdisciplinarity i ON i.author = a.author_oa
                        WHERE a.is_clinical_ni AND a.likely_authentic AND a.specialty = ? AND i.joint_with_specialists >= 50
                        ORDER BY i.cross_specialty_share DESC LIMIT 20""", [bspec]).fetch_df()
    cols = st.columns(2)
    for j, (_, r) in enumerate(br.iterrows()):
        with cols[j % 2]:
            author_button(r, "bridge", f" · {r['cross_specialty_share']:.0%} cross-specialty")
    st.stop()

# ---------------------------------------------------------------------------------------------- leaderboards
if page == "subspecialty":
    st.title("🏆 Subspecialty leaderboards")
    h = get_hierarchy()
    c1, c2, c3, c4 = st.columns([2, 3, 2, 1])
    dom = c1.selectbox("Domain", list(dict.fromkeys(h.domain)))
    subs = h[h.domain == dom]
    sub_opt = ["(whole domain)"] + list(subs.label)
    sub_lab = c2.selectbox("Subdomain", sub_opt)
    spec = c3.selectbox("Specialty", SPEC_FILTERS)
    rc_only = c4.checkbox("Rich club only")
    if sub_lab == "(whole domain)":
        lb = leaderboard("domain", dom, spec, rc_only); title = dom
    else:
        key = subs[subs.label == sub_lab].subspecialty.iat[0]
        lb = leaderboard("sub", key, spec, rc_only); title = f"{dom} → {sub_lab}"
    st.subheader(title)
    st.caption("Clinical neurointerventionalists ranked by share-weight (sum of fractional per-paper weights). "
               "⭐ = rich club.")
    if lb.empty:
        st.info("No authors match these filters.")
    else:
        mix = lb.specialty.value_counts()
        st.markdown("Specialty mix of the top 30: " + " · ".join(f"{spec_label(k)} **{v}**" for k, v in mix.items()))
        cols = st.columns(2)
        for j, (_, r) in enumerate(lb.iterrows()):
            with cols[j % 2]:
                author_button(r, f"lb_{dom}_{sub_lab}_{spec}", f" · share {r['share_weight']:.1f} · {int(r['n_papers'])} papers")
    st.stop()

# ---------------------------------------------------------------------------------------------- eras & milestones
if page == "eras":
    st.title("📈 Eras & milestones")
    fd = con.execute("SELECT * FROM field_domain_year WHERE year <= 2026").fetch_df()
    level = st.radio("Level", ["Domains", "Subdomains of one domain"], horizontal=True)
    if level == "Domains":
        d = fd.groupby(["year", "domain"], as_index=False).share.sum()
        fig = px.area(d, x="year", y="share", color="domain")
    else:
        dsel = st.selectbox("Domain", list(dict.fromkeys(get_hierarchy().domain)))
        d = fd[fd.domain == dsel].merge(get_hierarchy(), on=["subspecialty", "domain"])
        fig = px.area(d, x="year", y="share", color="label")
    for b in ERA_BREAKS:
        fig.add_vline(x=b, line_dash="dash", line_color="#333")
    fig.update_layout(height=460, yaxis_tickformat=".0%", yaxis_title="Share of procedural NI output", xaxis_title="Year",
                      title="Subject composition of the field; dashed lines = era boundaries (change-point detection, preliminary)")
    st.plotly_chart(fig, width="stretch")
    st.caption("Shares within each year; 2026 covers January–June.")
    ml = con.execute("SELECT * FROM field_milestones").fetch_df()
    opts = sorted(ml.milestone.unique())
    default = [m for m in opts if any(k in m for k in ("GDC", "Flow diverter", "Stent retriever", "2015", "MMA"))]
    pick = st.multiselect("Milestone topics", opts, default=default)
    if pick:
        fig = px.line(ml[ml.milestone.isin(pick)].sort_values("year"), x="year", y="n", color="milestone")
        fig.update_layout(height=420, yaxis_title="Papers per year", title="Diffusion of milestone devices, techniques and trials")
        st.plotly_chart(fig, width="stretch")
    st.stop()

# ---------------------------------------------------------------------------------------------- compare
if page == "compare":
    st.title("🔀 Compare authors")
    PAL = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#56B4E9", "#E69F00"]
    st.session_state.setdefault("compare_authors", [])
    cq = st.text_input("Search authors to add", placeholder="e.g. Nogueira, Siddiqui, Goyal")
    chosen = {o for o, _ in st.session_state["compare_authors"]}
    if cq:
        hits = search_authors(cq, 15)
        hc = st.columns(3)
        for j, (_, r) in enumerate(hits.iterrows()):
            with hc[j % 3]:
                full = len(st.session_state["compare_authors"]) >= 6
                if st.button(("✓ " if r["author_oa"] in chosen else "➕ ") + f"{r['name']} · {r['specialty']}",
                             key=f"cmp_{r['author_oa']}", disabled=r["author_oa"] in chosen or full, width="stretch"):
                    st.session_state["compare_authors"].append((r["author_oa"], r["name"])); st.rerun()
    sel_list = list(st.session_state["compare_authors"])
    if sel_list:
        cc = st.columns(len(sel_list))
        for i, (oa, nm) in enumerate(sel_list):
            with cc[i]:
                a = get_author(oa)
                st.markdown(f"<div style='border-left:6px solid {PAL[i]};padding-left:8px'><b>{nm}</b></div>", unsafe_allow_html=True)
                st.caption(f"{spec_label(a['specialty'])}{' · ⭐ rich club' if a['in_rich_club'] else ''}")
                st.metric("NI papers", f"{int(a['n_ni_core']):,}")
                st.metric("Degree", f"{int(a['degree']):,}")
                st.metric("Cross-specialty share", f"{a['cross_specialty_share']:.0%}" if pd.notna(a['cross_specialty_share']) else "—")
                if st.button("✕ remove", key=f"rm_{oa}"):
                    st.session_state["compare_authors"] = [x for x in sel_list if x[0] != oa]; st.rerun()
                if st.button("Open profile", key=f"op_{oa}"):
                    open_author(oa)
        fig = go.Figure()
        for i, (oa, nm) in enumerate(sel_list):
            y = get_yearly(oa)
            fig.add_trace(go.Scatter(x=y.year, y=y.cum_core, name=f"{nm} — NI papers", line=dict(color=PAL[i], width=3)))
            fig.add_trace(go.Scatter(x=y.year, y=y.cum_partners, name=f"{nm} — collaborators", line=dict(color=PAL[i], dash="dot")))
        fig.add_hline(y=K_STAR, line_dash="dot", annotation_text=f"Rich-club threshold ({K_STAR})")
        fig.update_layout(height=480, xaxis_title="Year", yaxis_title="Cumulative", legend=dict(orientation="h", y=-0.25))
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("Search above and add up to six authors.")
    st.stop()

# ---------------------------------------------------------------------------------------------- home
if not sel:
    if HAS_LOGO:
        st.columns([1, 2, 1])[1].image(str(LOGO_PATH), width=380)
    else:
        st.title("Lumen Atlas")
    st.markdown("<h3 style='text-align:center;margin-top:0'>Neurointerventional Co-Authorship Network</h3>", unsafe_allow_html=True)
    st.markdown(f"<p style='text-align:center'>Endovascular neurosurgery · interventional neurology · interventional "
                f"neuroradiology — publications through {END_LABEL}.</p>", unsafe_allow_html=True)
    s = con.execute("""SELECT count(*) n, count(*) FILTER (WHERE is_clinical_ni) cni,
                              count(*) FILTER (WHERE is_clinical_ni AND in_rich_club) rc FROM authors WHERE likely_authentic""").fetch_df().iloc[0]
    npap = con.execute("SELECT count(*) FILTER (WHERE ni_core) FROM papers").fetchone()[0]
    c = st.columns(4)
    c[0].metric("Network authors", f"{int(s.n):,}"); c[1].metric("Clinical neurointerventionalists", f"{int(s.cni):,}")
    c[2].metric("Rich-club CNIs", f"{int(s.rc):,}"); c[3].metric("Procedural NI papers", f"{int(npap):,}")
    sp = con.execute("""SELECT specialty, count(*) n FROM authors WHERE is_clinical_ni AND likely_authentic GROUP BY 1""").fetch_df()
    sp["Specialty"] = sp.specialty.map(spec_label)
    fig = px.pie(sp, values="n", names="Specialty", hole=0.55, color="Specialty",
                 color_discrete_map={spec_label(k): spec_color(k) for k in SPEC})
    fig.update_layout(height=360, title="Clinical neurointerventionalists by parent specialty")
    st.plotly_chart(fig, width="stretch")
    st.markdown("""**Start here:** search an author in the sidebar · open **🧭 Specialty landscape** to see how ENS, IN and INR
share the field · **🏆 Subspecialty leaderboards** for domain → subdomain rankings · **📈 Eras & milestones** for how the
field's subject matter has shifted.""")
    st.stop()

# ---------------------------------------------------------------------------------------------- author profile
a = get_author(sel)
if not a:
    st.error("Author not found."); st.stop()
yearly, coll, sub = get_yearly(sel), get_collaborators(sel), get_subspecialty(sel)
rc_year = get_rc_entry_year(sel)
hc = st.columns([3, 2])
with hc[0]:
    st.title(a["name"])
    cni = "**Clinical neurointerventionalist**" if a["is_clinical_ni"] else "*Collaborator (not classified as a clinical neurointerventionalist)*"
    st.markdown(f"<span style='background:{spec_color(a['specialty'])};color:white;padding:2px 8px;border-radius:10px'>"
                f"{spec_label(a['specialty'])}</span> &nbsp; {cni} · {'⭐ **Rich-club member**' if a['in_rich_club'] else 'Not in rich club'}",
                unsafe_allow_html=True)
    if a.get("specialty_source") and str(a["specialty_source"]).startswith("cortex_PI"):
        st.caption("Specialty confirmed by manual review.")
    st.caption(f"OpenAlex: {a['author_oa']}")
with hc[1]:
    st.markdown(f"**NI papers**: {int(a['n_ni_core']):,} · **neurovascular field**: {int(a['n_ni_field']):,} · "
                f"**all papers**: {int(a['n_total_papers']):,}")
    st.markdown(f"**Active**: {a['first_year'] or '—'}–{a['last_year'] or '—'} · **Country**: {a['country'] or '—'}")
    st.markdown(f"**Degree**: {int(a['degree']):,} · **k-core**: {int(a['k_core'])} · **PageRank**: {a['pagerank']:.2e}")
    if rc_year:
        st.markdown(f"**Crossed rich-club threshold**: {rc_year}")
    if pd.notna(a.get("cross_specialty_share")):
        pct = f" ({a['cross_pct']:.0%} percentile among CNIs)" if pd.notna(a.get("cross_pct")) else ""
        st.markdown(f"**Cross-specialty share**: {a['cross_specialty_share']:.0%}{pct}")

t_car, t_net, t_col, t_spec, t_sub, t_men, t_pap = st.tabs(
    ["Career", "Network at year", "Collaborators", "Specialty & interdisciplinarity", "Subspecialty", "Mentor / Mentee", "Top papers"])

with t_car:
    if len(yearly):
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=yearly.year, y=yearly.cum_core, name="Cumulative NI papers", line=dict(color="#0072B2", width=3)))
        fig.add_trace(go.Scatter(x=yearly.year, y=yearly.cum_partners, name="Cumulative collaborators", line=dict(color="#D55E00", width=3)))
        if rc_year:
            fig.add_vline(x=rc_year, line_dash="dash", line_color=RC_RED, annotation_text=f"Rich-club entry ({rc_year})")
        fig.add_hline(y=K_STAR, line_dash="dot", annotation_text=f"Rich-club threshold ({K_STAR})")
        fig.update_layout(height=420, xaxis_title="Year", yaxis_title="Count", legend=dict(orientation="h", y=1.05))
        st.plotly_chart(fig, width="stretch")
        fig2 = go.Figure([go.Bar(x=yearly.year, y=yearly.core_this_year, name="NI papers", marker_color="#0072B2"),
                          go.Bar(x=yearly.year, y=yearly.new_partners, name="New collaborators", marker_color="#009E73")])
        fig2.update_layout(barmode="group", height=320, title="Per year")
        st.plotly_chart(fig2, width="stretch")

with t_net:
    y0 = int(yearly.year.min()) if len(yearly) else 1990
    y1 = int(yearly.year.max()) if len(yearly) else 2026
    yr = st.slider("Year", y0, max(y1, y0 + 1), y1)
    mxn = st.slider("Max collaborators shown", 20, 300, 120, 20)
    with st.spinner("Rendering network…"):
        st.components.v1.html(render_network_viz(sel, a["name"], yr, mxn), height=640)
    st.markdown(SPEC_LEGEND, unsafe_allow_html=True)

with t_col:
    if len(coll):
        d = coll.copy()
        d["Specialty"] = [spec_label(s) if c else spec_label("Other") for s, c in zip(d.partner_specialty, d.partner_is_cni)]
        d["Rich club"] = d.partner_in_rc.map({True: "⭐", False: ""})
        d = d[["partner_name", "Specialty", "first_collab_year", "joint_papers", "partner_degree", "partner_kcore", "partner_rc_entry_year", "Rich club"]]
        d.columns = ["Partner", "Specialty", "First collab", "Joint papers", "Degree", "k-core", "RC entry", "RC"]
        st.dataframe(d.sort_values("Joint papers", ascending=False), width="stretch", height=520)
    else:
        st.info("No collaborators recorded.")

with t_spec:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Own affiliations** — share of this author's NI-field papers with each department type")
        aff = pd.DataFrame({"Department": ["Neurosurgery", "Neurology", "Radiology", "Explicit NI unit"],
                            "share": [a["s_ns"], a["s_neuro"], a["s_rad"], a["s_ni"]]})
        fig = go.Figure(go.Bar(x=aff.share, y=aff.Department, orientation="h",
                               marker_color=["#0072B2", "#D55E00", "#009E73", "#666"], text=[f"{v:.0%}" for v in aff.share], textposition="outside"))
        fig.update_layout(xaxis_tickformat=".0%", xaxis_range=[0, 1.1], height=300, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width="stretch")
        st.caption(f"Based on {int(a['n_affil'] or 0)} authorships with affiliation text. Joint departments count toward both.")
    with c2:
        st.markdown("**Collaborators** — joint papers by the collaborator's parent specialty")
        mix = pd.DataFrame({"g": ["ENS", "IN", "INR", "Mixed", "Other"],
                            "w": [a.get(k) or 0 for k in ("w_ens", "w_in", "w_inr", "w_mixed", "w_other")]})
        mix = mix[mix.w > 0]
        if len(mix):
            mix["Specialty"] = mix.g.map(spec_label)
            fig = px.pie(mix, values="w", names="Specialty", hole=0.5, color="Specialty",
                         color_discrete_map={spec_label(k): spec_color(k) for k in SPEC})
            fig.update_layout(height=300, margin=dict(t=10, b=10))
            st.plotly_chart(fig, width="stretch")
    m = st.columns(3)
    m[0].metric("Cross-specialty share", f"{a['cross_specialty_share']:.0%}" if pd.notna(a.get("cross_specialty_share")) else "—",
                help="Of joint papers with ENS/IN/INR clinical neurointerventionalists, the share with a different specialty than this author's.")
    m[1].metric("Partner diversity (Blau)", f"{a['partner_diversity']:.2f}" if pd.notna(a.get("partner_diversity")) else "—",
                help="0 = all specialist collaborators from one specialty; 0.67 = evenly split across ENS, IN and INR.")
    m[2].metric("Percentile among CNIs", f"{a['cross_pct']:.0%}" if pd.notna(a.get("cross_pct")) else "—",
                help="Among clinical neurointerventionalists with ≥ 10 joint papers with specialists.")

with t_sub:
    if len(sub):
        fig = px.sunburst(sub, path=["domain", "label"], values="share_weight")
        fig.update_layout(height=520, margin=dict(t=10, b=10))
        st.plotly_chart(fig, width="stretch")
        with st.expander("Table"):
            st.dataframe(sub.rename(columns={"label": "subdomain"})[["domain", "subdomain", "share_weight", "n_papers"]], width="stretch")
    else:
        st.info("No subspecialty-tagged papers for this author.")

with t_men:
    st.info("Inferred from authorship order on NI-field papers: last author ↔ first author, within the first 10 years of "
            "the junior author's NI publishing. Informal mentorship without joint papers is not visible.")
    c1, c2 = st.columns(2)
    for col, title, df in ((c1, "Early-career mentees", get_mentees(sel)), (c2, "Senior collaborators / mentors", get_mentors(sel))):
        with col:
            st.subheader(title)
            if len(df):
                df["specialty"] = df.specialty.map(spec_label); df["RC"] = df.in_rich_club.map({True: "⭐", False: ""})
                st.dataframe(df[["name", "specialty", "first_collab_year", "n_papers", "degree", "RC"]], width="stretch", height=400)
            else:
                st.caption("None identified.")

with t_pap:
    tp = get_top_papers(sel)
    if len(tp):
        tp["link"] = tp.oa_id
        tp["type"] = tp.ni_core.map({True: "Procedural NI", False: "Neurovascular"})
        st.dataframe(tp[["year", "title", "cited_by_count", "type", "position", "link"]], width="stretch", height=520,
                     column_config={"link": st.column_config.LinkColumn("OpenAlex")})
    else:
        st.info("No papers.")
