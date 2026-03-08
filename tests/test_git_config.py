"""Test auto git config on pane creation (GitHub issue #7)"""
import time
import subprocess
import requests


def test_auto_git_config():
    """Test that git user.email and user.name are auto-configured when creating a pane"""
    
    # Load API token
    import json
    with open("/home/w3c_offical/global.json") as f:
        token = json.load(f).get("api_token", "")
    
    # Create a test pane
    response = requests.post(
        "http://localhost:14444/api/tmux/create",
        json={
            "win_name": f"git_test_{int(time.time())}",
            "init_script": "pwd",
            "dev": True
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    pane_id = data["session"]
    full_pane_id = f"{pane_id}:main.0"
    
    try:
        # Wait for pane to initialize
        time.sleep(3)
        
        # Check git user.email
        subprocess.run(
            ["tmux", "send-keys", "-t", full_pane_id, "git config --global user.email", "Enter"],
            check=True
        )
        time.sleep(1)
        
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", full_pane_id, "-p"],
            capture_output=True,
            text=True,
            check=True
        )
        
        expected_email = f"{pane_id}@cicy.de5.net"
        assert expected_email in result.stdout, f"Expected email {expected_email} not found in output"
        
        # Check git user.name
        subprocess.run(
            ["tmux", "send-keys", "-t", full_pane_id, "git config --global user.name", "Enter"],
            check=True
        )
        time.sleep(1)
        
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", full_pane_id, "-p"],
            capture_output=True,
            text=True,
            check=True
        )
        
        assert pane_id in result.stdout, f"Expected username {pane_id} not found in output"
        
    finally:
        # Cleanup
        subprocess.run(["tmux", "kill-session", "-t", pane_id], check=False)


if __name__ == "__main__":
    test_auto_git_config()
    print("✓ Git auto-config test passed")
