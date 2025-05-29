#!/usr/bin/env python3
"""
GitHub-Native Agent Controller
Orchestrates a constellation of GitHub-native AI agents.
"""
import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone

# Configuration
GITHUB_API_URL = "https://api.github.com"
OWNER = "zipaJopa"  # The owner of the constellation repositories
AGENT_TASKS_REPO = f"{OWNER}/agent-tasks"
AGENT_RESULTS_REPO = f"{OWNER}/agent-results"
AGENT_CONTROLLER_REPO = f"{OWNER}/agent-controller" # For alerts

# Mapping task types to agent bot usernames (or GitHub App slugs)
# These usernames will be assigned to issues.
# Ensure these users/apps have permissions to be assigned and to comment/label.
AGENT_MAPPING = {
    "harvest": "github-harvester-bot",
    "arbitrage": "github-arbitrage-agent-bot",
    "wrapper": "ai-wrapper-factory-bot",
    "saas_template": "saas-template-mill-bot",
    "automation_broker": "automation-broker-bot",
    "trade_signal": "crypto-financial-core-bot",
    "self_healing": "autonomous-infrastructure-bot",
    "performance_optimization": "performance-optimizer-bot",
    "financial_management": "financial-manager-bot",
    # Add more based on wave2_agents.py and hyperstride_multipliers.py
    "crypto_degen": "crypto-degen-bot",
    "influencer_farm": "influencer-farm-bot",
    "course_generator": "course-generator-bot",
    "patent_scraper": "patent-scraper-bot",
    "domain_flipper": "domain-flipper-bot",
    "affiliate_army": "affiliate-army-bot",
    "lead_magnet": "lead-magnet-factory-bot",
    "copywriter_swarm": "ai-copywriter-swarm-bot",
    "price_scraper": "price-scraper-network-bot",
    "startup_idea": "startup-idea-generator-bot",
}

# Mapping agent bots to their primary repository and workflow file for health checks
AGENT_WORKFLOW_INFO = {
    "github-harvester-bot": {"repo": f"{OWNER}/github-harvester", "workflow_file": "main.yml", "schedule_minutes": 120},
    "github-arbitrage-agent-bot": {"repo": f"{OWNER}/github-arbitrage-agent", "workflow_file": "main.yml", "schedule_minutes": 240},
    "ai-wrapper-factory-bot": {"repo": f"{OWNER}/ai-wrapper-factory", "workflow_file": "main.yml", "schedule_minutes": 240},
    "crypto-financial-core-bot": {"repo": f"{OWNER}/crypto-financial-core", "workflow_file": "main.yml", "schedule_minutes": 15},
    # Add all agents defined in AGENT_MAPPING
}


class GitHubAgentController:
    def __init__(self, github_token):
        self.token = github_token
        self.headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.controller_bot_username = self._get_authenticated_user()

    def _get_authenticated_user(self):
        try:
            response = self._github_api_request("GET", "/user")
            return response.get("login", "agent-controller-bot") # Default if something fails
        except requests.exceptions.RequestException as e:
            print(f"Error getting authenticated user: {e}")
            return "agent-controller-bot"


    def _github_api_request(self, method, endpoint, params=None, data=None, max_retries=3, base_url=GITHUB_API_URL):
        url = f"{base_url}{endpoint}"
        for attempt in range(max_retries):
            try:
                response = self.session.request(method, url, params=params, json=data)
                response.raise_for_status()  # Raise an exception for bad status codes
                # Handle rate limiting
                if 'X-RateLimit-Remaining' in response.headers and int(response.headers['X-RateLimit-Remaining']) < 10:
                    reset_time = int(response.headers.get('X-RateLimit-Reset', time.time() + 60))
                    sleep_duration = max(0, reset_time - time.time()) + 5 # Add a small buffer
                    print(f"Rate limit low. Sleeping for {sleep_duration} seconds.")
                    time.sleep(sleep_duration)
                return response.json() if response.content else {}
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 403 and "rate limit exceeded" in e.response.text.lower():
                    reset_time = int(e.response.headers.get('X-RateLimit-Reset', time.time() + 60* (attempt + 1)))
                    sleep_duration = max(0, reset_time - time.time()) + 5 # Add buffer
                    print(f"Rate limit exceeded. Retrying in {sleep_duration} seconds (attempt {attempt+1}/{max_retries})...")
                    time.sleep(sleep_duration)
                    continue
                elif e.response.status_code == 404 and method == "GET": # For GETs, 404 might be a valid "not found"
                    return None
                print(f"GitHub API request failed ({e.response.status_code}): {e.response.text}")
                if attempt == max_retries - 1:
                    raise
            except requests.exceptions.RequestException as e:
                print(f"GitHub API request failed: {e}")
                if attempt == max_retries - 1:
                    raise
            time.sleep(2 ** attempt) # Exponential backoff for other errors
        return {} # Should not be reached if raise is working

    def get_pending_tasks(self):
        print("🔍 Scanning for pending tasks...")
        endpoint = f"/repos/{AGENT_TASKS_REPO}/issues"
        params = {"labels": "todo", "state": "open", "assignee": "none", "sort": "created", "direction": "asc"}
        try:
            issues = self._github_api_request("GET", endpoint, params=params)
            pending_tasks = []
            if issues:
                for issue in issues:
                    try:
                        # Task details are expected in the issue body as JSON
                        task_details = json.loads(issue.get("body", "{}"))
                        if "type" in task_details and "id" in task_details: # Basic validation
                            pending_tasks.append({"issue_number": issue["number"], "details": task_details, "title": issue["title"]})
                        else:
                            print(f"⚠️ Task issue #{issue['number']} body is not valid JSON with type/id: {issue.get('body', '')[:100]}...")
                    except json.JSONDecodeError:
                        print(f"⚠️ Could not parse JSON from issue #{issue['number']} body: {issue.get('body', '')[:100]}...")
            print(f"Found {len(pending_tasks)} pending tasks.")
            return pending_tasks
        except requests.exceptions.RequestException as e:
            print(f"Error fetching pending tasks: {e}")
            return []

    def assign_task_to_agent(self, task_issue):
        issue_number = task_issue["issue_number"]
        task_type = task_issue["details"].get("type")
        task_id = task_issue["details"].get("id")
        
        agent_bot_username = AGENT_MAPPING.get(task_type)
        if not agent_bot_username:
            print(f"⚠️ No agent mapped for task type '{task_type}' (Task ID: {task_id}, Issue: {issue_number}). Skipping.")
            # Optionally, add a "needs-agent-mapping" label
            self._github_api_request("POST", f"/repos/{AGENT_TASKS_REPO}/issues/{issue_number}/labels", data={"labels": ["needs-agent-mapping"]})
            return

        print(f"Assigning Task ID {task_id} (Issue #{issue_number}, Type: {task_type}) to agent '{agent_bot_username}'...")
        assign_endpoint = f"/repos/{AGENT_TASKS_REPO}/issues/{issue_number}/assignees"
        label_endpoint = f"/repos/{AGENT_TASKS_REPO}/issues/{issue_number}/labels"
        
        try:
            # Assign the issue
            self._github_api_request("POST", assign_endpoint, data={"assignees": [agent_bot_username]})
            # Remove 'todo' label and add 'in-progress' label
            self._github_api_request("DELETE", f"{label_endpoint}/todo") # Assumes 'todo' is a single label
            self._github_api_request("POST", label_endpoint, data={"labels": ["in-progress"]})
            print(f"✅ Task ID {task_id} (Issue #{issue_number}) assigned to {agent_bot_username} and labeled 'in-progress'.")
        except requests.exceptions.RequestException as e:
            print(f"Error assigning task {task_id} (Issue #{issue_number}): {e}")


    def monitor_completed_tasks(self):
        print("🔄 Monitoring for completed tasks...")
        endpoint = f"/repos/{AGENT_TASKS_REPO}/issues"
        # Check issues that are in-progress or recently updated and closed
        # GitHub API doesn't allow OR for labels easily, so we might need multiple queries or broader fetch
        params = {"labels": "in-progress", "state": "all", "sort": "updated", "direction": "desc", "per_page": 50}
        try:
            issues = self._github_api_request("GET", endpoint, params=params)
            if not issues:
                print("No 'in-progress' tasks found to monitor.")
                return

            completed_count = 0
            for issue in issues:
                issue_number = issue["number"]
                is_in_progress = any(label["name"] == "in-progress" for label in issue.get("labels", []))

                # Check for "DONE ✅" comment
                comments_url = issue.get("comments_url")
                task_marked_done_by_comment = False
                if comments_url:
                    comments = self._github_api_request("GET", "", base_url=comments_url) # Pass full URL
                    if comments:
                        for comment in reversed(comments): # Check recent comments first
                            if "DONE ✅" in comment.get("body", ""):
                                task_marked_done_by_comment = True
                                break
                
                is_closed = issue.get("state") == "closed"

                if (is_in_progress and (task_marked_done_by_comment or is_closed)):
                    print(f"🏁 Task Issue #{issue_number} appears completed.")
                    label_endpoint = f"/repos/{AGENT_TASKS_REPO}/issues/{issue_number}/labels"
                    # Remove 'in-progress', add 'completed'
                    self._github_api_request("DELETE", f"{label_endpoint}/in-progress", data={}) # Empty data for DELETE label
                    self._github_api_request("POST", label_endpoint, data={"labels": ["completed"]})
                    
                    # If not already closed, close it
                    if not is_closed:
                        self._github_api_request("PATCH", f"/repos/{AGENT_TASKS_REPO}/issues/{issue_number}", data={"state": "closed"})
                    
                    print(f"Processed completion for Task Issue #{issue_number}.")
                    completed_count +=1
            print(f"Processed {completed_count} completed tasks.")

        except requests.exceptions.RequestException as e:
            print(f"Error monitoring completed tasks: {e}")


    def perform_agent_health_checks(self):
        print("🩺 Performing agent health checks...")
        unhealthy_agents = []
        for agent_bot, info in AGENT_WORKFLOW_INFO.items():
            repo_full_name = info["repo"]
            workflow_file = info["workflow_file"]
            schedule_minutes = info.get("schedule_minutes", 24*60) # Default to 1 day if not specified
            max_delay_minutes = schedule_minutes * 2 # Allow 2x schedule interval

            endpoint = f"/repos/{repo_full_name}/actions/workflows/{workflow_file}/runs"
            params = {"status": "success", "per_page": 1} # Get the latest successful run
            
            try:
                runs = self._github_api_request("GET", endpoint, params=params)
                if runs and runs.get("workflow_runs"):
                    last_run = runs["workflow_runs"][0]
                    last_run_time_str = last_run.get("updated_at") # or "created_at"
                    last_run_time = datetime.fromisoformat(last_run_time_str.replace("Z", "+00:00"))
                    
                    if datetime.now(timezone.utc) - last_run_time > timedelta(minutes=max_delay_minutes):
                        unhealthy_agents.append({
                            "agent": agent_bot, 
                            "repo": repo_full_name,
                            "last_success": last_run_time_str,
                            "reason": f"Last successful run was more than {max_delay_minutes} minutes ago."
                        })
                        print(f"⚠️ Agent {agent_bot} ({repo_full_name}) might be unhealthy. Last success: {last_run_time_str}")
                    else:
                        print(f"✅ Agent {agent_bot} ({repo_full_name}) is healthy. Last success: {last_run_time_str}")

                else: # No successful runs found
                    unhealthy_agents.append({
                        "agent": agent_bot,
                        "repo": repo_full_name,
                        "reason": "No successful workflow runs found."
                    })
                    print(f"⚠️ Agent {agent_bot} ({repo_full_name}) might be unhealthy. No successful runs found.")
            except requests.exceptions.RequestException as e:
                print(f"Error checking health for agent {agent_bot} ({repo_full_name}): {e}")
                unhealthy_agents.append({"agent": agent_bot, "repo": repo_full_name, "reason": f"API error during health check: {str(e)}"})
        
        if unhealthy_agents:
            self._create_health_alert_issue(unhealthy_agents)
        return unhealthy_agents


    def _create_health_alert_issue(self, unhealthy_agents):
        print(f"🚨 Creating health alert issue for {len(unhealthy_agents)} agent(s).")
        issue_title = f"Automated Health Alert: {len(unhealthy_agents)} Agent(s) Unhealthy - {datetime.now(timezone.utc).isoformat()}"
        issue_body_parts = ["The following agents appear to be unhealthy based on their last successful workflow run:\n"]
        for agent_info in unhealthy_agents:
            issue_body_parts.append(f"- **Agent:** {agent_info['agent']} ({agent_info['repo']})\n  - **Reason:** {agent_info['reason']}\n  - **Last Success:** {agent_info.get('last_success', 'N/A')}\n")
        
        issue_body = "\n".join(issue_body_parts)
        data = {
            "title": issue_title,
            "body": issue_body,
            "labels": ["alert", "health-check", "automated"],
            "assignee": self.controller_bot_username # Assign to self or a maintenance team
        }
        try:
            # Check if a similar open alert already exists to avoid spamming
            open_alerts = self._github_api_request("GET", f"/repos/{AGENT_CONTROLLER_REPO}/issues", params={"labels": "alert,health-check", "state": "open", "creator": self.controller_bot_username})
            if open_alerts:
                for alert in open_alerts: # A very basic check, could be more sophisticated
                    if "Automated Health Alert" in alert.get("title", ""):
                        print("An open health alert already exists. Skipping new issue creation.")
                        # Optionally, update the existing issue
                        self._github_api_request("POST", f"/repos/{AGENT_CONTROLLER_REPO}/issues/{alert['number']}/comments", data={"body": f"**Update {datetime.now(timezone.utc).isoformat()}:**\nHealth check still reporting issues. Details:\n{issue_body}"})
                        return

            self._github_api_request("POST", f"/repos/{AGENT_CONTROLLER_REPO}/issues", data=data)
            print("✅ Health alert issue created.")
        except requests.exceptions.RequestException as e:
            print(f"Error creating health alert issue: {e}")


    def update_system_metrics(self):
        print("📊 Updating system metrics...")
        # Fetch task counts by labels
        pending_count = 0
        inprogress_count = 0
        completed_count = 0
        failed_count = 0 # Assuming a 'failed' label exists or closed without "DONE"

        try:
            issues_todo = self._github_api_request("GET", f"/repos/{AGENT_TASKS_REPO}/issues", params={"labels": "todo", "state": "open", "per_page": 1}) # Just need total_count
            pending_count = issues_todo.get("total_count", 0) if isinstance(issues_todo, list) else len(self._github_api_request("GET", f"/repos/{AGENT_TASKS_REPO}/issues", params={"labels": "todo", "state": "open"}) or [])


            issues_inprogress = self._github_api_request("GET", f"/repos/{AGENT_TASKS_REPO}/issues", params={"labels": "in-progress", "state": "open", "per_page": 1})
            inprogress_count = issues_inprogress.get("total_count", 0) if isinstance(issues_inprogress, list) else len(self._github_api_request("GET", f"/repos/{AGENT_TASKS_REPO}/issues", params={"labels": "in-progress", "state": "open"}) or [])
            
            # Completed could be closed issues with 'completed' label
            issues_completed = self._github_api_request("GET", f"/repos/{AGENT_TASKS_REPO}/issues", params={"labels": "completed", "state": "closed", "per_page": 1, "since": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}) # Recently completed
            completed_today_count = issues_completed.get("total_count", 0) if isinstance(issues_completed, list) else len(self._github_api_request("GET", f"/repos/{AGENT_TASKS_REPO}/issues", params={"labels": "completed", "state": "closed", "since": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}) or [])


            # This is a simplified metrics structure. Could be expanded.
            metrics = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tasks_pending": pending_count,
                "tasks_in_progress": inprogress_count,
                "tasks_completed_last_24h": completed_today_count,
                "active_agents": len(AGENT_MAPPING), # Simplistic, could be based on health checks
                "pionex_balance_usdt": self.get_pionex_balance(), # Example integration
            }
            
            metrics_file_path = f"metrics/daily_metrics_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
            
            # Try to get existing metrics file to append, or create new
            try:
                existing_content_res = self._github_api_request(
                    "GET", f"/repos/{AGENT_RESULTS_REPO}/contents/{metrics_file_path}"
                )
                existing_metrics_data = []
                sha = None
                if existing_content_res and 'content' in existing_content_res: # File exists
                    import base64
                    content = base64.b64decode(existing_content_res['content']).decode('utf-8')
                    existing_metrics_data = json.loads(content)
                    sha = existing_content_res['sha']
                
                existing_metrics_data.append(metrics)
                new_content_b64 = base64.b64encode(json.dumps(existing_metrics_data, indent=2).encode('utf-8')).decode('utf-8')
                
                commit_message = f"Update system metrics {datetime.now(timezone.utc).isoformat()}"
                commit_data = {
                    "message": commit_message,
                    "content": new_content_b64,
                    "branch": "main" # Or default branch
                }
                if sha: # If updating existing file
                    commit_data["sha"] = sha

                self._github_api_request("PUT", f"/repos/{AGENT_RESULTS_REPO}/contents/{metrics_file_path}", data=commit_data)
                print(f"✅ System metrics updated in {AGENT_RESULTS_REPO}/{metrics_file_path}")

            except Exception as e: # Catch broader errors for file operations
                 # If file doesn't exist or other error, create it
                if "404" in str(e) or not sha: # File not found, create new
                    new_content_b64 = base64.b64encode(json.dumps([metrics], indent=2).encode('utf-8')).decode('utf-8')
                    commit_message = f"Create system metrics {datetime.now(timezone.utc).isoformat()}"
                    commit_data = {
                        "message": commit_message,
                        "content": new_content_b64,
                        "branch": "main"
                    }
                    self._github_api_request("PUT", f"/repos/{AGENT_RESULTS_REPO}/contents/{metrics_file_path}", data=commit_data)
                    print(f"✅ System metrics created in {AGENT_RESULTS_REPO}/{metrics_file_path}")
                else:
                    print(f"Error updating/creating metrics file: {e}")

        except requests.exceptions.RequestException as e:
            print(f"Error updating system metrics: {e}")

    def get_pionex_balance(self):
        # Placeholder for actual Pionex API integration
        # This would typically involve calling the crypto_financial_core logic
        # For now, returning a dummy value.
        # Ensure PIONEX_API_KEY and PIONEX_API_SECRET are available if implementing
        # from crypto_financial_core import PionexAPI # Example
        # pionex_api = PionexAPI(os.getenv("PIONEX_API_KEY"), os.getenv("PIONEX_API_SECRET"))
        # return pionex_api.get_balance("USDT") 
        return 1000.00 # Dummy value

    def run_coordination_cycle(self):
        print(f"🎯 Agent coordination cycle started at {datetime.now(timezone.utc).isoformat()} by {self.controller_bot_username}")
        
        # 1. Scan for and assign new tasks
        pending_tasks = self.get_pending_tasks()
        # Prioritize tasks (e.g. by a 'priority' field in task_issue['details'] or specific labels)
        # For now, FIFO based on 'created asc' from get_pending_tasks
        for task in pending_tasks:
            self.assign_task_to_agent(task)
            time.sleep(1) # Small delay to avoid hitting secondary rate limits if many tasks

        # 2. Monitor completed tasks
        self.monitor_completed_tasks()
        
        # 3. Perform agent health checks
        self.perform_agent_health_checks()
        
        # 4. Update system metrics
        self.update_system_metrics()
        
        print(f"✅ Agent coordination cycle finished at {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        raise ValueError("GITHUB_TOKEN environment variable not set.")
    
    controller = GitHubAgentController(github_token)
    controller.run_coordination_cycle()
