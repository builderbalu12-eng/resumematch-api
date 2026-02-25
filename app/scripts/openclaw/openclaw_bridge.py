import subprocess
import os
from pathlib import Path
from fastapi import HTTPException
from app.config import settings
import time


class OpenClawBridge:
    BASE_DIR = Path.home() / "openclaw_data"
    LOG_DIR = Path.home() / "openclaw_logs"

    @staticmethod
    def ensure_profile_dirs():
        """Ensure base and log directories exist and set OPENCLAW_HOME."""
        OpenClawBridge.BASE_DIR.mkdir(parents=True, exist_ok=True)
        OpenClawBridge.LOG_DIR.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("OPENCLAW_HOME", str(OpenClawBridge.BASE_DIR))

    @staticmethod
    def run_command(cmd: list[str]) -> str:
        """Run a CLI command and return stdout, raise HTTPException on failure."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                env=os.environ.copy()
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() or e.stdout.strip() or str(e)
            raise HTTPException(500, f"OpenClaw command failed: {error_msg}")

    @staticmethod
    def is_gateway_running(port: int) -> bool:
        """Check if any process is listening on the gateway port."""
        result = subprocess.run(
            ["lsof", "-i", f":{port}"],
            capture_output=True,
            text=True
        )
        return "openclaw" in result.stdout.lower()

    @staticmethod
    def ensure_gateway_config(profile: str):
        """
        Ensure required config values exist for this profile.
        Safe to call multiple times.
        """
        # Set local mode
        OpenClawBridge.run_command([
            "openclaw",
            "--profile", profile,
            "config", "set",
            "gateway.mode", "local"
        ])

        # Set token
        OpenClawBridge.run_command([
            "openclaw",
            "--profile", profile,
            "config", "set",
            "gateway.auth.token",
            settings.openclaw_gateway_token
        ])

    @staticmethod
    def start_gateway(profile: str, port: int):
        """Start OpenClaw gateway for a profile on a given port."""
        OpenClawBridge.ensure_profile_dirs()
        OpenClawBridge.ensure_gateway_config(profile)

        if OpenClawBridge.is_gateway_running(port):
            print(f"[DEBUG] Gateway already running on port {port}")
            return

        log_path = OpenClawBridge.LOG_DIR / f"openclaw_{profile}.log"

        cmd = [
            "openclaw",
            "--profile", profile,
            "gateway",
            "--port", str(port),
            "--token", settings.openclaw_gateway_token
        ]

        with open(log_path, "a") as log_file:
            subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=log_file,
                env=os.environ.copy()
            )

        # Optional wait for startup
        for _ in range(10):
            time.sleep(1)
            if OpenClawBridge.is_gateway_running(port):
                break

        print(f"[DEBUG] Gateway started → {profile} :{port} (log: {log_path})")

    @staticmethod
    def trigger_status(profile: str) -> str:
        """Get current OpenClaw channel status for a profile."""
        return OpenClawBridge.run_command([
            "openclaw",
            "--profile", profile,
            "channels", "status"
        ])

    @staticmethod
    def send_message(profile: str, phone: str, text: str) -> str:
        """Send WhatsApp message through OpenClaw."""
        return OpenClawBridge.run_command([
            "openclaw",
            "--profile", profile,
            "send", "whatsapp", phone, text
        ])

    @staticmethod
    def get_conversation(profile: str, phone: str) -> str:
        """Get WhatsApp conversation history for a phone number."""
        return OpenClawBridge.run_command([
            "openclaw",
            "--profile", profile,
            "get", "whatsapp", phone
        ])