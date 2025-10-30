import sys
import os
import time
import subprocess
import shutil
import requests
from typing import Tuple, Optional


class UpdateChecker:
    def __init__(self, package_name: str, current_version: str) -> None:
        self.package_name = package_name
        self.current_version = current_version
        self.check_file = os.path.expanduser("~/.config/alibuild/last-update-check")

    def _detect_package_manager(self) -> Optional[str]:
        """Detect which package manager was used to install alibuild

        Detection is based purely on WHERE the module is installed.
        We check the path of alibuild_helpers to determine the installation method.
        """
        try:
            # Get the installation path of this module
            import alibuild_helpers
            install_path = os.path.realpath(alibuild_helpers.__file__)

            # Check for Homebrew installation. Similar logic as used by GitHub CLI
            # https://github.com/cli/cli/blob/152d328db80d4d4d7318c7700b6644ee827618a7/internal/ghcmd/cmd.go#L233
            brew_exe = shutil.which('brew')
            if brew_exe:
                try:
                    brew_prefix = subprocess.check_output([brew_exe, '--prefix'], 
                                                         text=True, 
                                                         stderr=subprocess.DEVNULL).strip()
                    brew_lib_prefix = os.path.join(brew_prefix, 'lib') + os.sep
                    if install_path.startswith(brew_lib_prefix):
                        return 'brew'
                except (subprocess.CalledProcessError, FileNotFoundError):
                    pass

            # Check for system package managers (apt/yum)
            # dist-packages is the key indicator for system package managers
            if 'dist-packages' in install_path:
                if shutil.which('apt') or shutil.which('apt-get'):
                    return 'apt'
                elif shutil.which('yum') or shutil.which('dnf'):
                    return 'yum'
                # If we have dist-packages but can't identify the PM, still return pip as fallback
                return 'pip'

            # Check for pip installation
            # Currently redundant as we default to pip anyway, but kept for clarity
            if 'site-packages' in install_path or '.local' in install_path:
                return 'pip'

        except Exception:
            pass

        return None

    def _get_upgrade_command(self, package_manager: Optional[str]) -> str:
        """Get the appropriate upgrade command based on package manager"""
        commands = {
            'brew': 'brew upgrade alibuild',
            'pip': 'pip install --upgrade alibuild',
            'apt': 'sudo apt update && sudo apt install --only-upgrade alibuild',
            'yum': 'sudo yum update alibuild',
        }

        if package_manager and package_manager in commands:
            return commands[package_manager]

        # pip is a safe default
        return 'pip install --upgrade alibuild'

    def _parse_version(self, version_string: str) -> Tuple[int, ...]:
        """Simple version parsing - converts version string to tuple of integers"""
        try:
            # Some versions look like "1.2.3", "1.2.3.dev1", "1.2.3a1", etc.
            parts: list[int] = []
            for part in version_string.split('.'):
                # Extract leading digits
                numeric: str = ''
                for char in part:
                    if char.isdigit():
                        numeric += char
                    else:
                        break
                if numeric:
                    parts.append(int(numeric))
            return tuple(parts) if parts else (0,)
        except Exception:
            return (0,)

    def _should_check_for_updates(self) -> bool:
        """Check if we should perform an update check (once per day)"""
        if not os.path.exists(self.check_file):
            return True

        try:
            with open(self.check_file, 'r') as f:
                last_check = float(f.read().strip())

            # Only check once every 24 hours
            return (time.time() - last_check) > 24 * 60 * 60
        except Exception:
            return True

    def _update_check_timestamp(self) -> None:
        """Update the last check timestamp"""
        try:
            os.makedirs(os.path.dirname(self.check_file), exist_ok=True)
            with open(self.check_file, 'w') as f:
                f.write(str(time.time()))
        except Exception:
            pass

    def check_for_updates(self) -> bool:
        """Check PyPI and notify if update available (max once per day, only in TTY)

        Skip if:
        1. ALIBUILD_NO_UPDATE_CHECK env var is set
        2. Not running in a TTY (piped output, etc.)
        3. Already checked within the last 24 hours
        """

        if "ALIBUILD_NO_UPDATE_CHECK" in os.environ:
            return False

        if not sys.stdout.isatty():
            return False

        if not self._should_check_for_updates():
            return False

        try:
            response = requests.get(f"https://pypi.org/pypi/{self.package_name}/json", timeout=2)
            latest: str = response.json()["info"]["version"]

            current_parsed: Tuple[int, ...] = self._parse_version(self.current_version)
            latest_parsed: Tuple[int, ...] = self._parse_version(latest)

            # Update timestamp after successful check
            self._update_check_timestamp()

            if latest_parsed > current_parsed:
                arrow = "\033[1;34m==>\033[m"
                bold = "\033[1m"
                green = "\033[1;32m"
                reset = "\033[m"

                print(f"\n{arrow} {bold}Update available:{reset} {self.current_version} → {green}{latest}{reset}")

                package_manager = self._detect_package_manager()
                upgrade_cmd = self._get_upgrade_command(package_manager)
                print(f"{arrow} {bold}Run:{reset} {upgrade_cmd}")

                print(f"{arrow} {bold}What's new:{reset} https://github.com/alisw/alibuild/releases/tag/v{latest}")
                print(f"{arrow} {bold}More info:{reset} https://alice-doc.github.io/alice-analysis-tutorial/building/custom.html")
                return True
        except Exception:
              pass
        return False


# Usage
if __name__ == "__main__":
    try:
        from alibuild_helpers import __version__
        CURRENT_VERSION = __version__ or "0.0.0"
    except ImportError:
        CURRENT_VERSION = "0.0.0"

    PACKAGE_NAME = "alibuild"
    UpdateChecker(PACKAGE_NAME, CURRENT_VERSION).check_for_updates()
