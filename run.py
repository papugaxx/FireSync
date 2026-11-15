#!/usr/bin/env python3
"""
run.py — START FIRESYNC (backend + website) WITH ONE COMMAND

    python3 run.py                 # development: auto-reload; open http://127.0.0.1:3000/explore
    python3 run.py --prod          # production build locally (next build + next start, no reload)
    python3 run.py --setup         # only install what is missing, then exit
    python3 run.py --no-update     # do not download new NASA data in the background
    python3 run.py --api-port 8001 --web-port 3001

On Windows use `py run.py` instead of `python3 run.py`.

What it does
------------
1. backend/venv: created if missing; Python packages installed if any is missing.
2. fire-calendar/node_modules: `npm ci` if missing or older than package-lock.json.
3. Checks that both ports are free and says which program holds a busy one.
4. Starts the API (uvicorn) and waits until it answers.
5. Starts the website with NEXT_PUBLIC_API_URL pointing at that API.
6. Ctrl+C stops both. If one of them stops, the other one is stopped too.

Only the standard library is used, so it runs with any Python 3.11+.
"""

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
WEB = ROOT / "fire-calendar"
WINDOWS = os.name == "nt"
VENV_PYTHON = BACKEND / "venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
NPM = "npm.cmd" if WINDOWS else "npm"


def say(text):
    print(f"[run] {text}", flush=True)


def fail(text):
    say(text)
    sys.exit(1)


def run(cmd, cwd, env=None):
    say(" ".join(str(c) for c in cmd))
    if subprocess.call([str(c) for c in cmd], cwd=cwd, env=env) != 0:
        fail(f"This step failed: {' '.join(str(c) for c in cmd)}")


# ---------- 1–2. Install what is missing ----------

def setup_backend():
    if not VENV_PYTHON.exists():
        if sys.version_info < (3, 11):
            fail("Python 3.11 or newer is needed (python.org). Then run this again.")
        say("Creating backend/venv …")
        run([sys.executable, "-m", "venv", "venv"], BACKEND)
    check = subprocess.call([str(VENV_PYTHON), "-c", "import fastapi, uvicorn, numpy, fires_data"],
                            cwd=BACKEND, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if check != 0:
        say("Installing the backend packages …")
        run([VENV_PYTHON, "-m", "pip", "install", "--upgrade", "pip"], BACKEND)
        run([VENV_PYTHON, "-m", "pip", "install", "-r", "requirements.txt"], BACKEND)
        run([VENV_PYTHON, "-m", "pip", "install", "-e", "./data_pipeline"], BACKEND)
    if not (BACKEND / "data" / "firesync.sqlite3").exists():
        say("WARNING: backend/data/firesync.sqlite3 does not exist. The site will start but show errors.")
        say("         Import the archive once:  cd backend && venv/bin/python importer.py   (about 10 minutes)")
    env_file = BACKEND / "data_pipeline" / ".env"
    has_key = env_file.exists() and any(line.strip().startswith("FIRMS_MAP_KEY=") and line.split("=", 1)[1].strip()
                                        for line in env_file.read_text(encoding="utf-8-sig").splitlines())
    if not (has_key or os.environ.get("FIRMS_MAP_KEY")):
        say("Note: no NASA key in backend/data_pipeline/.env (FIRMS_MAP_KEY) — new days will not be downloaded.")


def setup_web():
    if not shutil.which(NPM):
        fail("Node.js is not installed. Install Node.js 20.9 or newer (nodejs.org), then run this again.")
    version = subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip().lstrip("v")
    major, minor = (int(x) for x in (version.split(".") + ["0", "0"])[:2])
    if (major, minor) < (20, 9):
        fail(f"Node.js {version} is too old for Next.js 16. Install Node.js 20.9 or newer.")
    modules = WEB / "node_modules" / ".package-lock.json"
    lock = WEB / "package-lock.json"
    if not modules.exists() or modules.stat().st_mtime < lock.stat().st_mtime:
        say("Installing the website packages (npm ci) …")
        run([NPM, "ci", "--no-audit", "--no-fund"], WEB)


# ---------- 3. Ports ----------

def port_busy(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def who_holds(port):
    if WINDOWS:
        out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True).stdout
        lines = [line for line in out.splitlines() if f":{port} " in line and "LISTENING" in line]
        return f"process id {lines[0].split()[-1]}" if lines else "another program"
    if shutil.which("lsof"):
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
        rows = out.splitlines()[1:]
        if rows:
            name, pid = rows[0].split()[:2]
            return f"{name} (process id {pid})"
    return "another program"


def check_ports(host, ports):
    for name, port, flag in ports:
        if port_busy(host, port):
            fail(f"Port {port} ({name}) is already in use by {who_holds(port)}. "
                 f"Stop it, or start with another port: python3 run.py {flag} {port + 1}")


# ---------- 4–6. Start, watch, stop ----------

class Service:
    def __init__(self, name, cmd, cwd, env):
        self.name = name
        flags = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
        self.process = subprocess.Popen([str(c) for c in cmd], cwd=cwd, env=env, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1, **flags)
        threading.Thread(target=self._copy_output, daemon=True).start()

    def _copy_output(self):
        for line in self.process.stdout:
            print(f"[{self.name}] {line.rstrip()}", flush=True)

    def alive(self):
        return self.process.poll() is None

    def stop(self):
        if not self.alive():
            return
        try:
            if WINDOWS:
                subprocess.call(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                os.killpg(self.process.pid, signal.SIGTERM)
            self.process.wait(timeout=10)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            if not WINDOWS:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def wait_for(url, service, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not service.alive():
            return False
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def main():
    parser = argparse.ArgumentParser(description="Start the FireSync backend and website together.")
    parser.add_argument("--prod", action="store_true", help="production build (next build + next start)")
    parser.add_argument("--setup", action="store_true", help="only install what is missing")
    parser.add_argument("--no-update", action="store_true", help="no background NASA downloads")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--web-port", type=int, default=3000)
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on (default: this computer only)")
    args = parser.parse_args()

    setup_backend()
    setup_web()
    if args.setup:
        say("Everything is installed. Start with: python3 run.py")
        return 0
    check_ports(args.host, [("API", args.api_port, "--api-port"), ("website", args.web_port, "--web-port")])

    api_url = f"http://{args.host}:{args.api_port}"
    web_url = f"http://{args.host}:{args.web_port}"
    api_env = dict(os.environ, PYTHONUNBUFFERED="1")
    api_env.setdefault("FRONTEND_URLS", f"http://localhost:{args.web_port},http://127.0.0.1:{args.web_port}"
                                        + (f",{web_url}" if args.host not in ("127.0.0.1", "localhost") else ""))
    if args.no_update:
        api_env["FIRESYNC_AUTO_UPDATE"] = "0"
    web_env = dict(os.environ, NEXT_PUBLIC_API_URL=os.environ.get("NEXT_PUBLIC_API_URL", api_url))
    if args.prod:
        web_env["NODE_ENV"] = "production"

    services = []

    def stop_all(*_):
        for service in reversed(services):
            service.stop()

    if not WINDOWS:
        signal.signal(signal.SIGTERM, lambda *_: (stop_all(), sys.exit(0)))
    try:
        api_cmd = [VENV_PYTHON, "-m", "uvicorn", "main:app", "--host", args.host, "--port", args.api_port]
        services.append(Service("api", api_cmd + ([] if args.prod else ["--reload"]), BACKEND, api_env))
        if not wait_for(f"{api_url}/health", services[0], 60):
            stop_all()
            fail("The API did not start; see the [api] lines above.")
        say(f"API is running: {api_url}/docs")
        if args.prod:
            run([NPM, "run", "build"], WEB, web_env)
            web_cmd = [NPM, "run", "start", "--", "--port", args.web_port, "--hostname", args.host]
        else:
            web_cmd = [NPM, "run", "dev", "--", "--port", args.web_port, "--hostname", args.host]
        services.append(Service("web", web_cmd, WEB, web_env))
        if wait_for(web_url, services[1], 180):
            say(f"Website is running: {web_url}/explore   (Ctrl+C stops everything)")
        while all(service.alive() for service in services):
            time.sleep(0.5)
        stopped = next(service for service in services if not service.alive())
        say(f"The {stopped.name} process stopped (exit code {stopped.process.returncode}); stopping the rest.")
        return 1
    except KeyboardInterrupt:
        say("Stopping …")
        return 0
    finally:
        stop_all()


if __name__ == "__main__":
    sys.exit(main())
