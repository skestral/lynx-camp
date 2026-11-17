"""Test a disposable browser worker without contacting reservation providers.

Build lynx-camp-browser:local first. This script creates and removes only its own
randomly named Compose project, including its temporary profile volume.
"""
import argparse
import base64
import http.client
import json
import os
import secrets
import socket
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshot", type=Path, help="Export the disposable blank-console screenshot")
    args = parser.parse_args()
    project = "campfinder-browser-check-" + secrets.token_hex(6)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    password = secrets.token_urlsafe(32)
    env = {**os.environ, "CAMPFINDER_BROWSER_PASSWORD": password, "CAMPFINDER_BROWSER_PORT": str(port)}
    compose = ["docker", "compose", "-p", project, "-f", "compose.browser.yaml"]

    def run(args, *, check=True):
        result = subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True, timeout=180)
        if check and result.returncode:
            raise RuntimeError((result.stdout + result.stderr)[-6000:].replace(password, "[redacted]"))
        return result

    def request(path, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request("GET", path, headers=headers or {})
            response = connection.getresponse()
            # A successful WebSocket upgrade stays open, so do not read to EOF.
            if response.status != 101:
                response.read()
            return response.status
        finally:
            connection.close()

    auth = {"Authorization": "Basic " + base64.b64encode(f"campfinder:{password}".encode()).decode()}
    try:
        run([*compose, "up", "--no-build", "-d"])
        container = run([*compose, "ps", "-a", "-q", "browser"]).stdout.strip()
        for _ in range(60):
            health = run(["docker", "exec", container, "python", "-m", "browser_worker.control", "health"], check=False)
            if health.returncode == 0:
                break
            state = json.loads(run(["docker", "inspect", "--format", "{{json .State}}", container]).stdout)
            if not state["Running"]:
                raise RuntimeError("Worker exited:\n" + run([*compose, "logs", "--tail", "60"]).stdout)
            time.sleep(1)
        else:
            raise RuntimeError("Worker did not become healthy")
        print("PASS: non-root browser worker started", flush=True)
        for path in ("/vnc.html", "/app/ui.js"):
            assert request(path) == 401, "Console asset exposed without authentication"
            assert request(path, {"Authorization": "Basic !!!"}) == 401
            assert request(path, auth) == 200
        websocket = {**auth, "Origin": f"http://127.0.0.1:{port}", "Upgrade": "websocket", "Connection": "Upgrade",
                     "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": base64.b64encode(secrets.token_bytes(16)).decode()}
        assert request("/websockify", {key: value for key, value in websocket.items() if key != "Authorization"}) == 401
        assert request("/websockify", {**websocket, "Origin": "https://untrusted.invalid"}) == 403
        assert request("/websockify", websocket) == 101
        print("PASS: console assets and WebSockets require authentication; cross-origin control rejected", flush=True)
        host = json.loads(run(["docker", "inspect", "--format", "{{json .HostConfig}}", container]).stdout)
        assert host["CapDrop"] == ["ALL"] and not host["Privileged"]
        assert list(host["PortBindings"]) == ["6080/tcp"]
        assert host["PortBindings"]["6080/tcp"][0]["HostIp"] == "127.0.0.1"
        assert "no-new-privileges:true" in host["SecurityOpt"]
        assert run(["docker", "exec", container, "id", "-u"]).stdout.strip() == "1001"
        permissions = run(["docker", "exec", container, "stat", "-c", "%a", "/run/campfinder"]).stdout.strip()
        assert permissions == "700"
        print("PASS: only authenticated console published on loopback; private control directory mode 700", flush=True)
        tests = run(["docker", "exec", "-e", "CAMPFINDER_BROWSER_TESTS=1", container,
                     "python", "-m", "unittest", "discover", "-s", "browser_worker/tests", "-v"])
        print((tests.stdout + tests.stderr).strip(), flush=True)
        if args.screenshot:
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            # Docker's archive endpoint does not reliably expose tmpfs files.
            screenshot = subprocess.run(["docker", "exec", container, "cat", "/tmp/test-browser-console.png"],
                                        cwd=ROOT, capture_output=True, check=True, timeout=10)
            args.screenshot.write_bytes(screenshot.stdout)
        status = json.loads(run(["docker", "exec", container, "python", "-m", "browser_worker.control", "status"]).stdout)
        assert status["provider_tabs"] == 0 and status["scanner_enabled"] is False
        run([*compose, "restart", "browser"])
        for _ in range(60):
            result = run(["docker", "exec", container, "python", "-m", "browser_worker.control", "status"], check=False)
            if result.returncode == 0 and json.loads(result.stdout)["browser_running"]:
                assert json.loads(result.stdout)["provider_tabs"] == 0
                break
            time.sleep(1)
        else:
            raise RuntimeError("Worker failed to restart")
        print("PASS: restart returns to a blank browser with scanning disabled", flush=True)
    finally:
        result = run([*compose, "down", "--volumes"], check=False)
        if result.returncode:
            raise RuntimeError(f"Could not remove disposable test project {project}")
        print("Removed disposable test container, network, and profile volume", flush=True)


if __name__ == "__main__":
    main()
