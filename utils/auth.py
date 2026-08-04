#!/usr/bin/env python3
"""
MNX Authentication Module (Improved)

Linux 시스템 계정 인증 모듈.
/etc/passwd, /etc/shadow 기반 인증 + PAM fallback.

개선사항:
- 프로덕션 로깅 (stdout 디버그 제거)
- PAM 인증 안정화
- sudo 세션 관리 개선
- 계정 상태 검증 (잠금, 만료 등)
- 보안 강화 (비밀번호 메모리 처리)

Author: MNX Team
Version: 2.3.3
"""

import os
import pwd
import subprocess
import time
import logging
import socket
from datetime import datetime
from typing import Tuple, Optional
from pathlib import Path

# Python 3.13에서 crypt 제거 대응: passlib 우선, 없으면 표준 crypt fallback
try:
    from passlib.hash import sha512_crypt, sha256_crypt, md5_crypt
    _PASSLIB_AVAILABLE = True
except ImportError:
    _PASSLIB_AVAILABLE = False
    try:
        import crypt as _crypt
    except ImportError:
        _crypt = None

# ═══════════════════════════════════════════════════════════════════════════════
# 상수 정의
# ═══════════════════════════════════════════════════════════════════════════════

# 로그인 정책
MAX_LOGIN_ATTEMPTS = 3
LOCKOUT_DURATION = 30  # seconds
PASSWORD_TIMEOUT = 5   # seconds

# 로그 파일
AUTH_LOG_DIR = Path("/var/log/mnx")
AUTH_LOG_FILE = AUTH_LOG_DIR / "mnx_auth.log"

# 허용된 셸 (로그인 허용)
ALLOWED_SHELLS = [
    "/bin/bash",
    "/bin/sh",
    "/bin/zsh",
    "/usr/bin/bash",
    "/usr/bin/zsh",
]

# 시스템 계정 UID 범위 (일반적으로 1000 이상이 일반 사용자)
MIN_USER_UID = 500  # 일부 시스템은 500부터


# ═══════════════════════════════════════════════════════════════════════════════
# 예외 클래스
# ═══════════════════════════════════════════════════════════════════════════════

class AuthenticationError(Exception):
    """인증 관련 기본 예외."""
    pass


class AccountLockedException(AuthenticationError):
    """계정 잠금 예외."""
    def __init__(self, remaining_seconds: int):
        self.remaining_seconds = remaining_seconds
        super().__init__(f"Account locked for {remaining_seconds} seconds")


class AccountDisabledException(AuthenticationError):
    """계정 비활성화 예외."""
    pass


class AccountExpiredException(AuthenticationError):
    """계정 만료 예외."""
    pass


class InvalidCredentialsError(AuthenticationError):
    """잘못된 자격 증명 예외."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# 로깅 설정
# ═══════════════════════════════════════════════════════════════════════════════

def _get_auth_logger() -> logging.Logger:
    """인증 로거 가져오기."""
    logger = logging.getLogger("mnx_auth")
    
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        
        try:
            AUTH_LOG_DIR.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(AUTH_LOG_FILE)
            file_handler.setLevel(logging.INFO)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except PermissionError:
            pass
    
    return logger


# ═══════════════════════════════════════════════════════════════════════════════
# 계정 정보 클래스
# ═══════════════════════════════════════════════════════════════════════════════

class AccountInfo:
    """
    시스템 계정 정보.
    
    Attributes:
        username: 사용자명
        uid: User ID
        gid: Group ID
        home: 홈 디렉토리
        shell: 로그인 셸
        is_system: 시스템 계정 여부
        is_locked: 계정 잠금 여부
        is_expired: 계정 만료 여부
    """
    
    def __init__(self, username: str):
        self.username = username
        self.uid = 0
        self.gid = 0
        self.home = ""
        self.shell = ""
        self.is_system = False
        self.is_locked = False
        self.is_expired = False
        self.password_hash = ""
        
        self._load_from_passwd()
        self._load_from_shadow()
    
    def _load_from_passwd(self):
        """passwd 파일에서 정보 로드."""
        try:
            pw_entry = pwd.getpwnam(self.username)
            self.uid = pw_entry.pw_uid
            self.gid = pw_entry.pw_gid
            self.home = pw_entry.pw_dir
            self.shell = pw_entry.pw_shell
            self.is_system = (self.uid < MIN_USER_UID) and (self.uid != 0)
        except KeyError:
            raise AccountDisabledException(f"User not found: {self.username}")
    
    def _load_from_shadow(self):
        """shadow 파일에서 정보 로드 (가능한 경우)."""
        try:
            # spwd는 Python 3.13에서 제거됨 → /etc/shadow 직접 파싱으로 대체
            shadow_entry = self._read_shadow_entry(self.username)
            if shadow_entry is None:
                return

            self.password_hash = shadow_entry.get('password', '')

            # 계정 잠금 확인
            if self.password_hash.startswith(('!', '*')):
                self.is_locked = True

            # 계정 만료 확인 (sp_expire > 0: 1970-01-01 기준 일수, -1/0: 만료 없음)
            sp_expire = shadow_entry.get('expire', -1)
            if sp_expire > 0:
                expire_date = sp_expire * 86400  # days → seconds (epoch)
                if time.time() > expire_date:
                    self.is_expired = True
        except (KeyError, PermissionError):
            # shadow 접근 불가 - PAM 인증으로 fallback
            pass

    @staticmethod
    def _read_shadow_entry(username: str) -> Optional[dict]:
        """
        /etc/shadow를 직접 파싱하여 계정 정보 반환.
        spwd 대체 (Python 3.13 호환).
        """
        try:
            with open('/etc/shadow', 'r') as f:
                for line in f:
                    parts = line.strip().split(':')
                    if len(parts) >= 8 and parts[0] == username:
                        try:
                            expire = int(parts[7]) if parts[7] else -1
                        except ValueError:
                            expire = -1
                        return {
                            'password': parts[1],
                            'expire': expire,
                        }
        except (PermissionError, FileNotFoundError):
            pass
        return None
    
    def can_login(self) -> Tuple[bool, str]:
        """
        로그인 가능 여부 확인.
        
        Returns:
            (가능여부, 사유)
        """
        if self.is_locked:
            return False, "Account is locked"
        
        if self.is_expired:
            return False, "Account has expired"
        
        if self.shell and self.shell not in ALLOWED_SHELLS:
            if self.shell in ["/sbin/nologin", "/usr/sbin/nologin", "/bin/false"]:
                return False, "Login disabled for this account"
        
        return True, ""


# ═══════════════════════════════════════════════════════════════════════════════
# 인증 관리자
# ═══════════════════════════════════════════════════════════════════════════════

class AuthenticationManager:
    """
    Linux 시스템 계정 인증 관리자.
    
    인증 순서:
    1. 계정 상태 확인 (passwd, shadow)
    2. /etc/shadow 직접 인증 (root 권한 필요)
    3. PAM 인증 fallback (su 명령 사용)
    
    보안 기능:
    - 로그인 시도 제한
    - 계정 잠금
    - 인증 이벤트 로깅
    """
    
    def __init__(self):
        self.failed_attempts = 0
        self.max_attempts = MAX_LOGIN_ATTEMPTS
        self.locked_until = 0
        self.lockout_duration = LOCKOUT_DURATION
        
        self._logger = _get_auth_logger()
        self._hostname = socket.gethostname()
    
    def authenticate(self, username: str, password: str) -> Tuple[bool, Optional[str]]:
        """
        시스템 사용자 인증.
        
        Args:
            username: 사용자명
            password: 비밀번호
        
        Returns:
            (성공여부, 에러메시지)
        
        Raises:
            AccountLockedException: 계정 잠금 시
        """
        # 1. 잠금 확인
        if time.time() < self.locked_until:
            remaining = int(self.locked_until - time.time())
            raise AccountLockedException(remaining)
        
        # 2. 입력 검증
        if not username or not password:
            return False, "Username and password required"
        
        # 3. 계정 정보 확인
        try:
            account = AccountInfo(username)
        except AccountDisabledException as e:
            self._log_auth_event(username, False, str(e))
            return False, "Invalid username or password"
        
        # 4. 로그인 가능 여부 확인
        can_login, reason = account.can_login()
        if not can_login:
            self._log_auth_event(username, False, reason)
            return False, reason
        
        # 5. 비밀번호 인증
        auth_success = False
        auth_method = ""
        
        # 방법 1: shadow 직접 인증 (root 권한)
        if account.password_hash and not account.password_hash.startswith(('!', '*')):
            auth_success = self._verify_shadow_password(account.password_hash, password)
            auth_method = "shadow"
        
        # 방법 2: PAM 인증 (fallback)
        # ★ 보안: root로 실행 중이면 `su`가 패스워드 검증 없이 통과하여
        #    인증 우회가 발생한다. TUI는 root로 구동되므로 non-root일 때만 허용한다.
        if not auth_success and os.geteuid() != 0:
            auth_success = self._verify_with_pam(username, password)
            auth_method = "pam"
        
        # 6. 결과 처리
        if auth_success:
            self._on_auth_success(username, password)
            self._log_auth_event(username, True, f"method={auth_method}")
            return True, None
        else:
            return self._on_auth_failure(username)
    
    def _verify_shadow_password(self, stored_hash: str, password: str) -> bool:
        """
        /etc/shadow 해시로 비밀번호 검증.
        passlib 우선 사용, 없으면 표준 crypt fallback (Python 3.12 이하).

        Args:
            stored_hash: 저장된 비밀번호 해시
            password: 입력된 비밀번호

        Returns:
            검증 성공 여부
        """
        try:
            if not stored_hash.startswith('$'):
                return False

            if _PASSLIB_AVAILABLE:
                if stored_hash.startswith('$6$'):
                    return sha512_crypt.verify(password, stored_hash)
                elif stored_hash.startswith('$5$'):
                    return sha256_crypt.verify(password, stored_hash)
                elif stored_hash.startswith('$1$'):
                    return md5_crypt.verify(password, stored_hash)
                return False

            if _crypt is not None:
                return _crypt.crypt(password, stored_hash) == stored_hash

            return False
        except Exception:
            return False
    
    def _verify_with_pam(self, username: str, password: str) -> bool:
        """
        PAM 인증 (su 명령 사용).
        
        Args:
            username: 사용자명
            password: 비밀번호
        
        Returns:
            인증 성공 여부
        """
        try:
            process = subprocess.Popen(
                ['su', '-', username, '-c', 'echo AUTH_SUCCESS'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={'LC_ALL': 'C'}
            )
            
            stdout, stderr = process.communicate(
                input=password + '\n',
                timeout=PASSWORD_TIMEOUT
            )
            
            return 'AUTH_SUCCESS' in stdout
        
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except Exception:
                pass
            return False
        except Exception:
            return False
    
    def _on_auth_success(self, username: str, password: str):
        """인증 성공 처리."""
        self.failed_attempts = 0
        self.locked_until = 0
        
        # sudo 세션 사전 획득 (선택적)
        self._establish_sudo_session(password)
    
    def _on_auth_failure(self, username: str) -> Tuple[bool, str]:
        """
        인증 실패 처리.
        
        Returns:
            (False, 에러메시지)
        """
        self.failed_attempts += 1
        remaining_attempts = self.max_attempts - self.failed_attempts
        
        if self.failed_attempts >= self.max_attempts:
            self.locked_until = time.time() + self.lockout_duration
            self._log_auth_event(username, False, "Too many failures - account locked")
            return False, f"Too many failures. Locked for {self.lockout_duration}s"
        else:
            self._log_auth_event(username, False, f"Invalid credentials ({remaining_attempts} remaining)")
            return False, f"Invalid username or password ({remaining_attempts} attempts remaining)"
    
    def _establish_sudo_session(self, password: str):
        """sudo 세션 사전 획득 (선택적)."""
        process = None
        try:
            process = subprocess.Popen(
                ['sudo', '-S', '-v'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            process.communicate(
                input=password + '\n',
                timeout=PASSWORD_TIMEOUT
            )
        except subprocess.TimeoutExpired:
            if process:
                process.kill()
                process.wait()  # 좀비 프로세스 방지
        except Exception:
            pass
    
    def _log_auth_event(self, username: str, success: bool, detail: str = ""):
        """
        인증 이벤트 로깅.
        
        Args:
            username: 사용자명
            success: 성공 여부
            detail: 상세 정보
        """
        status = "SUCCESS" if success else "FAILED"
        
        try:
            remote_host = os.environ.get('SSH_CLIENT', '').split()[0] if 'SSH_CLIENT' in os.environ else 'local'
        except (IndexError, AttributeError):
            remote_host = 'local'
        
        log_message = f"AUTH {status}: user={username} host={self._hostname} remote={remote_host}"
        if detail:
            log_message += f" ({detail})"
        
        if success:
            self._logger.info(log_message)
        else:
            self._logger.warning(log_message)
    
    def get_lockout_remaining(self) -> int:
        """
        잠금 남은 시간.
        
        Returns:
            남은 초 (0이면 잠금 없음)
        """
        if time.time() < self.locked_until:
            return int(self.locked_until - time.time())
        return 0
    
    def reset(self):
        """인증 상태 초기화."""
        self.failed_attempts = 0
        self.locked_until = 0
    
    def get_status(self) -> dict:
        """
        인증 상태 정보.
        
        Returns:
            상태 딕셔너리
        """
        return {
            'failed_attempts': self.failed_attempts,
            'max_attempts': self.max_attempts,
            'is_locked': time.time() < self.locked_until,
            'lockout_remaining': self.get_lockout_remaining(),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 유틸리티 함수
# ═══════════════════════════════════════════════════════════════════════════════

def get_system_users() -> list:
    """
    로그인 가능한 시스템 사용자 목록.
    
    Returns:
        사용자명 리스트
    """
    users = []
    
    try:
        for pw_entry in pwd.getpwall():
            # 일반 사용자 (UID >= 1000) 또는 root
            if pw_entry.pw_uid >= 1000 or pw_entry.pw_uid == 0:
                # 로그인 가능한 셸 확인
                if pw_entry.pw_shell in ALLOWED_SHELLS:
                    users.append(pw_entry.pw_name)
    except Exception:
        pass
    
    return sorted(users)


def check_user_exists(username: str) -> bool:
    """
    사용자 존재 여부 확인.
    
    Args:
        username: 사용자명
    
    Returns:
        존재 여부
    """
    try:
        pwd.getpwnam(username)
        return True
    except KeyError:
        return False


def get_user_info(username: str) -> Optional[dict]:
    """
    사용자 정보 조회.
    
    Args:
        username: 사용자명
    
    Returns:
        사용자 정보 딕셔너리 또는 None
    """
    try:
        account = AccountInfo(username)
        return {
            'username': account.username,
            'uid': account.uid,
            'gid': account.gid,
            'home': account.home,
            'shell': account.shell,
            'is_system': account.is_system,
            'is_locked': account.is_locked,
            'is_expired': account.is_expired,
        }
    except AccountDisabledException:
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# 테스트
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import getpass
    
    print("MNX Authentication Module Test")
    print("=" * 40)
    
    # 시스템 사용자 목록
    print("\nAvailable users:")
    for user in get_system_users():
        print(f"  - {user}")
    
    print()
    
    # 인증 테스트
    auth = AuthenticationManager()
    
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")
    
    try:
        success, error = auth.authenticate(username, password)
        
        if success:
            print(f"\n✓ Authentication successful: {username}")
        else:
            print(f"\n✗ Authentication failed: {error}")
    
    except AccountLockedException as e:
        print(f"\n✗ Account locked: {e.remaining_seconds}s remaining")