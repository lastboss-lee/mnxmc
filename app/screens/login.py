"""
Login Screen - Secure Authentication

MNX Management Console Login Screen.
Shadow-only authentication (no su fallback when running as root).

Author: MNX Team
Version: 2.4.0
"""

from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal, Center
from textual.screen import Screen
from textual.widgets import Static, Input, Button
from textual.binding import Binding

import socket
import subprocess
import os
import time
from datetime import datetime

try:
    import crypt
    _CRYPT_AVAILABLE = True
except ImportError:
    _CRYPT_AVAILABLE = False


# ===========================================================================
# Authentication Manager (SECURE)
# ===========================================================================

class AccountLockedException(Exception):
    def __init__(self, remaining_seconds):
        self.remaining_seconds = remaining_seconds


class AuthenticationManager:
    """
    Secure Linux authentication.
    
    IMPORTANT: When running as root, 'su' command doesn't require password!
    So we MUST use shadow file authentication only.
    """
    
    def __init__(self):
        self.failed_attempts = 0
        self.max_attempts = 3
        self.locked_until = 0
        self.lockout_duration = 30
        self._is_root = os.geteuid() == 0
    
    def authenticate(self, username, password):
        """
        Authenticate user against Linux system.
        
        Returns: (success: bool, error_message: str or None)
        Raises: AccountLockedException if too many failures
        """
        # Check lockout
        if time.time() < self.locked_until:
            remaining = int(self.locked_until - time.time())
            raise AccountLockedException(remaining)
        
        # Validate input
        if not username or not password:
            return False, "Username and password required"
        
        username = username.strip()
        
        # Check user exists
        try:
            import pwd
            pwd.getpwnam(username)
        except KeyError:
            return self._handle_failure()
        
        # SECURE: Use shadow authentication (requires root)
        auth_ok = self._verify_shadow(username, password)
        
        # ONLY use su fallback if NOT running as root
        # (When running as root, su doesn't check password!)
        if not auth_ok and not self._is_root:
            auth_ok = self._verify_with_su(username, password)
        
        if auth_ok:
            self.failed_attempts = 0
            self.locked_until = 0
            return True, None
        else:
            return self._handle_failure()
    
    def _verify_shadow(self, username, password):
        """
        Verify password against /etc/shadow.
        
        This is the SECURE method - actually checks the password hash.
        Requires root privileges to read /etc/shadow.
        """
        try:
            import spwd
            shadow = spwd.getspnam(username)
            stored_hash = shadow.sp_pwdp
            
            # Check for locked/disabled accounts
            if not stored_hash:
                return False
            if stored_hash in ('*', '!', '!!', '*LK*'):
                return False
            if stored_hash.startswith('!'):
                return False
            
            # Must be a valid hash format ($id$salt$hash)
            if not stored_hash.startswith('$'):
                return False
            
            # Compute hash and compare
            if not _CRYPT_AVAILABLE:
                return False
            computed = crypt.crypt(password, stored_hash)

            # Secure comparison
            if len(computed) != len(stored_hash):
                return False

            result = 0
            for a, b in zip(computed, stored_hash):
                result |= ord(a) ^ ord(b)

            return result == 0

        except ImportError:
            # spwd not available
            return False
        except KeyError:
            # User not in shadow file
            return False
        except PermissionError:
            # Can't read shadow file (not root)
            return False
        except Exception:
            return False
    
    def _verify_with_su(self, username, password):
        """
        Verify via su command (PAM).
        
        WARNING: This does NOT work when running as root!
        Root can su to any user without password.
        Only use this as fallback when NOT running as root.
        """
        if self._is_root:
            # NEVER use su when running as root - it bypasses password check!
            return False
        
        try:
            proc = subprocess.Popen(
                ['su', '-', username, '-c', 'echo __AUTH_OK__'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={'LC_ALL': 'C', 'PATH': '/usr/bin:/bin', 'TERM': 'dumb'}
            )
            stdout, _ = proc.communicate(input=password + '\n', timeout=10)
            return '__AUTH_OK__' in stdout
        except Exception:
            return False
    
    def _handle_failure(self):
        """Handle authentication failure."""
        self.failed_attempts += 1
        remaining = self.max_attempts - self.failed_attempts
        
        if self.failed_attempts >= self.max_attempts:
            self.locked_until = time.time() + self.lockout_duration
            self.failed_attempts = 0
            return False, f"Too many failures. Locked for {self.lockout_duration}s"
        
        return False, f"Invalid username or password ({remaining} attempts left)"


# ===========================================================================
# Login Screen
# ===========================================================================

class LoginScreen(Screen):
    """MNX Login Screen."""
    
    CSS = """
    LoginScreen {
        align: center middle;
        background: #0c0c0c;
    }

    #main-box {
        width: 62;
        height: auto;
        align: center middle;
        background: #141414;
        padding: 2 3;
    }

    #logo {
        width: 100%;
        color: #5fd7d7;
        text-align: center;
    }

    #version {
        width: 100%;
        color: #5fd7d7;
        text-align: center;
        margin-top: 1;
    }

    #company {
        width: 100%;
        color: #d7af00;
        text-align: center;
        margin-bottom: 2;
    }

    .row {
        width: 100%;
        height: 2;
        layout: horizontal;
        align: center middle;
        margin: 0 0 1 0;
    }

    .lbl {
        width: 12;
        height: 2;
        color: #5fd7d7;
        content-align: right middle;
        padding-right: 1;
    }

    .inp {
        width: 36;
        height: 2;
        background: #0c0c0c;
        color: white;
        border-top: none;
        border-right: none;
        border-bottom: solid #5fd7d7;
        border-left: none;
    }

    .inp:focus {
        border-top: none;
        border-right: none;
        border-bottom: solid #87ffff;
        border-left: none;
    }

    #btn-login {
        width: 12;
        height: 1;
        margin-top: 2;
        background: #141414;
        color: #5fd7d7;
        border: none;
        text-style: bold;
    }

    #btn-login:hover {
        background: #141414;
        color: #87ffff;
        border: none;
    }

    #btn-login:focus {
        background: #141414;
        color: #87ffff;
        border: none;
    }

    #status {
        width: 100%;
        height: 2;
        text-align: center;
        margin-top: 1;
        color: #aaaaaa;
    }

    #footer {
        width: 100%;
        height: 1;
        text-align: center;
        color: #444444;
        margin-top: 2;
    }
    """
    
    BINDINGS = [
        # Ctrl+Q, Ctrl+P 무시 (아무 동작 안함)
        Binding("ctrl+q", "noop", show=False),
        Binding("ctrl+p", "noop", show=False),
    ]
    
    def action_noop(self) -> None:
        """아무 동작도 하지 않음."""
        pass
    
    def __init__(self):
        super().__init__()
        self.auth = AuthenticationManager()
        self._cached_ip = self._get_local_ip()

    def _get_local_ip(self) -> str:
        """로컬 IP를 한 번만 조회 (startup 시 캐싱)."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
    
    def compose(self):
        with Center():
            with Container(id="main-box"):
                yield Static(self._logo(), id="logo")
                yield Static("Management Console v2.4.0", id="version")
                yield Static("SANDSLAB Inc.  NDR Solution", id="company")
                
                with Horizontal(classes="row"):
                    yield Static("Username:", classes="lbl")
                    yield Input(id="username", placeholder="Enter username", classes="inp")
                
                with Horizontal(classes="row"):
                    yield Static("Password:", classes="lbl")
                    yield Input(id="password", placeholder="Enter password", password=True, classes="inp")
                
                with Center():
                    yield Button("< LOGIN >", id="btn-login")
                
                yield Static("", id="status")
                yield Static(self._footer(), id="footer")
    
    def _logo(self):
        """MNX 로고."""
        return (
            "███╗   ███╗███╗   ██╗██╗  ██╗\n"
            "████╗ ████║████╗  ██║╚██╗██╔╝\n"
            "██╔████╔██║██╔██╗ ██║ ╚███╔╝ \n"
            "██║╚██╔╝██║██║╚██╗██║ ██╔██╗ \n"
            "██║ ╚═╝ ██║██║ ╚████║██╔╝ ██╗\n"
            "╚═╝     ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝"
        )
    
    def _footer(self):
        try:
            with open('/proc/uptime') as f:
                up = float(f.read().split()[0])
            days = int(up // 86400)
            hours = int((up % 86400) // 3600)
            mins = int((up % 3600) // 60)
            uptime = f"{days}d {hours}h {mins}m" if days else f"{hours}h {mins}m"
        except Exception:
            uptime = "N/A"

        now = datetime.now().strftime("%H:%M:%S")
        return f"IP: {self._cached_ip}    Uptime: {uptime}    Time: {now}"
    
    def on_mount(self):
        self.set_timer(0.1, lambda: self.query_one("#username").focus())
        self._footer_handle = self.set_interval(1.0, self._update_footer)

    def on_unmount(self):
        if hasattr(self, '_footer_handle') and self._footer_handle:
            self._footer_handle.stop()
            self._footer_handle = None
    
    def _update_footer(self):
        try:
            self.query_one("#footer").update(self._footer())
        except Exception:
            pass
    
    def _set_status(self, msg, color="white"):
        try:
            self.query_one("#status").update(f"[{color}]{msg}[/]")
        except Exception:
            pass
    
    def on_input_submitted(self, event):
        if event.input.id == "username":
            self.query_one("#password").focus()
        elif event.input.id == "password":
            self._login()
    
    def on_button_pressed(self, event):
        if event.button.id == "btn-login":
            self._login()
    
    def _login(self):
        username = self.query_one("#username").value.strip()
        password = self.query_one("#password").value
        
        if not username:
            self._set_status("Enter username", "yellow")
            self.query_one("#username").focus()
            return
        
        if not password:
            self._set_status("Enter password", "yellow")
            self.query_one("#password").focus()
            return
        
        self._set_status("Authenticating...", "cyan")
        
        try:
            ok, err = self.auth.authenticate(username, password)
            
            if ok:
                self._set_status("Login successful!", "green")
                self.app.authenticated_user = username
                self.set_timer(0.5, self._goto_dashboard)
            else:
                self._set_status(err or "Login failed", "red")
                self.query_one("#password").value = ""
                self.query_one("#password").focus()
        
        except AccountLockedException as e:
            self._set_status(f"Locked. Wait {e.remaining_seconds}s", "red")
            self.query_one("#password").value = ""
    
    def _goto_dashboard(self):
        try:
            from app.screens.dashboard import DashboardScreen
            self.app.switch_screen(DashboardScreen())
        except Exception as e:
            self._set_status(f"Dashboard error: {e}", "red")


# ===========================================================================
# Test
# ===========================================================================

if __name__ == "__main__":
    # Quick authentication test
    print("=== Authentication Test ===")
    print(f"Running as root: {os.geteuid() == 0}")
    
    auth = AuthenticationManager()
    
    # Test with wrong password
    print("\nTest 1: Wrong password for 'root'")
    result = auth.authenticate('root', 'wrongpassword123')
    print(f"Result: {result}")
    print(f"Expected: (False, 'Invalid username or password (2 attempts left)')")
    
    # Test with wrong password again
    print("\nTest 2: Wrong password again")
    result = auth.authenticate('root', 'anotherWrongPwd')
    print(f"Result: {result}")