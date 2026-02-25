"""
GitHub Projects 看板集成 API
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
import subprocess
import json
import os

router = APIRouter(prefix="/api/board", tags=["board"])

REPO = "cicy-dev/ai-workers"
PROJECT_NUMBER = "2"

class IssueCreate(BaseModel):
    title: str
    body: Optional[str] = ""
    labels: Optional[List[str]] = []
    assignees: Optional[List[str]] = []

class IssueUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    state: Optional[str] = None  # "open" or "closed"
    labels: Optional[List[str]] = None

def run_gh(args: List[str]) -> dict:
    """执行 gh 命令"""
    try:
        env = os.environ.copy()
        # 确保 GH_TOKEN 存在
        if "GH_TOKEN" not in env:
            gh_token = os.getenv("GH_TOKEN")
            if gh_token:
                env["GH_TOKEN"] = gh_token
        
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"gh command failed: {result.stderr}")
        return {"success": True, "output": result.stdout.strip()}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="gh command timeout")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/issues")
async def create_issue(issue: IssueCreate):
    """创建 issue 并添加到看板"""
    args = [
        "issue", "create",
        "--repo", REPO,
        "--title", issue.title,
        "--body", issue.body or ""
    ]
    
    if issue.labels:
        for label in issue.labels:
            args.extend(["--label", label])
    
    if issue.assignees:
        for assignee in issue.assignees:
            args.extend(["--assignee", assignee])
    
    result = run_gh(args)
    
    # 提取 issue 号
    output = result["output"]
    issue_url = output.split("\n")[-1] if output else ""
    issue_number = issue_url.split("/")[-1] if "/" in issue_url else None
    
    return {
        "success": True,
        "issue_number": issue_number,
        "url": issue_url
    }

@router.get("/issues")
async def list_issues(state: str = "open", limit: int = 30):
    """列出 issues"""
    args = [
        "issue", "list",
        "--repo", REPO,
        "--state", state,
        "--limit", str(limit),
        "--json", "number,title,state,labels,assignees,createdAt,updatedAt"
    ]
    
    result = run_gh(args)
    try:
        issues = json.loads(result["output"])
        return {"success": True, "issues": issues}
    except json.JSONDecodeError:
        return {"success": True, "issues": []}

@router.get("/issues/{issue_number}")
async def get_issue(issue_number: int):
    """获取 issue 详情"""
    args = [
        "issue", "view", str(issue_number),
        "--repo", REPO,
        "--json", "number,title,body,state,labels,assignees,createdAt,updatedAt,comments"
    ]
    
    result = run_gh(args)
    try:
        issue = json.loads(result["output"])
        return {"success": True, "issue": issue}
    except json.JSONDecodeError:
        raise HTTPException(status_code=404, detail="Issue not found")

@router.patch("/issues/{issue_number}")
async def update_issue(issue_number: int, update: IssueUpdate):
    """更新 issue"""
    args = ["issue", "edit", str(issue_number), "--repo", REPO]
    
    if update.title:
        args.extend(["--title", update.title])
    
    if update.body is not None:
        args.extend(["--body", update.body])
    
    if update.labels:
        for label in update.labels:
            args.extend(["--add-label", label])
    
    result = run_gh(args)
    
    # 如果需要关闭/重开
    if update.state:
        state_args = ["issue", update.state, str(issue_number), "--repo", REPO]
        run_gh(state_args)
    
    return {"success": True, "message": f"Issue #{issue_number} updated"}

@router.post("/issues/{issue_number}/close")
async def close_issue(issue_number: int, comment: Optional[str] = None):
    """关闭 issue"""
    if comment:
        comment_args = [
            "issue", "comment", str(issue_number),
            "--repo", REPO,
            "--body", comment
        ]
        run_gh(comment_args)
    
    args = ["issue", "close", str(issue_number), "--repo", REPO]
    result = run_gh(args)
    
    return {"success": True, "message": f"Issue #{issue_number} closed"}

@router.post("/issues/{issue_number}/reopen")
async def reopen_issue(issue_number: int):
    """重开 issue"""
    args = ["issue", "reopen", str(issue_number), "--repo", REPO]
    result = run_gh(args)
    
    return {"success": True, "message": f"Issue #{issue_number} reopened"}

@router.post("/issues/{issue_number}/comment")
async def add_comment(issue_number: int, comment: dict):
    """添加评论"""
    body = comment.get("body", "")
    if not body:
        raise HTTPException(status_code=400, detail="body is required")
    
    args = [
        "issue", "comment", str(issue_number),
        "--repo", REPO,
        "--body", body
    ]
    result = run_gh(args)
    
    return {"success": True, "message": "Comment added"}
