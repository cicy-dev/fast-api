# Skill List

## 1. fast-api

CLI tool to access FastAPI server (http://localhost:14444).

**Features:**
- Call API endpoints: `fast-api /api/tmux/panes`
- List endpoints: `fast-api --tools`
- View endpoint details: `fast-api --tools /api/health`
- Auto-loads token from `~/global.json`

**Location:** `./bin/fast-api` → `~/.local/bin/fast-api` (global)

## 2. gpt

Simple CLI to ask Cloudflare AI questions.

**Usage:**
```bash
gpt <your question>
```

**Examples:**
```bash
gpt hi
gpt what is 10 + 20
gpt explain quantum computing
```

**Location:** `./bin/gpt` → `~/.local/bin/gpt` (global)

## 3. gpt-chat

Multi-turn conversation with history (stored in `~/Private/data/gpt-chat-history.json`).

**Usage:**
```bash
gpt-chat <your message>
gpt-chat --clear                    # Clear conversation history
gpt-chat --system <text>            # Set system prompt
gpt-chat --show-system              # Show current system prompt
```

**Examples:**
```bash
# Set system prompt
gpt-chat --system "You are a helpful math tutor."

# Chat with system prompt
gpt-chat "Hi, my name is Alice"
gpt-chat "What is my name?"        # Remembers: "Your name is Alice."
gpt-chat "What is 5+3?"
gpt-chat "Multiply that by 2"      # Remembers: "8 * 2 = 16."

# Show current system prompt
gpt-chat --show-system

# Clear history
gpt-chat --clear
```

**Files:**
- History: `~/Private/data/gpt-chat-history.json`
- System prompt: `~/Private/data/gpt-chat-system.txt`

**Location:** `./bin/gpt-chat` → `~/.local/bin/gpt-chat` (global)

**Advanced (with system prompt):**
```bash
fast-api /api/cf/chat '{"messages":[{"role":"system","content":"You are a pirate."},{"role":"user","content":"Hello"}]}'
```

## 4. tm

Tmux manager CLI using fast-api.

**Usage:**
```bash
tm <command> [args]
```

**Commands:**
```bash
tm msg <pane_id> <text>                    # Send message to pane (auto-adds Enter)
tm msg_wait <pane_id> <text> [timeout] [prompt_type]  # Send and wait for reply (default: bash, 60s)
tm ls                                      # List all panes
tm status [pane_id]                        # Show pane status (all if no pane_id)
tm capture <pane_id>                       # Capture pane content
tm tree                                    # Show tmux tree
```

**Examples:**
```bash
tm msg w-10001 "echo 'test'"
tm msg_wait w-20083 "pwd" 30 kiro-cli     # Wait for kiro-cli prompt
tm msg_wait w-20089 "ls" 10 bash          # Wait for bash prompt
tm ls
tm status w-10001
tm capture w-10001
tm tree
```

**Location:** `./bin/tm` → `~/.local/bin/tm` (global)

## 5. eng

English grammar correction using GPT.

**Usage:**
```bash
eng <text to correct>
```

**Examples:**
```bash
eng "how r u?"                      # Output: How are you?
eng "i goes to school yesterday"   # Output: I went to school yesterday.
eng "she dont like apples"          # Output: She doesn't like apples.
```

**Location:** `./bin/eng` → `~/.local/bin/eng` (global)


