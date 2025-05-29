#!/usr/bin/env python3
"""
Galaxy-Brained Hyper-Budget Allocator for AI Metaconstellation
-----------------------------------------------------------------
Manages the $40 USDT (and growing) budget with sophisticated risk management,
allocating capital across various risk tiers and value-generation strategies.

Features:
- Divides budget across configurable risk tiers (conservative, moderate, aggressive).
- Allocates capital to different strategy types (crypto trading, arbitrage, etc.).
- Implements position sizing rules (max trade size, max concurrent trades per strategy).
- Tracks capital allocation across all agents and strategies.
- Reallocates profits (and losses) back into the system for compounding.
- Prevents any single trade/strategy from risking too much capital.
- Includes emergency circuit breakers (e.g., total portfolio drawdown).
- Persists its state to a JSON file in a GitHub repository (e.g., agent-results).

This script is intended to be run periodically (e.g., daily) via GitHub Actions.
Individual agents would then query the persisted budget state to determine
available capital for their operations.
"""

import os
import sys
import json
import time
import base64
import requests
import logging
import traceback
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple

# --- Configuration ---
GITHUB_API_URL = "https://api.github.com"
OWNER = "zipaJopa"  # Your GitHub Organization/Username
BUDGET_STATE_REPO_NAME = "agent-results" # Repository to store budget_state.json
BUDGET_STATE_REPO_FULL = f"{OWNER}/{BUDGET_STATE_REPO_NAME}"
BUDGET_STATE_FILE_PATH = "budget/budget_state.json" # Path within the BUDGET_STATE_REPO_NAME

MAX_RETRIES = 3
RETRY_DELAY = 5 # seconds

# --- Initial Budget & Allocation Configuration ---
TOTAL_INITIAL_BUDGET_USDT = 40.0

# Risk Tiers: Percentage of total budget allocated to each tier.
# max_loss_pct_of_tier: If a tier's P&L drops below this, actions might be taken (e.g., reduce allocation).
RISK_TIER_CONFIG = {
    "conservative": {"percentage": 0.30, "max_loss_pct_of_tier": 0.10},  # $12, max loss $1.20
    "moderate":     {"percentage": 0.40, "max_loss_pct_of_tier": 0.15},  # $16, max loss $2.40
    "aggressive":   {"percentage": 0.30, "max_loss_pct_of_tier": 0.25},  # $12, max loss $3.00
}

# Strategy Configuration:
# - risk_tier: Which tier this strategy draws capital from.
# - tier_share_percentage: What percentage of its assigned tier's capital this strategy can use.
# - max_capital_per_trade_usdt: Max USDT for a single trade/position by this strategy.
# - max_concurrent_positions: Max number of active positions for this strategy.
# - requires_capital: Boolean, True if the strategy needs direct USDT allocation.
STRATEGY_CONFIG = {
    # Conservative Strategies
    "pionex_btc_eth_grid": {
        "risk_tier": "conservative", "tier_share_percentage": 0.60,
        "max_capital_per_trade_usdt": 6.0, "max_concurrent_positions": 1, # Max $6 (50% of $12 tier)
        "requires_capital": True, "description": "Conservative grid trading on BTC/ETH pairs."
    },
    "defi_stablecoin_yield": {
        "risk_tier": "conservative", "tier_share_percentage": 0.40,
        "max_capital_per_trade_usdt": 4.0, "max_concurrent_positions": 1, # Max $4
        "requires_capital": True, "description": "Low-risk yield farming with stablecoins."
    },
    # Moderate Strategies
    "crypto_rsi_momentum_altcoins": {
        "risk_tier": "moderate", "tier_share_percentage": 0.50,
        "max_capital_per_trade_usdt": 5.0, "max_concurrent_positions": 2, # Max $8 total (2x $4 from $16 tier)
        "requires_capital": True, "description": "RSI-based momentum trading on selected altcoins."
    },
    "github_arbitrage_automation": {
        "risk_tier": "moderate", "tier_share_percentage": 0.25,
        "max_capital_per_trade_usdt": 0.0, "max_concurrent_positions": 5, # Value generation, not capital intensive
        "requires_capital": False, "description": "Automated forking and improvement of undervalued GitHub repos."
    },
    "api_wrapper_generation_service": {
        "risk_tier": "moderate", "tier_share_percentage": 0.25,
        "max_capital_per_trade_usdt": 0.0, "max_concurrent_positions": 3,
        "requires_capital": False, "description": "Generates and potentially sells API wrappers."
    },
    # Aggressive Strategies
    "memecoin_early_detection_trade": {
        "risk_tier": "aggressive", "tier_share_percentage": 0.70,
        "max_capital_per_trade_usdt": 3.0, "max_concurrent_positions": 3, # Max $8.4 total (3x $2.8 from $12 tier)
        "requires_capital": True, "description": "High-risk/reward trading of newly detected memecoins."
    },
    "nft_micro_cap_flips": {
        "risk_tier": "aggressive", "tier_share_percentage": 0.30,
        "max_capital_per_trade_usdt": 3.0, "max_concurrent_positions": 1, # Max $3.6
        "requires_capital": True, "description": "Speculative flipping of micro-cap NFTs."
    }
}

# Circuit Breaker Configuration
TOTAL_PORTFOLIO_MAX_DRAWDOWN_PCT_FROM_INITIAL = 0.30 # Halt new capital-intensive trades if total budget drops 30% from initial $40
TOTAL_PORTFOLIO_MAX_DRAWDOWN_PCT_FROM_PEAK = 0.20 # Halt if drops 20% from highest recorded budget (peak)

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(module)s - %(message)s',
    handlers=[
        logging.FileHandler("budget_allocator.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("BudgetAllocator")

# --- GitHub Interaction Helper Class (from other constellation scripts) ---
class GitHubInteraction:
    def __init__(self, token):
        self.token = token
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def _request(self, method, endpoint, data=None, params=None, max_retries=MAX_RETRIES, base_url=GITHUB_API_URL):
        url = f"{base_url}{endpoint}"
        for attempt in range(max_retries):
            try:
                response = self.session.request(method, url, params=params, json=data)
                if 'X-RateLimit-Remaining' in response.headers and int(response.headers['X-RateLimit-Remaining']) < 10:
                    reset_time = int(response.headers.get('X-RateLimit-Reset', time.time() + 60))
                    sleep_duration = max(0, reset_time - time.time()) + 5
                    logger.warning(f"Rate limit low. Sleeping for {sleep_duration:.2f} seconds.")
                    time.sleep(sleep_duration)
                response.raise_for_status()
                return response.json() if response.content else {}
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 403 and "rate limit exceeded" in e.response.text.lower():
                    reset_time = int(e.response.headers.get('X-RateLimit-Reset', time.time() + 60 * (attempt + 1)))
                    sleep_duration = max(0, reset_time - time.time()) + 5
                    logger.warning(f"Rate limit exceeded. Retrying in {sleep_duration:.2f}s (attempt {attempt+1}/{max_retries}).")
                    time.sleep(sleep_duration)
                    continue
                elif e.response.status_code == 404 and method == "GET":
                    return None
                elif e.response.status_code == 422 and data and "sha" in data and "No commit found for SHA" in e.response.text:
                     logger.warning(f"SHA mismatch for {file_path} during update. Will attempt to re-fetch and retry if applicable.")
                     return {"error": "sha_mismatch", "message": e.response.text} # Special case for SHA mismatch
                logger.error(f"GitHub API request failed ({method} {url}): {e.response.status_code} - {e.response.text}")
                if attempt == max_retries - 1: raise
            except requests.exceptions.RequestException as e:
                logger.error(f"GitHub API request failed ({method} {url}): {e}")
                if attempt == max_retries - 1: raise
            time.sleep(RETRY_DELAY * (2 ** attempt))
        return None

    def get_file_content_and_sha(self, repo_full_name, file_path):
        endpoint = f"/repos/{repo_full_name}/contents/{file_path.lstrip('/')}"
        file_data = self._request("GET", endpoint)
        if file_data and "content" in file_data and "sha" in file_data:
            try:
                content = base64.b64decode(file_data["content"]).decode('utf-8')
                return content, file_data["sha"]
            except Exception as e:
                logger.error(f"Error decoding file content for {file_path}: {e}")
                return None, None
        return None, None

    def create_or_update_file(self, repo_full_name, file_path, content_str, commit_message, current_sha=None, branch="main"):
        file_path = file_path.lstrip('/')
        encoded_content = base64.b64encode(content_str.encode('utf-8')).decode('utf-8')
        payload = {"message": commit_message, "content": encoded_content, "branch": branch}
        if current_sha:
            payload["sha"] = current_sha
        
        endpoint = f"/repos/{repo_full_name}/contents/{file_path}"
        response = self._request("PUT", endpoint, data=payload)
        
        if response and response.get("error") == "sha_mismatch": # Handle SHA mismatch by re-fetching
            logger.warning(f"SHA mismatch for {file_path}. Re-fetching SHA and retrying update once.")
            _, new_sha = self.get_file_content_and_sha(repo_full_name, file_path)
            if new_sha: # If file exists with new_sha
                payload["sha"] = new_sha
                response = self._request("PUT", endpoint, data=payload)
            else: # File might have been deleted, try creating without SHA
                del payload["sha"]
                response = self._request("PUT", endpoint, data=payload)

        return response is not None and "content" in response and "sha" in response.get("content", {})


class BudgetAllocator:
    def __init__(self, total_initial_budget: float, risk_tier_cfg: Dict, strategy_cfg: Dict, github_interaction: GitHubInteraction):
        self.gh = github_interaction
        self.state_file_repo = BUDGET_STATE_REPO_FULL
        self.state_file_path = BUDGET_STATE_FILE_PATH
        
        self.risk_tier_config = risk_tier_cfg
        self.strategy_config = strategy_cfg
        
        self.state = self._load_state(total_initial_budget)

    def _default_state(self, initial_budget: float) -> Dict:
        return {
            "last_updated_utc": datetime.now(timezone.utc).isoformat(),
            "initial_budget_usdt": initial_budget,
            "current_total_budget_usdt": initial_budget,
            "peak_total_budget_usdt": initial_budget, # For drawdown from peak calculation
            "overall_pnl_usdt": 0.0,
            "risk_tiers": {}, # Populated by _initialize_allocations
            "strategies": {}, # Populated by _initialize_allocations
            "active_positions_by_strategy": {strat_name: [] for strat_name in self.strategy_config}, # {strategy_name: [{pos_id, capital_usdt, open_time}]}
            "circuit_breaker_status": "active", # "active", "total_drawdown_initial_tripped", "total_drawdown_peak_tripped"
            "log": [f"Initialized with budget: ${initial_budget:.2f} USDT"]
        }

    def _load_state(self, initial_budget: float) -> Dict:
        logger.info(f"Loading budget state from GitHub: {self.state_file_repo}/{self.state_file_path}")
        content_str, sha = self.gh.get_file_content_and_sha(self.state_file_repo, self.state_file_path)
        
        if content_str:
            try:
                loaded_state = json.loads(content_str)
                logger.info("Successfully loaded existing budget state.")
                # Basic validation and migration if needed (e.g., add new keys with defaults)
                default_template = self._default_state(initial_budget)
                for key, value in default_template.items():
                    if key not in loaded_state:
                        logger.warning(f"Key '{key}' missing in loaded state, adding with default.")
                        loaded_state[key] = value
                loaded_state["_file_sha"] = sha # Store SHA for updates
                return loaded_state
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing budget state JSON: {e}. Initializing with default state.")
        else:
            logger.info("No existing budget state file found or file is empty. Initializing with default state.")
        
        # Initialize if no state found or parsing failed
        new_state = self._default_state(initial_budget)
        self._initialize_allocations(new_state)
        new_state["_file_sha"] = None # No SHA for a new file
        return new_state

    def _save_state(self) -> bool:
        self.state["last_updated_utc"] = datetime.now(timezone.utc).isoformat()
        current_sha = self.state.pop("_file_sha", None) # Remove temp SHA before saving
        
        content_str = json.dumps(self.state, indent=2)
        commit_message = f"Update budget allocation state - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
        
        logger.info(f"Attempting to save budget state (SHA: {current_sha})...")
        success = self.gh.create_or_update_file(self.state_file_repo, self.state_file_path, content_str, commit_message, current_sha)
        
        if success:
            logger.info("Budget state saved successfully to GitHub.")
            # Re-fetch SHA after successful save
            _, new_sha = self.gh.get_file_content_and_sha(self.state_file_repo, self.state_file_path)
            self.state["_file_sha"] = new_sha
        else:
            logger.error("Failed to save budget state to GitHub.")
            self.state["_file_sha"] = current_sha # Put back old SHA if save failed
        return success

    def _log_event(self, message: str):
        self.state["log"].append(f"{datetime.now(timezone.utc).isoformat()} - {message}")
        if len(self.state["log"]) > 100: # Keep log size manageable
            self.state["log"] = self.state["log"][-100:]

    def _initialize_allocations(self, state_dict: Dict):
        logger.info("Initializing/Re-calculating budget allocations...")
        total_budget = state_dict["current_total_budget_usdt"]
        state_dict["risk_tiers"] = {}
        state_dict["strategies"] = {}

        # 1. Allocate to Risk Tiers
        for tier_name, tier_cfg in self.risk_tier_config.items():
            tier_capital = total_budget * tier_cfg["percentage"]
            state_dict["risk_tiers"][tier_name] = {
                "total_capital_usdt": round(tier_capital, 2),
                "available_capital_usdt": round(tier_capital, 2), # Initially all available
                "current_pnl_usdt": 0.0,
                "max_loss_threshold_usdt": round(tier_capital * tier_cfg["max_loss_pct_of_tier"], 2)
            }
            self._log_event(f"Allocated ${tier_capital:.2f} to risk tier '{tier_name}'.")

        # 2. Allocate Tier Capital to Strategies
        for strat_name, strat_cfg in self.strategy_config.items():
            tier_name = strat_cfg["risk_tier"]
            if tier_name not in state_dict["risk_tiers"]:
                logger.error(f"Strategy '{strat_name}' assigned to unknown risk tier '{tier_name}'. Skipping.")
                continue

            tier_total_capital = state_dict["risk_tiers"][tier_name]["total_capital_usdt"]
            strategy_potential_capital = tier_total_capital * strat_cfg["tier_share_percentage"]
            
            # For non-capital intensive strategies, allocation is conceptual (tracking performance)
            # For capital intensive, this is real USDT.
            is_capital_intensive = strat_cfg.get("requires_capital", False)

            state_dict["strategies"][strat_name] = {
                "risk_tier": tier_name,
                "tier_share_percentage": strat_cfg["tier_share_percentage"],
                "potential_capital_usdt": round(strategy_potential_capital, 2),
                "allocated_capital_usdt": 0.0, # Capital actively given to this strategy's pool
                "available_for_new_positions_usdt": 0.0, # Derived from allocated_capital_usdt - in_use
                "capital_in_use_usdt": 0.0, # Sum of active positions
                "current_pnl_usdt": 0.0,
                "max_capital_per_trade_usdt": strat_cfg["max_capital_per_trade_usdt"],
                "max_concurrent_positions": strat_cfg["max_concurrent_positions"],
                "requires_capital": is_capital_intensive,
                "description": strat_cfg["description"]
            }
            self._log_event(f"Strategy '{strat_name}' configured for tier '{tier_name}' with potential capital ${strategy_potential_capital:.2f}.")
        
        # 3. Distribute tier capital to strategies that require it
        # This is a simplified initial distribution. More complex logic could consider strategy performance.
        for tier_name in state_dict["risk_tiers"]:
            tier_available_capital = state_dict["risk_tiers"][tier_name]["available_capital_usdt"]
            
            # Sum of shares for capital-intensive strategies in this tier
            total_share_for_capital_strategies_in_tier = sum(
                s_cfg["tier_share_percentage"] for s_name, s_cfg in self.strategy_config.items()
                if s_cfg["risk_tier"] == tier_name and s_cfg.get("requires_capital", False)
            )
            if total_share_for_capital_strategies_in_tier == 0: continue

            for strat_name, strat_state in state_dict["strategies"].items():
                strat_cfg = self.strategy_config[strat_name]
                if strat_cfg["risk_tier"] == tier_name and strat_cfg.get("requires_capital", False):
                    # Allocate proportionally based on tier_share_percentage among capital-intensive strategies
                    proportional_share = strat_cfg["tier_share_percentage"] / total_share_for_capital_strategies_in_tier
                    allocated_to_strategy = tier_available_capital * proportional_share
                    
                    strat_state["allocated_capital_usdt"] = round(allocated_to_strategy, 2)
                    strat_state["available_for_new_positions_usdt"] = round(allocated_to_strategy, 2) # Initially all available
                    
                    # Deduct from tier's available capital (conceptually, as it's now strategy-specific)
                    # This step is more about tracking than actual movement if it's all one pool.
                    # For now, let's assume tier_available_capital is the pool strategies draw from.
                    # This part of the logic might need refinement based on how capital is actually managed.
                    self._log_event(f"Assigned ${allocated_to_strategy:.2f} from tier '{tier_name}' to strategy '{strat_name}'.")


    def rebalance_allocations(self):
        """Re-calculates all allocations based on current total budget. Typically run daily."""
        logger.info("--- Running Daily Budget Rebalance ---")
        self._check_circuit_breakers() # Check breakers before rebalancing

        if "tripped" in self.state["circuit_breaker_status"]:
            logger.warning(f"Circuit breaker '{self.state['circuit_breaker_status']}' is tripped. Rebalancing might be limited or skipped.")
            # Potentially implement logic to only rebalance conservative tiers or reduce overall risk.
            # For now, we proceed but this is a point for enhancement.

        # Recalculate tier and strategy allocations based on the new current_total_budget_usdt
        self._initialize_allocations(self.state) # This re-calculates based on current_total_budget_usdt
        
        # Update peak budget
        if self.state["current_total_budget_usdt"] > self.state["peak_total_budget_usdt"]:
            self.state["peak_total_budget_usdt"] = self.state["current_total_budget_usdt"]
            self._log_event(f"New peak total budget reached: ${self.state['peak_total_budget_usdt']:.2f} USDT.")

        self._log_event("Daily rebalance complete.")
        self._save_state()
        logger.info("--- Daily Budget Rebalance Finished ---")

    def request_capital_for_trade(self, strategy_name: str, requested_usdt: float, position_id: str) -> Tuple[bool, float, str]:
        """
        An agent calls this to request capital for a new trade.
        Returns (approved: bool, allocated_usdt: float, message: str).
        """
        self._check_circuit_breakers()
        if "tripped" in self.state["circuit_breaker_status"]:
            msg = f"Capital request for '{strategy_name}' denied. Circuit breaker '{self.state['circuit_breaker_status']}' is tripped."
            logger.warning(msg)
            self._log_event(msg)
            return False, 0.0, msg

        if strategy_name not in self.state["strategies"]:
            msg = f"Strategy '{strategy_name}' not found in configuration."
            logger.error(msg)
            return False, 0.0, msg

        strat_state = self.state["strategies"][strategy_name]
        strat_cfg = self.strategy_config[strategy_name]

        if not strat_cfg.get("requires_capital", False):
            msg = f"Strategy '{strategy_name}' does not require direct capital. Request conceptual."
            # logger.info(msg) # This might be too noisy if called often
            return True, 0.0, msg # Approved, but 0 capital as it's not managed here

        num_current_positions = len(self.state["active_positions_by_strategy"].get(strategy_name, []))
        if num_current_positions >= strat_cfg["max_concurrent_positions"]:
            msg = f"Strategy '{strategy_name}' at max concurrent positions ({num_current_positions}/{strat_cfg['max_concurrent_positions']}). Request denied."
            logger.warning(msg)
            self._log_event(msg)
            return False, 0.0, msg

        # Determine actual amount to allocate for this trade
        # Use min of requested, max_per_trade, and available for strategy
        capital_to_allocate = min(
            requested_usdt,
            strat_cfg["max_capital_per_trade_usdt"],
            strat_state["available_for_new_positions_usdt"]
        )

        if capital_to_allocate <= 0.01: # Effectively zero or too small
            msg = f"Insufficient available capital (${strat_state['available_for_new_positions_usdt']:.2f}) or request too small for strategy '{strategy_name}'. Requested: ${requested_usdt:.2f}."
            logger.warning(msg)
            self._log_event(msg)
            return False, 0.0, msg

        # Approve and update state
        strat_state["available_for_new_positions_usdt"] -= capital_to_allocate
        strat_state["capital_in_use_usdt"] += capital_to_allocate
        
        self.state["active_positions_by_strategy"].setdefault(strategy_name, []).append({
            "id": position_id,
            "capital_usdt": round(capital_to_allocate, 2),
            "open_time_utc": datetime.now(timezone.utc).isoformat()
        })
        
        msg = f"Approved ${capital_to_allocate:.2f} USDT for strategy '{strategy_name}', position ID '{position_id}'."
        logger.info(msg)
        self._log_event(msg)
        self._save_state()
        return True, round(capital_to_allocate, 2), msg

    def report_trade_close(self, strategy_name: str, position_id: str, pnl_usdt: float):
        """
        An agent calls this to report a closed trade and its P&L.
        This updates the strategy's capital and the overall budget.
        """
        if strategy_name not in self.state["strategies"]:
            logger.error(f"Strategy '{strategy_name}' not found when reporting trade close for position '{position_id}'.")
            return

        strat_state = self.state["strategies"][strategy_name]
        active_positions = self.state["active_positions_by_strategy"].get(strategy_name, [])
        
        position_found = False
        for i, pos in enumerate(active_positions):
            if pos["id"] == position_id:
                closed_position = active_positions.pop(i)
                position_found = True
                
                original_capital = closed_position["capital_usdt"]
                capital_returned = original_capital + pnl_usdt # Capital + P&L
                
                # Update strategy state
                strat_state["capital_in_use_usdt"] -= original_capital
                strat_state["capital_in_use_usdt"] = max(0, strat_state["capital_in_use_usdt"]) # Ensure not negative
                strat_state["available_for_new_positions_usdt"] += capital_returned
                strat_state["current_pnl_usdt"] += pnl_usdt
                
                # Update overall budget and P&L
                self.state["current_total_budget_usdt"] += pnl_usdt
                self.state["overall_pnl_usdt"] += pnl_usdt
                
                # Update risk tier P&L
                tier_name = strat_cfg["risk_tier"]
                if tier_name in self.state["risk_tiers"]:
                    self.state["risk_tiers"][tier_name]["current_pnl_usdt"] += pnl_usdt
                    # Note: Tier capital itself is rebalanced daily, not directly adjusted here per trade.
                    # Available capital for the tier is implicitly increased by P&L flowing to total budget.

                msg = (f"Trade closed for strategy '{strategy_name}', position '{position_id}'. "
                       f"Original capital: ${original_capital:.2f}, P&L: ${pnl_usdt:.2f}. "
                       f"Strategy available: ${strat_state['available_for_new_positions_usdt']:.2f}. "
                       f"Total budget: ${self.state['current_total_budget_usdt']:.2f} USDT.")
                logger.info(msg)
                self._log_event(msg)
                break
        
        if not position_found:
            logger.warning(f"Could not find active position ID '{position_id}' for strategy '{strategy_name}' to close.")
            self._log_event(f"Warning: Position ID '{position_id}' not found for strategy '{strategy_name}' during close report.")

        self._save_state()

    def _check_circuit_breakers(self):
        """Checks and potentially trips circuit breakers."""
        # 1. Drawdown from initial budget
        drawdown_from_initial = (self.state["initial_budget_usdt"] - self.state["current_total_budget_usdt"]) / self.state["initial_budget_usdt"]
        if drawdown_from_initial >= TOTAL_PORTFOLIO_MAX_DRAWDOWN_PCT_FROM_INITIAL:
            if self.state["circuit_breaker_status"] != "total_drawdown_initial_tripped":
                self.state["circuit_breaker_status"] = "total_drawdown_initial_tripped"
                msg = (f"CRITICAL: Circuit breaker tripped! Total budget drawdown "
                       f"({drawdown_from_initial*100:.2f}%) exceeded initial limit "
                       f"({TOTAL_PORTFOLIO_MAX_DRAWDOWN_PCT_FROM_INITIAL*100:.2f}%). "
                       f"Halting new capital-intensive deployments/trades.")
                logger.critical(msg)
                self._log_event(msg)
                # TODO: Implement actions like notifying admin, pausing specific agent types.
                self._save_state() # Save immediately after tripping
            return # Don't check other breakers if this one is tripped

        # 2. Drawdown from peak budget
        if self.state["peak_total_budget_usdt"] > self.state["initial_budget_usdt"]: # Only if we've made profit
            drawdown_from_peak = (self.state["peak_total_budget_usdt"] - self.state["current_total_budget_usdt"]) / self.state["peak_total_budget_usdt"]
            if drawdown_from_peak >= TOTAL_PORTFOLIO_MAX_DRAWDOWN_PCT_FROM_PEAK:
                 if self.state["circuit_breaker_status"] != "total_drawdown_peak_tripped":
                    self.state["circuit_breaker_status"] = "total_drawdown_peak_tripped"
                    msg = (f"CRITICAL: Circuit breaker tripped! Total budget drawdown from peak "
                           f"({drawdown_from_peak*100:.2f}%) exceeded limit "
                           f"({TOTAL_PORTFOLIO_MAX_DRAWDOWN_PCT_FROM_PEAK*100:.2f}%). "
                           f"Reducing risk / Halting new capital-intensive deployments/trades.")
                    logger.critical(msg)
                    self._log_event(msg)
                    self._save_state() # Save immediately
                return

        # 3. Tier-specific max loss (optional, can be more complex)
        for tier_name, tier_state in self.state["risk_tiers"].items():
            if tier_state["current_pnl_usdt"] < 0 and abs(tier_state["current_pnl_usdt"]) >= tier_state["max_loss_threshold_usdt"]:
                # Tier specific action, e.g., reduce its allocation percentage temporarily or pause its strategies
                msg = (f"WARNING: Risk tier '{tier_name}' P&L (${tier_state['current_pnl_usdt']:.2f}) "
                       f"has breached its max loss threshold (${tier_state['max_loss_threshold_usdt']:.2f}). "
                       f"Consider reviewing strategies in this tier.")
                logger.warning(msg)
                self._log_event(msg)
                # TODO: Implement automated de-risking for this tier.

        # If no breakers tripped, ensure status is active
        if "tripped" in self.state["circuit_breaker_status"]:
            # This implies a manual reset is needed or a cool-down period.
            # For now, once tripped, it stays tripped until manually reset or state is re-initialized.
            logger.info(f"Circuit breaker '{self.state['circuit_breaker_status']}' remains tripped.")
        elif self.state["circuit_breaker_status"] != "active":
             self.state["circuit_breaker_status"] = "active" # Reset if previously tripped but conditions no longer met
             logger.info("Circuit breaker status reset to 'active'.")
             self._log_event("Circuit breaker status reset to 'active'.")
             self._save_state()


    def get_full_state_for_ui(self) -> Dict:
        """Returns a copy of the current state, suitable for UI display."""
        # Make a deep copy if complex objects are involved, but for dicts of primitives, this is fine.
        state_copy = json.loads(json.dumps(self.state))
        state_copy.pop("_file_sha", None) # Don't expose internal SHA
        return state_copy

# --- Main Execution (for scheduled runs) ---
if __name__ == "__main__":
    logger.info("🚀 Initializing Galaxy-Brained Hyper-Budget Allocator 🚀")
    
    gh_pat = os.getenv("GH_PAT")
    if not gh_pat:
        logger.critical("❌ CRITICAL ERROR: GH_PAT environment variable not set. Budget Allocator cannot run.")
        sys.exit(1)

    try:
        gh_interaction = GitHubInteraction(token=gh_pat)
        allocator = BudgetAllocator(
            total_initial_budget=TOTAL_INITIAL_BUDGET_USDT,
            risk_tier_cfg=RISK_TIER_CONFIG,
            strategy_cfg=STRATEGY_CONFIG,
            github_interaction=gh_interaction
        )

        # This would typically be called by a daily GitHub Action
        allocator.rebalance_allocations()
        
        # Example: Simulate a capital request and trade close for testing
        # This part would normally be initiated by an agent, not run directly here.
        # Comment out for production scheduled runs.
        """
        logger.info("\\n--- Example Interaction Simulation ---")
        # Test capital request
        strategy_to_test = "memecoin_early_detection_trade"
        pos_id = f"testpos_{int(time.time())}"
        approved, capital, msg = allocator.request_capital_for_trade(strategy_to_test, 2.5, pos_id)
        logger.info(f"Capital Request Result: Approved={approved}, Capital=${capital:.2f}, Msg='{msg}'")

        if approved and capital > 0:
            # Simulate trade P&L
            simulated_pnl = round(random.uniform(-capital * 0.5, capital * 1.5), 2) # Random P&L
            logger.info(f"Simulating trade close for {pos_id} with P&L: ${simulated_pnl:.2f}")
            allocator.report_trade_close(strategy_to_test, pos_id, simulated_pnl)
        
        logger.info(f"Final state after simulation: {json.dumps(allocator.state, indent=2)}")
        logger.info("--- End Example Interaction Simulation ---")
        """

        logger.info("✅ Budget Allocator cycle finished successfully.")

    except Exception as e:
        logger.critical(f"❌ CRITICAL UNHANDLED ERROR in Budget Allocator: {e}")
        traceback.print_exc()
        sys.exit(1)
