# Delivery Alternatives for `metagen`

Reference catalog of options for delivering `metagen` to non-technical librarians.
Surveyed June 2026. Each option lists cost, setup time, friction (1=easiest, 5=hardest),
and a real example where one is known.

---

## Decision Flowchart

```
Do you have IT support to host a server?
├─ YES → Tailscale + VPS + Caddy (A4)        ← best fit for universities
└─ NO
   → Is async (2-10 min) latency acceptable?
      ├─ YES → GitHub Pages + Actions (A2)   ← the "pseudo-static" pattern
      └─ NO  → Gradio on HF Spaces (A1)      ← fastest, free, works today
```

---

## Tier A — Best Fits (recommend shortlist)

### A1. Gradio on Hugging Face Spaces

| Field | Value |
|---|---|
| Cost | **$0** (free 2 CPU / 16 GB RAM) |
| Setup | ~30 min |
| Friction | 1/5 |
| Best for | Getting something live this week with zero IT involvement |

Gradio wraps a Python function in a web UI in ~20 lines. Native support for forms,
file upload, streaming LLM output, markdown rendering. HF Spaces gives you a secrets
tab for API keys, git-push-to-deploy, and auto-HTTPS. URL: `https://<org>-metagen.hf.space`.

- **Gradio docs:** https://www.gradio.app/
- **HF Spaces docs:** https://huggingface.co/docs/hub/spaces
- **HF Spaces secrets:** https://huggingface.co/docs/hub/spaces-overview#secrets
- **Docker SDK on Spaces:** https://huggingface.co/docs/hub/spaces-sdks-docker
- **Example (scholarly metadata tool on HF):** https://huggingface.co/spaces/magedbekheet/literature-metadata-intelligence-dashboard
- **Example (Streamlit GenAI chatbot):** https://huggingface.co/spaces/shinzoxD/streamlit-genai-chatbot

**Deployment recipe:**

```dockerfile
# Dockerfile
FROM python:3.11-slim
COPY . /app
WORKDIR /app
RUN pip install -e .
RUN pip install gradio uvicorn
EXPOSE 7860
CMD ["python", "app.py"]  # gr.Interface.launch(server_name="0.0.0.0", server_port=7860)
```

Set `OPENAI_API_KEY` (or `ZAI_API_KEY`) in **Space Settings → Secrets**.

---

### A2. GitHub Pages + GitHub Actions (the "pseudo-static" pattern)

| Field | Value |
|---|---|
| Cost | **$0** |
| Setup | 2-4 hrs |
| Friction | 2/5 |
| Best for | Zero-cost, zero-server, auditable workflow that fits library governance |

This is the **literal "pseudo-static website"** pattern. Architecture:

1. Static form on GitHub Pages (HTML/JS, no backend).
2. Form submit → `repository_dispatch` event → triggers GitHub Action.
3. Action runs `metagen` in CI runner (API key stored in **GitHub Actions secrets**, never exposed).
4. Action writes output JSON to a branch, opens a PR.
5. Librarian gets email, reviews PR, merges.
6. Merge triggers GH Pages rebuild → new output available for download.

**Latency:** 2-10 min async. **University IT:** already approves GitHub.

- **GitHub Pages:** https://pages.github.com/
- **GitHub Actions docs:** https://docs.github.com/en/actions
- **Actions secrets:** https://docs.github.com/en/actions/security-guides/using-secrets-in-github-actions
- **`repository_dispatch` event:** https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#repository_dispatch
- **Example (static forms → GHA backend, 1.6k stars):** https://github.com/Luigigreco/gitforms
- **Example (Netlify + dispatch plugin):** https://github.com/bahmutov/netlify-plugin-github-dispatch
- **Example (Formspree-style GH Actions form):** https://github.com/bytebeast/newshub

---

### A3. Streamlit Community Cloud

| Field | Value |
|---|---|
| Cost | **$0** (3 apps, sleeps after ~12h inactivity) |
| Setup | ~10 min |
| Friction | 1/5 |
| Best for | Form-heavy apps with rich tables, file upload, downloads |

Streamlit is better than Gradio for **form-heavy** apps (which metadata enrichment is).
Multi-page, file upload, data tables, downloads are all native. `st.secrets` for API keys.

- **Streamlit:** https://streamlit.io/
- **Streamlit Community Cloud:** https://streamlit.io/cloud
- **st.secrets docs:** https://docs.streamlit.io/library/advanced-features/secrets-management
- **Example gallery:** https://streamlit.io/gallery

---

### A4. Tailscale + tiny VPS + Caddy (the "university stealth" option)

| Field | Value |
|---|---|
| Cost | $0-10/mo (Oracle free tier VM or university VM) |
| Setup | 2-3 hrs |
| Friction | 3/5 |
| Best for | IT-restricted environments that allow private VMs |

Spin up a small VM, install Tailscale + Caddy + FastAPI.
Caddy gives auto-HTTPS. Tailscale gives private mesh access — **zero public exposure**.
URL: `https://metagen.youruni.ts.net` (only resolves inside the tailnet).

- **Tailscale:** https://tailscale.com/
- **Tailscale ACLs:** https://tailscale.com/kb/1018/acls
- **Caddy:** https://caddyserver.com/
- **Caddy + FastAPI pattern:** https://caddyserver.com/docs/quick-starts/reverse-proxy
- **Oracle Cloud free tier:** https://www.oracle.com/cloud/free/
- **FastAPI:** https://fastapi.tiangolo.com/

---

## Tier B — Viable but heavier

### B1. Marimo (notebook-as-app, with WASM export)

| Field | Value |
|---|---|
| Cost | Free |
| Setup | 1-2 hrs |
| Friction | 2/5 |
| Best for | Air-gapped libraries; reactive notebook UX |

`.py` notebook files, `marimo run` serves as a web app. **WASM export** runs entirely
in browser, no server — works for air-gapped libraries. Catch: WASM can't reach OpenAI
without network, so you'd need a local proxy for offline use.

- **Marimo:** https://marimo.io/
- **Marimo WASM export:** https://docs.marimo.io/guides/wasm/
- **GitHub:** https://github.com/marimo-team/marimo

---

### B2. Open WebUI + Pipe Functions (ChatGPT-like UX)

| Field | Value |
|---|---|
| Cost | Requires server ($5-7/mo Railway/Render) |
| Setup | 2-3 hrs |
| Friction | 3/5 |
| Best for | Libraries where staff already use ChatGPT and want a similar interface |

Wrap `metagen` as a **Pipe Function** — it appears as a "model" in the sidebar.
Librarians chat with it like ChatGPT.

- **Open WebUI:** https://openwebui.com/
- **GitHub:** https://github.com/open-webui/open-webui
- **Pipe Functions docs:** https://docs.openwebui.com/features/plugin/functions/
- **Railway:** https://railway.app/
- **Render:** https://render.com/

---

### B3. Railway / Render / Fly.io (always-on FastAPI)

| Field | Value |
|---|---|
| Cost | **$5-7/mo** for always-on |
| Setup | ~20 min |
| Friction | 2/5 |
| Best for | Conventional website with always-on availability, no cold starts |

FastAPI + Jinja2 templates = traditional form-submit-results web app.

- **Railway:** https://railway.app/
- **Render:** https://render.com/
- **Fly.io:** https://fly.io/
- **FastAPI deployment guide:** https://fastapi.tiangolo.com/deployment/
- **Example (FastAPI ML on Railway):** https://github.com/mehdighelich1379/loan-ml-system

---

### B4. Flet (desktop app)

| Field | Value |
|---|---|
| Cost | Free |
| Setup | 2-3 hrs |
| Friction | 3/5 |
| Best for | Desktop icon librarians double-click; IT permits unsigned installs |

Python writes once → desktop app for Win/Mac/Linux (plus web/PWA). Avoid PyInstaller
directly (AV false positives); Flet handles packaging.

- **Flet:** https://flet.dev/
- **Flet packaging:** https://flet.dev/docs/publish/
- **GitHub:** https://github.com/flet-dev/flet

---

### B5. Cloudflare Workers + Pages (serverless Python)

| Field | Value |
|---|---|
| Cost | Free 125K invocations/day |
| Setup | ~30 min |
| Friction | 3/5 |
| Best for | IT shops that love Cloudflare and hate servers |

**Catch:** Python support is in beta; some packages don't work. Test `instructor` +
`httpx` compatibility first.

- **Cloudflare Workers Python:** https://developers.cloudflare.com/workers/languages/python/
- **Cloudflare Pages:** https://pages.cloudflare.com/

---

## Tier C — Do NOT recommend

| Option | Why not |
|---|---|
| **PyScript / Pyodide client-side** | Exposes API keys in devtools. Fatal for any LLM call. https://pyodide.org/ |
| **PikaPods** | Only runs catalog apps, can't deploy arbitrary Python. https://www.pikapods.com/ |
| **Vercel Python** | 300s function timeout kills long LLM jobs; cold starts painful. https://vercel.com/docs/functions/serverless-functions |
| **Docker on librarian laptops** | Docker Desktop install is a non-starter for non-technical users + IT restrictions. |

---

## UX Patterns to Steal from Existing Metadata Tools

Surveyed: DataCite Fabrica, Crossref, Zenodo, OpenAIRE, Dryad, Figshare, OSTI,
ArchivesSpace, Dublin Core generators, LLM tools (AutoDDG, LLMDap, Dataverse AI,
Croissant Baker).

### Must-have UX

1. **Required fields with red asterisks** (90% of tools).
2. **Creators as repeatable blocks** with ORCID lookup + ROR affiliation autocomplete.
   - ORCID API: https://orcid.org/developers
   - ROR API: https://ror.org/
3. **Resource type from DataCite controlled vocabulary** (dropdown, not free text).
   - https://schema.datacite.org/meta/kernel-4.6/
4. **Save-triggers-validation** (Zenodo/Figshare/Dryad pattern).
5. **LLM output clearly labeled DRAFT, requires human review before publish.**

### Stretch UX (differentiators)

- **Fabrica-style instant field-level validation** — green/red border on blur.
  Only Fabrica does this today. Big trust signal for librarians.
  https://datacite.org/fabrica.html
- **Figshare's right-side action panel** — DOI reserve, embargo, private link,
  custom thumbnail visible without scrolling. https://figshare.com/
- **Dryad's collaborative pipeline** — submitter → curator → publish with edit locking.
  https://datadryad.org/
- **Multi-format citation export** — BibTeX, RIS, DataCite XML, Dublin Core.
- **Novel opportunity:** Side-by-side comparison of original input vs LLM-generated
  metadata. **No competitor does this today.**

### Reference Tools

- **DataCite Fabrica:** https://fabrica.datacite.org/
- **Zenodo:** https://zenodo.org/
- **Figshare:** https://figshare.com/
- **Dryad:** https://datadryad.org/
- **OpenAIRE:** https://www.openaire.eu/
- **OSTI:** https://www.osti.gov/
- **ArchivesSpace:** https://archivesspace.org/
- **Croissant Baker (MLCommons):** https://github.com/mlcommons/croissant

---

## Recommended Path for `metagen`

| Phase | Tool | Why |
|---|---|---|
| Week 1 (demo) | **Gradio on HF Spaces (A1)** | 30-min setup, live URL to show librarians |
| Month 1 (pilot) | **GitHub Pages + Actions (A2)** | Matches library governance, zero ongoing cost |
| Month 3 (production) | **Tailscale + VPS + Caddy (A4)** | If pilot succeeds and IT permits private VMs |
| Always (differentiator) | **Side-by-side diff viewer** | No competitor has this |

---

## Comparable Tools — AI/LLM Scholarly Metadata Enrichment

Tools with the same scope as `metagen` (generate or enrich scholarly metadata using
LLMs or other AI). Organized by closeness of scope.

### Tier 1 — Direct same-scope (LLM-generated scholarly metadata)

These are the closest competitors to `metagen`. All use LLMs to generate or enrich
scholarly dataset metadata from minimal inputs.

| Tool | Scope | Notes |
|---|---|---|
| **Croissant Baker** | LLM-assisted ML dataset metadata in [Croissant](https://github.com/mlcommons/croissant) schema | MLCommons. Web UI + LLM. Closest analogue to `metagen`. https://github.com/mlcommons/croissant |
| **AutoDDG** | Auto Data Documentation Generator — LLM produces Data Documentation Guidelines from datasets | Academic project. https://github.com/sahitj/AutoDDG (search required — multiple forks exist) |
| **LLMDap** | LLM-generated Data Management Plans (DMPs) | Academic; DMPs are metadata-adjacent. https://github.com/research-boring/llmdap (search required) |
| **Dataverse AI Assistant** | AI-assisted metadata entry for [Dataverse](https://dataverse.org/) installations | Harvard IQSS has explored AI helpers; check current Dataverse releases. https://dataverse.org/ |

### Tier 2 — ML-based scholarly metadata extraction (not LLM, but same deliverable)

These use traditional NLP/ML (CRF, transformers, regex) to extract metadata from PDFs
or documents. Useful as comparators for output quality and as **input enrichers** for
`metagen` (e.g., run Grobid on a PDF → feed to `metagen` for LLM expansion).

| Tool | Scope | Notes |
|---|---|---|
| **Grobid** | ML-based PDF parsing → TEI/XML metadata (title, authors, abstract, references) | Production-grade. https://github.com/kermitt2/grobid |
| **CERMINE** | Java-based PDF metadata extraction (CEUR-WS derived) | Less active; https://github.com/CeON/CERMINE |
| **anystyle** | Ruby CRF-based reference and metadata parser | https://anystyle.io/ · https://github.com/inukshuk/anystyle |
| **refextract** | Python reference extractor (INSPIRE/DSpace lineage) | https://github.com/inspirehep/refextract |
| **ScienceParse** | Allen AI PDF metadata parser (older) | https://github.com/allenai/science-parse |
| **GROK** | PDF → metadata (older, OAI-PMH era) | https://github.com/kjm twohig/grok (search required) |

### Tier 3 — Repository platforms with AI features

These are the systems `metagen` could plug into or replace metadata entry for. Most
have experimented with AI suggestions in the last 2-3 years.

| Platform | AI feature | Link |
|---|---|---|
| **DataCite Fabrica** | Exploring AI metadata suggestions (drafts) | https://fabrica.datacite.org/ |
| **Zenodo** | AI-assisted subject tagging (limited production) | https://zenodo.org/ |
| **Figshare** | Auto-tagging from abstracts | https://figshare.com/ |
| **Dryad** | AI-assisted metadata curation pipeline (curator-in-the-loop) | https://datadryad.org/ |
| **DSpace 7+** | Community AI metadata helpers (modules vary by install) | https://duraspace.org/dspace/ |
| **InvenioRDM** (CERN) | Experimental AI metadata suggester | https://inveniosoftware.org/products/rdm/ |
| **OpenAIRE** | AI-enhanced discovery and metadata linking | https://www.openaire.eu/ |

### Tier 4 — AI research assistants (extract metadata as side effect)

These don't primarily target metadata generation, but librarians and researchers use
them for similar tasks (summarize, extract authors/affiliations, suggest keywords).
Worth knowing because they're often the "default" alternative to a specialized tool.

| Tool | What it does | Link |
|---|---|---|
| **Scholarcy** | AI summarization with structured metadata extraction (flashcards) | https://scholarcy.com/ |
| **Elicit** | AI research assistant; automates literature review with metadata extraction | https://elicit.com/ |
| **Scite.ai** | AI citations + Smart Citations metadata | https://scite.ai/ |
| **Consensus** | AI search over papers with metadata extraction | https://consensus.app/ |
| **Research Rabbit** | Discovery + citation graph metadata | https://www.researchrabbit.ai/ |
| **Inciteful** | Literature mapping with metadata | https://inciteful.xyz/ |
| **Connected Papers** | Citation graph metadata visualization | https://www.connectedpapers.com/ |
| **Dimensions AI** (Digital Science) | AI-augmented scholarly metadata database | https://www.dimensions.ai/ |
| **Lens.org** | Scholarly metadata search with AI features | https://www.lens.org/ |

### Tier 5 — Generic LLM tools (the "do it manually" baseline)

Librarians often just paste content into these. They're the implicit baseline — any
specialized tool must beat them on UX, structure, or domain knowledge.

| Tool | Link |
|---|---|
| **ChatGPT** (OpenAI) | https://chat.openai.com/ |
| **Claude** (Anthropic) | https://claude.ai/ |
| **Gemini** (Google) | https://gemini.google.com/ |
| **Grok** (xAI) | https://grok.com/ |
| **Perplexity** | https://www.perplexity.ai/ |
| **Copilot** (Microsoft) | https://copilot.microsoft.com/ |

### Tier 6 — Data catalog tools with AI (DIFFERENT scope, listed for clarity)

**These are NOT scholarly metadata tools** — they catalog enterprise data warehouses
(tables, columns, lineage). Listed here only because the term "metadata enrichment" is
ambiguous. `metagen` is NOT in this category.

- **OpenMetadata**: https://open-metadata.org/
- **DataHub** (Acryl Data): https://datahubproject.io/
- **Amundsen** (Lyft): https://amundsen.io/
- **CastorDoc**: https://www.castordoc.com/
- **Select Star**: https://www.selectstar.com/
- **Atlan**: https://atlan.com/
- **Alation**: https://www.alation.com/
- **Collibra**: https://www.collibra.com/

### Where `metagen` fits in this landscape

- **`metagen` is Tier 1** — direct LLM generation of DataCite 4.6 metadata.
- **Closest direct competitor: Croissant Baker** (different schema, same approach).
- **Differentiator opportunities:**
  1. **DataCite-specific** (most LLM tools target ML schemas or generic JSON).
  2. **Multi-agent pipeline** (most tools use single LLM call — `metagen` orchestrates 5 specialized agents).
  3. **Side-by-side diff viewer** (no Tier 1-3 competitor has this).
  4. **Chilean gov data / Spanish prompts** (no competitor specializes in this corpus).

---

## See Also

- [CONFIGURATION.md](./CONFIGURATION.md) — `metagen` runtime config
- Project README — `metagen` CLI usage
