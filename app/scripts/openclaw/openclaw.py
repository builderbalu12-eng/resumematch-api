import os
import subprocess
import argparse
from pathlib import Path
from app.config import settings
import time  # ← ADD THIS LINE

def run_command(cmd, shell=False, cwd=None, check=True):
    result = subprocess.run(cmd, shell=shell, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()

def install_openclaw():
    print("Installing OpenClaw...")
    run_command("curl -fsSL https://openclaw.ai/install.sh | bash", shell=True)

def configure_gemini():
    api_key = os.getenv("GEMINI_API_KEY") or settings.gemini_api_key
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment or config")
    print("Gemini API key found (using env variable).")
    # OpenClaw uses env var directly — no need for config command

def connect_whatsapp():
    print("Starting WhatsApp connection. Scan QR code in terminal/browser.")
    subprocess.Popen(["openclaw", "connect", "whatsapp"])

def start_background():
    log_file = Path("openclaw.log").absolute()
    print(f"Starting OpenClaw in background. Logs → {log_file}")
    subprocess.Popen(
        f"nohup openclaw run > {log_file} 2>&1 &",
        shell=True
    )

def main():
    parser = argparse.ArgumentParser(description="Setup OpenClaw automatically")
    parser.add_argument("--reinstall", action="store_true")
    args = parser.parse_args()

    if args.reinstall or not Path("/usr/local/bin/openclaw").exists():
        install_openclaw()
    else:
        print("OpenClaw already installed.")

    configure_gemini()
    connect_whatsapp()
    time.sleep(70)  # time to scan QR
    start_background()

    print("\nSetup complete!")
    print("1. WhatsApp bot ready (scan QR if not done)")
    print("2. Test: Send 'hello' to bot on WhatsApp")
    print("3. Backend send: POST /api/openclaw/send")

if __name__ == "__main__":
    main()