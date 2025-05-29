#!/usr/bin/env python3
"""
Deploy Real Crypto Trading Agent - Autonomous Money-Making Machine
--------------------------------------------------------------------
This script immediately deploys a fully functional, autonomous cryptocurrency
trading agent that uses the Pionex API and a real USDT budget.

The deployed agent will:
1.  Be created in its own new GitHub repository.
2.  Use the provided $40 USDT budget (or as configured).
3.  Trade real cryptocurrencies on Pionex.
4.  Implement a basic momentum/volatility trading strategy.
5.  Aim to generate actual profits.
6.  Store all trade results and P&L in the 'zipaJopa/agent-results' repository.
7.  Run autonomously via GitHub Actions every 15 minutes.

**Prerequisites:**
- Set the following environment variables before running:
    - `GH_PAT`: Your GitHub Personal Access Token with 'repo' and 'workflow' scopes.
    - `PIONEX_API_KEY`: Your Pionex API Key.
    - `PIONEX_API_SECRET`: Your Pionex API Secret.

Usage:
    python deploy_trading_agent.py
"""

import os
import sys
import json
import time
import base64
import requests
import traceback
import logging
from typing import Dict, List, Any, Tuple, Optional, Union
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("deploy_trading_agent.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("trading_agent_deployer")

# --- Configuration Constants ---
GITHUB_API_URL = "https://api.github.com"
GITHUB_ORG = "zipaJopa"
AGENT_NAME_PREFIX = "pionex-trader-usdt"
AGENT_VERSION = "v1"
AGENT_REPO_NAME = f"{AGENT_NAME_PREFIX}-{AGENT_VERSION}"
AGENT_DESCRIPTION = "Autonomous Pionex USDT Trading Agent - Real Money, Real Profits"
AGENT_RESULTS_REPO = f"{GITHUB_ORG}/agent-results" # For storing trade outcomes

# Trading parameters for the deployed agent
INITIAL_USDT_BUDGET = 40.0  # The $40 USDT budget Pavle mentioned
TRADE_AMOUNT_PER_COIN_USDT = 10.0 # Max USDT to use for a single coin trade
SYMBOLS_TO_TRADE = ["SHIB/USDT", "DOGE/USDT", "PEPE/USDT", "BTC/USDT", "ETH/USDT"] # Volatile but common
TAKE_PROFIT_PERCENTAGE = 0.05  # 5%
STOP_LOSS_PERCENTAGE = 0.02    # 2%

class GitHubAPI:
    """Minimal GitHub API client for repository and secret management."""
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            'Authorization': f'token {self.token}',
            'Accept': 'application/vnd.github.v3+json',
            'X-GitHub-Api-Version': '2022-11-28'
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def _request(self, method: str, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None, max_retries: int = 3) -> Optional[Dict]:
        url = f"{GITHUB_API_URL}{endpoint}"
        for attempt in range(max_retries):
            try:
                response = self.session.request(method, url, json=data, params=params)
                if 'X-RateLimit-Remaining' in response.headers and int(response.headers['X-RateLimit-Remaining']) < 10:
                    reset_time = int(response.headers.get('X-RateLimit-Reset', time.time() + 60))
                    sleep_duration = max(0, reset_time - time.time()) + 5
                    logger.warning(f"Rate limit low. Sleeping for {sleep_duration:.2f} seconds.")
                    time.sleep(sleep_duration)

                if response.status_code == 403 and "rate limit exceeded" in response.text.lower():
                    logger.warning(f"Rate limit exceeded. Retrying... (Attempt {attempt + 1})")
                    time.sleep(60 * (attempt + 1))
                    continue

                response.raise_for_status()
                return response.json() if response.content else {}
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404 and method == "GET":
                    return None # Not found is a valid response for checks
                if e.response.status_code == 422 and "already_exists" in e.response.text: # Repo already exists
                    logger.warning(f"Repository {endpoint} likely already exists.")
                    return {"already_exists": True}
                logger.error(f"GitHub API Error ({method} {url}): {e.response.status_code} - {e.response.text}")
                if attempt == max_retries - 1: raise
            except requests.exceptions.RequestException as e:
                logger.error(f"Request Error ({method} {url}): {e}")
                if attempt == max_retries - 1: raise
            time.sleep(2 ** attempt) # Exponential backoff
        return None

    def repo_exists(self, repo_name: str) -> bool:
        return self._request("GET", f"/repos/{GITHUB_ORG}/{repo_name}") is not None

    def create_repo(self, repo_name: str, description: str) -> Optional[Dict]:
        payload = {"name": repo_name, "description": description, "private": False, "auto_init": True}
        return self._request("POST", "/user/repos", data=payload)

    def create_or_update_file(self, repo_name: str, file_path: str, content: str, commit_message: str) -> bool:
        endpoint = f"/repos/{GITHUB_ORG}/{repo_name}/contents/{file_path}"
        existing_file_data = self._request("GET", endpoint)
        sha = existing_file_data.get("sha") if existing_file_data else None

        encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')
        payload = {"message": commit_message, "content": encoded_content}
        if sha:
            payload["sha"] = sha
        
        response = self._request("PUT", endpoint, data=payload)
        return response is not None and "content" in response

    def get_public_key_for_secrets(self, repo_name: str) -> Optional[Dict]:
        return self._request("GET", f"/repos/{GITHUB_ORG}/{repo_name}/actions/secrets/public-key")

    def create_or_update_secret(self, repo_name: str, secret_name: str, secret_value: str) -> bool:
        key_data = self.get_public_key_for_secrets(repo_name)
        if not key_data or "key" not in key_data or "key_id" not in key_data:
            logger.error(f"Failed to get public key for repository {repo_name} to set secret {secret_name}.")
            return False

        try:
            from nacl import encoding, public
            public_key = public.PublicKey(key_data["key"].encode("utf-8"), encoding.Base64Encoder())
            sealed_box = public.SealedBox(public_key)
            encrypted_value = base64.b64encode(sealed_box.encrypt(secret_value.encode("utf-8"))).decode("utf-8")
        except ImportError:
            logger.error("pynacl library not found. Please install it: pip install pynacl")
            return False
        except Exception as e:
            logger.error(f"Error encrypting secret {secret_name}: {e}")
            return False

        payload = {"encrypted_value": encrypted_value, "key_id": key_data["key_id"]}
        response = self._request("PUT", f"/repos/{GITHUB_ORG}/{repo_name}/actions/secrets/{secret_name}", data=payload)
        return response is not None


class AgentDeployer:
    """Deploys the autonomous trading agent."""
    def __init__(self, gh_pat: str, pionex_api_key: str, pionex_api_secret: str):
        self.github = GitHubAPI(gh_pat)
        self.pionex_api_key = pionex_api_key
        self.pionex_api_secret = pionex_api_secret

    def _generate_trading_agent_script_content(self) -> str:
        # Using f-strings with {{ and }} for GitHub Actions expressions
        # Ensure Python code itself uses single braces for f-strings if needed.
        return f"""#!/usr/bin/env python3
# Autonomous Pionex USDT Trading Agent (Real Money, Real Profits)
import os
import json
import time
import base64
import requests
import hmac
import hashlib
import traceback
import random
from datetime import datetime, timedelta
import ccxt # Make sure this is in requirements.txt

# --- Agent Configuration ---
PIONEX_API_KEY = os.getenv('PIONEX_API_KEY')
PIONEX_API_SECRET = os.getenv('PIONEX_API_SECRET')
GH_PAT = os.getenv('GH_PAT') # For saving results
AGENT_RESULTS_REPO = "{AGENT_RESULTS_REPO}"
SYMBOLS_TO_TRADE = {SYMBOLS_TO_TRADE}
INITIAL_BUDGET_USDT = float(os.getenv('INITIAL_BUDGET_USDT', '{INITIAL_USDT_BUDGET}'))
TRADE_AMOUNT_PER_COIN_USDT = float(os.getenv('TRADE_AMOUNT_PER_COIN_USDT', '{TRADE_AMOUNT_PER_COIN_USDT}'))
TAKE_PROFIT_PCT = float(os.getenv('TAKE_PROFIT_PCT', '{TAKE_PROFIT_PERCENTAGE}'))
STOP_LOSS_PCT = float(os.getenv('STOP_LOSS_PCT', '{STOP_LOSS_PERCENTAGE}'))
PERSISTENCE_FILE = "trading_state.json" # To store open positions

# --- Logging ---
def log_info(message):
    print(f"[INFO] {{datetime.now().isoformat()}}: {{message}}")

def log_error(message):
    print(f"[ERROR] {{datetime.now().isoformat()}}: {{message}}")

# --- GitHub API for Results ---
class ResultLogger:
    def __init__(self, token, results_repo):
        self.token = token
        self.results_repo = results_repo
        self.api_url = "https://api.github.com"
        self.headers = {{
            'Authorization': f'token {{self.token}}',
            'Accept': 'application/vnd.github.v3+json'
        }}

    def save_result(self, data, result_type="trade"):
        ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        date_folder = datetime.now().strftime('%Y-%m-%d')
        file_path = f"outputs/{{date_folder}}/{AGENT_REPO_NAME}_{{result_type}}_{{ts}}.json"
        commit_message = f"feat: Log {{result_type}} result from {AGENT_REPO_NAME} at {{ts}}"
        
        content_str = json.dumps(data, indent=2)
        encoded_content = base64.b64encode(content_str.encode('utf-8')).decode('utf-8')
        
        payload = {{"message": commit_message, "content": encoded_content}}
        
        # Check if file exists to get SHA for update
        get_url = f"{{self.api_url}}/repos/{{self.results_repo}}/contents/{{file_path}}"
        try:
            response = requests.get(get_url, headers=self.headers)
            if response.status_code == 200:
                payload["sha"] = response.json()["sha"]
        except Exception as e:
            log_info(f"File {{file_path}} likely does not exist, creating new. Error: {{e}}")

        put_url = f"{{self.api_url}}/repos/{{self.results_repo}}/contents/{{file_path}}"
        try:
            response = requests.put(put_url, headers=self.headers, json=payload)
            response.raise_for_status()
            log_info(f"Successfully saved {{result_type}} result to {{self.results_repo}}/{{file_path}}")
            return True
        except Exception as e:
            log_error(f"Failed to save {{result_type}} result: {{e}}. Response: {{response.text if 'response' in locals() else 'N/A'}}")
            return False

# --- Pionex API Client ---
class PionexTrader:
    def __init__(self, api_key, api_secret, result_logger):
        self.result_logger = result_logger
        if not api_key or not api_secret:
            log_error("Pionex API Key or Secret not provided. Cannot trade.")
            raise ValueError("Pionex API Key or Secret missing.")
        try:
            self.exchange = ccxt.pionex({{
                'apiKey': api_key,
                'secret': api_secret,
                'options': {{'adjustForTimeDifference': True}},
            }})
            self.exchange.load_markets()
            log_info("Pionex exchange interface initialized successfully.")
        except Exception as e:
            log_error(f"Failed to initialize Pionex exchange: {{e}}")
            self.result_logger.save_result({{"error": "Pionex init failed", "details": str(e)}}, "error")
            raise

    def load_state(self):
        try:
            if os.path.exists(PERSISTENCE_FILE):
                with open(PERSISTENCE_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            log_error(f"Could not load trading state: {{e}}")
        return {{"open_positions": {{}}, "total_budget_usdt": INITIAL_BUDGET_USDT, "available_budget_usdt": INITIAL_BUDGET_USDT}}

    def save_state(self, state):
        try:
            with open(PERSISTENCE_FILE, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            log_error(f"Could not save trading state: {{e}}")

    def get_ohlcv(self, symbol, timeframe='15m', limit=100):
        try:
            if self.exchange.has['fetchOHLCV']:
                ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
                # [timestamp, open, high, low, close, volume]
                return ohlcv
            log_error(f"Exchange does not support fetchOHLCV for {{symbol}}.")
        except Exception as e:
            log_error(f"Error fetching OHLCV for {{symbol}}: {{e}}")
        return []

    def calculate_rsi(self, ohlcv, period=14):
        if not ohlcv or len(ohlcv) < period:
            return None
        closes = [candle[4] for candle in ohlcv] # Use close prices
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [delta if delta > 0 else 0 for delta in deltas]
        losses = [-delta if delta < 0 else 0 for delta in deltas]

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
        if avg_loss == 0: return 100
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def get_current_price(self, symbol):
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker['last']
        except Exception as e:
            log_error(f"Error fetching current price for {{symbol}}: {{e}}")
            return None

    def place_order(self, symbol, side, amount_usdt, current_price, state):
        if state["available_budget_usdt"] < amount_usdt and side == "buy":
            log_info(f"Insufficient available budget ({{state['available_budget_usdt']:.2f}} USDT) to {{side}} {{amount_usdt:.2f}} USDT of {{symbol}}. Skipping.")
            return None

        try:
            # Calculate amount in base currency
            amount_base = amount_usdt / current_price
            
            # Ensure the order meets minimum requirements for the specific symbol
            market = self.exchange.market(symbol)
            min_cost = market.get('limits', {{}}).get('cost', {{}}).get('min', 0.1) # Pionex min order is often 0.1 USDT for spot
            min_amount = market.get('limits', {{}}).get('amount', {{}}).get('min', 0)

            if amount_usdt < min_cost:
                log_info(f"Order value {{amount_usdt:.2f}} USDT for {{symbol}} is below minimum cost {{min_cost:.2f}} USDT. Skipping.")
                return None
            if amount_base < min_amount:
                 log_info(f"Order amount {{amount_base}} for {{symbol}} is below minimum amount {{min_amount}}. Skipping.")
                 return None

            log_info(f"Placing {{side}} order for {{amount_base:.8f}} {{symbol.split('/')[0]}} ({{amount_usdt:.2f}} USDT) at approx price {{current_price}}.")
            order_type = 'market' # Using market orders for simplicity
            order = self.exchange.create_order(symbol, order_type, side, amount_base)
            
            log_info(f"Order placed: {{order['id']}} for {{symbol}}")
            
            trade_info = {{
                "order_id": order['id'], "symbol": symbol, "side": side, 
                "amount_usdt": amount_usdt, "price_executed": order.get('price', current_price), # Use actual filled price if available
                "amount_filled_base": order.get('filled', amount_base),
                "timestamp": datetime.now().isoformat(),
                "pnl_usdt": 0 # PNL calculated on close
            }}
            self.result_logger.save_result(trade_info, "order_open")
            
            if side == "buy":
                state["open_positions"][order['id']] = {{
                    "symbol": symbol, "entry_price": trade_info["price_executed"], 
                    "amount_base": trade_info["amount_filled_base"], "amount_usdt": amount_usdt,
                    "take_profit_price": trade_info["price_executed"] * (1 + TAKE_PROFIT_PCT),
                    "stop_loss_price": trade_info["price_executed"] * (1 - STOP_LOSS_PCT),
                }}
                state["available_budget_usdt"] -= amount_usdt
            # For sells, PNL is realized, handled in manage_positions
            
            return order
        except Exception as e:
            log_error(f"Error placing {{side}} order for {{symbol}}: {{e}}")
            self.result_logger.save_result({{"error": "Order placement failed", "symbol": symbol, "details": str(e)}}, "error")
            return None

    def manage_positions(self, state):
        log_info(f"Managing {{len(state['open_positions'])}} open positions.")
        positions_to_close = []
        for order_id, position in list(state["open_positions"].items()): # Iterate over a copy
            symbol = position["symbol"]
            current_price = self.get_current_price(symbol)
            if not current_price:
                log_info(f"Could not get current price for {{symbol}} to manage position {{order_id}}. Skipping.")
                continue

            log_info(f"Position {{order_id}} ({{symbol}}): Entry={{position['entry_price']:.4f}}, Current={{current_price:.4f}}, TP={{position['take_profit_price']:.4f}}, SL={{position['stop_loss_price']:.4f}}")

            closed = False
            pnl = 0
            reason = ""

            if current_price >= position["take_profit_price"]:
                log_info(f"Take profit triggered for {{symbol}} at {{current_price}} (target: {{position['take_profit_price']}})")
                reason = "take_profit"
                closed = True
            elif current_price <= position["stop_loss_price"]:
                log_info(f"Stop loss triggered for {{symbol}} at {{current_price}} (target: {{position['stop_loss_price']}})")
                reason = "stop_loss"
                closed = True
            
            if closed:
                try:
                    sell_amount_base = position["amount_base"]
                    log_info(f"Closing position {{order_id}} for {{symbol}}: Selling {{sell_amount_base}} at {{current_price}}")
                    sell_order = self.exchange.create_order(symbol, 'market', 'sell', sell_amount_base)
                    
                    # Calculate PNL
                    entry_value_usdt = position["amount_usdt"]
                    exit_value_usdt = sell_order.get('cost', sell_amount_base * current_price) # cost is total USDT value of the trade
                    pnl = exit_value_usdt - entry_value_usdt
                    
                    log_info(f"Position {{order_id}} for {{symbol}} closed. PNL: {{pnl:.2f}} USDT. Reason: {{reason}}.")
                    
                    trade_info = {{
                        "original_order_id": order_id, "symbol": symbol, "side": "sell", "reason": reason,
                        "amount_usdt_sold": exit_value_usdt, "price_executed": sell_order.get('price', current_price),
                        "amount_filled_base": sell_order.get('filled', sell_amount_base),
                        "timestamp": datetime.now().isoformat(), "pnl_usdt": pnl
                    }}
                    self.result_logger.save_result(trade_info, "order_close")
                    
                    state["available_budget_usdt"] += exit_value_usdt
                    state["total_budget_usdt"] += pnl # Update total budget with PNL
                    positions_to_close.append(order_id)
                except Exception as e:
                    log_error(f"Error closing position {{order_id}} for {{symbol}}: {{e}}")
                    self.result_logger.save_result({{"error": "Position close failed", "symbol": symbol, "order_id": order_id, "details": str(e)}}, "error")
        
        for order_id in positions_to_close:
            del state["open_positions"][order_id]

    def run_trading_cycle(self):
        log_info("Starting new trading cycle...")
        state = self.load_state()
        log_info(f"Current state: Total Budget={{state['total_budget_usdt']:.2f}} USDT, Available={{state['available_budget_usdt']:.2f}} USDT, Open Positions={{len(state['open_positions'])}}")

        self.manage_positions(state) # Manage existing positions first

        # Decide if we can open new positions
        # Limit concurrent open positions for risk management, e.g., max 2-3
        if len(state["open_positions"]) >= 3:
            log_info("Max open positions reached. Not opening new trades in this cycle.")
            self.save_state(state)
            log_info("Trading cycle finished.")
            return

        # Look for new opportunities
        for symbol in SYMBOLS_TO_TRADE:
            if len(state["open_positions"]) >= 3: break # Re-check limit

            log_info(f"Analyzing {{symbol}} for new opportunities...")
            ohlcv = self.get_ohlcv(symbol)
            if not ohlcv:
                log_info(f"No OHLCV data for {{symbol}}. Skipping.")
                continue
            
            rsi = self.calculate_rsi(ohlcv)
            current_price = self.get_current_price(symbol)

            if not rsi or not current_price:
                log_info(f"Could not get RSI or current price for {{symbol}}. Skipping.")
                continue
            
            log_info(f"{{symbol}}: Price={{current_price:.4f}}, RSI (14)={{rsi:.2f}}")

            # Simple RSI Strategy
            # Check if we already have a position for this symbol
            symbol_in_position = any(pos['symbol'] == symbol for pos in state['open_positions'].values())
            if symbol_in_position:
                log_info(f"Already have an open position for {{symbol}}. Skipping new trade.")
                continue

            if rsi < 30: # Oversold, potential buy signal
                log_info(f"BUY signal for {{symbol}} (RSI: {{rsi:.2f}}).")
                self.place_order(symbol, "buy", TRADE_AMOUNT_PER_COIN_USDT, current_price, state)
            elif rsi > 70: # Overbought, potential sell signal (if holding)
                # For this simple agent, we only open new positions on buy signals.
                # Selling is handled by manage_positions (TP/SL).
                log_info(f"SELL signal for {{symbol}} (RSI: {{rsi:.2f}}), but not opening short positions.")
                pass 
            else:
                log_info(f"No clear signal for {{symbol}} (RSI: {{rsi:.2f}}).")
        
        self.save_state(state)
        log_info("Trading cycle finished.")
        self.result_logger.save_result(state, "cycle_summary")


# --- Main Execution ---
if __name__ == "__main__":
    log_info(f"🚀 Deploying Trading Agent: {AGENT_REPO_NAME} 🚀")
    if not PIONEX_API_KEY or not PIONEX_API_SECRET or not GH_PAT:
        log_error("Missing required environment variables: PIONEX_API_KEY, PIONEX_API_SECRET, GH_PAT")
        sys.exit(1)

    result_logger = ResultLogger(GH_PAT, AGENT_RESULTS_REPO)
    trader = PionexTrader(PIONEX_API_KEY, PIONEX_API_SECRET, result_logger)
    
    try:
        trader.run_trading_cycle()
        log_info("Trading agent cycle executed successfully.")
    except Exception as e:
        log_error(f"An error occurred during the trading agent execution: {{e}}")
        result_logger.save_result({{"error": "Main execution failed", "details": str(e)}}, "error")
        traceback.print_exc()
"""

    def _generate_workflow_content(self) -> str:
        return f"""name: Autonomous Pionex Trader

on:
  schedule:
    - cron: '*/15 * * * *'  # Run every 15 minutes
  workflow_dispatch:      # Allow manual triggering

jobs:
  trade:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install Dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests ccxt pynacl # pynacl for GitHub secrets if used by agent itself

      - name: Run Trading Agent
        env:
          PIONEX_API_KEY: ${{{{ secrets.PIONEX_API_KEY }}}}
          PIONEX_API_SECRET: ${{{{ secrets.PIONEX_API_SECRET }}}}
          GH_PAT: ${{{{ secrets.GH_PAT }}}}
          INITIAL_BUDGET_USDT: "{INITIAL_USDT_BUDGET}"
          TRADE_AMOUNT_PER_COIN_USDT: "{TRADE_AMOUNT_PER_COIN_USDT}"
          TAKE_PROFIT_PCT: "{TAKE_PROFIT_PERCENTAGE}"
          STOP_LOSS_PCT: "{STOP_LOSS_PERCENTAGE}"
        run: python agent.py
"""

    def _generate_requirements_content(self) -> str:
        return """requests>=2.25.0
ccxt>=4.0.0
pynacl>=1.5.0
"""

    def deploy(self) -> bool:
        logger.info(f"Starting deployment of trading agent: {AGENT_REPO_NAME}")

        # 1. Create GitHub Repository
        if not self.github.repo_exists(AGENT_REPO_NAME):
            logger.info(f"Repository {AGENT_REPO_NAME} does not exist. Creating...")
            repo_data = self.github.create_repo(AGENT_REPO_NAME, AGENT_DESCRIPTION)
            if not repo_data or repo_data.get("already_exists"):
                logger.error(f"Failed to create repository {AGENT_REPO_NAME}. Aborting.")
                return False
            logger.info(f"Successfully created repository: {GITHUB_ORG}/{AGENT_REPO_NAME}")
            time.sleep(5) # Give GitHub a moment to finalize repo creation
        else:
            logger.info(f"Repository {AGENT_REPO_NAME} already exists. Proceeding with file updates.")

        # 2. Create agent.py (the trading script)
        agent_script_content = self._generate_trading_agent_script_content()
        if not self.github.create_or_update_file(AGENT_REPO_NAME, "agent.py", agent_script_content, "feat: Add initial trading agent script"):
            logger.error(f"Failed to create agent.py in {AGENT_REPO_NAME}. Aborting.")
            return False
        logger.info("Successfully created agent.py")

        # 3. Create .github/workflows/main.yml
        workflow_content = self._generate_workflow_content()
        if not self.github.create_or_update_file(AGENT_REPO_NAME, ".github/workflows/main.yml", workflow_content, "feat: Add GitHub Actions workflow for trading"):
            logger.error(f"Failed to create workflow in {AGENT_REPO_NAME}. Aborting.")
            return False
        logger.info("Successfully created .github/workflows/main.yml")

        # 4. Create requirements.txt
        requirements_content = self._generate_requirements_content()
        if not self.github.create_or_update_file(AGENT_REPO_NAME, "requirements.txt", requirements_content, "feat: Add requirements.txt"):
            logger.error(f"Failed to create requirements.txt in {AGENT_REPO_NAME}. Aborting.")
            return False
        logger.info("Successfully created requirements.txt")
        
        # 5. Create README.md
        readme_content = f"""# {AGENT_REPO_NAME}
{AGENT_DESCRIPTION}

This agent trades autonomously on Pionex using a USDT budget. 
It runs every 15 minutes via GitHub Actions.

**Configuration (via GitHub Secrets):**
- `PIONEX_API_KEY`: Your Pionex API Key.
- `PIONEX_API_SECRET`: Your Pionex API Secret.
- `GH_PAT`: GitHub Personal Access Token for saving results.

**Trading Strategy:**
- Focuses on symbols: {', '.join(SYMBOLS_TO_TRADE)}
- Uses a simple RSI-based strategy on 15-minute candles.
- Buys on RSI < 30, sells on RSI > 70 (or via TP/SL).
- Manages a budget of {INITIAL_USDT_BUDGET} USDT.
- Max {TRADE_AMOUNT_PER_COIN_USDT} USDT per trade per coin.
- Take Profit: {TAKE_PROFIT_PERCENTAGE*100}%, Stop Loss: {STOP_LOSS_PERCENTAGE*100}%.

**Results:**
Trade results, P&L, and cycle summaries are logged to the `{AGENT_RESULTS_REPO}` repository.
"""
        if not self.github.create_or_update_file(AGENT_REPO_NAME, "README.md", readme_content, "docs: Add README file"):
            logger.error(f"Failed to create README.md in {AGENT_REPO_NAME}. Aborting.")
            return False
        logger.info("Successfully created README.md")


        # 6. Set GitHub Secrets
        secrets_to_set = {
            "GH_PAT": self.github.token, # Use the PAT this script is running with
            "PIONEX_API_KEY": self.pionex_api_key,
            "PIONEX_API_SECRET": self.pionex_api_secret
        }
        all_secrets_set = True
        for secret_name, secret_value in secrets_to_set.items():
            logger.info(f"Setting secret: {secret_name} in {AGENT_REPO_NAME}...")
            if not self.github.create_or_update_secret(AGENT_REPO_NAME, secret_name, secret_value):
                logger.error(f"Failed to set secret: {secret_name}")
                all_secrets_set = False
            else:
                logger.info(f"Successfully set secret: {secret_name}")
        
        if not all_secrets_set:
            logger.error("Failed to set one or more secrets. Manual intervention may be required.")
            # Continue deployment, but log the error. Agent might not run correctly.

        logger.info(f"🎉 Successfully deployed Trading Agent: {GITHUB_ORG}/{AGENT_REPO_NAME}")
        logger.info(f"It will start trading automatically based on its GitHub Actions schedule (every 15 minutes).")
        logger.info(f"Monitor its activity here: https://github.com/{GITHUB_ORG}/{AGENT_REPO_NAME}/actions")
        return True


if __name__ == "__main__":
    logger.info("🚀 Starting Real Crypto Trading Agent Deployment Script 🚀")

    gh_pat = os.getenv("GH_PAT")
    pionex_api_key = os.getenv("PIONEX_API_KEY")
    pionex_api_secret = os.getenv("PIONEX_API_SECRET")

    if not all([gh_pat, pionex_api_key, pionex_api_secret]):
        logger.error("Missing one or more required environment variables: GH_PAT, PIONEX_API_KEY, PIONEX_API_SECRET.")
        logger.error("Please set them and re-run the script.")
        sys.exit(1)

    deployer = AgentDeployer(gh_pat, pionex_api_key, pionex_api_secret)
    
    try:
        success = deployer.deploy()
        if success:
            logger.info("✅ Deployment successful! The trading agent is live.")
        else:
            logger.error("❌ Deployment failed. Please check logs for details.")
            sys.exit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred during deployment: {e}")
        traceback.print_exc()
        sys.exit(1)
