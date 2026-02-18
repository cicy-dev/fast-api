import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from main import app, AUTH_TOKEN
import time

class TestCreateWindow:
    def setup_method(self):
        self.client = TestClient(app)
        self.headers = {
            "Authorization": f"Bearer {AUTH_TOKEN}",
            "Accept": "application/json"
        }
    
    def test_create_window(self):
        win_name = f"test_win_{int(time.time())}"
        
        response = self.client.post("/api/tmux/create", 
            headers=self.headers,
            json={
                "session_name": "test_session",
                "win_name": win_name,
                "workspace": "~/test_workspace",
                "init_script": "echo 'Hello World'",
                "dev": False,
                "use_local_ip": True
            })
        
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
        
        data = response.json()
        assert response.status_code == 200
        assert data["success"] is True
        assert data["session"] == "test_session"
        assert data["window"] == win_name
        assert "ttyd_port" in data
        assert "url" in data
        assert "127.0.0.1" in data["url"], f"Expected 127.0.0.1 in URL, got {data['url']}"
        
        print("✓ Test passed!")
    
    def test_workspace_directory(self):
        """Test that workspace directory is used correctly"""
        import subprocess
        import os
        
        win_name = f"test_ws_{int(time.time())}"
        workspace = f"~/workers/{win_name}"
        
        # Create workspace first
        expanded_path = os.path.expanduser(workspace)
        os.makedirs(expanded_path, exist_ok=True)
        
        response = self.client.post("/api/tmux/create",
            headers=self.headers,
            json={
                "session_name": "test_session",
                "win_name": win_name,
                "workspace": workspace,
                "init_script": "pwd",
                "dev": False,
                "use_local_ip": True
            })
        
        data = response.json()
        assert response.status_code == 200
        
        # Get pane working directory
        pane_id = data["pane_id"]
        time.sleep(0.5)
        result = subprocess.run(
            ["tmux", "display-message", "-p", "-t", pane_id, "#{pane_current_path}"],
            capture_output=True, text=True
        )
        current_path = result.stdout.strip()
        assert current_path == expanded_path, f"Expected {expanded_path}, got {current_path}"
        
        print(f"✓ Workspace test passed! Directory: {expanded_path}")
    
    def test_init_script(self):
        """Test that init_script is executed correctly"""
        import subprocess
        import os
        
        win_name = f"test_init_{int(time.time())}"
        test_file = f"/tmp/test_init_{win_name}.txt"
        
        response = self.client.post("/api/tmux/create",
            headers=self.headers,
            json={
                "session_name": "test_session",
                "win_name": win_name,
                "workspace": "~/test_workspace",
                "init_script": f"echo 'test_success' > {test_file}",
                "dev": False,
                "use_local_ip": True
            })
        
        data = response.json()
        assert response.status_code == 200
        
        # Wait for script to execute
        time.sleep(1)
        
        # Check if file was created
        assert os.path.exists(test_file), f"Init script did not create {test_file}"
        
        with open(test_file) as f:
            content = f.read().strip()
        
        assert content == "test_success", f"Expected 'test_success', got '{content}'"
        
        # Cleanup
        os.remove(test_file)
        
        print(f"✓ Init script test passed!")
    
    def test_ttyd_url_accessible(self):
        """Test that ttyd is running on the correct port"""
        import requests
        
        win_name = f"test_url_{int(time.time())}"
        
        response = self.client.post("/api/tmux/create",
            headers=self.headers,
            json={
                "session_name": "test_session",
                "win_name": win_name,
                "workspace": "~/test_workspace",
                "init_script": "echo 'test'",
                "dev": False,
                "use_local_ip": True
            })
        
        data = response.json()
        assert response.status_code == 200
        
        url = data["url"]
        assert "127.0.0.1" in url, f"Expected 127.0.0.1 in URL, got {url}"
        
        print(f"Testing URL: {url}")
        
        # Wait for ttyd to start
        time.sleep(1)
        
        # Test URL is accessible
        try:
            r = requests.get(url, timeout=5)
            assert r.status_code == 200, f"URL returned {r.status_code}"
            print(f"✓ ttyd URL test passed! URL is accessible")
        except Exception as e:
            print(f"✗ URL test failed: {e}")
            raise
    
    def test_send_keys(self):
        """Test sending keys to window and capturing output"""
        import subprocess
        
        win_name = f"test_send_{int(time.time())}"
        
        response = self.client.post("/api/tmux/create",
            headers=self.headers,
            json={
                "session_name": "test_session",
                "win_name": win_name,
                "workspace": "~/test_workspace",
                "init_script": "clear",
                "dev": False,
                "use_local_ip": True
            })
        
        data = response.json()
        assert response.status_code == 200
        pane_id = data["pane_id"]
        
        time.sleep(0.5)
        
        # Send command
        send_response = self.client.post(
            "/api/tmux/send",
            headers=self.headers,
            json={
                "win_id": pane_id,
                "keys": "echo 'hello_test'"
            })
        
        assert send_response.status_code == 200
        
        # Send Enter
        self.client.post(
            "/api/tmux/send",
            headers=self.headers,
            json={
                "win_id": pane_id,
                "keys": "Enter"
            })
        
        time.sleep(0.5)
        
        # Capture pane output
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", pane_id, "-p"],
            capture_output=True, text=True
        )
        
        output = result.stdout
        assert "hello_test" in output, f"Expected 'hello_test' in output, got: {output}"
        
        print(f"✓ Send keys test passed! Output captured: {output.strip()}")

if __name__ == "__main__":
    test = TestCreateWindow()
    test.setup_method()
    test.test_create_window()
    test.test_workspace_directory()
    test.test_init_script()
    test.test_ttyd_url_accessible()
    test.test_send_keys()
