#!/usr/bin/env python3
"""
Personal AI agent for Jira DC
────────────────────────────────────────────────────────────
Features:
  • Multiple named environments (dev / staging / prod / …)
  • Certificate-based mTLS authentication
  • Natural-language queries via local LM Studio instance
  • Interactive AI chat mode (asks questions, runs Jira queries)
  • Ticket status, sprint status, sprint planning
────────────────────────────────────────────────────────────
Install:  pip install requests rich
Usage:    python jira_tool.py --help
"""

import os
import sys
import json
import argparse
import getpass
import re
from datetime import datetime
from typing import Optional

# ── Optional deps ──────────────────────────────────────────────────────────────
try:
    import requests
except ImportError:
    print("Missing: pip install requests")
    sys.exit(1)

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich import box
    from rich.text import Text
    from rich.rule import Rule
    from rich.markdown import Markdown
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

console = Console() if HAS_RICH else None

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG  ─  multi-environment, cert auth, LM Studio settings
# ══════════════════════════════════════════════════════════════════════════════

CONFIG_FILE = os.path.expanduser("~/.jira_tool_config.json")

DEFAULT_CONFIG = {
    "active_env": None,
    "environments": {},
    "lmstudio": {
        "base_url": "http://localhost:1234",
        "model":    "local-model",   # must match the identifier shown in LM Studio
    },
}


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            data.setdefault(k, v)
        return data
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(CONFIG_FILE, 0o600)


def _ask(prompt: str, default: str = "", secret: bool = False) -> str:
    display = f"{prompt} [{default}]: " if default else f"{prompt}: "
    if secret:
        val = getpass.getpass(display)
    else:
        val = input(display).strip()
    return val or default


def get_active_env(cfg: dict, env_name: str = None):
    name = env_name or cfg.get("active_env")
    if not name:
        _print("[red]No environment set. Run: python jira_tool.py env add[/red]")
        sys.exit(1)
    env = cfg["environments"].get(name)
    if not env:
        _print(f"[red]Environment '{name}' not found. Run: python jira_tool.py env list[/red]")
        sys.exit(1)
    return env, name


def cmd_env(args, cfg: dict):
    """Manage named Jira environments."""
    sub = args.env_action

    # ── list ──────────────────────────────────────────────────────────────────
    if sub == "list":
        envs   = cfg["environments"]
        active = cfg.get("active_env")
        if not envs:
            _print("[yellow]No environments configured. Run: jira_tool.py env add[/yellow]")
            return
        if HAS_RICH:
            t = Table(title="Jira Environments", box=box.ROUNDED, header_style="bold blue")
            t.add_column("",        width=2)
            t.add_column("Name",    style="bold cyan")
            t.add_column("URL")
            t.add_column("Auth")
            t.add_column("SSL Verify")
            for name, env in envs.items():
                marker = "●" if name == active else " "
                t.add_row(
                    f"[green]{marker}[/green]",
                    name,
                    env.get("base_url", ""),
                    env.get("auth_type", "cert"),
                    "yes" if env.get("verify_ssl", True) else "[yellow]no[/yellow]",
                )
            console.print(t)
            if active:
                console.print(f"\n  Active: [bold green]{active}[/bold green]\n")
        else:
            for name, env in envs.items():
                marker = "* " if name == active else "  "
                print(f"{marker}{name}  {env.get('base_url','')}  ({env.get('auth_type','cert')})")

    # ── add ───────────────────────────────────────────────────────────────────
    elif sub == "add":
        _print("\n[bold]Add Jira Environment[/bold]\n")
        name = _ask("Environment name (e.g. prod, staging, dev)")
        if not name:
            _print("[red]Name required.[/red]")
            return

        base_url  = _ask("Jira base URL (e.g. https://jira.company.com)")
        auth_type = _ask("Auth type  cert / token / basic", default="cert")
        env: dict = {"base_url": base_url.rstrip("/"), "auth_type": auth_type, "verify_ssl": True}

        if auth_type == "cert":
            env["cert"]      = _ask("Path to client certificate (.pem / .crt)")
            env["key"]       = _ask("Path to private key (.pem / .key)  [blank if bundled in cert]")
            env["ca_bundle"] = _ask("Path to CA bundle / CA cert  [blank for system CAs]")
            verify_raw       = _ask("Verify SSL? yes / no / path-to-ca-file", default="yes")
            if verify_raw.lower() in ("no", "false", "0"):
                env["verify_ssl"] = False
            elif verify_raw.lower() not in ("yes", "true", "1"):
                env["verify_ssl"] = verify_raw   # treat as filesystem path
            else:
                env["verify_ssl"] = True

        elif auth_type == "token":
            env["token"] = _ask("Personal Access Token", secret=True)

        elif auth_type == "basic":
            env["username"] = _ask("Username")
            env["token"]    = _ask("Password", secret=True)

        cfg["environments"][name] = env
        if not cfg.get("active_env"):
            cfg["active_env"] = name
            _print("  [dim]Set as active environment.[/dim]")
        save_config(cfg)
        _print(f"[green]✓ Environment '{name}' saved.[/green]")

    # ── use ───────────────────────────────────────────────────────────────────
    elif sub == "use":
        name = args.name
        if name not in cfg["environments"]:
            _print(f"[red]Unknown environment '{name}'.[/red]")
            return
        cfg["active_env"] = name
        save_config(cfg)
        _print(f"[green]✓ Active environment → '{name}'.[/green]")

    # ── remove ────────────────────────────────────────────────────────────────
    elif sub == "remove":
        name = args.name
        if name not in cfg["environments"]:
            _print(f"[red]Unknown environment '{name}'.[/red]")
            return
        del cfg["environments"][name]
        if cfg.get("active_env") == name:
            cfg["active_env"] = next(iter(cfg["environments"]), None)
        save_config(cfg)
        _print(f"[green]✓ Environment '{name}' removed.[/green]")

    else:
        _print("[yellow]Unknown action. Use: list / add / use / remove[/yellow]")


def cmd_lmstudio_config(args, cfg: dict):
    """Configure LM Studio URL and model identifier."""
    _print("\n[bold]LM Studio Configuration[/bold]\n")
    _print("[dim]LM Studio exposes an OpenAI-compatible API. "
           "Default port is 1234 (set in LM Studio → Local Server).[/dim]\n")
    o             = cfg.get("lmstudio", {})
    o["base_url"] = _ask("LM Studio base URL", default=o.get("base_url", "http://localhost:1234"))
    o["model"]    = _ask(
        "Model identifier (copy from LM Studio UI, e.g. lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF)",
        default=o.get("model", "local-model"),
    )
    cfg["lmstudio"] = o
    save_config(cfg)
    _print(f"[green]✓ LM Studio config saved  model={o['model']}  url={o['base_url']}[/green]")


# ══════════════════════════════════════════════════════════════════════════════
# JIRA CLIENT  ─  certificate mTLS / Bearer token / Basic auth
# ══════════════════════════════════════════════════════════════════════════════

class JiraClient:
    def __init__(self, env: dict):
        self.base_url  = env["base_url"].rstrip("/")
        self.auth_type = env.get("auth_type", "cert")
        self.session   = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept":       "application/json",
        })

        # ── SSL verification ───────────────────────────────────────────────────
        verify = env.get("verify_ssl", True)
        if isinstance(verify, str):
            if verify.lower() in ("true", "yes", "1"):
                verify = True
            elif verify.lower() in ("false", "no", "0"):
                verify = False
            # else: leave as path string
        self.session.verify = verify

        # ── Authentication ─────────────────────────────────────────────────────
        if self.auth_type == "cert":
            cert     = env.get("cert", "")
            key      = env.get("key", "")
            ca_bundle = env.get("ca_bundle", "")
            # If a separate key file is provided use (cert, key) tuple; otherwise
            # assume the PEM bundles both certificate and private key.
            self.session.cert = (cert, key) if key else cert
            if ca_bundle:
                # CA bundle overrides verify so server cert is validated against it
                self.session.verify = ca_bundle

        elif self.auth_type == "token":
            self.session.headers["Authorization"] = f"Bearer {env.get('token', '')}"

        elif self.auth_type == "basic":
            from requests.auth import HTTPBasicAuth
            self.session.auth = HTTPBasicAuth(
                env.get("username", ""), env.get("token", "")
            )

    # ── internal helpers ───────────────────────────────────────────────────────

    def _get(self, path: str, params: dict = None, agile: bool = False) -> dict:
        api = "agile/1.0" if agile else "api/2"
        url = f"{self.base_url}/rest/{api}/{path}"
        r   = self.session.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, data: dict, agile: bool = False) -> requests.Response:
        api = "agile/1.0" if agile else "api/2"
        url = f"{self.base_url}/rest/{api}/{path}"
        r   = self.session.post(url, json=data, timeout=30)
        r.raise_for_status()
        return r

    # ── public API ─────────────────────────────────────────────────────────────

    def test_connection(self) -> dict:
        try:
            return self._get("myself")
        except Exception as e:
            print(f"Connection test failed: {e}")
            return {}

    def get_issue(self, key: str) -> dict:
        try:
            return self._get(f"issue/{key}")
        except Exception as e:
            print(f"Failed to get issue {key}: {e}")
            return {}

    def search_issues(self, jql: str, max_results: int = 100) -> list:
        try:
            data = self._get("search", params={"jql": jql, "maxResults": max_results})
            return data.get("issues", [])
        except Exception as e:
            print(f"Failed to search issues with JQL '{jql}': {e}")
            return []

    def get_my_issues(self, status_filter: str = None) -> list:
        try:
            jql = "assignee = currentUser()"
            if status_filter:
                jql += f' AND status = "{status_filter}"'
            return self.search_issues(jql + " ORDER BY updated DESC")
        except Exception as e:
            print(f"Failed to get my issues: {e}")
            return []

    def get_project_issues(self, project: str, open_only: bool = True) -> list:
        try:
            jql = f"project = {project}"
            if open_only:
                jql += ' AND status NOT IN ("Done","Closed")'
            return self.search_issues(jql + " ORDER BY created DESC", max_results=200)
        except Exception as e:
            print(f"Failed to get project issues for {project}: {e}")
            return []

    def get_boards(self, project: str = None) -> list:
        try:
            params = {"projectKeyOrId": project} if project else {}
            return self._get("board", params=params, agile=True).get("values", [])
        except Exception as e:
            print(f"Failed to get boards: {e}")
            return []

    def get_sprints(self, board_id: int, state: str = "active,future") -> list:
        try:
            return self._get(
                f"board/{board_id}/sprint", params={"state": state}, agile=True
            ).get("values", [])
        except Exception as e:
            print(f"Failed to get sprints for board {board_id}: {e}")
            return []

    def get_sprint_issues(self, sprint_id: int) -> list:
        try:
            return self._get(
                f"sprint/{sprint_id}/issue", params={"maxResults": 200}, agile=True
            ).get("issues", [])
        except Exception as e:
            print(f"Failed to get sprint issues for sprint {sprint_id}: {e}")
            return []

    def get_backlog(self, board_id: int) -> list:
        try:
            return self._get(
                f"board/{board_id}/backlog", params={"maxResults": 100}, agile=True
            ).get("issues", [])
        except Exception as e:
            print(f"Failed to get backlog for board {board_id}: {e}")
            return []

    def move_to_sprint(self, sprint_id: int, keys: list) -> bool:
        try:
            r = self._post(f"sprint/{sprint_id}/issue", {"issues": keys}, agile=True)
            return r.status_code in (200, 204)
        except Exception as e:
            print(f"Failed to move issues to sprint {sprint_id}: {e}")
            return False

    def get_projects(self) -> list:
        try:
            return self._get("project")
        except Exception as e:
            print(f"Failed to get projects: {e}")
            return []


# ══════════════════════════════════════════════════════════════════════════════
# LM STUDIO CLIENT  ─  OpenAI-compatible REST API
# ══════════════════════════════════════════════════════════════════════════════

class LMStudioClient:
    """
    Talks to LM Studio's built-in OpenAI-compatible local server.

    LM Studio API endpoints used:
      POST  /v1/chat/completions   – chat inference
      GET   /v1/models             – list loaded models

    Start the server in LM Studio:  Local Server → Start Server  (default port 1234)
    """

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model    = model

    def chat(self, messages: list, system: str = None) -> str:
        """
        Send a conversation to LM Studio and return the assistant's reply.

        LM Studio follows the OpenAI Chat Completions spec:
          POST /v1/chat/completions
          Body: { model, messages: [{role, content}], temperature, stream }
          Response: { choices: [{ message: { role, content } }] }
        """
        payload_messages: list = []
        if system:
            payload_messages.append({"role": "system", "content": system})
        payload_messages.extend(messages)

        payload = {
            "model":       self.model,
            "messages":    payload_messages,
            "temperature": 0.7,
            "stream":      False,
        }

        try:
            r = requests.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=180,
            )
            r.raise_for_status()
            data = r.json()
            # OpenAI-compatible response shape
            return data["choices"][0]["message"]["content"].strip()

        except requests.exceptions.ConnectionError:
            return (
                "⚠️  Cannot connect to LM Studio. "
                "Make sure the Local Server is running in LM Studio "
                f"(Local Server → Start Server) and the URL '{self.base_url}' is correct.\n"
                "Run: python jira_tool.py lmstudio-config  to update settings."
            )
        except requests.exceptions.HTTPError as e:
            return f"⚠️  LM Studio HTTP error {e.response.status_code}: {e.response.text[:200]}"
        except (KeyError, IndexError, ValueError) as e:
            return f"⚠️  Unexpected LM Studio response format: {e}"
        except Exception as e:
            return f"⚠️  LM Studio error: {e}"

    def list_models(self) -> list:
        """
        Return loaded model identifiers from LM Studio.
        GET /v1/models  →  { data: [{ id: "..." }, …] }
        """
        try:
            r = requests.get(f"{self.base_url}/v1/models", timeout=10)
            r.raise_for_status()
            return [m["id"] for m in r.json().get("data", [])]
        except Exception:
            return []


# ══════════════════════════════════════════════════════════════════════════════
# FIELD HELPERS
# ══════════════════════════════════════════════════════════════════════════════

STATUS_COLORS = {
    "To Do": "cyan", "In Progress": "yellow", "Done": "green",
    "Closed": "green", "Blocked": "red", "In Review": "magenta",
    "Testing": "blue", "Reopened": "red",
}
PRIORITY_ICONS = {
    "Highest": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🔵", "Lowest": "⚪",
}


def _sp(fields: dict):
    for key in ("story_points", "customfield_10016", "customfield_10028", "customfield_10014"):
        v = fields.get(key)
        if v not in (None, ""):
            return v
    return None


def extract(issue: dict) -> dict:
    f  = issue.get("fields", {})
    sp = _sp(f)
    return {
        "key":      issue.get("key", ""),
        "summary":  (f.get("summary") or "")[:72],
        "status":   (f.get("status") or {}).get("name", "Unknown"),
        "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
        "priority": (f.get("priority") or {}).get("name", "—"),
        "type":     (f.get("issuetype") or {}).get("name", "—"),
        "updated":  _fmtd(f.get("updated", "")),
        "due":      _fmtd(f.get("duedate", "")),
        "sp":       str(sp) if sp is not None else "—",
        "labels":   ", ".join(f.get("labels") or []) or "—",
        "desc":     (f.get("description") or "")[:600],
    }


def _fmtd(s: str) -> str:
    if not s:
        return "—"
    try:
        return datetime.fromisoformat(s[:10]).strftime("%b %d, %Y")
    except Exception:
        return s[:10]


def issues_to_text(issues: list) -> str:
    """Compact plain-text representation of issues suitable for LLM context."""
    if not issues:
        return "(none)"
    lines = []
    for i in issues:
        d = extract(i)
        lines.append(
            f"[{d['key']}] {d['summary']}  |  "
            f"status={d['status']}  priority={d['priority']}  "
            f"assignee={d['assignee']}  sp={d['sp']}  due={d['due']}"
        )
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# DISPLAY HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _print(msg: str):
    if HAS_RICH:
        console.print(msg)
    else:
        print(re.sub(r'\[/?[a-zA-Z_ ]*\]', '', msg))


def _rule(title: str = ""):
    if HAS_RICH:
        console.print(Rule(title, style="blue"))
    else:
        print(f"\n{'─'*60}  {title}")


def print_issues_table(issues: list, title: str = "Issues"):
    if not issues:
        _print("  [dim]No issues found.[/dim]")
        return
    if HAS_RICH:
        t = Table(title=title, box=box.ROUNDED, header_style="bold blue", show_lines=False)
        t.add_column("Key",      style="bold cyan", no_wrap=True)
        t.add_column("Type",     max_width=12)
        t.add_column("Summary",  max_width=52)
        t.add_column("Status",   no_wrap=True)
        t.add_column("Priority", no_wrap=True)
        t.add_column("Assignee", max_width=20)
        t.add_column("SP",       justify="center", max_width=4)
        t.add_column("Updated",  no_wrap=True)
        for issue in issues:
            d = extract(issue)
            t.add_row(
                d["key"], d["type"], d["summary"],
                Text(d["status"], style=STATUS_COLORS.get(d["status"], "white")),
                f"{PRIORITY_ICONS.get(d['priority'], '  ')} {d['priority']}",
                d["assignee"], d["sp"], d["updated"],
            )
        console.print(t)
    else:
        print(f"\n{'─'*110}\n  {title}\n{'─'*110}")
        for issue in issues:
            d = extract(issue)
            print(f"  {d['key']:<13} {d['status']:<15} {d['summary']:<55} {d['assignee']}")


# ══════════════════════════════════════════════════════════════════════════════
# STANDARD JIRA COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

def cmd_status(client: JiraClient, args):
    status_filter = getattr(args, "filter", None)
    _print("\n[bold]Fetching your tickets…[/bold]")
    issues = client.get_my_issues(status_filter)
    title  = "My Tickets" + (f" — {status_filter}" if status_filter else "")
    print_issues_table(issues, title=title)
    if issues and HAS_RICH:
        from collections import Counter
        c    = Counter(extract(i)["status"] for i in issues)
        line = "   ".join(
            f"[{STATUS_COLORS.get(s,'white')}]{s}[/{STATUS_COLORS.get(s,'white')}]: {n}"
            for s, n in c.most_common()
        )
        console.print(f"\n  {line}\n")


def cmd_ticket(client: JiraClient, args):
    _print(f"\n[bold]Fetching {args.key}…[/bold]")
    issue = client.get_issue(args.key)
    d     = extract(issue)
    f     = issue.get("fields", {})
    comments = f.get("comment", {}).get("comments", [])
    last_c   = ""
    if comments:
        lc     = comments[-1]
        author = (lc.get("author") or {}).get("displayName", "?")
        last_c = f"\n\n[dim]Last comment ({author}):[/dim] {(lc.get('body') or '')[:250]}"

    body = (
        f"[bold cyan]{d['key']}[/bold cyan]  "
        f"[{STATUS_COLORS.get(d['status'],'white')}]{d['status']}"
        f"[/{STATUS_COLORS.get(d['status'],'white')}]\n"
        f"[bold]{d['summary']}[/bold]\n\n"
        f"Type: {d['type']}   Priority: {PRIORITY_ICONS.get(d['priority'],'')} {d['priority']}   "
        f"Assignee: {d['assignee']}   SP: {d['sp']}\n"
        f"Updated: {d['updated']}   Due: {d['due']}   Labels: {d['labels']}\n\n"
        f"[dim]Description:[/dim]\n{d['desc']}{last_c}"
    ) if HAS_RICH else (
        f"{d['key']} | {d['status']}\n{d['summary']}\n"
        f"Priority: {d['priority']} | Assignee: {d['assignee']} | SP: {d['sp']}\n{d['desc']}"
    )

    if HAS_RICH:
        console.print(Panel(body, title=d["key"], border_style="blue"))
    else:
        print(f"\n=== {d['key']} ===\n{body}\n")


def cmd_project(client: JiraClient, args):
    _print(f"\n[bold]Fetching project {args.project}…[/bold]")
    issues = client.get_project_issues(args.project, open_only=not getattr(args, "all", False))
    print_issues_table(issues, title=f"Project {args.project}")


def cmd_sprint_status(client: JiraClient, args):
    _print("\n[bold]Loading sprint status…[/bold]")
    boards = client.get_boards(getattr(args, "project", None))
    if not boards:
        _print("[red]No boards found.[/red]")
        return
    board = boards[0]
    _print(f"  Board: [cyan]{board['name']}[/cyan]")
    sprints = client.get_sprints(board["id"], state="active")
    if not sprints:
        _print("[yellow]No active sprint.[/yellow]")
        return
    sprint = sprints[0]
    _print(
        f"  Sprint: [bold]{sprint['name']}[/bold]  "
        f"({_fmtd(sprint.get('startDate',''))} → {_fmtd(sprint.get('endDate',''))})"
    )
    issues = client.get_sprint_issues(sprint["id"])
    print_issues_table(issues, title=f"Sprint: {sprint['name']}")
    if issues:
        total_sp = done_sp = 0.0
        for i in issues:
            d = extract(i)
            try:
                sp = float(d["sp"])
                total_sp += sp
                if d["status"] in ("Done", "Closed"):
                    done_sp += sp
            except Exception:
                pass
        pct    = int(done_sp / total_sp * 100) if total_sp else 0
        filled = int(30 * pct / 100)
        bar    = "█" * filled + "░" * (30 - filled)
        _print(f"\n  [bold]Progress:[/bold] [{bar}] {pct}%  ({int(done_sp)}/{int(total_sp)} SP)\n")


def cmd_sprint_plan(client: JiraClient, args):
    _print("\n[bold blue]═══ Sprint Planning ═══[/bold blue]\n")
    boards = client.get_boards(getattr(args, "project", None))
    if not boards:
        _print("[red]No boards found.[/red]")
        return

    if len(boards) == 1:
        board = boards[0]
    else:
        for i, b in enumerate(boards):
            _print(f"  [{i}] {b['name']}")
        board = boards[int(_ask("Board number", "0"))]

    _print(f"  Board: [cyan]{board['name']}[/cyan]")
    future = client.get_sprints(board["id"], state="future")
    active = client.get_sprints(board["id"], state="active")

    if not future and not active:
        _print("[yellow]No sprints found.[/yellow]")
        return

    if future:
        for i, s in enumerate(future):
            _print(f"  [{i}] {s['name']}")
        sprint = future[int(_ask("Sprint number", "0"))]
    else:
        sprint = active[0]

    _print(f"\n  Planning: [bold green]{sprint['name']}[/bold green]")
    capacity    = float(_ask("  Team capacity (story points)", "40"))
    existing    = client.get_sprint_issues(sprint["id"])
    existing_sp = sum(
        float(extract(i)["sp"]) for i in existing if extract(i)["sp"] != "—"
    )
    remaining = capacity - existing_sp
    _print(f"  Committed: {existing_sp} SP  |  Remaining: [yellow]{remaining} SP[/yellow]\n")

    backlog       = client.get_backlog(board["id"])
    existing_keys = {i["key"] for i in existing}
    backlog       = [i for i in backlog if i["key"] not in existing_keys]
    print_issues_table(backlog[:30], title="Backlog (top 30)")

    suggested, sp_used = [], 0.0
    for i in backlog:
        try:
            sp = float(extract(i)["sp"])
        except Exception:
            sp = 0
        if sp_used + sp <= remaining:
            suggested.append(i)
            sp_used += sp
    if suggested:
        print_issues_table(suggested, title=f"Suggested ({sp_used} SP)")

    raw = _ask("\nKeys to add (comma-separated, Enter to skip)")
    if raw:
        keys = [k.strip().upper() for k in raw.split(",") if k.strip()]
        try:
            ok   = client.move_to_sprint(sprint["id"], keys)
            color = "green" if ok else "red"
            verb  = "✓ Moved" if ok else "✗ Failed"
            _print(f"  [{color}]{verb}[/{color}]: {', '.join(keys)}")
        except Exception as e:
            _print(f"  [red]✗ Error:[/red] Invalid issue ID or sprint operation failed: {str(e)}")
    _print("\n[bold green]Sprint planning complete![/bold green]\n")


def cmd_search(client: JiraClient, args):
    _print(f"\n[bold]JQL:[/bold] {args.jql}")
    issues = client.search_issues(args.jql, max_results=getattr(args, "limit", 50))
    print_issues_table(issues, title=f"Results ({len(issues)})")


# ══════════════════════════════════════════════════════════════════════════════
# OLLAMA  ─  natural-language interface
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """\
You are a helpful Jira assistant with access to a user's Jira Data Center instance.

Jira ticket data is injected into the conversation inside [CONTEXT] blocks.
Answer questions about tickets, sprints, workloads, and priorities in clear,
concise natural language.

When you need to look up Jira data that has not been provided yet, output a line
in EXACTLY this format (and nothing else on that line):
  JIRA_QUERY: <valid JQL expression>

Examples:
  JIRA_QUERY: assignee = currentUser() AND status = "In Progress"
  JIRA_QUERY: project = PROJ AND priority = High ORDER BY created DESC
  JIRA_QUERY: sprint in openSprints() AND status != Done ORDER BY priority ASC

The tool will execute your JQL, inject the results, and ask you to continue.
Only use JIRA_QUERY when you genuinely need data not yet provided.
Never make up ticket details — always query first if unsure.
"""

JIRA_QUERY_RE = re.compile(r'JIRA_QUERY:\s*(.+)', re.IGNORECASE)


def _run_llm_queries(lms: LMStudioClient, client: JiraClient,
                     history: list, reply: str, max_loops: int = 3) -> str:
    """
    If the LLM reply contains a JIRA_QUERY directive, execute the JQL,
    inject results back, and get a new reply. Repeat up to max_loops times.
    """
    for _ in range(max_loops):
        m = JIRA_QUERY_RE.search(reply)
        if not m:
            break
        jql = m.group(1).strip()
        _print(f"  [dim]→ Jira query: {jql}[/dim]")
        try:
            issues  = client.search_issues(jql, max_results=50)
            context = issues_to_text(issues)
        except Exception as e:
            context = f"Query failed: {e}"

        history.append({"role": "assistant", "content": reply})
        history.append({
            "role": "user",
            "content": (
                f"[CONTEXT — results for JQL: {jql}]\n{context}\n[/CONTEXT]\n"
                "Please continue answering my question using these results."
            ),
        })
        reply = lms.chat(history, system=SYSTEM_PROMPT)
    return reply


def cmd_ask(client: JiraClient, lms: LMStudioClient, args):
    """One-shot natural-language question."""
    question = " ".join(args.question)
    _print(f"\n[dim]Thinking with {lms.model}…[/dim]")
    history = [{"role": "user", "content": question}]
    reply   = lms.chat(history, system=SYSTEM_PROMPT)
    reply   = _run_llm_queries(lms, client, history, reply)
    _rule("Answer")
    if HAS_RICH:
        console.print(Markdown(reply))
    else:
        print(reply)
    print()


def cmd_chat(client: JiraClient, lms: LMStudioClient, args):
    """
    Interactive multi-turn AI chat.
    The model can autonomously issue JIRA_QUERY directives to fetch data.
    """
    _rule(f"Jira AI Chat  ·  model={lms.model}")
    _print("[dim]Ask anything about your tickets. Type 'quit' to exit, 'clear' to reset.[/dim]\n")

    # Seed context: pre-load the user's open tickets
    try:
        my_issues = client.get_my_issues()
        ctx       = issues_to_text(my_issues)
        seed_msg  = (
            f"[CONTEXT — my currently assigned open tickets]\n{ctx}\n[/CONTEXT]\n"
            "I'm ready. What would you like to know about your Jira tickets or sprint?"
        )
    except Exception:
        seed_msg = (
            "I'm connected to your Jira. "
            "What would you like to know about your tickets or sprint?"
        )

    history: list = []
    history.append({"role": "user",      "content": seed_msg})
    opener = lms.chat(history, system=SYSTEM_PROMPT)
    history.append({"role": "assistant", "content": opener})

    if HAS_RICH:
        console.print(Panel(Markdown(opener), title="🤖 Assistant", border_style="green"))
    else:
        print(f"\nAssistant: {opener}\n")

    while True:
        try:
            user_input = (
                Prompt.ask("\n[bold cyan]You[/bold cyan]") if HAS_RICH
                else input("\nYou: ").strip()
            )
        except (KeyboardInterrupt, EOFError):
            _print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "bye", "q"):
            _print("[dim]Goodbye![/dim]")
            break
        if user_input.lower() == "clear":
            history = []
            _print("[dim]Conversation cleared.[/dim]")
            continue

        history.append({"role": "user", "content": user_input})
        _print("[dim]Thinking…[/dim]")
        reply = lms.chat(history, system=SYSTEM_PROMPT)
        reply = _run_llm_queries(lms, client, history, reply)
        history.append({"role": "assistant", "content": reply})

        if HAS_RICH:
            console.print(Panel(Markdown(reply), title="🤖 Assistant", border_style="green"))
        else:
            print(f"\nAssistant: {reply}\n")


def cmd_sprint_ai(client: JiraClient, lms: LMStudioClient, args):
    """AI sprint planning advice based on backlog + capacity."""
    _print("\n[bold]Loading sprint data for AI analysis…[/bold]")
    boards = client.get_boards(getattr(args, "project", None))
    if not boards:
        _print("[red]No boards found.[/red]")
        return

    board   = boards[0]
    backlog = client.get_backlog(board["id"])
    active  = client.get_sprints(board["id"], state="active")

    active_ctx = ""
    if active:
        si         = client.get_sprint_issues(active[0]["id"])
        active_ctx = f"\nCurrent active sprint ({active[0]['name']}) issues:\n{issues_to_text(si)}"

    capacity = _ask("Team capacity for next sprint (story points)", "40")
    _print(f"\n[dim]Asking {lms.model} for sprint advice…[/dim]\n")

    prompt = (
        f"Here is our Jira backlog ({len(backlog)} items):\n"
        f"{issues_to_text(backlog[:50])}\n"
        f"{active_ctx}\n\n"
        f"Team capacity for the next sprint: {capacity} story points.\n\n"
        "Please do the following:\n"
        "1. Suggest which backlog items to pull into the next sprint to best "
        "fill the capacity, prioritising high-priority items and a coherent theme.\n"
        "2. Calculate the total story points for your suggestion.\n"
        "3. Flag any risks, missing estimates, or blockers you notice.\n"
        "4. Propose a one-sentence sprint goal that captures the selected work."
    )

    reply = lms.chat([{"role": "user", "content": prompt}], system=SYSTEM_PROMPT)
    _rule("AI Sprint Planning Advice")
    if HAS_RICH:
        console.print(Markdown(reply))
    else:
        print(reply)
    print()


# ══════════════════════════════════════════════════════════════════════════════
# CLI PARSER & MAIN
# ══════════════════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jira_tool",
        description=(
            "Jira Data Center CLI  ·  certificate auth  ·  "
            "multi-environment  ·  LM Studio AI"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python jira_tool.py env add                     # add an environment
  python jira_tool.py env use prod                # switch to prod
  python jira_tool.py status                      # your tickets (active env)
  python jira_tool.py -e staging status           # your tickets in staging
  python jira_tool.py ticket PROJ-42              # ticket detail
  python jira_tool.py sprint-status PROJ          # active sprint board
  python jira_tool.py sprint-plan PROJ            # interactive planning
  python jira_tool.py ask "what blockers do I have?"
  python jira_tool.py chat                        # interactive AI chat
  python jira_tool.py sprint-ai PROJ              # AI sprint advice
  python jira_tool.py lmstudio-config             # change LM Studio model / URL
""",
    )
    p.add_argument(
        "--env", "-e", metavar="NAME",
        help="Override active environment for this command",
    )

    sub = p.add_subparsers(dest="command", metavar="<command>")

    # ── environment management ─────────────────────────────────────────────────
    p_env     = sub.add_parser("env", help="Manage Jira environments")
    env_sub   = p_env.add_subparsers(dest="env_action", metavar="<action>")
    env_sub.add_parser("list",   help="List all environments")
    env_sub.add_parser("add",    help="Add a new environment")
    p_eu = env_sub.add_parser("use",    help="Set active environment")
    p_eu.add_argument("name")
    p_er = env_sub.add_parser("remove", help="Remove an environment")
    p_er.add_argument("name")

    # ── lm studio ─────────────────────────────────────────────────────────────
    sub.add_parser("lmstudio-config", help="Configure LM Studio URL and model")

    # ── ticket commands ────────────────────────────────────────────────────────
    p_st = sub.add_parser("status", help="Show your assigned tickets")
    p_st.add_argument("--filter", "-f", metavar="STATUS",
                      help="Filter by status, e.g. 'In Progress'")

    p_tk = sub.add_parser("ticket", help="Show full details of a ticket")
    p_tk.add_argument("key", help="Issue key, e.g. PROJ-123")

    p_pj = sub.add_parser("project", help="Show open issues in a project")
    p_pj.add_argument("project")
    p_pj.add_argument("--all", action="store_true", help="Include done/closed issues")

    p_ss = sub.add_parser("sprint-status", help="Show active sprint board")
    p_ss.add_argument("project", nargs="?", default=None, help="Project key (optional)")

    p_sp = sub.add_parser("sprint-plan", help="Interactive sprint planning")
    p_sp.add_argument("project", nargs="?", default=None)

    p_sr = sub.add_parser("search", help="Run a raw JQL query")
    p_sr.add_argument("jql", help='JQL string, e.g. "project=PROJ AND priority=High"')
    p_sr.add_argument("--limit", "-l", type=int, default=50, help="Max results")

    # ── AI commands ────────────────────────────────────────────────────────────
    p_ask = sub.add_parser("ask",  help="Ask a natural-language question")
    p_ask.add_argument("question", nargs="+", help="Question in plain English")

    sub.add_parser("chat",       help="Interactive multi-turn AI chat session")

    p_sai = sub.add_parser("sprint-ai", help="AI-powered sprint planning advice")
    p_sai.add_argument("project", nargs="?", default=None)

    return p


def main():
    parser = build_parser()
    args   = parser.parse_args()
    cfg    = load_config()

    # ── Commands that do NOT need a Jira connection ────────────────────────────
    if args.command == "env":
        if not getattr(args, "env_action", None):
            parser.parse_args(["env", "--help"])
            return
        cmd_env(args, cfg)
        return

    if args.command == "lmstudio-config":
        cmd_lmstudio_config(args, cfg)
        return

    if not args.command:
        if not cfg["environments"]:
            _print("\n[bold yellow]Welcome to Jira Tool![/bold yellow]")
            _print("No environments configured yet. Let's add your first one.\n")
            # Fake args for cmd_env
            class _FakeArgs:
                env_action = "add"
            cmd_env(_FakeArgs(), cfg)
            cfg = load_config()
        else:
            parser.print_help()
        return

    # ── Resolve environment ────────────────────────────────────────────────────
    env, env_name = get_active_env(cfg, getattr(args, "env", None))
    _print(f"[dim]Environment: [bold]{env_name}[/bold]  {env.get('base_url','')}[/dim]")

    # ── Build & test Jira client ───────────────────────────────────────────────
    try:
        client = JiraClient(env)
        me     = client.test_connection()
        _print(f"[dim]Authenticated as: {me.get('displayName', me.get('name','?'))}[/dim]\n")
    except requests.exceptions.SSLError as e:
        _print(f"[red]SSL/certificate error:[/red] {e}")
        _print("[dim]Check cert, key, ca_bundle paths in your environment config.[/dim]")
        sys.exit(1)
    except requests.exceptions.ConnectionError:
        _print(f"[red]Cannot connect to {env.get('base_url','')}. Check URL and network.[/red]")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code
        if code == 401:
            _print("[red]Authentication failed. Check certificate / token.[/red]")
        else:
            _print(f"[red]HTTP {code}:[/red] {e.response.text[:200]}")
        sys.exit(1)

    # ── Lazy LM Studio client ──────────────────────────────────────────────────
    def get_lms() -> LMStudioClient:
        o = cfg.get("lmstudio", DEFAULT_CONFIG["lmstudio"])
        return LMStudioClient(
            o.get("base_url", "http://localhost:1234"),
            o.get("model",    "local-model"),
        )

    # ── Dispatch ───────────────────────────────────────────────────────────────
    try:
        if   args.command == "status":        cmd_status(client, args)
        elif args.command == "ticket":        cmd_ticket(client, args)
        elif args.command == "project":       cmd_project(client, args)
        elif args.command == "sprint-status": cmd_sprint_status(client, args)
        elif args.command == "sprint-plan":   cmd_sprint_plan(client, args)
        elif args.command == "search":        cmd_search(client, args)
        elif args.command == "ask":           cmd_ask(client, get_lms(), args)
        elif args.command == "chat":          cmd_chat(client, get_lms(), args)
        elif args.command == "sprint-ai":     cmd_sprint_ai(client, get_lms(), args)
        else:
            parser.print_help()

    except requests.exceptions.HTTPError as e:
        _print(f"[red]Jira API error {e.response.status_code}:[/red] {e.response.text[:300]}")
        sys.exit(1)
    except KeyboardInterrupt:
        _print("\n[dim]Interrupted.[/dim]")


if __name__ == "__main__":
    main()
