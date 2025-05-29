# AI Constellation ‑ System Architecture & Implementation Guide  
**Version:** 1.0  **Maintainer:** Pavle Bradic (System Architect)  

---

## 1 System Architecture Overview
```
┌─────────────┐    GitHub Issues      ┌──────────────┐
│ agent-tasks │  ── Task Queue  ───▶  │ agent-tasks  │
│  (Queue)    │                      │  (Runner)    │
└─────────────┘                      └──────────────┘
       ▲                                   │
       │ JSON results push                 │REST/JSON
       │                                   ▼
┌─────────────┐    REST / Webhook   ┌─────────────────┐
│agent-memory │  ◀───────────────── │ agent-controller│
│ (Vector DB) │          ▲         └─────────────────┘
└─────────────┘          │ GitHub API      │
       ▲                 │                 │ dispatch
       │                 │                 ▼
       │   Embedding     │          ┌───────────────┐
       │                 └─────────│ agent-results │
       │                            │  (Metrics)   │
       │            cron schedule   └───────────────┘
       │                                   ▲
       │                                   │
┌─────────────┐  REST / GitHub API  ┌───────────────┐
│github-*     │  (Harvester, etc.) │crypto_core    │
└─────────────┘                    └───────────────┘
```
* **Execution layer** – GitHub Actions runners (free tier)  
* **Storage** – repo files (JSON/CSV), vector embeddings (`agent-memory`)  
* **Queue** – GitHub Issues; each open issue = task record  
* **Coordination** – `agent-controller` (Python) triggered every 5 min  
* **External value layer** – Pionex API for live USDT trading  

---

## 2 Repository Integration Matrix

| Repo | Purpose | Consumes | Produces | Trigger |
|------|---------|----------|----------|---------|
| agent-controller | Master orchestrator | Issues, Memory, Results | Task assignments (labels/comment) | `controller.yml` cron 5 min |
| agent-tasks | Worker template & queue logic | Tasks Issues | Completion comments, JSON result blobs committed to `results/YYYY-MM/*.json` | On issue assigned |
| agent-memory | Vector store (embeddings/metadata) | Raw text, code snippets | `embeddings/*.jsonl` | Reusable lib, imported |
| agent-results | KPI dashboards | Results JSON | Markdown reports, metrics JSON | Nightly cron |
| github-harvester | Discover repos | GitHub Search API | `tasks/harvest_*.json` -> opens Task issue | Cron 2 h |
| github-arbitrage-agent | Fork/enhance undervalued repos | Harvester data | Pull-requests, revenue metrics | On new task |
| ai-wrapper-factory | Generate API wrappers | Task queue | Wrapper repos, SaaS metrics | On new task |
| crypto_financial_core | Trade USDT (Pionex) | Signals tasks | P&L logs JSON | 15 min cron |
| autonomous_infrastructure | Self-healing & scaling | GH Actions status API | Alerts (Issues), PRs | 30 min cron |

---

## 3 Data Flow Architecture

1. **Task creation**  
   - Any agent opens an Issue in `agent-tasks` with label `todo` and JSON payload in body.  
2. **Controller cycle**  
   - `agent-controller` scans issues → assigns by adding `assignee: <agent-bot>` & `in-progress` label.  
3. **Execution**  
   - The assignee repo has a workflow listening to `issues.assigned`.  
   - Action checks out repo, parses task JSON, performs work.  
4. **Result storage**  
   - On success:  
     - Comment “DONE ✅” with result link.  
     - Commit result file into `agent-results/outputs/` via GitHub API.  
5. **Memory update**  
   - Embed relevant text via `agent-memory` helper → push embedding JSON.  
6. **Metrics**  
   - `agent-results` nightly aggregates revenue, P&L, success‐rate → publishes dashboard to GitHub Pages.

---

## 4 GitHub Actions Orchestration

### Example: Controller workflow (`.github/workflows/controller.yml`)
```yaml
name: controller
on:
  schedule:
    - cron:  '*/5 * * * *'
  workflow_dispatch: {}
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Python
        uses: actions/setup-python@v5
        with: {python-version: '3.11'}
      - name: Install deps
        run: pip install -r requirements.txt
      - name: Run coordination cycle
        env:
          GITHUB_TOKEN: ${{ secrets.GH_PAT }}
        run: python agent_controller.py
```

### Worker template (`agent-tasks` repo)
```
.github/workflows/worker.yml
```
Listens to issue assignment → executes `task_manager.py`.

---

## 5 Value Generation Workflows

| Workflow | Input Task Example | Key Logic | Output |
|----------|-------------------|-----------|--------|
| **GitHub Arbitrage** | `{type:"arbitrage", repo_url:"…"}` | fork, add AI README, open PR | new repo & monetization URL |
| **Wrapper Factory** | `{type:"wrapper", api_spec_url:"…"}` | parse OpenAPI, code-gen SDK, publish PyPI | wrapper repo & PyPI link |
| **SaaS Template Mill** | `{type:"saas_template", niche:"HR"}` | clone boilerplate, customise | deployable template URL |
| **Crypto Degen Bot** | `{type:"trade_signal", pair:"BTCUSDT"}` | TA + momentum; place orders via crypto core | trade receipts JSON |

---

## 6 Crypto Trading Integration

```python
# crypto_financial_core.py snippet
import hmac, hashlib, time, requests, os, json
API_KEY  = os.getenv("PIONEX_API_KEY")
API_SEC  = os.getenv("PIONEX_API_SECRET")
ENDPOINT = "https://api.pionex.com/api/v1"

def sign(payload:str)->str:
    return hmac.new(API_SEC.encode(), payload.encode(), hashlib.sha256).hexdigest()

def place_order(symbol, side, qty, price):
    ts = int(time.time()*1000)
    body = json.dumps({"symbol":symbol,"type":"limit","side":side,
                       "quantity":qty,"price":price,"timestamp":ts})
    headers={"PIONEX-KEY":API_KEY,"PIONEX-SIGN":sign(body)}
    r = requests.post(f"{ENDPOINT}/order", headers=headers, data=body, timeout=10)
    r.raise_for_status()
    return r.json()
```
* **Secrets** stored in repo → Settings → *Actions secrets* (`PIONEX_API_KEY`, `PIONEX_API_SECRET`).  
* Trading bot commits order receipts to `agent-results/crypto/`.

---

## 7 Implementation Roadmap

| Phase | Duration | Deliverables |
|-------|----------|--------------|
| **0** Bootstrap | **Day 1-2** | Repo secrets, PAT token, initial Actions enabled |
| **1** MVP Integration | Week 1 | Controller + Tasks + Memory wired, Harvester generates tasks |
| **2** Value Agents v1 | Week 2 | GitHub Arbitrage, Wrapper Factory live, results dashboard |
| **3** Crypto Core | Week 3 | Pionex trading bot trading testnet; P&L metrics |
| **4** Autonomous Infra | Week 4 | Self-healing workflows, auto-scaling (# of runners via `actions-runner-controller` optional) |
| **5** Monetisation & Scale | Week 5-6 | Marketing automations, paid API endpoints, Wave 3 agents |

---

## 8 Technical Specifications

| Component | Language | Key Libraries | Interfaces |
|-----------|----------|---------------|------------|
| agent-controller | Python 3.11 | `requests`, `PyGitHub` | REST → GitHub API |
| agent-tasks | Python | `aiohttp`, `pygithub`, `tqdm` | Issue JSON schema v1 |
| agent-memory | Python | `sentence-transformers`, `faiss` | `embed(text) -> vector` |
| crypto_financial_core | Python | `requests` | Pionex REST |
| dashboards | JavaScript (Pages) | `Chart.js`, `D3` | Static JSON fetch |

*JSON Task Schema v1:*  
```json
{
  "id": "task-2025-0001",
  "type": "wrapper",
  "payload": {
    "api_spec_url": "https://raw.githubusercontent.com/.../openapi.yaml"
  },
  "priority": 5,
  "created_at": "ISO8601"
}
```

---

## 9 Monitoring & Scaling Strategy
* **Status Board** – GitHub Projects board aggregates open / in-progress / done issues across repos.  
* **Alerts** – `autonomous_infrastructure` workflow checks last run time & exits; if >2× cron interval → opens “ALERT” issue and pings maintainer.  
* **Cost Control** – Keep under 2 k Action-minutes/month (free tier), else down-schedule low priority agents.  
* **Horizontal Scaling** – Add new repo with identical workflow, label tasks with `team:<repo>` so controller shards.  

---

## 10 Deployment Instructions

1. **Fork / clone all constellation repos** under one GitHub org.  
2. Add required secrets to *each* repo:  
   - `GH_PAT` (classic token with `repo` + `workflow`)  
   - `OPENAI_API_KEY` (if wrappers need LLM)  
   - Crypto repos: `PIONEX_API_KEY`, `PIONEX_API_SECRET`  
3. Enable GitHub Actions in org settings.  
4. Manually dispatch **controller** workflow once to seed labels.  
5. Verify that `github-harvester` creates new task issues.  
6. Observe assigned issues and resulting commits in `agent-results/`.  
7. Check `Pages` site (from `agent-results` > Settings > Pages) for dashboards.  
8. Adjust cron expressions for frequency & free-tier limits.  
9. **Security** – Restrict PAT to org; use branch protection rules; use `dependabot` for CVEs.  

---

**You now have the blueprint to convert all nimble code shards into a cohesive, continuously running, revenue-generating AI constellation.**  

*Happy orbiting!*
