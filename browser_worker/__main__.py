"""Supervise a private display, authenticated console, and inspection socket."""
import asyncio
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

import uvicorn

from .auth import console_password
from .server import create_app


async def run():
    console_password()
    os.umask(0o077)
    Path("/run/campfinder").mkdir(exist_ok=True)
    processes = []
    public_env = {key: value for key, value in os.environ.items() if key != "CAMPFINDER_BROWSER_PASSWORD"}
    server = uvicorn.Server(uvicorn.Config(create_app(), uds="/run/campfinder/inspect.sock",
                                          access_log=False, log_level="warning"))
    try:
        processes.append(subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1440x1000x24", "-nolisten", "tcp"], env=public_env))
        for _ in range(50):
            if processes[0].poll() is not None:
                raise RuntimeError("Private display exited")
            ready = subprocess.run(["xdpyinfo", "-display", ":99"], env=public_env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            if ready.returncode == 0:
                break
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError("Private display did not start")
        processes.append(subprocess.Popen(["openbox"], env=public_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        processes.append(subprocess.Popen(["x11vnc", "-display", ":99", "-localhost", "-rfbport", "5900", "-forever",
                                           "-shared", "-nopw", "-quiet"], env=public_env,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        processes.append(subprocess.Popen([sys.executable, "-m", "websockify", "--web", "/usr/share/novnc",
                                           "--web-auth", "--auth-plugin", "browser_worker.auth.ConsoleAuth",
                                           "6080", "127.0.0.1:5900"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

        failed_process = None

        async def monitor():
            nonlocal failed_process
            while not server.should_exit:
                for name, process in zip(("display", "window manager", "VNC server", "authenticated console"), processes):
                    if process.poll() is not None:
                        failed_process = name
                        logging.error("Browser %s exited with code %s", name, process.returncode)
                        server.should_exit = True
                        return
                await asyncio.sleep(0.5)

        for name in (signal.SIGTERM, signal.SIGINT):
            asyncio.get_running_loop().add_signal_handler(name, lambda: setattr(server, "should_exit", True))
        monitor_task = asyncio.create_task(monitor())
        try:
            await server.serve()
            if failed_process or not server.started:
                raise RuntimeError("Browser worker startup or supporting process failed")
        finally:
            monitor_task.cancel()
            await asyncio.gather(monitor_task, return_exceptions=True)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    asyncio.run(run())
