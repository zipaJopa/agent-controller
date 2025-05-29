#!/usr/bin/env python3
"""
AI Constellation Self-Test & Auto-Deployment System
--------------------------------------------------
This script autonomously tests, fixes, and deploys the entire AI constellation.
It requires no manual intervention and will:

1. Test all constellation components
2. Fix common issues automatically
3. Create test tasks and verify end-to-end flow
4. Auto-deploy Wave 2 agents if core system works
5. Generate status dashboard
6. Run health checks and auto-remediation

Usage:
    python self_test.py

Requirements:
    - GitHub PAT with repo and workflow scopes as GH_PAT environment variable
    - Python 3.9+
    - requests, colorama packages
"""

import os
import sys
import json
import time
import base64
import random
import string
import requests
import subprocess
from datetime import datetime, timedelta
import traceback
import logging
from typing import Dict, List, Any, Tuple, Optional, Union

try:
    from colorama import Fore, Style, init
    init()  # Initialize colorama
except ImportError:
    # Define fallback color codes if colorama is not available
    class DummyFore:
        def __getattr__(self, name):
            return ""
    class DummyStyle:
        def __getattr__(self, name):
            return ""
    Fore = DummyFore()
    Style = DummyStyle()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("constellation_test.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("constellation")

# Configuration Constants
GITHUB_API_URL = "https://api.github.com"
GITHUB_ORG = "zipaJopa"  # GitHub organization/username
RETRY_DELAY = 5  # seconds between retries
MAX_RETRIES = 3  # maximum number of retries for API calls

# Core repositories
CORE_REPOS = {
    "agent-controller": {
        "description": "Central orchestrator for the AI agent constellation",
        "required_files": ["agent_controller.py", ".github/workflows/main.yml", "requirements.txt"]
    },
    "agent-tasks": {
        "description": "Task queue and execution engine for AI agents",
        "required_files": ["task_manager.py", ".github/workflows/main.yml", "requirements.txt"]
    },
    "agent-memory": {
        "description": "Vector store and knowledge management for AI agents",
        "required_files": ["memory_manager.py", ".github/workflows/main.yml", "requirements.txt", "vector_store.py"]
    },
    "agent-results": {
        "description": "Results tracking and value calculation for AI agents",
        "required_files": ["results_tracker.py", ".github/workflows/main.yml", "requirements.txt"]
    },
    "github-harvester": {
        "description": "Harvests valuable GitHub projects automatically",
        "required_files": ["harvester.py", ".github/workflows/main.yml", "requirements.txt"]
    }
}

# Wave 2 agent repositories to deploy if core tests pass
WAVE2_AGENTS = {
    "github-arbitrage-agent": {
        "description": "Finds and improves undervalued GitHub repositories",
        "template_files": {
            "arbitrage_agent.py": """#!/usr/bin/env python3
\"\"\"
GitHub Arbitrage Agent - Finds and improves undervalued repositories
\"\"\"
import os
import json
import requests
import time
from datetime import datetime

# Configuration
GITHUB_TOKEN = os.getenv('GH_PAT')
AGENT_TASKS_REPO = "zipaJopa/agent-tasks"
AGENT_RESULTS_REPO = "zipaJopa/agent-results"

def main():
    print("🔍 GitHub Arbitrage Agent running...")
    # Implement arbitrage logic here
    
if __name__ == "__main__":
    main()
"""
        }
    },
    "crypto-trading-agent": {
        "description": "Automated cryptocurrency trading via Pionex API",
        "template_files": {
            "trading_agent.py": """#!/usr/bin/env python3
\"\"\"
Crypto Trading Agent - Automated trading via Pionex API
\"\"\"
import os
import json
import requests
import time
import hmac
import hashlib
from datetime import datetime

# Configuration
PIONEX_API_KEY = os.getenv('PIONEX_API_KEY')
PIONEX_API_SECRET = os.getenv('PIONEX_API_SECRET')
AGENT_TASKS_REPO = "zipaJopa/agent-tasks"
AGENT_RESULTS_REPO = "zipaJopa/agent-results"

def main():
    print("💰 Crypto Trading Agent running...")
    # Implement trading logic here
    
if __name__ == "__main__":
    main()
"""
        }
    },
    "ai-wrapper-factory": {
        "description": "Automatically generates API wrappers and SDKs",
        "template_files": {
            "wrapper_factory.py": """#!/usr/bin/env python3
\"\"\"
AI Wrapper Factory - Generates API wrappers and SDKs
\"\"\"
import os
import json
import requests
from datetime import datetime

# Configuration
GITHUB_TOKEN = os.getenv('GH_PAT')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
AGENT_TASKS_REPO = "zipaJopa/agent-tasks"
AGENT_RESULTS_REPO = "zipaJopa/agent-results"

def main():
    print("🏭 AI Wrapper Factory running...")
    # Implement wrapper generation logic here
    
if __name__ == "__main__":
    main()
"""
        }
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
                if response.status_code == 403 and 'X-RateLimit-Remaining' in response.headers and int(response.headers['X-RateLimit-Remaining']) < 10:
                    reset_time = int(response.headers.get('X-RateLimit-Reset', time.time() + 60))
                    sleep_duration = max(0, reset_time - time.time()) + 5
                    logger.warning(f"Rate limit low. Sleeping for {sleep_duration:.2f} seconds.")
                    time.sleep(sleep_duration)
                
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
        sha = existing_file["sha"] if existing_file else None
        
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
        
        # TODO: Implement proper secret encryption using sodium library
        # For now, this is a placeholder
        logger.warning(f"Secret encryption not implemented. Secret {secret_name} not created.")
        return False

class ConstellationTester:
    """Tests and fixes the AI constellation components"""
    
    def __init__(self, github_token):
        self.github = GitHubAPI(github_token)
        self.token = github_token
        self.test_results = {
            "core_repos_exist": False,
            "required_files_exist": False,
            "workflows_configured": False,
            "test_tasks_created": False,
            "end_to_end_flow": False,
            "wave2_deployed": False,
            "status": "not_started",
            "issues": [],
            "fixes_applied": []
        }
    
    def run_all_tests(self):
        """Run all tests and fixes"""
        logger.info(f"{Fore.CYAN}Starting AI Constellation Self-Test{Style.RESET_ALL}")
        
        try:
            # Step 1: Check if core repositories exist
            self.test_core_repos_exist()
            
            # Step 2: Check if required files exist
            self.test_required_files_exist()
            
            # Step 3: Check if workflows are configured
            self.test_workflows_configured()
            
            # Step 4: Create test tasks
            self.create_test_tasks()
            
            # Step 5: Test end-to-end flow
            self.test_end_to_end_flow()
            
            # Step 6: Deploy Wave 2 agents if core tests pass
            if self.test_results["end_to_end_flow"]:
                self.deploy_wave2_agents()
            
            # Generate status dashboard
            self.generate_status_dashboard()
            
            # Final status
            if self.test_results["status"] == "success":
                logger.info(f"{Fore.GREEN}All tests passed! The constellation is fully operational.{Style.RESET_ALL}")
            else:
                logger.warning(f"{Fore.YELLOW}Some tests failed. Check the dashboard for details.{Style.RESET_ALL}")
                
        except Exception as e:
            logger.error(f"{Fore.RED}Error during testing: {str(e)}{Style.RESET_ALL}")
            traceback.print_exc()
            self.test_results["status"] = "error"
            self.test_results["issues"].append(f"Unhandled exception: {str(e)}")
    
    def test_core_repos_exist(self):
        """Test if core repositories exist and create them if they don't"""
        logger.info(f"{Fore.CYAN}Testing if core repositories exist...{Style.RESET_ALL}")
        
        missing_repos = []
        for repo_name, repo_info in CORE_REPOS.items():
            full_repo_name = f"{GITHUB_ORG}/{repo_name}"
            if self.github.repo_exists(repo_name):
                logger.info(f"✅ Repository {full_repo_name} exists")
            else:
                logger.warning(f"⚠️ Repository {full_repo_name} does not exist")
                missing_repos.append((repo_name, repo_info["description"]))
        
        # Fix: Create missing repositories
        if missing_repos:
            logger.info(f"{Fore.YELLOW}Creating missing repositories...{Style.RESET_ALL}")
            for repo_name, description in missing_repos:
                logger.info(f"Creating repository {repo_name}...")
                result = self.github.create_repo(repo_name, description)
                if result:
                    logger.info(f"✅ Created repository {repo_name}")
                    self.test_results["fixes_applied"].append(f"Created repository {repo_name}")
                else:
                    logger.error(f"❌ Failed to create repository {repo_name}")
                    self.test_results["issues"].append(f"Failed to create repository {repo_name}")
        
        # Check again after fixes
        all_repos_exist = all(self.github.repo_exists(repo_name) for repo_name in CORE_REPOS)
        self.test_results["core_repos_exist"] = all_repos_exist
        
        if all_repos_exist:
            logger.info(f"{Fore.GREEN}All core repositories exist{Style.RESET_ALL}")
        else:
            logger.error(f"{Fore.RED}Some core repositories could not be created{Style.RESET_ALL}")
    
    def test_required_files_exist(self):
        """Test if required files exist in core repositories and create them if they don't"""
        if not self.test_results["core_repos_exist"]:
            logger.warning("Skipping file check because some repositories don't exist")
            return
            
        logger.info(f"{Fore.CYAN}Testing if required files exist...{Style.RESET_ALL}")
        
        missing_files = {}
        for repo_name, repo_info in CORE_REPOS.items():
            repo_missing_files = []
            for file_path in repo_info["required_files"]:
                content = self.github.get_file_content(repo_name, file_path)
                if content:
                    logger.info(f"✅ File {file_path} exists in {repo_name}")
                else:
                    logger.warning(f"⚠️ File {file_path} missing in {repo_name}")
                    repo_missing_files.append(file_path)
            
            if repo_missing_files:
                missing_files[repo_name] = repo_missing_files
        
        # Fix: Create missing files with templates
        if missing_files:
            logger.info(f"{Fore.YELLOW}Creating missing files...{Style.RESET_ALL}")
            for repo_name, file_paths in missing_files.items():
                for file_path in file_paths:
                    # Generate template content based on file type
                    content = self._generate_template_file(repo_name, file_path)
                    if content:
                        result = self.github.create_or_update_file(
                            repo_name, 
                            file_path, 
                            content, 
                            f"Add {file_path} via self-test system"
                        )
                        if result:
                            logger.info(f"✅ Created file {file_path} in {repo_name}")
                            self.test_results["fixes_applied"].append(f"Created file {file_path} in {repo_name}")
                        else:
                            logger.error(f"❌ Failed to create file {file_path} in {repo_name}")
                            self.test_results["issues"].append(f"Failed to create file {file_path} in {repo_name}")
        
        # Check again after fixes
        all_files_exist = True
        for repo_name, repo_info in CORE_REPOS.items():
            for file_path in repo_info["required_files"]:
                if not self.github.get_file_content(repo_name, file_path):
                    all_files_exist = False
                    
        self.test_results["required_files_exist"] = all_files_exist
        
        if all_files_exist:
            logger.info(f"{Fore.GREEN}All required files exist{Style.RESET_ALL}")
        else:
            logger.error(f"{Fore.RED}Some required files could not be created{Style.RESET_ALL}")
    
    def test_workflows_configured(self):
        """Test if GitHub Actions workflows are properly configured"""
        if not self.test_results["required_files_exist"]:
            logger.warning("Skipping workflow check because some files don't exist")
            return
            
        logger.info(f"{Fore.CYAN}Testing if workflows are configured...{Style.RESET_ALL}")
        
        workflow_issues = {}
        for repo_name in CORE_REPOS:
            # Check if workflow file exists and contains GH_PAT
            workflow_content = self.github.get_file_content(repo_name, ".github/workflows/main.yml")
            if not workflow_content:
                logger.warning(f"⚠️ Workflow file missing in {repo_name}")
                workflow_issues[repo_name] = "Workflow file missing"
                continue
                
            if "GH_PAT" not in workflow_content:
                logger.warning(f"⚠️ Workflow in {repo_name} does not use GH_PAT")
                workflow_issues[repo_name] = "Workflow does not use GH_PAT"
                continue
                
            # Check if workflow runs exist
            workflows = self.github.list_workflows(repo_name)
            if not workflows or not workflows.get("workflows"):
                logger.warning(f"⚠️ No workflows found in {repo_name}")
                workflow_issues[repo_name] = "No workflows found"
                continue
                
            logger.info(f"✅ Workflows configured in {repo_name}")
        
        # Fix: Update workflow files to use GH_PAT
        if workflow_issues:
            logger.info(f"{Fore.YELLOW}Fixing workflow issues...{Style.RESET_ALL}")
            for repo_name, issue in workflow_issues.items():
                if issue == "Workflow file missing" or issue == "Workflow does not use GH_PAT":
                    # Generate template workflow
                    content = self._generate_template_workflow(repo_name)
                    if content:
                        result = self.github.create_or_update_file(
                            repo_name, 
                            ".github/workflows/main.yml", 
                            content, 
                            "Update workflow to use GH_PAT via self-test system"
                        )
                        if result:
                            logger.info(f"✅ Fixed workflow in {repo_name}")
                            self.test_results["fixes_applied"].append(f"Fixed workflow in {repo_name}")
                        else:
                            logger.error(f"❌ Failed to fix workflow in {repo_name}")
                            self.test_results["issues"].append(f"Failed to fix workflow in {repo_name}")
        
        # Check again after fixes
        all_workflows_ok = True
        for repo_name in CORE_REPOS:
            workflow_content = self.github.get_file_content(repo_name, ".github/workflows/main.yml")
            if not workflow_content or "GH_PAT" not in workflow_content:
                all_workflows_ok = False
                
        self.test_results["workflows_configured"] = all_workflows_ok
        
        if all_workflows_ok:
            logger.info(f"{Fore.GREEN}All workflows are properly configured{Style.RESET_ALL}")
        else:
            logger.error(f"{Fore.RED}Some workflows could not be fixed{Style.RESET_ALL}")
    
    def create_test_tasks(self):
        """Create test tasks in agent-tasks repository"""
        if not self.test_results["workflows_configured"]:
            logger.warning("Skipping test task creation because workflows are not configured")
            return
            
        logger.info(f"{Fore.CYAN}Creating test tasks...{Style.RESET_ALL}")
        
        # Check if test tasks already exist
        existing_issues = self.github.list_issues("agent-tasks", labels="test")
        if existing_issues:
            logger.info(f"Found {len(existing_issues)} existing test tasks")
            self.test_results["test_tasks_created"] = True
            return
        
        # Create test harvest task
        test_id = f"test-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        harvest_task = {
            "id": f"{test_id}-harvest",
            "type": "harvest",
            "payload": {
                "topics": ["ai-agent", "automation"],
                "min_stars": 25,
                "created_after": "2024-01-01",
                "count_per_topic": 2
            },
            "priority": 1,
            "created_at": datetime.now().isoformat()
        }
        
        result = self.github.create_issue(
            "agent-tasks",
            f"Test Harvest Task - Self-Test {test_id}",
            json.dumps(harvest_task, indent=2),
            ["test", "todo"]
        )
        
        if result:
            logger.info(f"✅ Created test harvest task")
            self.test_results["test_tasks_created"] = True
        else:
            logger.error(f"❌ Failed to create test harvest task")
            self.test_results["issues"].append("Failed to create test harvest task")
            self.test_results["test_tasks_created"] = False
    
    def test_end_to_end_flow(self):
        """Test the end-to-end flow by triggering workflows and checking results"""
        if not self.test_results["test_tasks_created"]:
            logger.warning("Skipping end-to-end test because test tasks were not created")
            return
            
        logger.info(f"{Fore.CYAN}Testing end-to-end flow...{Style.RESET_ALL}")
        
        # Trigger agent-controller workflow
        workflows = self.github.list_workflows("agent-controller")
        if not workflows or not workflows.get("workflows"):
            logger.error("❌ No workflows found in agent-controller")
            self.test_results["issues"].append("No workflows found in agent-controller")
            return
            
        workflow_id = workflows["workflows"][0]["id"]
        result = self.github.trigger_workflow("agent-controller", workflow_id)
        
        if not result:
            logger.error("❌ Failed to trigger agent-controller workflow")
            self.test_results["issues"].append("Failed to trigger agent-controller workflow")
            return
            
        logger.info("✅ Triggered agent-controller workflow")
        
        # Wait for agent-controller to assign tasks
        logger.info("Waiting for agent-controller to assign tasks (30s)...")
        time.sleep(30)
        
        # Check if tasks were assigned (label changed from todo to in-progress)
        assigned = False
        for _ in range(3):  # Try a few times
            issues = self.github.list_issues("agent-tasks", labels="in-progress")
            if issues:
                for issue in issues:
                    if "Test Harvest Task" in issue["title"]:
                        assigned = True
                        logger.info(f"✅ Test task was assigned: {issue['title']}")
                        break
            
            if assigned:
                break
                
            logger.info("Tasks not assigned yet, waiting 30s more...")
            time.sleep(30)
        
        if not assigned:
            logger.warning("⚠️ Test tasks were not assigned within the timeout period")
            self.test_results["issues"].append("Test tasks were not assigned within the timeout period")
            
            # Try to fix by manually triggering github-harvester
            logger.info("Trying to fix by manually triggering github-harvester...")
            workflows = self.github.list_workflows("github-harvester")
            if workflows and workflows.get("workflows"):
                workflow_id = workflows["workflows"][0]["id"]
                result = self.github.trigger_workflow("github-harvester", workflow_id)
                if result:
                    logger.info("✅ Manually triggered github-harvester workflow")
                    self.test_results["fixes_applied"].append("Manually triggered github-harvester workflow")
                    time.sleep(30)  # Wait a bit for the workflow to run
        
        # Check if results were stored in agent-results
        results_stored = False
        for _ in range(3):  # Try a few times
            # This is a simplification - we would need to check specific files
            # For now, just check if there's any content in the outputs directory
            content = self.github.get_file_content("agent-results", "outputs")
            if content:
                results_stored = True
                logger.info("✅ Results were stored in agent-results")
                break
                
            logger.info("Results not stored yet, waiting 30s more...")
            time.sleep(30)
        
        if not results_stored:
            logger.warning("⚠️ Results were not stored within the timeout period")
            self.test_results["issues"].append("Results were not stored within the timeout period")
        
        # Final determination
        self.test_results["end_to_end_flow"] = assigned and results_stored
        
        if self.test_results["end_to_end_flow"]:
            logger.info(f"{Fore.GREEN}End-to-end flow test passed!{Style.RESET_ALL}")
        else:
            logger.error(f"{Fore.RED}End-to-end flow test failed{Style.RESET_ALL}")
    
    def deploy_wave2_agents(self):
        """Deploy Wave 2 agents if core tests pass"""
        if not self.test_results["end_to_end_flow"]:
            logger.warning("Skipping Wave 2 deployment because end-to-end test failed")
            return
            
        logger.info(f"{Fore.CYAN}Deploying Wave 2 agents...{Style.RESET_ALL}")
        
        deployed_count = 0
        for repo_name, repo_info in WAVE2_AGENTS.items():
            # Check if repo already exists
            if self.github.repo_exists(repo_name):
                logger.info(f"✅ Wave 2 agent {repo_name} already exists")
                deployed_count += 1
                continue
            
            # Create repository
            result = self.github.create_repo(repo_name, repo_info["description"])
            if not result:
                logger.error(f"❌ Failed to create repository {repo_name}")
                self.test_results["issues"].append(f"Failed to create Wave 2 agent repository {repo_name}")
                continue
                
            logger.info(f"✅ Created repository {repo_name}")
            
            # Create template files
            for file_path, content in repo_info["template_files"].items():
                result = self.github.create_or_update_file(
                    repo_name,
                    file_path,
                    content,
                    f"Add {file_path} via self-test system"
                )
                if not result:
                    logger.error(f"❌ Failed to create file {file_path} in {repo_name}")
                    self.test_results["issues"].append(f"Failed to create file {file_path} in Wave 2 agent {repo_name}")
            
            # Create workflow file
            workflow_content = self._generate_template_workflow(repo_name)
            result = self.github.create_or_update_file(
                repo_name,
                ".github/workflows/main.yml",
                workflow_content,
                "Add workflow via self-test system"
            )
            if not result:
                logger.error(f"❌ Failed to create workflow in {repo_name}")
                self.test_results["issues"].append(f"Failed to create workflow in Wave 2 agent {repo_name}")
            
            # Create requirements.txt
            requirements_content = "requests>=2.25.0\n"
            result = self.github.create_or_update_file(
                repo_name,
                "requirements.txt",
                requirements_content,
                "Add requirements.txt via self-test system"
            )
            if not result:
                logger.error(f"❌ Failed to create requirements.txt in {repo_name}")
                self.test_results["issues"].append(f"Failed to create requirements.txt in Wave 2 agent {repo_name}")
            
            deployed_count += 1
            logger.info(f"✅ Deployed Wave 2 agent {repo_name}")
        
        self.test_results["wave2_deployed"] = deployed_count == len(WAVE2_AGENTS)
        
        if self.test_results["wave2_deployed"]:
            logger.info(f"{Fore.GREEN}All Wave 2 agents deployed successfully!{Style.RESET_ALL}")
        else:
            logger.error(f"{Fore.RED}Some Wave 2 agents could not be deployed{Style.RESET_ALL}")
    
    def generate_status_dashboard(self):
        """Generate a status dashboard in the agent-results repository"""
        logger.info(f"{Fore.CYAN}Generating status dashboard...{Style.RESET_ALL}")
        
        # Determine overall status
        if all([
            self.test_results["core_repos_exist"],
            self.test_results["required_files_exist"],
            self.test_results["workflows_configured"],
            self.test_results["test_tasks_created"],
            self.test_results["end_to_end_flow"]
        ]):
            self.test_results["status"] = "success"
        elif self.test_results["status"] == "not_started":
            self.test_results["status"] = "partial"
        
        # Create dashboard markdown
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        dashboard = [
            f"# AI Constellation Status Dashboard",
            f"",
            f"**Generated:** {timestamp}",
            f"**Overall Status:** {self._status_badge(self.test_results['status'])}",
            f"",
            f"## Core Components Status",
            f"",
            f"| Component | Status | Details |",
            f"|-----------|--------|---------|",
            f"| Core Repositories | {self._status_badge(self.test_results['core_repos_exist'])} | All required repositories exist |",
            f"| Required Files | {self._status_badge(self.test_results['required_files_exist'])} | All required files exist |",
            f"| Workflows | {self._status_badge(self.test_results['workflows_configured'])} | GitHub Actions workflows configured |",
            f"| Test Tasks | {self._status_badge(self.test_results['test_tasks_created'])} | Test tasks created |",
            f"| End-to-End Flow | {self._status_badge(self.test_results['end_to_end_flow'])} | Complete task flow working |",
            f"| Wave 2 Agents | {self._status_badge(self.test_results['wave2_deployed'])} | Additional agent deployment |",
            f"",
            f"## Issues and Fixes",
            f"",
        ]
        
        if self.test_results["issues"]:
            dashboard.append(f"### Issues")
            dashboard.append(f"")
            for issue in self.test_results["issues"]:
                dashboard.append(f"- ❌ {issue}")
            dashboard.append(f"")
        else:
            dashboard.append(f"### Issues")
            dashboard.append(f"")
            dashboard.append(f"- ✅ No issues detected")
            dashboard.append(f"")
        
        if self.test_results["fixes_applied"]:
            dashboard.append(f"### Fixes Applied")
            dashboard.append(f"")
            for fix in self.test_results["fixes_applied"]:
                dashboard.append(f"- 🔧 {fix}")
            dashboard.append(f"")
        else:
            dashboard.append(f"### Fixes Applied")
            dashboard.append(f"")
            dashboard.append(f"- ℹ️ No fixes needed to be applied")
            dashboard.append(f"")
        
        dashboard.append(f"## Next Steps")
        dashboard.append(f"")
        
        if self.test_results["status"] == "success":
            dashboard.append(f"✅ **The AI Constellation is fully operational!**")
            dashboard.append(f"")
            dashboard.append(f"You can now:")
            dashboard.append(f"1. Monitor the system in GitHub Actions")
            dashboard.append(f"2. Create new tasks in the agent-tasks repository")
            dashboard.append(f"3. Check results in the agent-results repository")
            dashboard.append(f"4. Deploy more specialized agents")
        else:
            dashboard.append(f"⚠️ **The AI Constellation needs attention**")
            dashboard.append(f"")
            dashboard.append(f"Recommended actions:")
            dashboard.append(f"1. Fix the issues listed above")
            dashboard.append(f"2. Run this self-test script again")
            dashboard.append(f"3. Check GitHub Actions logs for more details")
        
        dashboard_content = "\n".join(dashboard)
        
        # Save dashboard to agent-results repository
        result = self.github.create_or_update_file(
            "agent-results",
            "CONSTELLATION_STATUS.md",
            dashboard_content,
            "Update constellation status dashboard"
        )
        
        if result:
            logger.info(f"✅ Generated status dashboard in agent-results/CONSTELLATION_STATUS.md")
        else:
            logger.error(f"❌ Failed to generate status dashboard")
    
    def _status_badge(self, status):
        """Generate a status badge for the dashboard"""
        if status is True:
            return "✅ Passed"
        elif status is False:
            return "❌ Failed"
        elif status == "success":
            return "✅ Success"
        elif status == "partial":
            return "⚠️ Partial"
        elif status == "error":
            return "❌ Error"
        else:
            return "❓ Unknown"
    
    def _generate_template_file(self, repo_name, file_path):
        """Generate template content for missing files"""
        if file_path.endswith("agent_controller.py"):
            return """#!/usr/bin/env python3
\"\"\"
Agent Controller - Central orchestrator for the AI agent constellation
\"\"\"
import os
import json
import requests
import time
from datetime import datetime

# Configuration
GITHUB_TOKEN = os.getenv('GH_PAT')
AGENT_TASKS_REPO = "zipaJopa/agent-tasks"

def main():
    print("🎯 Agent coordination cycle started...")
    # Implement controller logic here
    
if __name__ == "__main__":
    main()
"""
        elif file_path.endswith("task_manager.py"):
            return """#!/usr/bin/env python3
\"\"\"
Task Manager - Task queue and execution engine for AI agents
\"\"\"
import os
import json
import requests
import time
from datetime import datetime

# Configuration
GITHUB_TOKEN = os.getenv('GH_PAT')

def main():
    print("🔧 Task manager running...")
    # Implement task management logic here
    
if __name__ == "__main__":
    main()
"""
        elif file_path.endswith("memory_manager.py"):
            return """#!/usr/bin/env python3
\"\"\"
Memory Manager - Vector store and knowledge management for AI agents
\"\"\"
import os
import json
import time
from datetime import datetime

# Configuration
GITHUB_TOKEN = os.getenv('GH_PAT')

def main():
    print("🧠 Memory manager running...")
    # Implement memory management logic here
    
if __name__ == "__main__":
    main()
"""
        elif file_path.endswith("vector_store.py"):
            return """#!/usr/bin/env python3
\"\"\"
Vector Store - Embedding storage and retrieval for AI agents
\"\"\"
import json
import numpy as np

class VectorStore:
    def __init__(self, file_path="vector_store.json"):
        self.file_path = file_path
        self.vectors = {}
        
    def add_vector(self, key, vector, metadata=None):
        \"\"\"Add a vector to the store\"\"\"
        self.vectors[key] = {
            "vector": vector,
            "metadata": metadata or {}
        }
        
    def get_vector(self, key):
        \"\"\"Get a vector from the store\"\"\"
        return self.vectors.get(key)
        
    def save(self):
        \"\"\"Save vectors to file\"\"\"
        with open(self.file_path, 'w') as f:
            json.dump(self.vectors, f)
            
    def load(self):
        \"\"\"Load vectors from file\"\"\"
        try:
            with open(self.file_path, 'r') as f:
                self.vectors = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.vectors = {}
"""
        elif file_path.endswith("results_tracker.py"):
            return """#!/usr/bin/env python3
\"\"\"
Results Tracker - Results tracking and value calculation for AI agents
\"\"\"
import os
import json
import requests
import time
from datetime import datetime

# Configuration
GITHUB_TOKEN = os.getenv('GH_PAT')
AGENT_RESULTS_REPO = "zipaJopa/agent-results"

def main():
    print("📊 Results tracker running...")
    # Implement results tracking logic here
    
if __name__ == "__main__":
    main()
"""
        elif file_path.endswith("harvester.py"):
            return """#!/usr/bin/env python3
\"\"\"
GitHub Project Harvester - Auto-discover valuable projects
\"\"\"
import os
import json
import requests
import time
from datetime import datetime

# Configuration
GITHUB_TOKEN = os.getenv('GH_PAT')
AGENT_TASKS_REPO = "zipaJopa/agent-tasks"
AGENT_RESULTS_REPO = "zipaJopa/agent-results"

def main():
    print("⚡ GitHub Harvester running...")
    # Implement harvesting logic here
    
if __name__ == "__main__":
    main()
"""
        elif file_path.endswith("requirements.txt"):
            return "requests>=2.25.0\n"
        elif file_path.endswith("main.yml"):
            return self._generate_template_workflow(repo_name)
        else:
            logger.warning(f"No template available for {file_path}")
            return None
    
    def _generate_template_workflow(self, repo_name):
        """Generate template GitHub Actions workflow based on repository"""
        if repo_name == "agent-controller":
            return """name: Agent Controller

on:
  schedule:
    - cron: '*/5 * * * *'  # Run every 5 minutes
  workflow_dispatch:  # Allow manual triggering

jobs:
  coordinate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then
            pip install -r requirements.txt
          else
            echo "requirements.txt not found. Installing default dependencies (requests)."
            pip install requests
          fi
      - name: Run controller
        run: python agent_controller.py
        env:
          GITHUB_TOKEN: ${{ secrets.GH_PAT }}
"""
        elif repo_name == "agent-tasks":
            return """name: Task Manager

on:
  issues:
    types: [assigned]
  workflow_dispatch:

jobs:
  process_task:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then
            pip install -r requirements.txt
          else
            echo "requirements.txt not found. Installing default dependencies (requests)."
            pip install requests
          fi
      - name: Run task manager
        run: python task_manager.py
        env:
          GITHUB_TOKEN: ${{ secrets.GH_PAT }}
          ISSUE_NUMBER: ${{ github.event.issue.number }}
"""
        elif repo_name == "agent-memory":
            return """name: Memory Manager

on:
  schedule:
    - cron: '0 * * * *'  # Run every hour
  workflow_dispatch:

jobs:
  process_memory:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then
            pip install -r requirements.txt
          else
            echo "requirements.txt not found. Installing default dependencies (requests)."
            pip install requests
          fi
      - name: Run memory manager
        run: python memory_manager.py
        env:
          GITHUB_TOKEN: ${{ secrets.GH_PAT }}
"""
        elif repo_name == "agent-results":
            return """name: Results Tracker

on:
  schedule:
    - cron: '0 0 * * *'  # Run daily at midnight
  workflow_dispatch:

jobs:
  track_results:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then
            pip install -r requirements.txt
          else
            echo "requirements.txt not found. Installing default dependencies (requests)."
            pip install requests
          fi
      - name: Run results tracker
        run: python results_tracker.py
        env:
          GITHUB_TOKEN: ${{ secrets.GH_PAT }}
"""
        elif repo_name == "github-harvester":
            return """name: GitHub Harvester

on:
  schedule:
    - cron: '0 */2 * * *'  # Run every 2 hours
  workflow_dispatch:

jobs:
  harvest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then
            pip install -r requirements.txt
          else
            echo "requirements.txt not found. Installing default dependencies (requests)."
            pip install requests
          fi
      - name: Run harvester
        run: python harvester.py
        env:
          GITHUB_TOKEN: ${{ secrets.GH_PAT }}
          SCHEDULED_RUN: "true"
"""
        elif repo_name in WAVE2_AGENTS:
            main_script = next(iter(WAVE2_AGENTS[repo_name]["template_files"].keys()))
            return f"""name: {repo_name.replace('-', ' ').title()}

on:
  schedule:
    - cron: '0 */4 * * *'  # Run every 4 hours
  workflow_dispatch:
  issues:
    types: [assigned]

jobs:
  run_agent:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then
            pip install -r requirements.txt
          else
            echo "requirements.txt not found. Installing default dependencies (requests)."
            pip install requests
          fi
      - name: Run agent
        run: python {main_script}
        env:
          GITHUB_TOKEN: ${{ secrets.GH_PAT }}
          ISSUE_NUMBER: ${{ github.event.issue.number }}
"""
        else:
            return """name: Default Workflow

on:
  workflow_dispatch:

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then
            pip install -r requirements.txt
          else
            echo "requirements.txt not found. Installing default dependencies (requests)."
            pip install requests
          fi
      - name: Run script
        run: echo "No script specified"
        env:
          GITHUB_TOKEN: ${{ secrets.GH_PAT }}
"""

def main():
    """Main entry point"""
    # Check for GitHub token
    github_token = os.getenv('GH_PAT')
    if not github_token:
        logger.error(f"{Fore.RED}Error: GH_PAT environment variable not set{Style.RESET_ALL}")
        logger.error("Please set the GH_PAT environment variable with a GitHub Personal Access Token")
        logger.error("The token needs 'repo' and 'workflow' scopes")
        sys.exit(1)
    
    # Run tests
    tester = ConstellationTester(github_token)
    tester.run_all_tests()
    
    # Exit with appropriate status code
    if tester.test_results["status"] == "success":
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
