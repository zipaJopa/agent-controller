#!/usr/bin/env python3
"""
Constellation Secret Setup - Autonomous GitHub Secret Propagation
-----------------------------------------------------------------
This script automatically sets up required GitHub Actions secrets (PIONEX_API_KEY,
PIONEX_API_SECRET, GH_PAT) across ALL repositories in the specified GitHub organization.

It is designed to be a one-time setup script to ensure all current and future
agents in the constellation have the necessary credentials.

**Prerequisites:**
1.  **Install pynacl:** `pip install pynacl requests`
2.  **Set Environment Variables:**
    *   `ADMIN_GH_PAT`: A GitHub Personal Access Token with `repo` scope (ideally `admin:org`
                       if you want it to discover all org repos, or at least access to all
                       target repos) to run THIS script. This PAT will be used to list
                       repositories and set secrets.
    *   `AGENT_GH_PAT`: The GitHub Personal Access Token that will be set as the `GH_PAT`
                       secret in all agent repositories. This token needs `repo` and `workflow`
                       scopes for the agents to function.
    *   `PIONEX_API_KEY_TO_SET`: The Pionex API Key to be set as a secret.
    *   `PIONEX_API_SECRET_TO_SET`: The Pionex API Secret to be set as a secret.

Usage:
    python setup_constellation_secrets.py
"""

import os
import sys
import json
import requests
import base64
import logging
import time
from typing import Dict, List, Optional, Any

try:
    from nacl import encoding, public
except ImportError:
    print("Error: pynacl library not found. Please install it: pip install pynacl")
    sys.exit(1)

# --- Configuration ---
GITHUB_API_URL = "https://api.github.com"
GITHUB_ORG = "zipaJopa"  # Your GitHub organization/username
SECRETS_TO_SET_MAP = { # Maps env var name to the secret name in GitHub
    "AGENT_GH_PAT": "GH_PAT",
    "PIONEX_API_KEY_TO_SET": "PIONEX_API_KEY",
    "PIONEX_API_SECRET_TO_SET": "PIONEX_API_SECRET"
}
MAX_RETRIES = 3
RETRY_DELAY = 5 # seconds

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("constellation_secrets_setup.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ConstellationSecretsSetup")

class GitHubAPI:
    """Helper class for GitHub API interactions."""
    def __init__(self, token: str):
        if not token:
            raise ValueError("GitHub token (ADMIN_GH_PAT) is required.")
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
                    sleep_duration = max(0, reset_time - time.time()) + 5 # Add buffer
                    logger.warning(f"Rate limit low. Sleeping for {sleep_duration:.2f} seconds.")
                    time.sleep(sleep_duration)

                if response.status_code == 403 and "rate limit exceeded" in response.text.lower():
                    logger.warning(f"Rate limit exceeded. Retrying in {RETRY_DELAY * (attempt + 1)}s...")
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                
                response.raise_for_status()
                return response.json() if response.content else {}
            except requests.exceptions.HTTPError as e:
                logger.error(f"GitHub API Error ({method} {url}): {e.response.status_code} - {e.response.text}")
                if attempt == MAX_RETRIES - 1: return None # Or raise
            except requests.exceptions.RequestException as e:
                logger.error(f"Request Error ({method} {url}): {e}")
                if attempt == MAX_RETRIES - 1: return None # Or raise
            time.sleep(RETRY_DELAY * (attempt + 1)) # Exponential backoff
        return None

    def get_org_repos(self, org: str) -> List[Dict]:
        """Get all repositories for an organization, handling pagination."""
        repos = []
        page = 1
        per_page = 100 
        while True:
            endpoint = f"/orgs/{org}/repos"
            params = {"type": "all", "per_page": per_page, "page": page}
            current_page_repos = self._request("GET", endpoint, params=params)
            if current_page_repos is None: # Error occurred
                logger.error(f"Failed to fetch repositories for org {org} on page {page}.")
                break
            if not current_page_repos: # No more repos
                break
            repos.extend(current_page_repos)
            if len(current_page_repos) < per_page:
                break
            page += 1
            logger.info(f"Fetched page {page-1} of repositories for {org}. Total fetched so far: {len(repos)}")
        logger.info(f"Total repositories fetched for {org}: {len(repos)}")
        return repos

    def get_user_repos(self) -> List[Dict]:
        """Get all repositories for the authenticated user, handling pagination."""
        repos = []
        page = 1
        per_page = 100
        while True:
            endpoint = "/user/repos" # Gets repos for the authenticated user
            params = {"per_page": per_page, "page": page, "affiliation": "owner"}
            current_page_repos = self._request("GET", endpoint, params=params)
            if current_page_repos is None:
                logger.error(f"Failed to fetch user repositories on page {page}.")
                break
            if not current_page_repos:
                break
            repos.extend(current_page_repos)
            if len(current_page_repos) < per_page:
                break
            page += 1
            logger.info(f"Fetched page {page-1} of user repositories. Total fetched so far: {len(repos)}")
        logger.info(f"Total user repositories fetched: {len(repos)}")
        return repos


    def get_repo_public_key(self, owner: str, repo: str) -> Optional[Dict]:
        """Get the public key for encrypting secrets for a repository."""
        endpoint = f"/repos/{owner}/{repo}/actions/secrets/public-key"
        return self._request("GET", endpoint)

    def set_repo_secret(self, owner: str, repo: str, secret_name: str, encrypted_value: str, key_id: str) -> bool:
        """Set an Actions secret for a repository."""
        endpoint = f"/repos/{owner}/{repo}/actions/secrets/{secret_name}"
        payload = {
            "encrypted_value": encrypted_value,
            "key_id": key_id
        }
        response = self._request("PUT", endpoint, data=payload)
        # Successful PUT to this endpoint returns 201 for new secret, 204 for update
        return response is not None 

def encrypt_secret(public_key_value: str, secret_value: str) -> str:
    """Encrypt a secret using the repository's public key."""
    public_key = public.PublicKey(public_key_value.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")

def main():
    logger.info("🚀 Starting Constellation Secrets Setup Script 🚀")

    # --- Get credentials from environment variables ---
    admin_gh_pat = os.getenv("ADMIN_GH_PAT")
    secrets_to_propagate = {}
    for env_var_name, secret_name_in_github in SECRETS_TO_SET_MAP.items():
        value = os.getenv(env_var_name)
        if value:
            secrets_to_propagate[secret_name_in_github] = value
        else:
            logger.warning(f"Environment variable {env_var_name} not set. Secret '{secret_name_in_github}' will not be propagated.")

    if not admin_gh_pat:
        logger.error("❌ Critical Error: ADMIN_GH_PAT environment variable not set. This script cannot run.")
        sys.exit(1)
    
    if not secrets_to_propagate:
        logger.error("❌ No secrets to propagate found in environment variables (e.g., AGENT_GH_PAT, PIONEX_API_KEY_TO_SET). Exiting.")
        sys.exit(1)

    logger.info(f"Will attempt to set the following secrets: {', '.join(secrets_to_propagate.keys())}")

    github = GitHubAPI(admin_gh_pat)

    # --- Fetch repositories ---
    logger.info(f"Fetching repositories for organization/user: {GITHUB_ORG}...")
    # Check if GITHUB_ORG is likely a username and prioritize fetching user repos
    if GITHUB_ORG == "zipaJopa":
        logger.info(f"'{GITHUB_ORG}' is specified as the target. Assuming it's a username and fetching user repositories...")
        repos = github.get_user_repos()
        if not repos:
             logger.error(f"❌ Failed to fetch any repositories for user '{GITHUB_ORG}'. Please check PAT permissions and username.")
             sys.exit(1)
    else:
        # Original logic: Try fetching as an organization first, then fallback to user
        logger.info(f"Fetching repositories for organization/user: {GITHUB_ORG}...")
        repos = github.get_org_repos(GITHUB_ORG)
        if not repos: # If no org repos, try fetching as user repos (in case GITHUB_ORG is a username)
            logger.info(f"No repositories found for org '{GITHUB_ORG}'. Trying to fetch repositories for the authenticated user...")
            repos = github.get_user_repos()
            if not repos:
                logger.error(f"❌ Failed to fetch any repositories for '{GITHUB_ORG}' (as org or user). Please check PAT permissions and org/user name.")
                sys.exit(1)

    logger.info(f"Found {len(repos)} repositories to process.")

    # --- Iterate and set secrets for each repository ---
    successful_updates = 0
    failed_updates = 0

    for repo_data in repos:
        repo_name = repo_data["name"]
        repo_owner = repo_data["owner"]["login"] # Use the actual owner from repo data
        
        logger.info(f"\nProcessing repository: {repo_owner}/{repo_name}")

        public_key_data = github.get_repo_public_key(repo_owner, repo_name)
        if not public_key_data or "key" not in public_key_data or "key_id" not in public_key_data:
            logger.error(f"  ❌ Failed to get public key for {repo_owner}/{repo_name}. Skipping secrets for this repo.")
            failed_updates += len(secrets_to_propagate)
            continue
        
        repo_public_key = public_key_data["key"]
        repo_key_id = public_key_data["key_id"]

        for secret_name, secret_value in secrets_to_propagate.items():
            try:
                logger.info(f"  Setting secret: {secret_name} for {repo_owner}/{repo_name}...")
                encrypted_value = encrypt_secret(repo_public_key, secret_value)
                if github.set_repo_secret(repo_owner, repo_name, secret_name, encrypted_value, repo_key_id):
                    logger.info(f"    ✅ Successfully set secret: {secret_name}")
                    successful_updates += 1
                else:
                    logger.error(f"    ❌ Failed to set secret: {secret_name}")
                    failed_updates += 1
            except Exception as e:
                logger.error(f"    ❌ Error encrypting/setting secret {secret_name} for {repo_owner}/{repo_name}: {e}")
                failed_updates += 1
                # traceback.print_exc() # Uncomment for detailed debugging

    # --- Summary ---
    logger.info("\n--- 🔑 Secrets Propagation Summary ---")
    logger.info(f"Total repositories processed: {len(repos)}")
    logger.info(f"Total secrets attempted to set per repo: {len(secrets_to_propagate)}")
    logger.info(f"Successfully set secrets: {successful_updates}")
    logger.info(f"Failed to set secrets: {failed_updates}")

    if failed_updates > 0:
        logger.warning("⚠️ Some secrets could not be set. Please review the logs.")
    else:
        logger.info("🎉 All specified secrets were successfully propagated across all found repositories!")

    logger.info("Secrets setup script finished.")

if __name__ == "__main__":
    main()
