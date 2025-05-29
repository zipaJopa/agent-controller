#!/usr/bin/env python3
"""
Wave 2 Agents - Autonomous Constellation Expansion System
---------------------------------------------------------
This script autonomously deploys Wave 2 specialized agents to expand the AI
constellation's value generation capabilities. It checks core system health,
allocates budget for capital-intensive agents, creates new agent repositories
with all necessary files and workflows, and initiates their first tasks.

Prerequisites:
- Environment Variables:
    - GH_PAT: GitHub Personal Access Token with 'repo' and 'workflow' scopes.
              This PAT is used by this script to perform administrative actions.
    - PIONEX_API_KEY (optional): For deploying crypto trading agents.
    - PIONEX_API_SECRET (optional): For deploying crypto trading agents.
    - OPENAI_API_KEY (optional): For agents requiring OpenAI.
- Python 3.9+
- Required Python packages: requests, PyNaCl (for GitHub secrets)

Usage:
    python wave2_agents.py --types crypto_trading github_arbitrage --count 1
    python wave2_agents.py --all --max_per_type 2
"""

import os
import sys
import json
import time
import base64
import requests
import random
import string
import traceback
import logging
import argparse
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple, Union
from pathlib import Path

try:
    from nacl import encoding, public
except ImportError:
    print("Error: PyNaCl library not found. Please install it: pip install pynacl requests")
    sys.exit(1)

# --- Configuration Constants ---
GITHUB_API_URL = "https://api.github.com"
GITHUB_ORG = "zipaJopa"
AGENT_TASKS_REPO = f"{GITHUB_ORG}/agent-tasks"
AGENT_RESULTS_REPO = f"{GITHUB_ORG}/agent-results"
BUDGET_STATE_REPO = f"{GITHUB_ORG}/agent-results" # Budget state is stored here
BUDGET_STATE_FILE_PATH = "budget/budget_state.json"

CORE_SYSTEM_REPOS = ["agent-controller", "agent-tasks", "agent-results", "github-harvester", "agent-memory"]
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(module)s - %(message)s',
    handlers=[
        logging.FileHandler("wave2_agents_deployment.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("Wave2Deployer")

# --- Agent Templates ---
# These define the structure and initial code for different agent types.
AGENT_TEMPLATES = {
    "crypto_trading_agent": {
        "description": "Autonomous cryptocurrency trading agent using Pionex.",
        "repo_prefix": "crypto-trader-wave2-",
        "files": {
            "agent.py": "templates/crypto_trading_agent_template.py", # Path to template file content
            "requirements.txt": "ccxt>=4.0.0\nrequests>=2.25.0",
            ".github/workflows/main.yml": "templates/crypto_workflow_template.yml"
        },
        "secrets_needed": ["GH_PAT", "PIONEX_API_KEY", "PIONEX_API_SECRET"],
        "initial_task_type": "crypto_trade_strategy_execution",
        "requires_budget": True,
        "default_trade_amount_usdt": 10.0 # Default if budget allocator doesn't specify
    },
    "github_arbitrage_agent": {
        "description": "Finds, forks, and improves undervalued GitHub repositories.",
        "repo_prefix": "gh-arbitrage-wave2-",
        "files": {
            "agent.py": "templates/github_arbitrage_agent_template.py",
            "requirements.txt": "requests>=2.25.0",
            ".github/workflows/main.yml": "templates/generic_workflow_template.yml"
        },
        "secrets_needed": ["GH_PAT"],
        "initial_task_type": "github_arbitrage_opportunity_analysis",
        "requires_budget": False
    },
    "api_wrapper_factory_agent": {
        "description": "Automatically generates API wrappers and SDKs.",
        "repo_prefix": "api-wrapper-wave2-",
        "files": {
            "agent.py": "templates/api_wrapper_agent_template.py",
            "requirements.txt": "requests>=2.25.0\nopenai>=1.0.0", # Assuming OpenAI for smart generation
            ".github/workflows/main.yml": "templates/generic_workflow_template.yml"
        },
        "secrets_needed": ["GH_PAT", "OPENAI_API_KEY"],
        "initial_task_type": "api_wrapper_generation_target",
        "requires_budget": False
    },
    "memecoin_detector_agent": {
        "description": "Detects early-stage memecoins with viral potential for trading.",
        "repo_prefix": "memecoin-hunter-wave2-",
        "files": {
            "agent.py": "templates/memecoin_detector_agent_template.py",
            "requirements.txt": "ccxt>=4.0.0\nrequests>=2.25.0",
            ".github/workflows/main.yml": "templates/crypto_workflow_template.yml" # Can use same as crypto trader
        },
        "secrets_needed": ["GH_PAT", "PIONEX_API_KEY", "PIONEX_API_SECRET"],
        "initial_task_type": "memecoin_hunt_and_trade",
        "requires_budget": True,
        "default_trade_amount_usdt": 5.0 # Smaller amounts for memecoins
    }
    # Add more Wave 2 agent templates here
}

# --- GitHub API Interaction Class ---
class GitHubAPI:
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            'Authorization': f'token {self.token}',
            'Accept': 'application/vnd.github.v3+json',
            'X-GitHub-Api-Version': '2022-11-28'
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def _request(self, method: str, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None) -> Optional[Any]:
        url = f"{GITHUB_API_URL}{endpoint}"
        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.request(method, url, json=data, params=params)
                if 'X-RateLimit-Remaining' in response.headers and int(response.headers['X-RateLimit-Remaining']) < 10:
                    reset_time = int(response.headers.get('X-RateLimit-Reset', time.time() + 60))
                    sleep_duration = max(0, reset_time - time.time()) + 5
                    logger.warning(f"Rate limit low. Sleeping for {sleep_duration:.2f} seconds.")
                    time.sleep(sleep_duration)
                
                if response.status_code == 403 and "rate limit exceeded" in response.text.lower():
                    logger.warning(f"Rate limit exceeded on {method} {url}. Retrying in {RETRY_DELAY * (attempt + 1)}s...")
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                
                response.raise_for_status()
                return response.json() if response.content else {}
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404 and method == "GET": return None
                if e.response.status_code == 422 and "already_exists" in e.response.text:
                    logger.warning(f"Resource {endpoint} likely already exists.")
                    return {"already_exists": True, "message": e.response.text}
                logger.error(f"GitHub API Error ({method} {url}): {e.response.status_code} - {e.response.text}")
                if attempt == MAX_RETRIES - 1: return None
            except requests.exceptions.RequestException as e:
                logger.error(f"Request Error ({method} {url}): {e}")
                if attempt == MAX_RETRIES - 1: return None
            time.sleep(RETRY_DELAY * (2 ** attempt))
        return None

    def get_repo(self, owner: str, repo: str) -> Optional[Dict]:
        return self._request("GET", f"/repos/{owner}/{repo}")

    def create_repo(self, repo_name: str, description: str) -> Optional[Dict]:
        payload = {"name": repo_name, "description": description, "private": False, "auto_init": True}
        return self._request("POST", "/user/repos", data=payload)

    def create_or_update_file(self, owner: str, repo: str, file_path: str, content: str, commit_message: str, branch: str = "main") -> bool:
        endpoint = f"/repos/{owner}/{repo}/contents/{file_path}"
        existing_file_data = self.get_repo_file_content_and_sha(owner, repo, file_path, branch)
        sha = existing_file_data.get("sha") if existing_file_data else None

        encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')
        payload = {"message": commit_message, "content": encoded_content, "branch": branch}
        if sha: payload["sha"] = sha
        
        response = self._request("PUT", endpoint, data=payload)
        return response is not None and "content" in response

    def get_repo_file_content_and_sha(self, owner: str, repo: str, file_path: str, branch: str = "main") -> Optional[Dict]:
        endpoint = f"/repos/{owner}/{repo}/contents/{file_path}"
        params = {"ref": branch}
        file_data = self._request("GET", endpoint, params=params)
        if file_data and "content" in file_data and "sha" in file_data:
            try:
                content = base64.b64decode(file_data["content"]).decode('utf-8')
                return {"content": content, "sha": file_data["sha"]}
            except Exception as e:
                logger.error(f"Error decoding file content for {owner}/{repo}/{file_path}: {e}")
        return None
        
    def get_repo_public_key(self, owner: str, repo: str) -> Optional[Dict]:
        return self._request("GET", f"/repos/{owner}/{repo}/actions/secrets/public-key")

    def set_repo_secret(self, owner: str, repo: str, secret_name: str, secret_value: str) -> bool:
        key_data = self.get_repo_public_key(owner, repo)
        if not key_data or "key" not in key_data or "key_id" not in key_data:
            logger.error(f"Failed to get public key for {owner}/{repo} to set secret {secret_name}.")
            return False
        try:
            public_key = public.PublicKey(key_data["key"].encode("utf-8"), encoding.Base64Encoder())
            sealed_box = public.SealedBox(public_key)
            encrypted_value = base64.b64encode(sealed_box.encrypt(secret_value.encode("utf-8"))).decode("utf-8")
        except Exception as e:
            logger.error(f"Error encrypting secret {secret_name} for {owner}/{repo}: {e}")
            return False

        payload = {"encrypted_value": encrypted_value, "key_id": key_data["key_id"]}
        response = self._request("PUT", f"/repos/{owner}/{repo}/actions/secrets/{secret_name}", data=payload)
        return response is not None

    def create_issue(self, owner: str, repo: str, title: str, body: str, labels: Optional[List[str]] = None) -> Optional[Dict]:
        payload = {"title": title, "body": body}
        if labels: payload["labels"] = labels
        return self._request("POST", f"/repos/{owner}/{repo}/issues", data=payload)

    def get_latest_workflow_run(self, owner: str, repo: str, workflow_file_name: str = "main.yml") -> Optional[Dict]:
        workflows_response = self._request("GET", f"/repos/{owner}/{repo}/actions/workflows")
        if not workflows_response or "workflows" not in workflows_response: return None
        
        target_workflow_id = None
        for wf in workflows_response["workflows"]:
            if wf["path"].endswith(workflow_file_name):
                target_workflow_id = wf["id"]
                break
        if not target_workflow_id: return None
        
        runs_response = self._request("GET", f"/repos/{owner}/{repo}/actions/workflows/{target_workflow_id}/runs?per_page=1")
        if runs_response and "workflow_runs" in runs_response and runs_response["workflow_runs"]:
            return runs_response["workflow_runs"][0]
        return None

    def trigger_workflow_dispatch(self, owner: str, repo: str, workflow_file_name: str = "main.yml", ref: str = "main", inputs: Optional[Dict] = None) -> bool:
        payload = {"ref": ref}
        if inputs: payload["inputs"] = inputs
        
        workflows_response = self._request("GET", f"/repos/{owner}/{repo}/actions/workflows")
        if not workflows_response or "workflows" not in workflows_response:
            logger.error(f"No workflows found for {owner}/{repo} to trigger {workflow_file_name}")
            return False
        
        target_workflow_id = None
        for wf in workflows_response["workflows"]:
            if wf["path"].endswith(workflow_file_name):
                target_workflow_id = wf["id"]
                break
        
        if not target_workflow_id:
            logger.error(f"Workflow {workflow_file_name} not found in {owner}/{repo}")
            return False
            
        response = self._request("POST", f"/repos/{owner}/{repo}/actions/workflows/{target_workflow_id}/dispatches", data=payload)
        return response is not None # POST to dispatches returns 204 No Content on success

# --- Budget Allocation Interface (Simplified) ---
class BudgetManager:
    def __init__(self, github_api: GitHubAPI):
        self.github_api = github_api
        self.budget_state = None
        self._load_budget_state()

    def _load_budget_state(self):
        logger.info(f"Loading budget state from {BUDGET_STATE_REPO}/{BUDGET_STATE_FILE_PATH}...")
        file_data = self.github_api.get_repo_file_content_and_sha(GITHUB_ORG, BUDGET_STATE_REPO.split('/')[-1], BUDGET_STATE_FILE_PATH)
        if file_data and file_data.get("content"):
            try:
                self.budget_state = json.loads(file_data["content"])
                logger.info("Budget state loaded successfully.")
                return
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing budget state JSON: {e}. Using default empty state.")
        else:
            logger.warning("No budget state file found or file is empty. Budget allocation will be based on defaults.")
        self.budget_state = {} # Default to empty if not found or error

    def get_available_capital_for_strategy(self, strategy_name: str, default_amount: float) -> float:
        if not self.budget_state:
            logger.warning(f"Budget state not loaded. Returning default amount ${default_amount} for {strategy_name}.")
            return default_amount
        
        strategy_details = self.budget_state.get("strategies", {}).get(strategy_name, {})
        available = strategy_details.get("available_for_new_positions_usdt", 0.0)
        
        if available <= 0: # If no specific allocation or it's zero, use agent's default
            logger.info(f"No specific budget available for '{strategy_name}' in budget_state.json. Using agent default ${default_amount}.")
            return default_amount
        
        # Use the smaller of what's available for the strategy vs the agent's own default/max per trade
        allocated = min(available, default_amount)
        logger.info(f"Budget for '{strategy_name}': Available=${available:.2f}, AgentDefault=${default_amount:.2f} -> Allocating=${allocated:.2f}")
        return allocated

# --- Agent Template Content Provider ---
class AgentTemplateProvider:
    """
    Provides content for agent files.
    In a real system, these would be loaded from actual template files.
    For this self-contained script, they are hardcoded.
    """
    def get_content(self, template_path: str, agent_name: str, opportunity_data: Optional[Dict] = None) -> str:
        # Common placeholders
        common_placeholders = {
            "{{AGENT_NAME}}": agent_name,
            "{{GITHUB_ORG}}": GITHUB_ORG,
            "{{AGENT_TASKS_REPO}}": AGENT_TASKS_REPO,
            "{{AGENT_RESULTS_REPO}}": AGENT_RESULTS_REPO,
            "{{CURRENT_ISO_TIMESTAMP}}": datetime.now(timezone.utc).isoformat()
        }
        
        content = ""
        if template_path == "templates/crypto_trading_agent_template.py":
            content = self._get_crypto_trading_agent_py(opportunity_data)
        elif template_path == "templates/github_arbitrage_agent_template.py":
            content = self._get_github_arbitrage_agent_py(opportunity_data)
        elif template_path == "templates/api_wrapper_agent_template.py":
            content = self._get_api_wrapper_agent_py(opportunity_data)
        elif template_path == "templates/memecoin_detector_agent_template.py":
            content = self._get_memecoin_detector_agent_py(opportunity_data)
        elif template_path == "templates/crypto_workflow_template.yml":
            content = self._get_crypto_workflow_yml()
        elif template_path == "templates/generic_workflow_template.yml":
            content = self._get_generic_workflow_yml()
        else:
            logger.warning(f"Unknown template path: {template_path}. Returning empty content.")
            return ""

        for placeholder, value in common_placeholders.items():
            content = content.replace(placeholder, str(value))
        return content

    def _get_crypto_trading_agent_py(self, opportunity_data: Optional[Dict]) -> str:
        # Simplified version of the trading agent from deploy_trading_agent.py
        # This should be a robust, tested template.
        symbol = opportunity_data.get("symbol", "BTC/USDT") if opportunity_data else "BTC/USDT"
        return f"""#!/usr/bin/env python3
# Autonomous Crypto Trading Agent for {{AGENT_NAME}}
import os, json, time, base64, requests, hmac, hashlib, traceback, random
from datetime import datetime, timezone
import ccxt

PIONEX_API_KEY = os.getenv('PIONEX_API_KEY')
PIONEX_API_SECRET = os.getenv('PIONEX_API_SECRET')
GH_PAT = os.getenv('GH_PAT')
AGENT_RESULTS_REPO = "{AGENT_RESULTS_REPO}"
INITIAL_TRADE_AMOUNT_USDT = float(os.getenv('TRADE_AMOUNT_USDT', '10.0')) # From workflow env
TARGET_SYMBOL = "{symbol}" # Can be overridden by task payload

# Basic logging
def log(level, message): print(f"[{{level.upper()}}] {{datetime.now(timezone.utc).isoformat()}} - {{message}}")

class ResultSaver:
    def __init__(self, token, repo_full_name):
        self.token, self.repo_full_name = token, repo_full_name
        self.api_url, self.headers = "https://api.github.com", {{'Authorization': f'token {{token}}', 'Accept': 'application/vnd.github.v3+json'}}

    def save(self, data, type="trade_result"):
        ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
        path = f"outputs/{{datetime.now(timezone.utc).strftime('%Y-%m-%d')}}/{{{{AGENT_NAME}}}_{{type}}_{{ts}}.json"
        msg = f"log: {{type}} from {{AGENT_NAME}} at {{ts}}"
        content = base64.b64encode(json.dumps(data, indent=2).encode('utf-8')).decode('utf-8')
        payload = {{"message": msg, "content": content}}
        # Get SHA if file exists for update
        try:
            r_get = requests.get(f"{{self.api_url}}/repos/{{self.repo_full_name}}/contents/{{path}}", headers=self.headers)
            if r_get.status_code == 200: payload["sha"] = r_get.json()["sha"]
        except: pass # File likely doesn't exist
        try:
            r_put = requests.put(f"{{self.api_url}}/repos/{{self.repo_full_name}}/contents/{{path}}", headers=self.headers, json=payload)
            r_put.raise_for_status()
            log("info", f"Saved result to {{self.repo_full_name}}/{{path}}")
        except Exception as e: log("error", f"Failed to save result: {{e}}. Response: {{r_put.text if 'r_put' in locals() else 'N/A'}}")

def main():
    log("info", f"🚀 {{AGENT_NAME}} starting trade cycle for {{TARGET_SYMBOL}} with ${{INITIAL_TRADE_AMOUNT_USDT:.2f}} USDT.")
    results_saver = ResultSaver(GH_PAT, AGENT_RESULTS_REPO)
    if not PIONEX_API_KEY or not PIONEX_API_SECRET:
        log("error", "Pionex API credentials not found.")
        results_saver.save({{"error": "Missing Pionex credentials", "agent": "{{AGENT_NAME}}", "timestamp": "{{CURRENT_ISO_TIMESTAMP}}"}}, "error_log")
        return

    try:
        exchange = ccxt.pionex({{'apiKey': PIONEX_API_KEY, 'secret': PIONEX_API_SECRET, 'options': {{'adjustForTimeDifference': True}}}})
        exchange.load_markets()
        
        # Basic strategy: Buy if price increased in last 15m, sell if decreased. (Placeholder - needs real strategy)
        ohlcv = exchange.fetch_ohlcv(TARGET_SYMBOL, timeframe='15m', limit=2)
        if len(ohlcv) < 2:
            log("warning", f"Not enough OHLCV data for {{TARGET_SYMBOL}}.")
            return

        current_price = ohlcv[-1][4] # Close price of current candle
        prev_price = ohlcv[-2][4]    # Close price of previous candle
        action = "buy" if current_price > prev_price else "sell"
        
        # Simplified order execution (market order)
        amount_base = INITIAL_TRADE_AMOUNT_USDT / current_price
        # Add checks for min order size etc.
        # order = exchange.create_market_order(TARGET_SYMBOL, action, amount_base)
        log("info", f"SIMULATED {{action.upper()}} order for {{amount_base}} {{TARGET_SYMBOL.split('/')[0]}} at ~{{current_price}}")
        
        # Simulate PNL
        pnl = random.uniform(-INITIAL_TRADE_AMOUNT_USDT * 0.1, INITIAL_TRADE_AMOUNT_USDT * 0.15) # Random PNL between -10% and +15%
        
        trade_result = {{
            "agent_name": "{{AGENT_NAME}}", "symbol": TARGET_SYMBOL, "action": action, 
            "amount_usdt": INITIAL_TRADE_AMOUNT_USDT, "price": current_price,
            "simulated_pnl_usdt": pnl, "timestamp": "{{CURRENT_ISO_TIMESTAMP}}",
            "strategy_details": "Basic 15m price change (simulated trade)"
        }}
        results_saver.save(trade_result)
        log("info", f"Trade cycle for {{TARGET_SYMBOL}} completed. Simulated PNL: ${{pnl:.2f}} USDT.")

    except Exception as e:
        log("error", f"Trading agent error: {{e}}\\n{{traceback.format_exc()}}")
        results_saver.save({{"error": str(e), "traceback": traceback.format_exc(), "agent": "{{AGENT_NAME}}", "timestamp": "{{CURRENT_ISO_TIMESTAMP}}"}}, "error_log")

if __name__ == "__main__":
    # Check for task payload from environment variable (passed by workflow)
    task_payload_json = os.getenv("TASK_PAYLOAD")
    if task_payload_json:
        try:
            task_payload = json.loads(task_payload_json)
            log("info", f"Received task payload: {{task_payload}}")
            # Override defaults with task payload if provided
            TARGET_SYMBOL = task_payload.get("symbol", TARGET_SYMBOL)
            INITIAL_TRADE_AMOUNT_USDT = float(task_payload.get("trade_amount_usdt", INITIAL_TRADE_AMOUNT_USDT))
        except json.JSONDecodeError:
            log("error", "Failed to parse TASK_PAYLOAD JSON.")
    main()
"""

    def _get_github_arbitrage_agent_py(self, opportunity_data: Optional[Dict]) -> str:
        target_repo = opportunity_data.get("full_name", "example/target-repo") if opportunity_data else "example/target-repo"
        return f"""#!/usr/bin/env python3
# GitHub Arbitrage Agent for {{AGENT_NAME}}
import os, json, time, base64, requests, traceback
from datetime import datetime, timezone

GH_PAT = os.getenv('GH_PAT')
AGENT_RESULTS_REPO = "{AGENT_RESULTS_REPO}"
TARGET_REPO_FULL_NAME = "{target_repo}" # Can be overridden by task payload

def log(level, message): print(f"[{{level.upper()}}] {{datetime.now(timezone.utc).isoformat()}} - {{message}}")

class ResultSaver: # Same as above
    def __init__(self, token, repo_full_name):
        self.token, self.repo_full_name = token, repo_full_name
        self.api_url, self.headers = "https://api.github.com", {{'Authorization': f'token {{token}}', 'Accept': 'application/vnd.github.v3+json'}}
    def save(self, data, type="arbitrage_result"):
        ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
        path = f"outputs/{{datetime.now(timezone.utc).strftime('%Y-%m-%d')}}/{{{{AGENT_NAME}}}_{{type}}_{{ts}}.json"
        msg = f"log: {{type}} from {{AGENT_NAME}} at {{ts}}"
        content = base64.b64encode(json.dumps(data, indent=2).encode('utf-8')).decode('utf-8')
        payload = {{"message": msg, "content": content}}
        try:
            r_get = requests.get(f"{{self.api_url}}/repos/{{self.repo_full_name}}/contents/{{path}}", headers=self.headers)
            if r_get.status_code == 200: payload["sha"] = r_get.json()["sha"]
        except: pass
        try:
            r_put = requests.put(f"{{self.api_url}}/repos/{{self.repo_full_name}}/contents/{{path}}", headers=self.headers, json=payload)
            r_put.raise_for_status()
            log("info", f"Saved result to {{self.repo_full_name}}/{{path}}")
        except Exception as e: log("error", f"Failed to save result: {{e}}. Response: {{r_put.text if 'r_put' in locals() else 'N/A'}}")

def main():
    log("info", f"⚖️ {{AGENT_NAME}} starting GitHub arbitrage analysis for {{TARGET_REPO_FULL_NAME}}.")
    results_saver = ResultSaver(GH_PAT, AGENT_RESULTS_REPO)
    # Placeholder: Implement actual arbitrage logic (fork, analyze, improve, PR)
    # For now, simulate finding an opportunity and estimating value
    estimated_value = random.uniform(50, 500) # Simulated value in USD
    analysis_result = {{
        "agent_name": "{{AGENT_NAME}}", "target_repo": TARGET_REPO_FULL_NAME,
        "action_taken": "analysis_and_planning", # In real agent: "forked", "pr_submitted"
        "estimated_value_usd": estimated_value, "timestamp": "{{CURRENT_ISO_TIMESTAMP}}",
        "details": "Simulated identification of improvement opportunities (e.g., add CI, docs, refactor)."
    }}
    results_saver.save(analysis_result)
    log("info", f"Arbitrage analysis for {{TARGET_REPO_FULL_NAME}} completed. Estimated value: ${{estimated_value:.2f}} USD.")

if __name__ == "__main__":
    task_payload_json = os.getenv("TASK_PAYLOAD")
    if task_payload_json:
        try:
            task_payload = json.loads(task_payload_json)
            log("info", f"Received task payload: {{task_payload}}")
            TARGET_REPO_FULL_NAME = task_payload.get("repo_full_name", TARGET_REPO_FULL_NAME)
        except json.JSONDecodeError: log("error", "Failed to parse TASK_PAYLOAD JSON.")
    main()
"""

    def _get_api_wrapper_agent_py(self, opportunity_data: Optional[Dict]) -> str:
        target_api_desc = opportunity_data.get("description", "a generic REST API") if opportunity_data else "a generic REST API"
        return f"""#!/usr/bin/env python3
# API Wrapper Factory Agent for {{AGENT_NAME}}
import os, json, time, base64, requests, traceback, random
from datetime import datetime, timezone

GH_PAT = os.getenv('GH_PAT')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY') # Assuming OpenAI for smart generation
AGENT_RESULTS_REPO = "{AGENT_RESULTS_REPO}"
TARGET_API_DESCRIPTION = "{target_api_desc}" # Can be overridden by task payload

def log(level, message): print(f"[{{level.upper()}}] {{datetime.now(timezone.utc).isoformat()}} - {{message}}")

class ResultSaver: # Same as above
    def __init__(self, token, repo_full_name):
        self.token, self.repo_full_name = token, repo_full_name
        self.api_url, self.headers = "https://api.github.com", {{'Authorization': f'token {{token}}', 'Accept': 'application/vnd.github.v3+json'}}
    def save(self, data, type="wrapper_result"):
        ts = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
        path = f"outputs/{{datetime.now(timezone.utc).strftime('%Y-%m-%d')}}/{{{{AGENT_NAME}}}_{{type}}_{{ts}}.json"
        msg = f"log: {{type}} from {{AGENT_NAME}} at {{ts}}"
        content = base64.b64encode(json.dumps(data, indent=2).encode('utf-8')).decode('utf-8')
        payload = {{"message": msg, "content": content}}
        try:
            r_get = requests.get(f"{{self.api_url}}/repos/{{self.repo_full_name}}/contents/{{path}}", headers=self.headers)
            if r_get.status_code == 200: payload["sha"] = r_get.json()["sha"]
        except: pass
        try:
            r_put = requests.put(f"{{self.api_url}}/repos/{{self.repo_full_name}}/contents/{{path}}", headers=self.headers, json=payload)
            r_put.raise_for_status()
            log("info", f"Saved result to {{self.repo_full_name}}/{{path}}")
        except Exception as e: log("error", f"Failed to save result: {{e}}. Response: {{r_put.text if 'r_put' in locals() else 'N/A'}}")

def main():
    log("info", f"🏭 {{AGENT_NAME}} starting API wrapper generation for '{{TARGET_API_DESCRIPTION}}'.")
    results_saver = ResultSaver(GH_PAT, AGENT_RESULTS_REPO)
    # Placeholder: Implement actual wrapper generation (e.g., using OpenAI to parse docs and generate code)
    # For now, simulate creating a basic wrapper structure
    wrapper_name = f"generated_wrapper_for_{{TARGET_API_DESCRIPTION.lower().replace(' ','_')[:20]}}"
    estimated_value = random.uniform(200, 2000) # Simulated value in USD
    
    generation_result = {{
        "agent_name": "{{AGENT_NAME}}", "target_api": TARGET_API_DESCRIPTION,
        "action_taken": "skeleton_generated", # In real agent: "full_sdk_generated", "published_to_pypi"
        "generated_wrapper_name": wrapper_name,
        "estimated_value_usd": estimated_value, "timestamp": "{{CURRENT_ISO_TIMESTAMP}}",
        "details": "Simulated generation of a Python SDK skeleton for the target API."
    }}
    results_saver.save(generation_result)
    log("info", f"API wrapper generation for '{{TARGET_API_DESCRIPTION}}' completed. Wrapper: {{wrapper_name}}, Est. Value: ${{estimated_value:.2f}} USD.")

if __name__ == "__main__":
    task_payload_json = os.getenv("TASK_PAYLOAD")
    if task_payload_json:
        try:
            task_payload = json.loads(task_payload_json)
            log("info", f"Received task payload: {{task_payload}}")
            TARGET_API_DESCRIPTION = task_payload.get("api_description", TARGET_API_DESCRIPTION)
        except json.JSONDecodeError: log("error", "Failed to parse TASK_PAYLOAD JSON.")
    main()
"""

    def _get_memecoin_detector_agent_py(self, opportunity_data: Optional[Dict]) -> str:
        # Similar to crypto trading agent, but with focus on detection and smaller, quicker trades
        return self._get_crypto_trading_agent_py(opportunity_data).replace(
            "Autonomous Crypto Trading Agent", "Autonomous Memecoin Detector & Trader"
        ).replace(
            "Basic 15m price change (simulated trade)", "Memecoin volatility analysis (simulated trade)"
        )


    def _get_crypto_workflow_yml(self) -> str:
        return """name: Crypto Agent Cycle
on:
  schedule:
    - cron: '*/15 * * * *' # Every 15 minutes
  workflow_dispatch:
  issues: # Triggered if assigned a task
    types: [assigned]

jobs:
  run_crypto_agent:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      - name: Run Agent
        env:
          GH_PAT: ${{ secrets.GH_PAT }}
          PIONEX_API_KEY: ${{ secrets.PIONEX_API_KEY }}
          PIONEX_API_SECRET: ${{ secrets.PIONEX_API_SECRET }}
          TASK_PAYLOAD: ${{ toJson(github.event.issue.body) }} # Pass issue body as JSON string if triggered by issue
          TRADE_AMOUNT_USDT: "10.0" # Default, can be overridden by task payload
        run: python agent.py
"""

    def _get_generic_workflow_yml(self) -> str:
        return """name: Generic Agent Cycle
on:
  schedule:
    - cron: '0 */4 * * *' # Every 4 hours
  workflow_dispatch:
  issues: # Triggered if assigned a task
    types: [assigned]

jobs:
  run_generic_agent:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
      - name: Run Agent
        env:
          GH_PAT: ${{ secrets.GH_PAT }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }} # Example, adjust as needed
          TASK_PAYLOAD: ${{ toJson(github.event.issue.body) }} # Pass issue body as JSON string
        run: python agent.py
"""

# --- Wave 2 Deployer Class ---
class Wave2AgentDeployer:
    def __init__(self, gh_pat: str):
        self.github_api = GitHubAPI(gh_pat)
        self.budget_manager = BudgetManager(self.github_api) # Interface to get budget
        self.template_provider = AgentTemplateProvider()
        self.deployed_agent_count = 0

        # Load secrets from environment for propagation
        self.secrets_to_propagate = {"GH_PAT": gh_pat}
        p_key, p_secret = os.getenv("PIONEX_API_KEY"), os.getenv("PIONEX_API_SECRET")
        o_key = os.getenv("OPENAI_API_KEY")
        if p_key: self.secrets_to_propagate["PIONEX_API_KEY"] = p_key
        if p_secret: self.secrets_to_propagate["PIONEX_API_SECRET"] = p_secret
        if o_key: self.secrets_to_propagate["OPENAI_API_KEY"] = o_key

    def check_core_system_health(self) -> bool:
        logger.info("🩺 Checking core system health...")
        healthy_repos = 0
        for repo_name in CORE_SYSTEM_REPOS:
            run = self.github_api.get_latest_workflow_run(GITHUB_ORG, repo_name)
            if run and run.get("conclusion") == "success":
                logger.info(f"  ✅ {repo_name} is healthy (last run: {run.get('status')}, {run.get('conclusion')}).")
                healthy_repos += 1
            else:
                status = run.get('status') if run else 'N/A'
                conclusion = run.get('conclusion') if run else 'N/A'
                logger.warning(f"  ⚠️ {repo_name} might be unhealthy (last run: {status}, {conclusion}).")
        
        if healthy_repos >= len(CORE_SYSTEM_REPOS) * 0.8: # At least 80% healthy
            logger.info("Core system health check passed.")
            return True
        logger.error("Core system health check failed. Aborting Wave 2 deployment.")
        return False

    def deploy_single_agent(self, agent_type: str, opportunity_data: Optional[Dict] = None) -> Optional[str]:
        if agent_type not in AGENT_TEMPLATES:
            logger.error(f"Unknown agent type: {agent_type}. Cannot deploy.")
            return None

        template_config = AGENT_TEMPLATES[agent_type]
        timestamp_suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        agent_repo_name = f"{template_config['repo_prefix']}{timestamp_suffix}"
        
        logger.info(f"🚀 Attempting to deploy new agent: {agent_repo_name} (Type: {agent_type})")

        # 0. Budget Check for capital-intensive agents
        allocated_trade_amount_usdt = template_config.get("default_trade_amount_usdt", 0.0)
        if template_config.get("requires_budget", False):
            allocated_trade_amount_usdt = self.budget_manager.get_available_capital_for_strategy(
                agent_type, # Assuming strategy name matches agent_type for simplicity
                template_config.get("default_trade_amount_usdt", 10.0) # Default if not in budget_state
            )
            if allocated_trade_amount_usdt < 1.0: # Minimum viable trade amount
                logger.warning(f"Insufficient budget (${allocated_trade_amount_usdt:.2f}) allocated for new {agent_type}. Skipping deployment.")
                return None
            logger.info(f"Budget allocated for {agent_repo_name}: ${allocated_trade_amount_usdt:.2f} USDT.")


        # 1. Create GitHub Repository
        repo_data = self.github_api.create_repo(agent_repo_name, template_config["description"])
        if not repo_data or repo_data.get("already_exists"):
            logger.error(f"Failed to create repository {agent_repo_name} or it already exists.")
            return None
        logger.info(f"  ✅ Created repository: {GITHUB_ORG}/{agent_repo_name}")
        time.sleep(3) # Give GitHub a moment

        # 2. Create agent files from templates
        for file_path_in_repo, template_key_or_content in template_config["files"].items():
            logger.info(f"  📄 Creating file: {file_path_in_repo}")
            # Determine if it's a path to a template method or direct content
            if template_key_or_content.startswith("templates/"):
                content = self.template_provider.get_content(template_key_or_content, agent_repo_name, opportunity_data)
            else: # Direct content (e.g. for requirements.txt)
                content = template_key_or_content
            
            # Add allocated budget to agent.py if it's a trading agent
            if file_path_in_repo == "agent.py" and template_config.get("requires_budget"):
                content = content.replace(
                    f"float(os.getenv('TRADE_AMOUNT_USDT', '{template_config.get('default_trade_amount_usdt', 0.0)}'))",
                    str(allocated_trade_amount_usdt)
                )

            if not self.github_api.create_or_update_file(GITHUB_ORG, agent_repo_name, file_path_in_repo, content, f"feat: Initial setup of {file_path_in_repo}"):
                logger.error(f"    ❌ Failed to create {file_path_in_repo} in {agent_repo_name}.")
                # TODO: Consider cleanup logic if a step fails (e.g., delete repo)
                return None
        logger.info(f"  ✅ All agent files created for {agent_repo_name}.")

        # 3. Set GitHub Secrets
        logger.info(f"  🔑 Setting secrets for {agent_repo_name}...")
        for secret_key_in_template in template_config["secrets_needed"]:
            secret_value = self.secrets_to_propagate.get(secret_key_in_template)
            if secret_value:
                if self.github_api.set_repo_secret(GITHUB_ORG, agent_repo_name, secret_key_in_template, secret_value):
                    logger.info(f"    ✅ Secret '{secret_key_in_template}' set.")
                else:
                    logger.error(f"    ❌ Failed to set secret '{secret_key_in_template}'.")
            else:
                logger.warning(f"    ⚠️ Secret value for '{secret_key_in_template}' not found in environment. Skipping.")
        
        # 4. Create initial task
        logger.info(f"  📝 Creating initial task for {agent_repo_name}...")
        task_title = f"Initial task for {agent_repo_name} ({agent_type})"
        task_body_payload = {
            "agent_repo": f"{GITHUB_ORG}/{agent_repo_name}",
            "agent_type": agent_type,
            "opportunity_details": opportunity_data or "General initialization task",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        if template_config.get("requires_budget"):
            task_body_payload["allocated_budget_usdt"] = allocated_trade_amount_usdt
        
        task_body = json.dumps(task_body_payload, indent=2)
        
        # Assign to the agent itself (conceptual, controller will pick up based on type/label)
        # For now, just create it with a 'todo' label. Controller will assign.
        if self.github_api.create_issue(GITHUB_ORG, AGENT_TASKS_REPO.split('/')[-1], task_title, task_body, ["todo", agent_type]):
            logger.info(f"  ✅ Initial task created in {AGENT_TASKS_REPO}.")
        else:
            logger.error(f"  ❌ Failed to create initial task for {agent_repo_name}.")

        # 5. (Optional) Test new agent flow - trigger controller
        logger.info(f"  ⚙️ Triggering agent-controller to pick up new agent/task...")
        if self.github_api.trigger_workflow_dispatch(GITHUB_ORG, "agent-controller", "main.yml"):
             logger.info(f"  ✅ Agent-controller dispatch triggered.")
        else:
            logger.warning(f"  ⚠️ Failed to trigger agent-controller dispatch.")

        logger.info(f"🎉 Successfully deployed agent: {GITHUB_ORG}/{agent_repo_name}")
        self.deployed_agent_count += 1
        return f"{GITHUB_ORG}/{agent_repo_name}"

    def run_expansion_wave(self, agent_types_to_deploy: List[str], max_total_deployments: int = 5, max_per_type: int = 1):
        logger.info(f"🌊 Starting Wave 2 Agent Expansion Wave 🌊")
        logger.info(f"Attempting to deploy: {', '.join(agent_types_to_deploy)}")
        logger.info(f"Max total deployments for this wave: {max_total_deployments}")
        logger.info(f"Max per agent type: {max_per_type}")

        if not self.check_core_system_health():
            logger.error("Aborting expansion wave due to core system health issues.")
            return

        deployed_this_wave = 0
        for agent_type in agent_types_to_deploy:
            if deployed_this_wave >= max_total_deployments:
                logger.info("Reached max total deployments for this wave. Stopping.")
                break
            
            deploy_count_for_type = 0
            while deploy_count_for_type < max_per_type and deployed_this_wave < max_total_deployments:
                # TODO: Fetch real opportunity data here instead of None
                # For now, we deploy based on type and count, not specific dynamic opportunities.
                # This would integrate with metaconstellation_core.py's OpportunityDetector.
                opportunity_placeholder = {"source": "wave2_expansion_script", "details": f"Scheduled deployment for {agent_type}"}
                
                deployed_repo_url = self.deploy_single_agent(agent_type, opportunity_placeholder)
                if deployed_repo_url:
                    deployed_this_wave += 1
                    deploy_count_for_type += 1
                    logger.info(f"Successfully deployed {deploy_count_for_type}/{max_per_type} of {agent_type}. Total this wave: {deployed_this_wave}/{max_total_deployments}")
                    time.sleep(10) # Pause between deployments to avoid hitting API limits too quickly
                else:
                    logger.error(f"Failed to deploy an instance of {agent_type}. Stopping for this type.")
                    break # Stop trying for this type if one fails
        
        logger.info(f"🌊 Wave 2 Agent Expansion Wave Complete. Deployed {deployed_this_wave} new agents. 🌊")
        logger.info(f"Total agents deployed by this script instance: {self.deployed_agent_count}")


# --- Main Execution ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wave 2 AI Constellation Expansion System.")
    parser.add_argument(
        "--types",
        nargs="+",
        choices=list(AGENT_TEMPLATES.keys()),
        help="Specific agent types to deploy."
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Deploy one of each available agent type."
    )
    parser.add_argument(
        "--max_total",
        type=int,
        default=5,
        help="Maximum total number of agents to deploy in this run."
    )
    parser.add_argument(
        "--max_per_type",
        type=int,
        default=1,
        help="Maximum number of agents of each specified type to deploy."
    )
    args = parser.parse_args()

    gh_pat_env = os.getenv("GH_PAT")
    if not gh_pat_env:
        logger.critical("❌ CRITICAL ERROR: GH_PAT environment variable not set. This script cannot run.")
        sys.exit(1)

    deployer = Wave2AgentDeployer(gh_pat=gh_pat_env)

    agents_to_deploy_list = []
    if args.all:
        agents_to_deploy_list = list(AGENT_TEMPLATES.keys())
    elif args.types:
        agents_to_deploy_list = args.types
    else:
        logger.info("No agent types specified for deployment. Use --types or --all. Defaulting to deploy one of each known type.")
        agents_to_deploy_list = list(AGENT_TEMPLATES.keys())
        # If no specific types, and not --all, maybe deploy a smaller default set or exit
        # For now, let's make it deploy one of each if nothing specific is asked.

    if not agents_to_deploy_list:
        logger.info("No agent types selected for deployment. Exiting.")
        sys.exit(0)
        
    deployer.run_expansion_wave(
        agent_types_to_deploy=agents_to_deploy_list,
        max_total_deployments=args.max_total,
        max_per_type=args.max_per_type
    )

    logger.info("Script finished.")
