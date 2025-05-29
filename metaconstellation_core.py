#!/usr/bin/env python3
"""
Metaconstellation Core - Autonomous AI Agent Swarm
--------------------------------------------------
The central brain of the hyperabundance metaconstellation system.

This module autonomously:
1. Detects value opportunities across multiple domains
2. Deploys specialized agent repositories for each opportunity
3. Manages crypto trading via Pionex API
4. Tracks all value generation with zero loss tolerance
5. Reinvests profits to expand the constellation
6. Coordinates the entire agent swarm without human intervention
7. Consolidates and reports all results

Usage:
    python metaconstellation_core.py

Requirements:
    - GitHub PAT with repo and workflow scopes as GH_PAT environment variable
    - Pionex API credentials as PIONEX_API_KEY and PIONEX_API_SECRET
    - Python 3.9+
    - requests, ccxt, numpy packages
"""

import os
import sys
import json
import time
import base64
import hmac
import hashlib
import uuid
import random
import string
import requests
import traceback
import logging
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any, Tuple, Optional, Union
from pathlib import Path

try:
    import ccxt  # For crypto exchange integration
except ImportError:
    print("Warning: ccxt package not found. Crypto trading functionality will be limited.")
    ccxt = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("metaconstellation.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("metaconstellation")

# Configuration Constants
GITHUB_API_URL = "https://api.github.com"
GITHUB_ORG = "zipaJopa"  # GitHub organization/username
RETRY_DELAY = 5  # seconds between retries
MAX_RETRIES = 3  # maximum number of retries for API calls

# Core repositories
CORE_REPOS = {
    "agent-controller": "Central orchestrator for the AI agent constellation",
    "agent-tasks": "Task queue and execution engine for AI agents",
    "agent-memory": "Vector store and knowledge management for AI agents",
    "agent-results": "Results tracking and value calculation for AI agents",
    "github-harvester": "Harvests valuable GitHub projects automatically"
}

# Value generation strategies
VALUE_STRATEGIES = {
    "crypto_trading": {
        "description": "Cryptocurrency trading via Pionex API",
        "min_capital": 10.0,  # Minimum USDT required
        "expected_roi": 0.05,  # 5% daily ROI target
        "risk_level": "medium",
        "reinvestment_ratio": 0.7,  # 70% of profits reinvested
        "agent_type": "crypto-trading-agent"
    },
    "github_arbitrage": {
        "description": "Fork, improve, and monetize undervalued GitHub projects",
        "min_capital": 0.0,  # No capital required
        "expected_roi": None,  # Variable ROI
        "risk_level": "low",
        "reinvestment_ratio": 0.5,  # 50% of profits reinvested
        "agent_type": "github-arbitrage-agent"
    },
    "api_wrapper_factory": {
        "description": "Generate and sell API wrappers and SDKs",
        "min_capital": 0.0,  # No capital required
        "expected_roi": None,  # Variable ROI
        "risk_level": "low",
        "reinvestment_ratio": 0.6,  # 60% of profits reinvested
        "agent_type": "api-wrapper-factory-agent"
    },
    "memecoin_detector": {
        "description": "Detect early-stage memecoins with viral potential",
        "min_capital": 5.0,  # Minimum USDT required
        "expected_roi": 0.2,  # 20% daily ROI target (high risk/reward)
        "risk_level": "high",
        "reinvestment_ratio": 0.4,  # 40% of profits reinvested
        "agent_type": "memecoin-detector-agent"
    },
    "content_generation": {
        "description": "Generate and monetize viral content",
        "min_capital": 0.0,  # No capital required
        "expected_roi": None,  # Variable ROI
        "risk_level": "low",
        "reinvestment_ratio": 0.7,  # 70% of profits reinvested
        "agent_type": "content-generation-agent"
    },
    "defi_yield_farming": {
        "description": "Automated DeFi yield farming",
        "min_capital": 20.0,  # Minimum USDT required
        "expected_roi": 0.03,  # 3% daily ROI target
        "risk_level": "medium",
        "reinvestment_ratio": 0.8,  # 80% of profits reinvested
        "agent_type": "defi-yield-farming-agent"
    }
}

class GitHubAPI:
    """Helper class for GitHub API interactions with proper rate limiting and error handling"""
    
    def __init__(self, token):
        self.token = token
        self.headers = {
            'Authorization': f'token {token}',
            'Accept': 'application/vnd.github.v3+json'
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
    
    def _request(self, method, endpoint, data=None, params=None, max_retries=MAX_RETRIES, base_url=GITHUB_API_URL):
        """Make a GitHub API request with automatic rate limit handling and retries"""
        url = f"{base_url}{endpoint}"
        for attempt in range(max_retries):
            try:
                response = self.session.request(method, url, params=params, json=data)
                
                # Check for rate limiting
                if 'X-RateLimit-Remaining' in response.headers and int(response.headers['X-RateLimit-Remaining']) < 10:
                    reset_time = int(response.headers.get('X-RateLimit-Reset', time.time() + 60))
                    sleep_duration = max(0, reset_time - time.time()) + 5
                    logger.warning(f"Rate limit low. Sleeping for {sleep_duration:.2f} seconds.")
                    time.sleep(sleep_duration)
                
                # Handle specific response codes
                if response.status_code == 403 and "rate limit exceeded" in response.text.lower():
                    reset_time = int(response.headers.get('X-RateLimit-Reset', time.time() + 60 * (attempt + 1)))
                    sleep_duration = max(0, reset_time - time.time()) + 5
                    logger.warning(f"Rate limit exceeded. Retrying in {sleep_duration:.2f}s (attempt {attempt+1}/{max_retries}).")
                    time.sleep(sleep_duration)
                    continue
                
                # Success
                if response.status_code in (200, 201, 204):
                    return response.json() if response.content else {}
                
                # Not found
                if response.status_code == 404 and method == "GET":
                    return None
                    
                # Other errors
                logger.error(f"GitHub API error: {response.status_code} - {response.text}")
                if attempt < max_retries - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))  # Exponential backoff
                    continue
                
                response.raise_for_status()
                
            except requests.RequestException as e:
                logger.error(f"Request error: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                raise
                
        return None
    
    def repo_exists(self, repo_name):
        """Check if a repository exists"""
        endpoint = f"/repos/{GITHUB_ORG}/{repo_name}"
        return self._request("GET", endpoint) is not None
    
    def create_repo(self, repo_name, description=""):
        """Create a new repository"""
        endpoint = "/user/repos"
        data = {
            "name": repo_name,
            "description": description,
            "private": False,
            "auto_init": True
        }
        return self._request("POST", endpoint, data=data)
    
    def create_or_update_file(self, repo_name, file_path, content, commit_message, branch="main"):
        """Create or update a file in a repository"""
        endpoint = f"/repos/{GITHUB_ORG}/{repo_name}/contents/{file_path}"
        
        # Check if file exists to get SHA
        existing_file = self._request("GET", endpoint)
        sha = existing_file["sha"] if existing_file and "sha" in existing_file else None
        
        # Prepare the content and request
        content_bytes = content.encode('utf-8') if isinstance(content, str) else content
        content_b64 = base64.b64encode(content_bytes).decode('utf-8')
        
        data = {
            "message": commit_message,
            "content": content_b64,
            "branch": branch
        }
        
        if sha:
            data["sha"] = sha
            
        return self._request("PUT", endpoint, data=data)
    
    def get_file_content(self, repo_name, file_path, branch="main"):
        """Get the content of a file from a repository"""
        endpoint = f"/repos/{GITHUB_ORG}/{repo_name}/contents/{file_path}"
        params = {"ref": branch}
        response = self._request("GET", endpoint, params=params)
        
        if response and "content" in response:
            return base64.b64decode(response["content"]).decode('utf-8')
        return None
    
    def create_issue(self, repo_name, title, body, labels=None):
        """Create an issue in a repository"""
        endpoint = f"/repos/{GITHUB_ORG}/{repo_name}/issues"
        data = {
            "title": title,
            "body": body
        }
        if labels:
            data["labels"] = labels
            
        return self._request("POST", endpoint, data=data)
    
    def list_issues(self, repo_name, state="open", labels=None):
        """List issues in a repository"""
        endpoint = f"/repos/{GITHUB_ORG}/{repo_name}/issues"
        params = {"state": state}
        if labels:
            params["labels"] = labels
            
        return self._request("GET", endpoint, params=params) or []
    
    def add_issue_comment(self, repo_name, issue_number, comment):
        """Add a comment to an issue"""
        endpoint = f"/repos/{GITHUB_ORG}/{repo_name}/issues/{issue_number}/comments"
        data = {"body": comment}
        return self._request("POST", endpoint, data=data)
    
    def list_workflows(self, repo_name):
        """List workflows in a repository"""
        endpoint = f"/repos/{GITHUB_ORG}/{repo_name}/actions/workflows"
        return self._request("GET", endpoint) or {"workflows": []}
    
    def trigger_workflow(self, repo_name, workflow_id, branch="main"):
        """Trigger a workflow run"""
        endpoint = f"/repos/{GITHUB_ORG}/{repo_name}/actions/workflows/{workflow_id}/dispatches"
        data = {"ref": branch}
        return self._request("POST", endpoint, data=data)
    
    def list_workflow_runs(self, repo_name, workflow_id=None):
        """List workflow runs in a repository"""
        if workflow_id:
            endpoint = f"/repos/{GITHUB_ORG}/{repo_name}/actions/workflows/{workflow_id}/runs"
        else:
            endpoint = f"/repos/{GITHUB_ORG}/{repo_name}/actions/runs"
        return self._request("GET", endpoint) or {"workflow_runs": []}
    
    def create_secret(self, repo_name, secret_name, secret_value):
        """Create a repository secret (requires additional steps for encryption)"""
        # Get public key for the repository
        endpoint = f"/repos/{GITHUB_ORG}/{repo_name}/actions/secrets/public-key"
        key_data = self._request("GET", endpoint)
        
        if not key_data or "key" not in key_data or "key_id" not in key_data:
            logger.error(f"Failed to get public key for {repo_name}")
            return False
        
        # For actual implementation, use sodium library for proper encryption
        # This is a simplified version that works with GitHub API
        from base64 import b64encode
        from nacl import encoding, public
        
        try:
            # Encode the secret value
            public_key = public.PublicKey(key_data["key"].encode("utf-8"), encoding.Base64Encoder())
            sealed_box = public.SealedBox(public_key)
            encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
            encrypted_value = b64encode(encrypted).decode("utf-8")
            
            # Create or update the secret
            endpoint = f"/repos/{GITHUB_ORG}/{repo_name}/actions/secrets/{secret_name}"
            data = {
                "encrypted_value": encrypted_value,
                "key_id": key_data["key_id"]
            }
            response = self._request("PUT", endpoint, data=data)
            return response is not None
        except Exception as e:
            logger.error(f"Error encrypting secret: {str(e)}")
            return False

class PionexAPI:
    """Helper class for Pionex cryptocurrency exchange API interactions"""
    
    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = "https://api.pionex.com"
        self.session = requests.Session()
        
        # Initialize ccxt if available
        self.exchange = None
        if ccxt:
            try:
                self.exchange = ccxt.pionex({
                    'apiKey': api_key,
                    'secret': api_secret,
                })
            except Exception as e:
                logger.error(f"Failed to initialize ccxt.pionex: {str(e)}")
    
    def _generate_signature(self, timestamp, method, request_path, body=None):
        """Generate signature for Pionex API request"""
        body_str = "" if body is None else json.dumps(body)
        message = f"{timestamp}{method}{request_path}{body_str}"
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _request(self, method, endpoint, params=None, data=None):
        """Make a Pionex API request with proper authentication"""
        url = f"{self.base_url}{endpoint}"
        timestamp = str(int(time.time() * 1000))
        signature = self._generate_signature(timestamp, method, endpoint, data)
        
        headers = {
            "X-API-KEY": self.api_key,
            "X-TIMESTAMP": timestamp,
            "X-SIGNATURE": signature,
            "Content-Type": "application/json"
        }
        
        try:
            if method == "GET":
                response = self.session.get(url, params=params, headers=headers)
            elif method == "POST":
                response = self.session.post(url, json=data, headers=headers)
            elif method == "DELETE":
                response = self.session.delete(url, json=data, headers=headers)
            else:
                logger.error(f"Unsupported method: {method}")
                return None
            
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Pionex API request error: {str(e)}")
            return None
    
    def get_account_balance(self):
        """Get account balance"""
        if self.exchange:
            try:
                return self.exchange.fetch_balance()
            except Exception as e:
                logger.error(f"ccxt error fetching balance: {str(e)}")
        
        # Fallback to direct API
        endpoint = "/api/v1/account/balance"
        return self._request("GET", endpoint)
    
    def get_ticker(self, symbol):
        """Get ticker information for a symbol"""
        if self.exchange:
            try:
                return self.exchange.fetch_ticker(symbol)
            except Exception as e:
                logger.error(f"ccxt error fetching ticker: {str(e)}")
        
        # Fallback to direct API
        endpoint = "/api/v1/market/ticker"
        params = {"symbol": symbol}
        return self._request("GET", endpoint, params=params)
    
    def create_order(self, symbol, order_type, side, amount, price=None):
        """Create a new order"""
        if self.exchange:
            try:
                return self.exchange.create_order(symbol, order_type, side, amount, price)
            except Exception as e:
                logger.error(f"ccxt error creating order: {str(e)}")
        
        # Fallback to direct API
        endpoint = "/api/v1/trade/order"
        data = {
            "symbol": symbol,
            "type": order_type,
            "side": side,
            "quantity": str(amount)
        }
        if price:
            data["price"] = str(price)
            
        return self._request("POST", endpoint, data=data)
    
    def get_open_orders(self, symbol=None):
        """Get open orders"""
        if self.exchange:
            try:
                return self.exchange.fetch_open_orders(symbol)
            except Exception as e:
                logger.error(f"ccxt error fetching open orders: {str(e)}")
        
        # Fallback to direct API
        endpoint = "/api/v1/trade/openOrders"
        params = {}
        if symbol:
            params["symbol"] = symbol
            
        return self._request("GET", endpoint, params=params)
    
    def cancel_order(self, order_id, symbol):
        """Cancel an order"""
        if self.exchange:
            try:
                return self.exchange.cancel_order(order_id, symbol)
            except Exception as e:
                logger.error(f"ccxt error canceling order: {str(e)}")
        
        # Fallback to direct API
        endpoint = "/api/v1/trade/order"
        data = {
            "symbol": symbol,
            "orderId": order_id
        }
        return self._request("DELETE", endpoint, data=data)
    
    def get_market_data(self):
        """Get market data for opportunity detection"""
        if self.exchange:
            try:
                markets = self.exchange.fetch_markets()
                tickers = {}
                for market in markets[:30]:  # Limit to 30 markets to avoid rate limiting
                    symbol = market['symbol']
                    try:
                        tickers[symbol] = self.exchange.fetch_ticker(symbol)
                    except Exception:
                        pass
                return {"markets": markets, "tickers": tickers}
            except Exception as e:
                logger.error(f"ccxt error fetching market data: {str(e)}")
        
        # Fallback - simplified version
        endpoint = "/api/v1/market/symbols"
        symbols = self._request("GET", endpoint)
        
        if not symbols:
            return {"markets": [], "tickers": {}}
        
        tickers = {}
        for symbol_data in symbols[:30]:  # Limit to 30 symbols
            symbol = symbol_data.get("symbol")
            if symbol:
                ticker = self.get_ticker(symbol)
                if ticker:
                    tickers[symbol] = ticker
        
        return {"markets": symbols, "tickers": tickers}

class OpportunityDetector:
    """Detects value generation opportunities across multiple domains"""
    
    def __init__(self, github_api, pionex_api=None):
        self.github = github_api
        self.pionex = pionex_api
        self.opportunities = []
    
    def detect_all_opportunities(self):
        """Run all opportunity detection methods"""
        logger.info("Starting opportunity detection across all domains...")
        
        try:
            # Detect crypto trading opportunities
            if self.pionex:
                self.detect_crypto_opportunities()
            
            # Detect GitHub opportunities
            self.detect_github_opportunities()
            
            # Detect content generation opportunities
            self.detect_content_opportunities()
            
            # Detect API wrapper opportunities
            self.detect_api_wrapper_opportunities()
            
            # Prioritize opportunities
            self.prioritize_opportunities()
            
            logger.info(f"Opportunity detection complete. Found {len(self.opportunities)} opportunities.")
            return self.opportunities
        except Exception as e:
            logger.error(f"Error during opportunity detection: {str(e)}")
            traceback.print_exc()
            return []
    
    def detect_crypto_opportunities(self):
        """Detect cryptocurrency trading opportunities"""
        if not self.pionex:
            logger.warning("Pionex API not available. Skipping crypto opportunity detection.")
            return
        
        logger.info("Detecting cryptocurrency trading opportunities...")
        
        try:
            # Get market data
            market_data = self.pionex.get_market_data()
            if not market_data or not market_data.get("tickers"):
                logger.warning("No market data available for crypto opportunity detection.")
                return
            
            # Analyze market data for opportunities
            tickers = market_data["tickers"]
            for symbol, ticker in tickers.items():
                # Skip non-USDT pairs for simplicity
                if not symbol.endswith("USDT"):
                    continue
                
                # Extract relevant metrics
                try:
                    price = float(ticker.get("last", 0))
                    volume = float(ticker.get("quoteVolume", 0))
                    price_change = float(ticker.get("percentage", 0))
                    
                    # Skip low volume or invalid price
                    if price <= 0 or volume < 10000:  # $10K minimum volume
                        continue
                    
                    # Check for significant price movements
                    if abs(price_change) > 5:  # >5% price change
                        opportunity_type = "memecoin_detector" if abs(price_change) > 15 else "crypto_trading"
                        direction = "buy" if price_change > 0 else "sell"
                        
                        # Calculate opportunity score
                        score = min(100, (abs(price_change) * volume / 100000) ** 0.5)
                        
                        self.opportunities.append({
                            "type": opportunity_type,
                            "subtype": "price_momentum",
                            "symbol": symbol,
                            "direction": direction,
                            "price": price,
                            "price_change": price_change,
                            "volume": volume,
                            "score": score,
                            "timestamp": datetime.now().isoformat(),
                            "details": f"{symbol} {direction} opportunity: {price_change:.2f}% change with ${volume:.2f} volume"
                        })
                        
                        logger.info(f"Detected crypto opportunity: {symbol} {direction} ({price_change:.2f}%)")
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error processing ticker data for {symbol}: {str(e)}")
        except Exception as e:
            logger.error(f"Error in crypto opportunity detection: {str(e)}")
    
    def detect_github_opportunities(self):
        """Detect GitHub project opportunities"""
        logger.info("Detecting GitHub project opportunities...")
        
        try:
            # Search for trending repositories
            trending_query = "stars:>100 created:>2024-01-01 sort:stars"
            endpoint = "/search/repositories"
            params = {"q": trending_query, "per_page": 30}
            
            search_results = self.github._request("GET", endpoint, params=params)
            if not search_results or "items" not in search_results:
                logger.warning("No GitHub search results available.")
                return
            
            # Analyze repositories for opportunities
            for repo in search_results["items"]:
                try:
                    # Extract relevant metrics
                    name = repo.get("name", "")
                    full_name = repo.get("full_name", "")
                    stars = repo.get("stargazers_count", 0)
                    forks = repo.get("forks_count", 0)
                    description = repo.get("description", "")
                    language = repo.get("language", "")
                    created_at = repo.get("created_at", "")
                    
                    # Skip repositories with too many forks (already well-exploited)
                    if forks > 100:
                        continue
                    
                    # Calculate fork-to-star ratio (lower is better for arbitrage)
                    fork_star_ratio = forks / max(1, stars)
                    
                    # Check for arbitrage opportunities (popular but not many forks)
                    if stars > 100 and fork_star_ratio < 0.1:
                        # Calculate opportunity score
                        score = min(100, (stars * (1 - fork_star_ratio) / 10) ** 0.5)
                        
                        self.opportunities.append({
                            "type": "github_arbitrage",
                            "subtype": "underforked_project",
                            "repo_name": name,
                            "full_name": full_name,
                            "stars": stars,
                            "forks": forks,
                            "language": language,
                            "score": score,
                            "timestamp": datetime.now().isoformat(),
                            "details": f"GitHub arbitrage opportunity: {full_name} with {stars} stars but only {forks} forks"
                        })
                        
                        logger.info(f"Detected GitHub opportunity: {full_name} ({stars} stars, {forks} forks)")
                except (ValueError, TypeError, ZeroDivisionError) as e:
                    logger.warning(f"Error processing repository data for {repo.get('full_name', 'unknown')}: {str(e)}")
        except Exception as e:
            logger.error(f"Error in GitHub opportunity detection: {str(e)}")
    
    def detect_api_wrapper_opportunities(self):
        """Detect API wrapper generation opportunities"""
        logger.info("Detecting API wrapper opportunities...")
        
        try:
            # Search for popular APIs without good wrappers
            api_query = "API documentation stars:>50 created:>2023-01-01"
            endpoint = "/search/repositories"
            params = {"q": api_query, "per_page": 20}
            
            search_results = self.github._request("GET", endpoint, params=params)
            if not search_results or "items" not in search_results:
                logger.warning("No API search results available.")
                return
            
            # Analyze repositories for wrapper opportunities
            for repo in search_results["items"]:
                try:
                    # Extract relevant metrics
                    name = repo.get("name", "")
                    full_name = repo.get("full_name", "")
                    stars = repo.get("stargazers_count", 0)
                    description = repo.get("description", "").lower() if repo.get("description") else ""
                    
                    # Check if it's an API
                    is_api = any(keyword in description for keyword in ["api", "sdk", "client", "interface", "wrapper"])
                    if not is_api:
                        continue
                    
                    # Search for existing wrappers
                    wrapper_query = f"{name} wrapper language:python language:javascript language:typescript"
                    wrapper_params = {"q": wrapper_query, "per_page": 10}
                    wrapper_results = self.github._request("GET", endpoint, params=wrapper_params)
                    
                    existing_wrappers = len(wrapper_results.get("items", [])) if wrapper_results else 0
                    
                    # If popular API with few wrappers, it's an opportunity
                    if stars > 50 and existing_wrappers < 3:
                        # Calculate opportunity score
                        score = min(100, (stars / (existing_wrappers + 1) / 5) ** 0.5)
                        
                        self.opportunities.append({
                            "type": "api_wrapper_factory",
                            "subtype": "missing_wrapper",
                            "repo_name": name,
                            "full_name": full_name,
                            "stars": stars,
                            "existing_wrappers": existing_wrappers,
                            "score": score,
                            "timestamp": datetime.now().isoformat(),
                            "details": f"API wrapper opportunity: {full_name} with {stars} stars but only {existing_wrappers} existing wrappers"
                        })
                        
                        logger.info(f"Detected API wrapper opportunity: {full_name} ({stars} stars, {existing_wrappers} existing wrappers)")
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error processing API data for {repo.get('full_name', 'unknown')}: {str(e)}")
        except Exception as e:
            logger.error(f"Error in API wrapper opportunity detection: {str(e)}")
    
    def detect_content_opportunities(self):
        """Detect content generation opportunities"""
        logger.info("Detecting content generation opportunities...")
        
        try:
            # List of trending topics to check
            trending_topics = [
                "artificial-intelligence", "machine-learning", "crypto", 
                "web-development", "blockchain", "nft", "defi"
            ]
            
            for topic in trending_topics:
                # Search for trending content in this topic
                topic_query = f"topic:{topic} created:>2024-01-01 sort:stars"
                endpoint = "/search/repositories"
                params = {"q": topic_query, "per_page": 5}
                
                search_results = self.github._request("GET", endpoint, params=params)
                if not search_results or "items" not in search_results:
                    continue
                
                # If we find popular repositories, it's a content opportunity
                if len(search_results["items"]) > 0:
                    avg_stars = sum(repo.get("stargazers_count", 0) for repo in search_results["items"]) / len(search_results["items"])
                    
                    if avg_stars > 20:
                        # Calculate opportunity score
                        score = min(100, (avg_stars / 10) ** 0.5)
                        
                        self.opportunities.append({
                            "type": "content_generation",
                            "subtype": "trending_topic",
                            "topic": topic,
                            "avg_stars": avg_stars,
                            "score": score,
                            "timestamp": datetime.now().isoformat(),
                            "details": f"Content generation opportunity: {topic} is trending with {avg_stars:.1f} average stars"
                        })
                        
                        logger.info(f"Detected content opportunity: {topic} ({avg_stars:.1f} avg stars)")
        except Exception as e:
            logger.error(f"Error in content opportunity detection: {str(e)}")
    
    def prioritize_opportunities(self):
        """Prioritize detected opportunities based on score and type"""
        if not self.opportunities:
            return
        
        # Sort opportunities by score (descending)
        self.opportunities.sort(key=lambda x: x.get("score", 0), reverse=True)
        
        # Log top opportunities
        logger.info("Top opportunities:")
        for i, opp in enumerate(self.opportunities[:5], 1):
            logger.info(f"{i}. {opp['type']}: {opp['details']} (Score: {opp['score']:.1f})")

class AgentDeployer:
    """Deploys and manages agent repositories based on detected opportunities"""
    
    def __init__(self, github_api, pionex_api=None):
        self.github = github_api
        self.pionex = pionex_api
        self.deployed_agents = []
    
    def deploy_agents_for_opportunities(self, opportunities, max_agents=5):
        """Deploy agents for the top opportunities"""
        if not opportunities:
            logger.info("No opportunities to deploy agents for.")
            return []
        
        logger.info(f"Deploying agents for top {min(max_agents, len(opportunities))} opportunities...")
        
        deployed = []
        for opp in opportunities[:max_agents]:
            try:
                # Determine agent type based on opportunity type
                agent_type = VALUE_STRATEGIES.get(opp["type"], {}).get("agent_type")
                if not agent_type:
                    agent_type = f"{opp['type']}-agent"
                
                # Generate unique agent name with timestamp
                timestamp = datetime.now().strftime("%m%d%H%M")
                agent_name = f"{agent_type}-{timestamp}"
                
                # Check if agent already exists
                if self.github.repo_exists(agent_name):
                    logger.warning(f"Agent repository {agent_name} already exists. Skipping.")
                    continue
                
                # Deploy the agent
                result = self.deploy_agent(agent_name, opp)
                if result:
                    deployed.append({
                        "agent_name": agent_name,
                        "opportunity": opp,
                        "deployment_time": datetime.now().isoformat()
                    })
                    logger.info(f"Successfully deployed agent: {agent_name}")
                else:
                    logger.error(f"Failed to deploy agent: {agent_name}")
            except Exception as e:
                logger.error(f"Error deploying agent for opportunity {opp.get('type')}: {str(e)}")
                traceback.print_exc()
        
        self.deployed_agents.extend(deployed)
        logger.info(f"Deployed {len(deployed)} new agents.")
        return deployed
    
    def deploy_agent(self, agent_name, opportunity):
        """Deploy a single agent repository"""
        try:
            # Create repository
            description = f"Autonomous agent for {opportunity['type']} opportunity"
            result = self.github.create_repo(agent_name, description)
            if not result:
                logger.error(f"Failed to create repository {agent_name}")
                return False
            
            # Create agent script
            agent_script = self._generate_agent_script(opportunity)
            result = self.github.create_or_update_file(
                agent_name,
                "agent.py",
                agent_script,
                "Initial agent script deployment"
            )
            if not result:
                logger.error(f"Failed to create agent script in {agent_name}")
                return False
            
            # Create workflow file
            workflow_content = self._generate_workflow_file(opportunity)
            result = self.github.create_or_update_file(
                agent_name,
                ".github/workflows/main.yml",
                workflow_content,
                "Add GitHub Actions workflow"
            )
            if not result:
                logger.error(f"Failed to create workflow in {agent_name}")
                return False
            
            # Create requirements.txt
            requirements = self._generate_requirements(opportunity)
            result = self.github.create_or_update_file(
                agent_name,
                "requirements.txt",
                requirements,
                "Add requirements.txt"
            )
            if not result:
                logger.error(f"Failed to create requirements.txt in {agent_name}")
                return False
            
            # Create opportunity.json with the opportunity details
            result = self.github.create_or_update_file(
                agent_name,
                "opportunity.json",
                json.dumps(opportunity, indent=2),
                "Add opportunity details"
            )
            if not result:
                logger.error(f"Failed to create opportunity.json in {agent_name}")
                return False
            
            # Add secrets if needed
            if opportunity["type"] in ["crypto_trading", "memecoin_detector", "defi_yield_farming"]:
                if self.pionex:
                    self.github.create_secret(agent_name, "PIONEX_API_KEY", self.pionex.api_key)
                    self.github.create_secret(agent_name, "PIONEX_API_SECRET", self.pionex.api_secret)
            
            # Always add GH_PAT secret
            self.github.create_secret(agent_name, "GH_PAT", self.github.token)
            
            # Create initial task in agent-tasks
            self._create_initial_task(agent_name, opportunity)
            
            return True
        except Exception as e:
            logger.error(f"Error deploying agent {agent_name}: {str(e)}")
            traceback.print_exc()
            return False
    
    def _create_initial_task(self, agent_name, opportunity):
        """Create initial task for the agent in agent-tasks repository"""
        try:
            task_id = f"init-{agent_name}-{int(time.time())}"
            task_payload = {
                "id": task_id,
                "type": opportunity["type"],
                "payload": opportunity,
                "priority": 1,
                "created_at": datetime.now().isoformat()
            }
            
            title = f"Initial task for {agent_name}"
            body = json.dumps(task_payload, indent=2)
            
            result = self.github.create_issue(
                "agent-tasks",
                title,
                body,
                ["todo"]
            )
            
            if result:
                logger.info(f"Created initial task for {agent_name}")
                return True
            else:
                logger.error(f"Failed to create initial task for {agent_name}")
                return False
        except Exception as e:
            logger.error(f"Error creating initial task: {str(e)}")
            return False
    
    def _generate_agent_script(self, opportunity):
        """Generate agent script based on opportunity type"""
        opp_type = opportunity["type"]
        
        if opp_type == "crypto_trading":
            return self._generate_crypto_trading_script(opportunity)
        elif opp_type == "github_arbitrage":
            return self._generate_github_arbitrage_script(opportunity)
        elif opp_type == "api_wrapper_factory":
            return self._generate_api_wrapper_script(opportunity)
        elif opp_type == "memecoin_detector":
            return self._generate_memecoin_script(opportunity)
        elif opp_type == "content_generation":
            return self._generate_content_script(opportunity)
        elif opp_type == "defi_yield_farming":
            return self._generate_defi_script(opportunity)
        else:
            return self._generate_generic_script(opportunity)
    
    def _generate_crypto_trading_script(self, opportunity):
        """Generate crypto trading agent script"""
        symbol = opportunity.get("symbol", "BTCUSDT")
        
        return f"""#!/usr/bin/env python3
\"\"\"
Crypto Trading Agent - Autonomous cryptocurrency trading
\"\"\"
import os
import json
import time
import requests
import hmac
import hashlib
import traceback
from datetime import datetime, timedelta
import ccxt

# Configuration
PIONEX_API_KEY = os.getenv('PIONEX_API_KEY')
PIONEX_API_SECRET = os.getenv('PIONEX_API_SECRET')
GITHUB_TOKEN = os.getenv('GH_PAT')
AGENT_RESULTS_REPO = "zipaJopa/agent-results"
TRADING_SYMBOL = "{symbol}"
MAX_POSITION_SIZE = 20.0  # Maximum USDT to use per trade
STOP_LOSS_PERCENT = 2.0  # 2% stop loss
TAKE_PROFIT_PERCENT = 5.0  # 5% take profit

def setup_pionex():
    \"\"\"Initialize Pionex exchange\"\"\"
    try:
        exchange = ccxt.pionex({{
            'apiKey': PIONEX_API_KEY,
            'secret': PIONEX_API_SECRET,
        }})
        return exchange
    except Exception as e:
        print(f"Error setting up Pionex: {{e}}")
        return None

def get_market_data(exchange, symbol):
    \"\"\"Get current market data\"\"\"
    try:
        ticker = exchange.fetch_ticker(symbol)
        return ticker
    except Exception as e:
        print(f"Error getting market data: {{e}}")
        return None

def analyze_market(ticker, opportunity):
    \"\"\"Analyze market and decide on action\"\"\"
    if not ticker:
        return None
    
    current_price = ticker['last']
    price_change = ticker['percentage']
    
    # Use the opportunity direction as initial signal
    signal = opportunity.get('direction', 'neutral')
    
    # Validate with current data
    if signal == 'buy' and price_change < 0:
        # Opportunity said buy but price is falling, be cautious
        if price_change < -3:
            signal = 'neutral'  # Changed too much, stay neutral
    elif signal == 'sell' and price_change > 0:
        # Opportunity said sell but price is rising, be cautious
        if price_change > 3:
            signal = 'neutral'  # Changed too much, stay neutral
    
    return {{
        'signal': signal,
        'price': current_price,
        'price_change': price_change,
        'timestamp': datetime.now().isoformat()
    }}

def execute_trade(exchange, symbol, signal, current_price):
    \"\"\"Execute trade based on signal\"\"\"
    try:
        # Get account balance
        balance = exchange.fetch_balance()
        usdt_balance = balance['total'].get('USDT', 0)
        
        # Determine trade amount
        trade_amount = min(MAX_POSITION_SIZE, usdt_balance * 0.5)
        if trade_amount < 10:  # Minimum $10 USDT
            print(f"Insufficient balance for trading: {{usdt_balance}} USDT")
            return None
        
        # Calculate quantity
        base_currency = symbol.split('/')[0]
        quantity = trade_amount / current_price
        
        # Execute trade
        if signal == 'buy':
            order = exchange.create_market_buy_order(symbol, quantity)
            print(f"Executed BUY order: {{quantity}} {{base_currency}} at {{current_price}}")
            return {{
                'action': 'buy',
                'symbol': symbol,
                'quantity': quantity,
                'price': current_price,
                'total': quantity * current_price,
                'order_id': order['id'],
                'timestamp': datetime.now().isoformat()
            }}
        elif signal == 'sell':
            # Check if we have the asset to sell
            asset_balance = balance['total'].get(base_currency, 0)
            if asset_balance < quantity:
                quantity = asset_balance  # Sell what we have
            
            if quantity > 0:
                order = exchange.create_market_sell_order(symbol, quantity)
                print(f"Executed SELL order: {{quantity}} {{base_currency}} at {{current_price}}")
                return {{
                    'action': 'sell',
                    'symbol': symbol,
                    'quantity': quantity,
                    'price': current_price,
                    'total': quantity * current_price,
                    'order_id': order['id'],
                    'timestamp': datetime.now().isoformat()
                }}
        
        return None
    except Exception as e:
        print(f"Error executing trade: {{e}}")
        traceback.print_exc()
        return None

def save_results(results):
    \"\"\"Save trading results to agent-results repository\"\"\"
    try:
        # Format results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"outputs/{{datetime.now().strftime('%Y-%m-%d')}}/crypto_trading_{{timestamp}}.json"
        
        # GitHub API request to create file
        url = f"https://api.github.com/repos/{{AGENT_RESULTS_REPO}}/contents/{{filename}}"
        headers = {{
            "Authorization": f"token {{GITHUB_TOKEN}}",
            "Accept": "application/vnd.github.v3+json"
        }}
        
        # Ensure the content is properly formatted
        content_str = json.dumps(results, indent=2)
        content_bytes = content_str.encode('utf-8')
        content_b64 = base64.b64encode(content_bytes).decode('utf-8')
        
        data = {{
            "message": f"Add trading results {{timestamp}}",
            "content": content_b64
        }}
        
        response = requests.put(url, headers=headers, json=data)
        if response.status_code in (201, 200):
            print(f"Results saved to {{filename}}")
            return True
        else:
            print(f"Error saving results: {{response.status_code}} - {{response.text}}")
            return False
    except Exception as e:
        print(f"Error saving results: {{e}}")
        return False

def main():
    \"\"\"Main trading function\"\"\"
    print(f"🚀 Crypto Trading Agent starting at {{datetime.now().isoformat()}}")
    
    try:
        # Load opportunity data
        with open('opportunity.json', 'r') as f:
            opportunity = json.load(f)
        
        # Setup exchange
        exchange = setup_pionex()
        if not exchange:
            print("Failed to setup exchange. Exiting.")
            return
        
        # Get trading symbol from opportunity or use default
        symbol = opportunity.get('symbol', TRADING_SYMBOL)
        
        # Get market data
        ticker = get_market_data(exchange, symbol)
        if not ticker:
            print("Failed to get market data. Exiting.")
            return
        
        # Analyze market
        analysis = analyze_market(ticker, opportunity)
        print(f"Market analysis: {{analysis}}")
        
        # Execute trade if signal is not neutral
        results = {{
            'agent_type': 'crypto_trading',
            'symbol': symbol,
            'analysis': analysis,
            'trade_executed': False,
            'trade_details': None,
            'pnl_usd': 0.0,
            'timestamp': datetime.now().isoformat()
        }}
        
        if analysis and analysis['signal'] in ('buy', 'sell'):
            trade = execute_trade(exchange, symbol, analysis['signal'], analysis['price'])
            if trade:
                results['trade_executed'] = True
                results['trade_details'] = trade
                
                # Estimate PnL (very rough estimate)
                if trade['action'] == 'buy':
                    # For buys, we're betting on future gains
                    results['pnl_usd'] = 0.0  # No immediate PnL
                else:  # sell
                    # For sells, estimate based on recent price change
                    price_change_pct = analysis['price_change']
                    avoided_loss = trade['total'] * (price_change_pct / 100)
                    results['pnl_usd'] = -avoided_loss  # Negative of the loss we avoided
        
        # Save results
        save_results(results)
        print(f"Trading cycle completed at {{datetime.now().isoformat()}}")
    
    except Exception as e:
        print(f"Error in trading cycle: {{e}}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
"""
    
    def _generate_github_arbitrage_script(self, opportunity):
        """Generate GitHub arbitrage agent script"""
        repo_name = opportunity.get("repo_name", "")
        full_name = opportunity.get("full_name", "")
        
        return f"""#!/usr/bin/env python3
\"\"\"
GitHub Arbitrage Agent - Find, fork, and improve undervalued repositories
\"\"\"
import os
import json
import time
import requests
import base64
import traceback
from datetime import datetime

# Configuration
GITHUB_TOKEN = os.getenv('GH_PAT')
AGENT_RESULTS_REPO = "zipaJopa/agent-results"
TARGET_REPO = "{full_name}"

def github_request(method, endpoint, data=None, params=None):
    \"\"\"Make a GitHub API request\"\"\"
    url = f"https://api.github.com{{endpoint}}"
    headers = {{
        "Authorization": f"token {{GITHUB_TOKEN}}",
        "Accept": "application/vnd.github.v3+json"
    }}
    
    try:
        if method == "GET":
            response = requests.get(url, headers=headers, params=params)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data)
        elif method == "PUT":
            response = requests.put(url, headers=headers, json=data)
        else:
            print(f"Unsupported method: {{method}}")
            return None
        
        if response.status_code in (200, 201, 204):
            return response.json() if response.content else {{}}
        else:
            print(f"GitHub API error: {{response.status_code}} - {{response.text}}")
            return None
    except Exception as e:
        print(f"Request error: {{e}}")
        return None

def fork_repository(repo_full_name):
    \"\"\"Fork a repository\"\"\"
    endpoint = f"/repos/{{repo_full_name}}/forks"
    return github_request("POST", endpoint)

def get_repository_info(repo_full_name):
    \"\"\"Get repository information\"\"\"
    endpoint = f"/repos/{{repo_full_name}}"
    return github_request("GET", endpoint)

def get_repository_contents(repo_full_name, path=""):
    \"\"\"Get repository contents\"\"\"
    endpoint = f"/repos/{{repo_full_name}}/contents/{{path}}"
    return github_request("GET", endpoint)

def analyze_repository(repo_full_name):
    \"\"\"Analyze repository for improvement opportunities\"\"\"
    # Get basic repo info
    repo_info = get_repository_info(repo_full_name)
    if not repo_info:
        return None
    
    # Get root contents
    contents = get_repository_contents(repo_full_name)
    if not contents:
        return None
    
    # Check for common improvement opportunities
    has_readme = any(item.get("name", "").lower() == "readme.md" for item in contents if isinstance(item, dict))
    has_license = any(item.get("name", "").lower() in ("license", "license.md", "license.txt") for item in contents if isinstance(item, dict))
    has_contributing = any(item.get("name", "").lower() in ("contributing.md", "contributing") for item in contents if isinstance(item, dict))
    has_ci = ".github/workflows" in [item.get("path") for item in contents if isinstance(item, dict)]
    
    improvement_opportunities = []
    
    if not has_readme:
        improvement_opportunities.append({{
            "type": "missing_readme",
            "description": "Repository is missing a README.md file"
        }})
    
    if not has_license:
        improvement_opportunities.append({{
            "type": "missing_license",
            "description": "Repository is missing a LICENSE file"
        }})
    
    if not has_contributing:
        improvement_opportunities.append({{
            "type": "missing_contributing",
            "description": "Repository is missing a CONTRIBUTING.md file"
        }})
    
    if not has_ci:
        improvement_opportunities.append({{
            "type": "missing_ci",
            "description": "Repository is missing CI/CD configuration"
        }})
    
    return {{
        "repo_name": repo_info.get("name"),
        "full_name": repo_info.get("full_name"),
        "description": repo_info.get("description"),
        "stars": repo_info.get("stargazers_count"),
        "forks": repo_info.get("forks_count"),
        "language": repo_info.get("language"),
        "improvement_opportunities": improvement_opportunities,
        "improvement_count": len(improvement_opportunities),
        "timestamp": datetime.now().isoformat()
    }}

def save_results(results):
    \"\"\"Save arbitrage results to agent-results repository\"\"\"
    try:
        # Format results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"outputs/{{datetime.now().strftime('%Y-%m-%d')}}/github_arbitrage_{{timestamp}}.json"
        
        # GitHub API request to create file
        url = f"https://api.github.com/repos/{{AGENT_RESULTS_REPO}}/contents/{{filename}}"
        headers = {{
            "Authorization": f"token {{GITHUB_TOKEN}}",
            "Accept": "application/vnd.github.v3+json"
        }}
        
        # Ensure the content is properly formatted
        content_str = json.dumps(results, indent=2)
        content_bytes = content_str.encode('utf-8')
        content_b64 = base64.b64encode(content_bytes).decode('utf-8')
        
        data = {{
            "message": f"Add GitHub arbitrage results {{timestamp}}",
            "content": content_b64
        }}
        
        response = requests.put(url, headers=headers, json=data)
        if response.status_code in (201, 200):
            print(f"Results saved to {{filename}}")
            return True
        else:
            print(f"Error saving results: {{response.status_code}} - {{response.text}}")
            return False
    except Exception as e:
        print(f"Error saving results: {{e}}")
        return False

def main():
    \"\"\"Main arbitrage function\"\"\"
    print(f"🔍 GitHub Arbitrage Agent starting at {{datetime.now().isoformat()}}")
    
    try:
        # Load opportunity data
        with open('opportunity.json', 'r') as f:
            opportunity = json.load(f)
        
        # Get target repository from opportunity or use default
        repo_full_name = opportunity.get('full_name', TARGET_REPO)
        if not repo_full_name:
            print("No target repository specified. Exiting.")
            return
        
        # Analyze repository
        analysis = analyze_repository(repo_full_name)
        if not analysis:
            print(f"Failed to analyze repository {{repo_full_name}}. Exiting.")
            return
        
        print(f"Repository analysis: {{analysis}}")
        
        # Fork repository if there are improvement opportunities
        forked = False
        fork_result = None
        
        if analysis['improvement_count'] > 0:
            print(f"Found {{analysis['improvement_count']}} improvement opportunities. Forking repository...")
            fork_result = fork_repository(repo_full_name)
            forked = fork_result is not None
        
        # Prepare results
        results = {{
            'agent_type': 'github_arbitrage',
            'target_repo': repo_full_name,
            'analysis': analysis,
            'forked': forked,
            'fork_details': fork_result,
            'value_score': analysis['improvement_count'] * (analysis['stars'] / 10),
            'timestamp': datetime.now().isoformat()
        }}
        
        # Save results
        save_results(results)
        print(f"Arbitrage cycle completed at {{datetime.now().isoformat()}}")
    
    except Exception as e:
        print(f"Error in arbitrage cycle: {{e}}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
"""
    
    def _generate_api_wrapper_script(self, opportunity):
        """Generate API wrapper factory script"""
        repo_name = opportunity.get("repo_name", "")
        full_name = opportunity.get("full_name", "")
        
        return f"""#!/usr/bin/env python3
\"\"\"
API Wrapper Factory - Generate API wrappers and SDKs for popular APIs
\"\"\"
import os
import json
import time
import requests
import base64
import traceback
from datetime import datetime

# Configuration
GITHUB_TOKEN = os.getenv('GH_PAT')
AGENT_RESULTS_REPO = "zipaJopa/agent-results"
TARGET_API_REPO = "{full_name}"

def github_request(method, endpoint, data=None, params=None):
    \"\"\"Make a GitHub API request\"\"\"
    url = f"https://api.github.com{{endpoint}}"
    headers = {{
        "Authorization": f"token {{GITHUB_TOKEN}}",
        "Accept": "application/vnd.github.v3+json"
    }}
    
    try:
        if method == "GET":
            response = requests.get(url, headers=headers, params=params)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data)
        elif method == "PUT":
            response = requests.put(url, headers=headers, json=data)
        else:
            print(f"Unsupported method: {{method}}")
            return None
        
        if response.status_code in (200, 201, 204):
            return response.json() if response.content else {{}}
        else:
            print(f"GitHub API error: {{response.status_code}} - {{response.text}}")
            return None
    except Exception as e:
        print(f"Request error: {{e}}")
        return None

def get_repository_info(repo_full_name):
    \"\"\"Get repository information\"\"\"
    endpoint = f"/repos/{{repo_full_name}}"
    return github_request("GET", endpoint)

def get_repository_contents(repo_full_name, path=""):
    \"\"\"Get repository contents\"\"\"
    endpoint = f"/repos/{{repo_full_name}}/contents/{{path}}"
    return github_request("GET", endpoint)

def get_file_content(repo_full_name, file_path):
    \"\"\"Get content of a specific file\"\"\"
    endpoint = f"/repos/{{repo_full_name}}/contents/{{file_path}}"
    response = github_request("GET", endpoint)
    
    if response and "content" in response:
        return base64.b64decode(response["content"]).decode('utf-8')
    return None

def create_repository(name, description):
    \"\"\"Create a new repository\"\"\"
    endpoint = "/user/repos"
    data = {{
        "name": name,
        "description": description,
        "private": False,
        "auto_init": True
    }}
    return github_request("POST", endpoint, data=data)

def create_file(repo_full_name, file_path, content, commit_message):
    \"\"\"Create a file in a repository\"\"\"
    endpoint = f"/repos/{{repo_full_name}}/contents/{{file_path}}"
    
    content_bytes = content.encode('utf-8')
    content_b64 = base64.b64encode(content_bytes).decode('utf-8')
    
    data = {{
        "message": commit_message,
        "content": content_b64
    }}
    
    return github_request("PUT", endpoint, data=data)

def analyze_api(repo_full_name):
    \"\"\"Analyze API repository for wrapper generation\"\"\"
    # Get basic repo info
    repo_info = get_repository_info(repo_full_name)
    if not repo_info:
        return None
    
    # Get root contents
    contents = get_repository_contents(repo_full_name)
    if not contents:
        return None
    
    # Look for API documentation files
    api_docs = []
    for item in contents:
        if isinstance(item, dict) and item.get("type") == "file":
            name = item.get("name", "").lower()
            if "api" in name or "doc" in name or name in ("readme.md", "swagger.json", "openapi.yaml", "openapi.json"):
                file_content = get_file_content(repo_full_name, item.get("path"))
                if file_content:
                    api_docs.append({{
                        "name": item.get("name"),
                        "path": item.get("path"),
                        "content_sample": file_content[:500] + "..." if len(file_content) > 500 else file_content
                    }})
    
    # Check for API endpoints
    api_endpoints = []
    for doc in api_docs:
        content = doc["content_sample"]
        # Very basic endpoint detection - would need to be more sophisticated in a real implementation
        if "/api/" in content or "endpoint" in content.lower() or "route" in content.lower():
            api_endpoints.append({{
                "doc_name": doc["name"],
                "detected": True
            }})
    
    return {{
        "repo_name": repo_info.get("name"),
        "full_name": repo_info.get("full_name"),
        "description": repo_info.get("description"),
        "stars": repo_info.get("stargazers_count"),
        "api_docs_found": len(api_docs) > 0,
        "api_docs": api_docs,
        "api_endpoints_detected": len(api_endpoints) > 0,
        "api_endpoints": api_endpoints,
        "wrapper_feasibility": "high" if len(api_docs) > 0 and len(api_endpoints) > 0 else "medium" if len(api_docs) > 0 else "low",
        "timestamp": datetime.now().isoformat()
    }}

def generate_wrapper_skeleton(api_name, api_analysis):
    \"\"\"Generate a basic wrapper skeleton\"\"\"
    wrapper_name = f"{{api_name.lower().replace(' ', '-')}}-wrapper"
    
    # Generate README
    readme = f\"\"\"# {{api_name}} Wrapper

A Python wrapper for the {{api_name}} API.

## Installation

```
pip install {{wrapper_name}}
```

## Usage

```python
from {{wrapper_name.replace('-', '_')}} import {{api_name.replace(' ', '')}}Client

# Initialize the client
client = {{api_name.replace(' ', '')}}Client(api_key="your_api_key")

# Make API calls
response = client.get_data()
print(response)
```

## API Reference

\"\"\"
    
    # Generate basic client class
    client_code = f\"\"\"import requests
import json

class {{api_name.replace(' ', '')}}Client:
    \"\"\"Client for the {{api_name}} API\"\"\"
    
    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key
        self.base_url = base_url or "https://api.example.com/v1"
        self.session = requests.Session()
        if api_key:
            self.session.headers.update({{"Authorization": f"Bearer {{self.api_key}}"}})
        self.session.headers.update({{"Content-Type": "application/json"}})
    
    def _request(self, method, endpoint, params=None, data=None):
        \"\"\"Make an API request\"\"\"
        url = f"{{self.base_url}}{{endpoint}}"
        
        try:
            if method == "GET":
                response = self.session.get(url, params=params)
            elif method == "POST":
                response = self.session.post(url, json=data)
            elif method == "PUT":
                response = self.session.put(url, json=data)
            elif method == "DELETE":
                response = self.session.delete(url)
            else:
                raise ValueError(f"Unsupported method: {{method}}")
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"API request error: {{e}}")
            return None
    
    def get_data(self, **params):
        \"\"\"Get data from the API\"\"\"
        return self._request("GET", "/data", params=params)
    
    # Add more methods based on API documentation
\"\"\"
    
    # Generate setup.py
    setup_py = f\"\"\"from setuptools import setup, find_packages

setup(
    name="{{wrapper_name}}",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "requests>=2.25.0",
    ],
    author="AI Agent",
    author_email="agent@example.com",
    description="Python wrapper for the {{api_name}} API",
    keywords="api, wrapper, {{api_name.lower()}}",
    url="https://github.com/zipaJopa/{{wrapper_name}}",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.6",
)
\"\"\"
    
    return {{
        "wrapper_name": wrapper_name,
        "files": {{
            "README.md": readme,
            f"{{wrapper_name.replace('-', '_')}}/client.py": client_code,
            f"{{wrapper_name.replace('-', '_')}}/__init__.py": f"from .client import {{api_name.replace(' ', '')}}Client\\n\\n__version__ = '0.1.0'\\n",
            "setup.py": setup_py
        }}
    }}

def save_results(results):
    \"\"\"Save wrapper factory results to agent-results repository\"\"\"
    try:
        # Format results
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"outputs/{{datetime.now().strftime('%Y-%m-%d')}}/api_wrapper_{{timestamp}}.json"
        
        # GitHub API request to create file
        url = f"https://api.github.com/repos/{{AGENT_RESULTS_REPO}}/contents/{{filename}}"
        headers = {{
            "Authorization": f"token {{GITHUB_TOKEN}}",
            "Accept": "application/vnd.github.v3+json"
        }}
        
        # Ensure the content is properly formatted
        content_str = json.dumps(results, indent=2)
        content_bytes = content_str.encode('utf-8')
        content_b64 = base64.b64encode(content_bytes).decode('utf-8')
        
        data = {{
            "message": f"Add API wrapper results {{timestamp}}",
            "content": content_b64
        }}
        
        response = requests.put(url, headers=headers, json=data)
        if response.status_code in (201, 200):
            print(f"Results saved to {{filename}}")
            return True
        else:
            print(f"Error saving results: {{response.status_code}} - {{response.text}}")
            return False
    except Exception as e:
        print(f"Error saving results: {{e}}")
        return False

def main():
    \"\"\"Main wrapper factory function\"\"\"
    print(f"🏭 API Wrapper Factory starting at {{datetime.now().isoformat()}}")
    
    try:
        # Load opportunity data
        with open('opportunity.json', 'r') as f:
            opportunity = json.load(f)
        
        # Get target API repository from opportunity or use default
        repo_full_name = opportunity.get('full_name', TARGET_API_REPO)
        if not repo_full_name:
            print("No target API repository specified. Exiting.")
            return
        
        # Analyze API repository
        analysis = analyze_api(repo_full_name)
        if not analysis:
            print(f"Failed to analyze API repository {{repo_full_name}}. Exiting.")
            return
        
        print(f"API repository analysis: {{analysis}}")
        
        # Generate wrapper if feasible
        wrapper_generated = False
        wrapper_repo_name = None
        wrapper_details = None
        
        if analysis['wrapper_feasibility'] in ('high', 'medium'):
            print(f"Generating wrapper for {{repo_full_name}}...")
            
            # Extract API name from repository name
            api_name = analysis['repo_name'].replace('-', ' ').replace('_', ' ').title()
            
            # Generate wrapper skeleton
            wrapper = generate_wrapper_skeleton(api_name, analysis)
            
            # Create wrapper repository
            wrapper_repo_name = wrapper['wrapper_name']
            wrapper_repo = create_repository(
                wrapper_repo_name,
                f"Python wrapper for the {{api_name}} API"
            )
            
            if wrapper_repo:
                # Create wrapper files
                for file_path, content in wrapper['files'].items():
                    create_file(
                        f"zipaJopa/{{wrapper_repo_name}}",
                        file_path,
                        content,
                        f"Add {{file_path}}"
                    )
                
                wrapper_generated = True
                wrapper_details = wrapper
        
        # Prepare results
        results = {{
            'agent_type': 'api_wrapper_factory',
            'target_api_repo': repo_full_name,
            'analysis': analysis,
            'wrapper_generated': wrapper_generated,
            'wrapper_repo_name': wrapper_repo_name,
            'wrapper_details': wrapper_details,
            'value_score': 50 if wrapper_generated else 10,
            'timestamp': datetime.now().isoformat()
        }}
        
        # Save results
        save_results(results)
        print(f"Wrapper factory cycle completed at {{datetime.now().isoformat()}}")
    
    except Exception as e:
        print(f"Error in wrapper factory cycle: {{e}}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
"""
    
    def _generate_memecoin_script(self, opportunity):
        """Generate memecoin detector script"""
        symbol = opportunity.get("symbol", "DOGEUSDT")
        
        return f"""#!/usr/bin/env python3
\"\"\"
Memecoin Detector - Find and trade early-stage memecoins
\"\"\"
import os
import json
import time
import requests
import hmac
import hashlib
import base64
import traceback
from datetime import datetime, timedelta
import ccxt

# Configuration
PIONEX_API_KEY = os.getenv('PIONEX_API_KEY')
PIONEX_API_SECRET = os.getenv('PIONEX_API_SECRET')
GITHUB_TOKEN = os.getenv('GH_PAT')
AGENT_RESULTS_REPO = "zipaJopa/agent-results"
TARGET_SYMBOL = "{symbol}"
MAX_POSITION_SIZE = 5.0  # Maximum USDT to use per trade
STOP_LOSS_PERCENT = 5.0  # 5% stop loss
TAKE_PROFIT_PERCENT = 20.0  # 20% take profit

def setup_pionex():
    \"\"\"Initialize Pionex exchange\"\"\"
    try:
        exchange = ccxt.pionex({{
            'apiKey': PIONEX_API_KEY,
            'secret': PIONEX_API_SECRET,
        }})
        return exchange
    except Exception as e:
        print(f"Error setting up Pionex: {{e}}")
        return None

def get_market_data(exchange):
    \"\"\"Get current market data for potential memecoins\"\"\"
    try:
        # Get all tickers
        tickers = exchange.fetch_tickers()
        
        # Filter for potential memecoins
        memecoin_candidates = []
        for symbol, ticker in tickers.items():
            # Only consider USDT pairs
            if not symbol.endswith('USDT'):
                continue
            
            # Extract base currency (e.g., "DOGE" from "DOGE/USDT")
            base_currency = symbol.split('/')[0]
            
            # Skip major cryptocurrencies
            major_cryptos = ['BTC', 'ETH', 'BNB', 'XRP', 'ADA', 'SOL', 'DOT', 'AVAX', 'MATIC']
            if base_currency in major_cryptos:
                continue
            
            # Check for high volatility and volume
            if ticker.get('percentage') and ticker.get('quoteVolume'):
                percentage = ticker.get('percentage', 0)
                volume = ticker.get('quoteVolume', 0)
                
                # Look for high volatility and decent volume
                if abs(percentage) > 5 and volume > 100000:  # >5% change and >$100K volume
                    memecoin_candidates.append({{
                        'symbol': symbol,
                        'price': ticker.get('last', 0),
                        'change_percentage': percentage,
                        'volume': volume,
                        'score': abs(percentage) * (volume / 100000) ** 0.5  # Score based on volatility and volume
                    }})
        
        # Sort by score
        memecoin_candidates.sort(key=lambda x: x['score'], reverse=True)
        return memecoin_candidates[:10]  # Return top 10 candidates
    except Exception as e:
        print(f"Error getting market data: {{e}}")
        return None

def analyze_memecoin(exchange, symbol):
    \"\"\"Analyze a specific memecoin\"\"\"
    try:
        # Get ticker
        ticker = exchange.fetch_ticker(symbol)
        if not ticker:
            return None
        
        # Get recent trades
        trades = exchange.fetch_trades(symbol, limit=100)
        
        # Get order book
        order_book = exchange.fetch_order_book(symbol)
        
        # Calculate buy/sell ratio from order book
        buy_volume = sum(order[1] for order in order_book['bids'][:10])
        sell_volume = sum(order[1] for order in order_book['asks'][:10])
        buy_sell_ratio = buy_volume / sell_volume if sell_volume > 0 else 0
        
        # Calculate recent trade direction
        buy_trades = sum(1 for trade in trades if trade['side'] == 'buy')
        sell_trades = sum(1 for trade in trades if trade['side'] == 'sell')
        buy_sell_trade_ratio = buy_trades / sell_trades if sell_trades > 0 else 0
        
        # Determine signal
        price_change = ticker.get('percentage', 0)
        signal = 'neutral'
        
        if price_change > 10 and buy_sell_ratio > 1.2 and buy_sell_trade_ratio > 1.2:
            signal = 'buy'  # Strong upward momentum
        elif price_change < -15 or (price_change < -5 and buy_sell_ratio < 0.8):
            signal = 'sell'  # Downward trend or potential dump
        
        return {{
            'symbol': symbol,
            'price': ticker.get('last', 0),
            'price_change': price_change,
            'volume': ticker.get('quoteVolume', 0),
            'buy_sell_ratio': buy_sell_ratio,
            'buy_sell_trade_ratio': buy_sell_trade_ratio,
            'signal': signal,
            'timestamp': datetime.now().isoformat()
        }}
    except Exception as e:
        print(f"Error analyzing memecoin: {{e}}")
        return None

def execute_trade(exchange, symbol, signal, analysis):
    \"\"\"Execute trade based on signal\"\"\"
    try:
        # Get account balance
        balance = exchange.fetch_balance()
        usdt_balance = balance['total'].get('USDT', 0)
        
        # Determine trade amount
        trade_amount = min(MAX_POSITION_SIZE, usdt_balance * 0.2)  # Use at most 20% of available USDT
        if trade_amount < 5:  # Minimum $5 USDT
            print(f"Insufficient balance for trading: {{usdt_balance}} USDT")
            return None
        
        # Calculate quantity
        base_currency = symbol.split('/')[0]
        price = analysis['price']
        quantity = trade_amount / price
        
        # Execute trade
        if signal == 'buy':
            order = exchange.create_market_buy_order(symbol, quantity)
            print(f"Executed BUY order: {{quantity}} {{base_currency}} at {{price}}")
            return {{
                'action': 'buy',
                'symbol': symbol,
                'quantity': quantity,
                'price': price,
                'total': quantity * price,
                'order_id': order['id'],
                'timestamp': datetime.now().isoformat()
            }}
        elif signal == 'sell':
            # Check if we have the asset to sell
            asset_balance = balance['total'].get(base_currency, 0)
            if asset_balance < quantity:
                quantity = asset_balance  # Sell what we have
            
            if quantity > 0:
                order = exchange.create_market_sell_order(symbol, quantity)
