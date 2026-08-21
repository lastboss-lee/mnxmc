#!/bin/bash
# =============================================================================
# build_deb.sh  v2.4
# 역할: /mnxmc 에 소스 + packages/ 를 그대로 풀어주는 아카이브 deb
# 설치 후: sudo bash /mnxmc/packages/install_packages.sh
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC_DIR="$(dirname "$SCRIPT_DIR")"
VERSION="${1:-2.2.0}"
PKG_NAME="mnxmc-${VERSION}"
BUILD_DIR="/tmp/mnxmc_build_$$"
# 출력 위치는 /data (대용량 디렉토리)에 저장. 필요 시 OUT_DIR 환경변수로 override.
OUT_DIR="${OUT_DIR:-/data}"
mkdir -p "$OUT_DIR"
OUT_DEB="${OUT_DIR}/${PKG_NAME}.deb"

GREEN="\033[0;32m"; YELLOW="\033[1;33m"; RED="\033[0;31m"; NC="\033[0m"
ok()   { echo -e "  ${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC}  $*"; }
fail() { echo -e "  ${RED}[FAIL]${NC}  $*"; exit 1; }

echo ""
echo "============================================================"
echo "  MNXMC 아카이브 deb 빌더  v${VERSION}"
echo "  출력 : $OUT_DEB"
echo "============================================================"
echo ""

command -v dpkg-deb &>/dev/null || fail "dpkg-deb 없음"
command -v rsync    &>/dev/null || fail "rsync 없음"

PKG_DIR="$BUILD_DIR/$PKG_NAME"
MNXMC="$PKG_DIR/mnxmc"

mkdir -p "$MNXMC"
mkdir -p "$PKG_DIR/DEBIAN"

# ── [1/3] 앱 소스 복사 ───────────────────────────────────────────
echo "[1/3] 앱 소스 복사 중..."

rsync -a --exclude='__pycache__' --exclude='*.pyc' \
    "$SRC_DIR/main.py" \
    "$SRC_DIR/main-login.py" \
    "$SRC_DIR/clean_cache.sh" \
    "$SRC_DIR/readme_install_mnxmc.txt" \
    "$MNXMC/"

for dir in app modules network_management utils test-tool infra_audit; do
    rsync -a \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='*.md' \
        --exclude='.claude/' \
        "$SRC_DIR/$dir/" "$MNXMC/$dir/"
done

ok "Python 파일: $(find "$MNXMC" -name '*.py' | wc -l)개"

# ── [2/3] packages/ 폴더 전체 복사 ──────────────────────────────
echo "[2/3] packages/ 폴더 복사 중..."

rsync -a \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.md' \
    --exclude='.claude/' \
    --exclude='lock' \
    --exclude='partial' \
    --exclude='*.swp' \
    --exclude='*.log' \
    "$SCRIPT_DIR/" "$MNXMC/packages/"

ok "packages/ 복사 완료"
# apt 세트는 OS 별로 분리되어 있다 (install_packages.sh 가 VERSION_CODENAME 으로 선택).
# deb 하나에 두 세트를 모두 담아 22.04/26.04 어느 쪽에서도 같은 산출물로 설치한다.
for suite_dir in "$MNXMC/packages/apt"/*/; do
    [ -d "$suite_dir" ] || continue
    ok "  apt/$(basename "$suite_dir") : $(ls "$suite_dir"*.deb 2>/dev/null | wc -l)개"
done
ok "  pip  : $(ls "$MNXMC/packages/pip/"*.whl 2>/dev/null | wc -l)개"
ok "  perccli: $(ls "$MNXMC/packages/perccli/"perccli* 2>/dev/null | wc -l)개 바이너리"

# ── [3/3] 권한 설정 (755/644) ────────────────────────────────────
echo "[3/3] 권한 설정 중 (디렉토리 755, 파일 644, 실행파일 755)..."

# 디렉토리: 755
find "$PKG_DIR" -type d -exec chmod 755 {} \;

# 일반 파일: 644
find "$PKG_DIR" -type f -exec chmod 644 {} \;

# 실행 파일: 755
find "$PKG_DIR" -type f \( \
    -name "*.py" \
    -o -name "*.sh" \
    -o -name "perccli" \
    -o -name "perccli64" \
    -o -name "storcli64" \
\) -exec chmod 755 {} \;

ok "권한 설정 완료"

# ── DEBIAN/control ────────────────────────────────────────────────
SIZE_KB=$(du -sk "$PKG_DIR" --exclude="$PKG_DIR/DEBIAN" 2>/dev/null | awk '{print $1}')

cat > "$PKG_DIR/DEBIAN/control" << EOF
Package: mnxmc
Version: $VERSION
Architecture: amd64
Maintainer: SANDS LAB Inc. <admin@sandslab.kr>
Depends: bash
Description: MNX Management Console Archive
 Extracts MNXMC source and offline packages to /mnxmc.
 After install, run: sudo bash /mnxmc/packages/install_packages.sh
Homepage: https://sandslab.kr
Installed-Size: $SIZE_KB
Priority: optional
Section: admin
EOF

# ── DEBIAN/postinst ───────────────────────────────────────────────
cat > "$PKG_DIR/DEBIAN/postinst" << 'POSTINST'
#!/bin/bash
set -e

# 실행 파일 권한 확인
chmod 755 /mnxmc/main.py /mnxmc/main-login.py 2>/dev/null || true
find /mnxmc/packages -name "*.sh" -exec chmod 755 {} \; 2>/dev/null || true
find /mnxmc/packages/perccli -name "perccli*" -exec chmod 755 {} \; 2>/dev/null || true

echo ""
echo "============================================================"
echo "  MNXMC 파일 설치 완료: /mnxmc"
echo ""
echo "  다음 명령으로 패키지 및 환경을 설치하세요:"
echo ""
echo "    sudo bash /mnxmc/packages/install_packages.sh"
echo ""
echo "============================================================"
echo ""
POSTINST

chmod 755 "$PKG_DIR/DEBIAN/postinst"

# ── DEBIAN/prerm ──────────────────────────────────────────────────
cat > "$PKG_DIR/DEBIAN/prerm" << 'PRERM'
#!/bin/bash
set -e
echo "MNXMC 제거 중..."
PRERM

chmod 755 "$PKG_DIR/DEBIAN/prerm"

# ── deb 빌드 ─────────────────────────────────────────────────────
echo ""
echo "[BUILD] dpkg-deb 빌드 중..."
dpkg-deb --root-owner-group --build "$PKG_DIR" "$OUT_DEB" 2>&1

if [ -f "$OUT_DEB" ]; then
    SIZE=$(ls -lh "$OUT_DEB" | awk '{print $5}')
    ok "빌드 완료: $OUT_DEB ($SIZE)"
else
    fail "빌드 실패"
fi

rm -rf "$BUILD_DIR"

echo ""
echo "============================================================"
echo "  빌드 완료: $OUT_DEB  ($SIZE)"
echo ""
echo "  [설치 순서]"
echo "  1. sudo dpkg -i $(basename "$OUT_DEB")"
echo "  2. sudo bash /mnxmc/packages/install_packages.sh"
echo "============================================================"
echo ""
