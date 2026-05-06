# Jira Personal AI Agent

A command-line tool for Jira Data Center that lets you check ticket statuses, manage sprints, and query your Jira in plain English using a locally-running LLM via LM Studio.

## Problem 
As a security engineer we all struggle planning projects and managing mnay tickets for day to day activities. Jira is great tool, but it could become cumbersome if the process demand a lot of data points and updates on it. For me it became 20% of my work which costed me a lot of focus time on actual work and brought down productivity. Hence, created a commanline assistant that can make it easier for me to plan my sprints and analyse my tickets.
---

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Setup](#setup)
  - [1. Add a Jira Environment](#1-add-a-jira-environment)
  - [2. Authentication Methods](#2-authentication-methods)
  - [3. Configure LM Studio (AI features)](#3-configure-lm-studio-ai-features)
- [Usage Examples](#usage-examples)
  - [Environment Management](#environment-management)
  - [Ticket Commands](#ticket-commands)
  - [Sprint Commands](#sprint-commands)
  - [AI Commands](#ai-commands)
- [Configuration File](#configuration-file)
- [Troubleshooting](#troubleshooting)

---

## Requirements

### Python

- Python **3.8 or higher**

### Python Libraries

```
requests
rich        (optional, but recommended — enables colour output and tables)
```

Install both in one go:

```bash
pip install requests rich
```

### Jira

- **Jira Data Center** (any recent version)
- The Jira Agile / Software REST API must be enabled — this is on by default for Software projects
- Your user account needs **browse** permission on the projects you want to query, and **edit** permission to move issues into sprints
- API endpoints used:
  - `GET  /rest/api/2/myself`
  - `GET  /rest/api/2/search`
  - `GET  /rest/api/2/issue/{key}`
  - `GET  /rest/agile/1.0/board`
  - `GET  /rest/agile/1.0/board/{id}/sprint`
  - `GET  /rest/agile/1.0/sprint/{id}/issue`
  - `GET  /rest/agile/1.0/board/{id}/backlog`
  - `POST /rest/agile/1.0/sprint/{id}/issue`

### LM Studio _(only needed for AI commands)_

- [LM Studio](https://lmstudio.ai) installed and running (free, Windows / macOS / Linux)
- At least one model downloaded inside LM Studio (e.g. Llama 3, Mistral, Phi-3)
- The **Local Server** started inside LM Studio (default port `1234`)

---

## Installation

1. **Download** `jira_tool.py` and place it anywhere on your machine.

2. **Install dependencies:**

   ```bash
   pip install requests rich
   ```

3. **Verify Python version:**

   ```bash
   python --version   # must be 3.8+
   ```

4. **Run the tool for the first time.** If no environment is configured it will walk you through adding one automatically:

   ```bash
   python jira_tool.py
   ```

---

## Setup

### 1. Add a Jira Environment

An "environment" is a named connection to a Jira server. You can have as many as you like (e.g. `prod`, `staging`, `dev`).

```bash
python jira_tool.py env add
```

You will be prompted for:

| Prompt | Example | Notes |
|--------|---------|-------|
| Environment name | `prod` | A short nickname — used to switch between servers |
| Jira base URL | `https://jira.mycompany.com` | No trailing slash |
| Auth type | `cert` | Choose from `cert`, `token`, or `basic` |
| _(cert only)_ Client certificate | `/home/me/certs/client.pem` | Path to your `.pem` or `.crt` file |
| _(cert only)_ Private key | `/home/me/certs/client.key` | Leave blank if the key is bundled in the cert file |
| _(cert only)_ CA bundle | `/etc/ssl/certs/company-ca.pem` | Your company CA chain — leave blank to use system CAs |
| _(cert only)_ Verify SSL | `yes` | `yes`, `no`, or a path to a CA file |
| _(token only)_ Personal Access Token | _(hidden input)_ | Generated in Jira → Profile → Personal Access Tokens |
| _(basic only)_ Username | `jsmith` | Your Jira username |
| _(basic only)_ Password | _(hidden input)_ | Your Jira password |

The first environment you add is automatically set as the active one.

---

### 2. Authentication Methods

#### Certificate (mTLS) — `cert`

Used when your company requires mutual TLS. You need three things from your IT / security team:

- **Client certificate** — a `.pem` or `.crt` file that identifies you
- **Private key** — a `.key` or `.pem` file (sometimes bundled into the same file as the cert)
- **CA bundle** — your company's Certificate Authority chain (so the tool trusts your Jira server's certificate)

```
Auth type:   cert
Cert path:   /home/me/certs/client.pem
Key path:    /home/me/certs/client.key    ← leave blank if bundled in cert
CA bundle:   /etc/ssl/certs/company-ca.pem
Verify SSL:  yes                           ← or path to CA file
```

> **Tip:** If your cert and key are in one file, just enter the cert path and leave the key path blank.

#### Personal Access Token — `token`

Generated inside Jira at **Profile → Personal Access Tokens**. Sent as a `Bearer` header.

```
Auth type:   token
Token:       ****************************
```

#### Basic (username + password) — `basic`

Plain username and password. Only use this if your Jira instance has no other option — PATs are safer.

```
Auth type:   basic
Username:    jsmith
Password:    ****
```

---

### 3. Configure LM Studio (AI features)

> Skip this section if you only need ticket and sprint commands.

**Step 1 — Install LM Studio**

Download from [lmstudio.ai](https://lmstudio.ai). It is free and works on Windows, macOS, and Linux.

**Step 2 — Download a model**

Inside LM Studio, go to the **Discover** tab and search for a model. Models tested by me are luisted below:

| Model | Size | Notes |
|-------|------|-------|
| qwen3:1.7b | ~1 GB | Incredibly faster good for quick summarization  |
| qwen3.5 9B | ~6 GB | Fast and intelligent, can provide good recommendations|
| gemma4 E4B 7.5B | ~6 GB | Similar performance as qwen3.5 |

Click **Download** next to your chosen model.

**Step 3 — Start the Local Server**

In LM Studio, click **Local Server** in the left sidebar → select your downloaded model → click **Start Server**.

The server runs on `http://localhost:1234` by default.

**Step 4 — Tell the tool which model to use**

```bash
python jira_tool.py lmstudio-config
```

```
LM Studio base URL [http://localhost:1234]:   ← press Enter to keep default
Model identifier: lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF
```

Copy the model identifier exactly as shown in LM Studio's Local Server tab.

---

## Usage Examples

### Environment Management

```bash
# Add a new environment (interactive wizard)
python jira_tool.py env add

# List all configured environments  (● = currently active)
python jira_tool.py env list

# Switch the active environment
python jira_tool.py env use staging

# Override the active env for a single command without switching
python jira_tool.py -e prod status

# Remove an environment
python jira_tool.py env remove dev
```

---

### Ticket Commands

**Show all your assigned open tickets:**

```bash
python jira_tool.py status
```

**Filter by status:**

```bash
python jira_tool.py status --filter "In Progress"
python jira_tool.py status -f "To Do"
python jira_tool.py status -f "Blocked"
```

**View full details of a specific ticket:**

```bash
python jira_tool.py ticket PROJ-123
```

Output includes: summary, status, type, priority, assignee, story points, due date, labels, description, and the most recent comment.

**Browse all open issues in a project:**

```bash
python jira_tool.py project PROJ

# Include Done and Closed issues too
python jira_tool.py project PROJ --all
```

**Run a raw JQL search:**

```bash
python jira_tool.py search "assignee = currentUser() AND priority = High"
python jira_tool.py search "project = PROJ AND status = Blocked ORDER BY created ASC"
python jira_tool.py search "due <= endOfWeek() AND status != Done" --limit 20
```

---

### Sprint Commands

**View the active sprint for a project:**

```bash
python jira_tool.py sprint-status PROJ
```

Shows: all tickets in the sprint, assignees, story points, status breakdown, and a text progress bar (e.g. `████████████░░░░░░░░░░░░░░░░░░ 42%  (17/40 SP)`).

**Interactive sprint planning:**

```bash
python jira_tool.py sprint-plan PROJ
```

The wizard will:
1. Ask you to pick a future sprint
2. Ask for your team's story-point capacity
3. Show the current backlog
4. Auto-suggest which items fit within your remaining capacity
5. Let you type issue keys to move into the sprint

Example session:

```
  [0] Sprint 24 — May 6–20
  [1] Sprint 25 — May 21–Jun 3
Sprint number [0]: 0

  Team capacity (story points) [40]: 35
  Committed: 8 SP  |  Remaining: 27 SP

  ┌── Suggested (26 SP) ──────────────────────────────┐
  │ PROJ-88   Fix login timeout bug         High   5 SP│
  │ PROJ-91   Update API docs               Medium 3 SP│
  │ PROJ-95   Add export button             Medium 8 SP│
  │ PROJ-99   Refactor auth module          High  10 SP│
  └────────────────────────────────────────────────────┘

Keys to add (comma-separated, Enter to skip): PROJ-88, PROJ-95, PROJ-99
  ✓ Moved PROJ-88, PROJ-95, PROJ-99 to Sprint 24
```

---

### AI Commands

> Requires LM Studio to be running with the Local Server started.

**Ask a one-off question in plain English:**

```bash
python jira_tool.py ask "what tickets are blocking me right now?"
python jira_tool.py ask "do I have anything due this week?"
python jira_tool.py ask "who has the most open tickets in PROJ?"
python jira_tool.py ask "summarise everything I have in progress"
python jira_tool.py ask "are there any high priority bugs in the backlog?"
```

The AI will automatically search Jira if it needs more data to answer your question.

**Start an interactive multi-turn chat session:**

```bash
python jira_tool.py chat
```

The session pre-loads your open tickets as context, then you can have a back-and-forth conversation. The AI can query Jira mid-conversation without you having to write JQL.

```
────────────── Jira AI Chat · model=Meta-Llama-3-8B-Instruct ──────────────
Ask anything about your tickets. Type 'quit' to exit, 'clear' to reset.

╭─ 🤖 Assistant ─────────────────────────────────────────────────────────╮
│ I can see you have 12 open tickets. 4 are In Progress, 6 are To Do,    │
│ and 2 are Blocked. Would you like me to focus on anything in particular?│
╰────────────────────────────────────────────────────────────────────────╯

You: which blocked tickets are mine?
  → Jira query: assignee = currentUser() AND status = Blocked

╭─ 🤖 Assistant ─────────────────────────────────────────────────────────╮
│ You have 2 blocked tickets:                                             │
│ • PROJ-77 — Payment gateway integration (blocked on vendor access)      │
│ • PROJ-84 — Deploy to staging (blocked on DevOps approval)              │
╰────────────────────────────────────────────────────────────────────────╯

You: quit
```

Special chat commands:

| Type | Effect |
|------|--------|
| `quit` / `exit` / `q` | End the session |
| `clear` | Wipe conversation history and start fresh |

**AI-powered sprint planning advice:**

```bash
python jira_tool.py sprint-ai PROJ
```

Fetches the backlog and active sprint, asks for your capacity, then the AI returns:
- A recommended selection of backlog items
- Total story points for the suggestion
- Any risks or missing estimates it notices
- A one-sentence sprint goal

---

## Configuration File

All settings are stored in `~/.jira_tool_config.json` with permissions `600` (only readable by you). You can inspect it at any time:

```bash
cat ~/.jira_tool_config.json
```

Structure:

```json
{
  "active_env": "prod",
  "environments": {
    "prod": {
      "base_url": "https://jira.mycompany.com",
      "auth_type": "cert",
      "cert": "/home/me/certs/client.pem",
      "key": "/home/me/certs/client.key",
      "ca_bundle": "/etc/ssl/certs/company-ca.pem",
      "verify_ssl": true
    },
    "staging": {
      "base_url": "https://jira-staging.mycompany.com",
      "auth_type": "token",
      "token": "your-personal-access-token"
    }
  },
  "lmstudio": {
    "base_url": "http://localhost:1234",
    "model": "lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF"
  }
}
```

To reset everything and start over, delete this file:

```bash
rm ~/.jira_tool_config.json
```

---

## Troubleshooting

**`SSL/certificate error`**

- Double-check the paths to your `cert`, `key`, and `ca_bundle` files — they must be absolute paths
- Make sure the certificate has not expired (`openssl x509 -enddate -noout -in client.pem`)
- If your company CA is not trusted, pass its path as the `ca_bundle` value instead of leaving it blank

**`Authentication failed` (HTTP 401)**

- For `cert` auth: your certificate may have expired or not be recognised by that Jira instance
- For `token` auth: regenerate your Personal Access Token in Jira → Profile → Personal Access Tokens
- For `basic` auth: confirm your username and password work in the Jira web UI

**`Cannot connect to [URL]`**

- Check the base URL has no typo and no trailing slash
- Confirm you can reach the URL from your machine: `curl -I https://jira.mycompany.com`
- Check whether a VPN is required

**`No boards found`**

- Sprint commands require a Jira Software (Agile) board. Confirm the project has one in the Jira web UI under **Board** view
- Your user needs **browse project** permission

**`Cannot connect to LM Studio`**

- Open LM Studio → **Local Server** → confirm the server is started and a model is loaded
- Check the port matches what you configured (default `1234`)
- Confirm no firewall is blocking `localhost:1234`
- Re-run `python jira_tool.py lmstudio-config` and verify the URL

**Ticket output is plain text without colour / tables**

- Install `rich`: `pip install rich`
- If already installed, make sure you are not piping the output (e.g. `| grep`), which disables colour automatically
