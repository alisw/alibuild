import sys
import os
import time
import requests
from typing import Tuple

class UpdateChecker:
    def __init__(self, package_name: str, current_version: str) -> None:
        self.package_name = package_name
        self.current_version = current_version
        self.check_file = os.path.expanduser("~/.config/alibuild/last-update-check")
    
    def _parse_version(self, version_string: str) -> Tuple[int, ...]:
        """Simple version parsing - converts version string to tuple of integers"""
        try:
            # Handle versions like "1.2.3", "1.2.3.dev1", "1.2.3a1", etc.
            # Extract only the numeric parts before any non-numeric suffix
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
            
            # Check if 24 hours (86400 seconds) have passed
            return (time.time() - last_check) > 86400
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
        2. Not running in a TTY (CI/CD, piped output, etc.)
        3. Already checked within the last 24 hours
        """
        
        # Skip if disabled via environment variable
        if "ALIBUILD_NO_UPDATE_CHECK" in os.environ:
            return False
        
        # Only check for updates when running in an interactive terminal
        if not sys.stdout.isatty():
            return False
        
        # Skip if we checked recently
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
                print(f"\nUpdate available: {self.current_version} → {latest}")
                print("You can find more information at: https://alice-doc.github.io/alice-analysis-tutorial/building/custom.html")
                return True
        except Exception:
              pass
        return False


# Usage
if __name__ == "__main__":
    from alibuild_helpers import __version__
    
    PACKAGE_NAME = "alibuild"
    CURRENT_VERSION = __version__ or "0.0.0"
    
    UpdateChecker(PACKAGE_NAME, CURRENT_VERSION).check_for_updates()
