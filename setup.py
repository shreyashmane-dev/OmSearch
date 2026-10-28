#!/usr/bin/env python3
"""
OM Search Engine — Cross-Platform Setup & Environment Bootstrapper
Automates complete installation for developers cloning the repository.
Works out-of-the-box on Windows, Linux, and macOS.

Usage:
    python setup.py          # Full interactive installation & validation
    python setup.py --start  # Install and immediately launch backend & frontend
    python setup.py --check  # Verify environment without modifying anything
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

# ANSI colors for friendly terminal output
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DATA_DIR = PROJECT_ROOT / "data"

IS_WINDOWS = sys.platform.startswith("win")
VENV_DIR = PROJECT_ROOT / ".venv"

if IS_WINDOWS:
    VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"
    VENV_PIP = VENV_DIR / "Scripts" / "pip.exe"
    VENV_UVICORN = VENV_DIR / "Scripts" / "uvicorn.exe"
else:
    VENV_PYTHON = VENV_DIR / "bin" / "python"
    VENV_PIP = VENV_DIR / "bin" / "pip"
    VENV_UVICORN = VENV_DIR / "bin" / "uvicorn"


def print_banner():
    print(f"\n{BLUE}{BOLD}================================================================================{RESET}")
    print(f"{BLUE}{BOLD}                    OM SEARCH ENGINE — ONE-CLICK SETUP WIZARD                    {RESET}")
    print(f"{BLUE}      Zero-Config Autonomous Setup: Backend, Frontend, SQLite FTS & Cloud      {RESET}")
    print(f"{BLUE}{BOLD}================================================================================{RESET}\n")


def log_step(msg: str):
    print(f"{BLUE}{BOLD}[➜]{RESET} {msg}")


def log_success(msg: str):
    print(f"{GREEN}{BOLD}[✓]{RESET} {msg}")


def log_warn(msg: str):
    print(f"{YELLOW}{BOLD}[!]{RESET} {msg}")


def log_error(msg: str):
    print(f"{RED}{BOLD}[✗]{RESET} {msg}")


def check_python_version():
    log_step("Checking Python version...")
    v = sys.version_info
    if v.major < 3 or (v.major == 3 and v.minor < 10):
        log_error(f"Python 3.10+ required. Detected: {v.major}.{v.minor}.{v.micro}")
        sys.exit(1)
    log_success(f"Python version: {v.major}.{v.minor}.{v.micro}")


def check_node():
    log_step("Checking Node.js & npm (required for frontend)...")
    node_cmd = shutil.which("node")
    npm_cmd = shutil.which("npm")
    if not node_cmd or not npm_cmd:
        log_warn("Node.js or npm is not detected in your PATH.")
        log_warn("You can still use the FastAPI backend, but frontend requires Node 18+.")
        log_warn("Download Node.js: https://nodejs.org/")
        return False
    try:
        node_v = subprocess.check_output([node_cmd, "--version"], text=True).strip()
        npm_v = subprocess.check_output([npm_cmd, "--version"], text=True).strip()
        log_success(f"Node.js: {node_v} | npm: {npm_v}")
        return True
    except Exception as e:
        log_warn(f"Failed to check Node version: {e}")
        return False


def setup_virtualenv():
    log_step(f"Setting up Python virtual environment in {VENV_DIR.name}/...")
    if not VENV_DIR.exists() or not VENV_PYTHON.exists():
        try:
            subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
            log_success(f"Created virtual environment at: {VENV_DIR}")
        except subprocess.CalledProcessError as e:
            log_error(f"Failed to create virtual environment: {e}")
            sys.exit(1)
    else:
        log_success(f"Virtual environment already exists at: {VENV_DIR}")


def install_backend_dependencies():
    log_step("Installing backend dependencies from backend/requirements.txt...")
    req_file = BACKEND_DIR / "requirements.txt"
    if not req_file.exists():
        log_error(f"requirements.txt not found at {req_file}")
        sys.exit(1)

    pip_exe = str(VENV_PIP) if VENV_PIP.exists() else "pip"
    try:
        # Upgrade pip first
        subprocess.check_call([pip_exe, "install", "--upgrade", "pip", "setuptools", "wheel"], stdout=subprocess.DEVNULL)
        # Install requirements
        subprocess.check_call([pip_exe, "install", "-r", str(req_file)])
        log_success("Backend dependencies installed successfully.")
    except subprocess.CalledProcessError as e:
        log_error(f"Failed to install backend dependencies: {e}")
        log_warn("Try running manually: pip install -r backend/requirements.txt")


def setup_env_files():
    log_step("Configuring environment files (.env)...")
    env_example = PROJECT_ROOT / ".env.example"
    root_env = PROJECT_ROOT / ".env"
    backend_env = BACKEND_DIR / ".env"

    if not root_env.exists() and env_example.exists():
        shutil.copy(str(env_example), str(root_env))
        log_success("Created .env from .env.example")
    elif root_env.exists():
        log_success(".env file already exists.")

    if not backend_env.exists() and env_example.exists():
        shutil.copy(str(env_example), str(backend_env))
        log_success("Created backend/.env from .env.example")
    elif backend_env.exists():
        log_success("backend/.env already exists.")


def setup_directories():
    log_step("Ensuring required data directories exist...")
    dirs = [
        DATA_DIR,
        DATA_DIR / "temp_drive_spool",
        BACKEND_DIR / "data",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    log_success("Data directories initialized.")


def install_frontend_dependencies(has_node: bool):
    if not has_node:
        log_warn("Skipping frontend dependency installation (Node.js not installed).")
        return

    log_step("Installing frontend dependencies with npm install...")
    npm_cmd = "npm.cmd" if IS_WINDOWS else "npm"
    try:
        subprocess.check_call([npm_cmd, "install"], cwd=str(FRONTEND_DIR))
        log_success("Frontend packages installed successfully.")
    except subprocess.CalledProcessError as e:
        log_warn(f"npm install failed: {e}")
        log_warn("You can install manually later by navigating to frontend/ and running 'npm install'.")


def verify_database_and_index():
    log_step("Verifying SQLite FTS5 database and search repository...")
    python_exe = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    code = (
        "import sys; sys.path.insert(0, 'backend'); "
        "from app.repositories.sqlite_fts_repo import get_sqlite_fts_repo; "
        "repo = get_sqlite_fts_repo(); "
        "count = repo.count(); "
        "print(f'[✓] SQLite FTS5 repository initialized. Indexed documents count: {count:,}')"
    )
    try:
        subprocess.check_call([python_exe, "-c", code], cwd=str(PROJECT_ROOT))
        log_success("Search engine repository verified and ready for live queries.")
    except Exception as e:
        log_warn(f"Repository verification note: {e}")


def launch_servers():
    print(f"\n{GREEN}{BOLD}================================================================================{RESET}")
    print(f"{GREEN}{BOLD}                     LAUNCHING OM SEARCH ENGINE SERVERS                         {RESET}")
    print(f"{GREEN}{BOLD}================================================================================{RESET}\n")

    print(f"Backend API:   {BOLD}http://127.0.0.1:8000{RESET}")
    print(f"Frontend UI:   {BOLD}http://127.0.0.1:5173{RESET}")
    print(f"API Docs:      {BOLD}http://127.0.0.1:8000/docs{RESET}\n")

    python_exe = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    npm_cmd = "npm.cmd" if IS_WINDOWS else "npm"

    # Start Backend process
    backend_cmd = [python_exe, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload"]
    print(f"Starting Backend: {' '.join(backend_cmd)}")
    backend_proc = subprocess.Popen(backend_cmd, cwd=str(BACKEND_DIR))

    # Start Frontend process if npm is available
    frontend_proc = None
    if shutil.which("npm") or shutil.which("npm.cmd"):
        frontend_cmd = [npm_cmd, "run", "dev"]
        print(f"Starting Frontend: {' '.join(frontend_cmd)}")
        frontend_proc = subprocess.Popen(frontend_cmd, cwd=str(FRONTEND_DIR))

    print(f"\n{GREEN}Both servers are running! Press Ctrl+C anytime to stop.{RESET}\n")

    try:
        backend_proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down servers...")
        backend_proc.terminate()
        if frontend_proc:
            frontend_proc.terminate()
        print("Done. Goodbye!")


def main():
    print_banner()

    start_immediately = "--start" in sys.argv
    check_only = "--check" in sys.argv

    check_python_version()
    has_node = check_node()

    if check_only:
        print(f"\n{GREEN}Environment check complete.{RESET}")
        return

    setup_virtualenv()
    install_backend_dependencies()
    setup_env_files()
    setup_directories()
    install_frontend_dependencies(has_node)
    verify_database_and_index()

    print(f"\n{GREEN}{BOLD}================================================================================{RESET}")
    print(f"{GREEN}{BOLD}                       SETUP COMPLETED SUCCESSFULLY!                           {RESET}")
    print(f"{GREEN}{BOLD}================================================================================{RESET}\n")
    print("Quick Run Instructions:")
    print(f"  1. Start the entire application:")
    if IS_WINDOWS:
        print(f"     {BOLD}start.bat{RESET}   or   {BOLD}python setup.py --start{RESET}")
    else:
        print(f"     {BOLD}./start.sh{RESET}  or   {BOLD}python3 setup.py --start{RESET}")
    print(f"\n  2. Or run manually:")
    if IS_WINDOWS:
        print(f"     Backend:   {BOLD}.venv\\Scripts\\uvicorn app.main:app --reload{RESET}")
        print(f"     Frontend:  {BOLD}cd frontend && npm run dev{RESET}")
    else:
        print(f"     Backend:   {BOLD}.venv/bin/uvicorn app.main:app --reload{RESET}")
        print(f"     Frontend:  {BOLD}cd frontend && npm run dev{RESET}")

    print(f"\n  3. Cloud Continuous Ingestion (Zero Disk Storage in Google Drive):")
    if IS_WINDOWS:
        print(f"     {BOLD}.venv\\Scripts\\python scripts\\run_continuous_drive_ingestion.py{RESET}")
    else:
        print(f"     {BOLD}.venv/bin/python scripts/run_continuous_drive_ingestion.py{RESET}")
    print()

    if start_immediately:
        launch_servers()
    else:
        try:
            choice = input(f"{YELLOW}Would you like to start the application right now? [Y/n]: {RESET}").strip().lower()
            if choice in ("", "y", "yes"):
                launch_servers()
        except (KeyboardInterrupt, EOFError):
            print("\nSetup finished.")


if __name__ == "__main__":
    main()
