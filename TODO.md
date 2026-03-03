# TODO

## API Fixes Needed

### 1. Fix bash prompt regex in `/api/tmux/send_wait`

**File:** `routers/tmux/router.py` line ~965

**Current:**
```python
prompt_pattern = re.compile(r'w-\d+\s+\$\s*$')
```

**Should be:**
```python
prompt_pattern = re.compile(r'w-\d+\s+\(.*?\)\$\s*$')
```

**Reason:** Current regex doesn't match actual bash prompt format `w-20092 (main)$`

### 2. Fix output extraction logic in `/api/tmux/send_wait`

**File:** `routers/tmux/router.py` line ~1000-1010

**Issue:** `answer` field returns empty string even when output exists

**Test case:**
```bash
tm msg_wait w-20083 "what is 2+2" 30 kiro-cli
# Returns: {"success": true, "answer": ""}
# Expected: {"success": true, "answer": "2+2 = 4"}
```

**Possible causes:**
- `baseline_len` calculation incorrect
- `new_lines = current_lines[baseline_len:]` not extracting correctly
- ANSI escape codes interfering with line counting

**Debug needed:** Add logging to see baseline_lines vs current_lines comparison
