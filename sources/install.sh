#!/usr/bin/env bash
# =============================================================================
# axupdate — source & script installer
# =============================================================================
# Installs:
#   1. APT source files  →  /etc/apt/sources.list.d/
#   2. axpm GPG key      →  /usr/share/keyrings/axpm-archive-keyring.gpg
#   3. axupdate.py       →  /usr/local/bin/axupdate.py
#   4. axupdate.desktop  →  /usr/share/applications/axupdate.desktop
#   5. Runs apt update
#
# Run as root:  sudo bash install.sh
# =============================================================================
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# USER CONFIGURATION — the only section you need to edit
# ─────────────────────────────────────────────────────────────────────────────

# Debian mirror for the main + updates repos.
# Leave as default (official CDN) or pick one from https://www.debian.org/mirror/list
# Examples:
#   http://ftp.us.debian.org/debian
#   http://ftp.de.debian.org/debian
#   http://mirror.aarnet.edu.au/debian
DEBIAN_MIRROR="http://deb.debian.org/debian"

# ── axpm repo (GitHub Pages or any HTTPS host) ────────────────────────────
#
# OPTION A — GitHub Pages (recommended, free):
#   If your repo is at  https://github.com/YourUser/axpm-repo
#   and GitHub Pages is enabled on the main branch:
#
#     AXPM_REPO_URI="https://YourUser.github.io/axpm-repo"
#     AXPM_REPO_SUITE="stable"
#     AXPM_KEY_URL="https://raw.githubusercontent.com/YourUser/axpm-repo/main/axpm.gpg"
#
# OPTION B — GitHub raw (single .deb only, NOT a proper repo, do not use for apt):
#   GitHub raw URLs cannot serve an apt repo — use GitHub Pages instead.
#
# OPTION C — Self-hosted:
#     AXPM_REPO_URI="https://repo.yourdomain.org/axpm"
#     AXPM_REPO_SUITE="stable"
#     AXPM_KEY_URL="https://repo.yourdomain.org/axpm/axpm.gpg"
#
# Leave the placeholders below if you do not have an axpm repo yet —
# the Debian Testing + Security sources will still be installed.

AXPM_REPO_URI="https://YourUser.github.io/axpm-repo"
AXPM_REPO_SUITE="stable"
AXPM_KEY_URL="https://raw.githubusercontent.com/YourUser/axpm-repo/main/axpm.gpg"

# ─────────────────────────────────────────────────────────────────────────────
# END OF USER CONFIGURATION — do not edit below this line
# ─────────────────────────────────────────────────────────────────────────────

# Sentinel values — if these are still set, skip the axpm step
_AXPM_PLACEHOLDER_URI="https://YourUser.github.io/axpm-repo"
_AXPM_PLACEHOLDER_KEY="https://raw.githubusercontent.com/YourUser/axpm-repo/main/axpm.gpg"

SOURCES_DIR="/etc/apt/sources.list.d"
KEYRING_PATH="/usr/share/keyrings/axpm-archive-keyring.gpg"
INSTALL_BIN="/usr/local/bin/axupdate.py"
DESKTOP_DST="/usr/share/applications/axupdate.desktop"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Colours
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${GREEN}[axupdate]${NC} $*"; }
warn()    { echo -e "${YELLOW}[axupdate] WARN:${NC} $*"; }
error()   { echo -e "${RED}[axupdate] ERROR:${NC} $*" >&2; exit 1; }
step()    { echo -e "\n${CYAN}━━━ $* ${NC}"; }

# ── 0. Root guard ────────────────────────────────────────────────────────────
[[ "$EUID" -eq 0 ]] || error "Run as root:  sudo bash install.sh"

# ── 1. Dependency checks ─────────────────────────────────────────────────────
step "Checking dependencies"

for dep in curl gpg apt-get python3; do
    command -v "$dep" &>/dev/null || error "Required tool not found: ${dep}. Install it and re-run."
done

# PyQt6
if ! python3 -c "import PyQt6" 2>/dev/null; then
    info "PyQt6 not found — installing python3-pyqt6…"
    apt-get install -y python3-pyqt6 \
        || error "Could not install python3-pyqt6. Run:  sudo apt install python3-pyqt6"
fi
info "PyQt6 ✔"

# notify-send (for KDE notifications fallback)
if ! command -v notify-send &>/dev/null; then
    info "notify-send not found — installing libnotify-bin…"
    apt-get install -y libnotify-bin || warn "Could not install libnotify-bin (non-fatal)."
fi

# plyer (optional — richer notifications)
if ! python3 -c "import plyer" 2>/dev/null; then
    info "plyer not installed — using notify-send fallback for notifications."
    info "  Optional:  sudo apt install python3-plyer   (or:  pip3 install plyer)"
fi

# ── 2. Backup existing sources.list ─────────────────────────────────────────
step "Checking /etc/apt/sources.list"

if [[ -f /etc/apt/sources.list ]] && grep -q "^deb " /etc/apt/sources.list 2>/dev/null; then
    warn "/etc/apt/sources.list has active lines. If it points to stable/bookworm,"
    warn "mixed stable+testing suites will cause apt errors."
    warn "Comment them out if you see 'Suite changed' errors after this install."
fi

# ── 3. Install Debian Testing source files ──────────────────────────────────
step "Installing APT source files"

# debian-testing.sources — patch mirror URL then install
sed "s|http://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
    "${SCRIPT_DIR}/debian-testing.sources" \
    > "${SOURCES_DIR}/debian-testing.sources"
chmod 644 "${SOURCES_DIR}/debian-testing.sources"
info "  ✔  ${SOURCES_DIR}/debian-testing.sources"

# debian-security.sources — URI must stay on security.debian.org (no mirrors)
cp "${SCRIPT_DIR}/debian-security.sources" "${SOURCES_DIR}/debian-security.sources"
chmod 644 "${SOURCES_DIR}/debian-security.sources"
info "  ✔  ${SOURCES_DIR}/debian-security.sources"

# debian-testing.list — saved as .disabled so it doesn't conflict
sed "s|http://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
    "${SCRIPT_DIR}/debian-testing.list" \
    > "${SOURCES_DIR}/debian-testing.list.disabled"
chmod 644 "${SOURCES_DIR}/debian-testing.list.disabled"
info "  ✔  ${SOURCES_DIR}/debian-testing.list.disabled  (fallback, not active)"

# ── 4. axpm GPG key + source ─────────────────────────────────────────────────
step "Setting up axpm repository"

if [[ "$AXPM_REPO_URI" == "$_AXPM_PLACEHOLDER_URI" || "$AXPM_KEY_URL" == "$_AXPM_PLACEHOLDER_KEY" ]]; then
    warn "AXPM_REPO_URI / AXPM_KEY_URL are still placeholders — skipping axpm repo setup."
    warn "Edit the USER CONFIGURATION block in this script and re-run to enable it."
else
    # ── Import GPG key — handles both armored (.asc) and binary (.gpg) ──────
    info "Downloading axpm GPG key from:  ${AXPM_KEY_URL}"

    TMP_KEY="$(mktemp /tmp/axpm-key.XXXXXX)"
    curl -fsSL --max-time 30 "$AXPM_KEY_URL" -o "$TMP_KEY" \
        || error "Failed to download GPG key from ${AXPM_KEY_URL}"

    # Detect armored vs binary: armored files start with "-----BEGIN"
    if head -c 27 "$TMP_KEY" | grep -q "BEGIN"; then
        info "  Detected ASCII-armored key (.asc) — dearmoring…"
        gpg --batch --yes --dearmor -o "$KEYRING_PATH" "$TMP_KEY"
    else
        info "  Detected binary key (.gpg) — copying directly…"
        cp "$TMP_KEY" "$KEYRING_PATH"
    fi
    rm -f "$TMP_KEY"
    chmod 644 "$KEYRING_PATH"
    info "  ✔  GPG key saved to ${KEYRING_PATH}"

    # ── Write axpm.sources ───────────────────────────────────────────────────
    cat > "${SOURCES_DIR}/axpm.sources" <<EOF
# /etc/apt/sources.list.d/axpm.sources
# Generated by axupdate install.sh — do not edit manually (re-run install.sh)
Types: deb
URIs: ${AXPM_REPO_URI}
Suites: ${AXPM_REPO_SUITE}
Components: main
Signed-By: ${KEYRING_PATH}
EOF
    chmod 644 "${SOURCES_DIR}/axpm.sources"
    info "  ✔  ${SOURCES_DIR}/axpm.sources"
fi

# ── 5. Install axupdate.py ───────────────────────────────────────────────────
step "Installing axupdate.py"

SCRIPT_SRC="${PROJECT_ROOT}/axupdate.py"
if [[ -f "$SCRIPT_SRC" ]]; then
    cp "$SCRIPT_SRC" "$INSTALL_BIN"
    chmod 755 "$INSTALL_BIN"
    chown root:root "$INSTALL_BIN"
    info "  ✔  ${INSTALL_BIN}"
else
    warn "axupdate.py not found at ${SCRIPT_SRC}"
    warn "  Copy manually:  sudo cp /path/to/axupdate.py ${INSTALL_BIN} && sudo chmod 755 ${INSTALL_BIN}"
fi

# ── 6. Install .desktop launcher ────────────────────────────────────────────
step "Installing desktop launcher"

DESKTOP_SRC="${PROJECT_ROOT}/axupdate.desktop"
if [[ -f "$DESKTOP_SRC" ]]; then
    cp "$DESKTOP_SRC" "$DESKTOP_DST"
    chmod 644 "$DESKTOP_DST"
    command -v update-desktop-database &>/dev/null \
        && update-desktop-database -q /usr/share/applications \
        || true
    info "  ✔  ${DESKTOP_DST}"
else
    warn "axupdate.desktop not found at ${DESKTOP_SRC} — skipping."
fi

# ── 7. Initial apt update ────────────────────────────────────────────────────
step "Running apt update"
apt-get update

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN} axupdate installed successfully!${NC}"
echo ""
echo -e " APT sources:"
echo -e "   ${SOURCES_DIR}/debian-testing.sources"
echo -e "   ${SOURCES_DIR}/debian-security.sources"
[[ "$AXPM_REPO_URI" != "$_AXPM_PLACEHOLDER_URI" ]] && \
    echo -e "   ${SOURCES_DIR}/axpm.sources"
echo ""
echo -e " Script:    ${INSTALL_BIN}"
echo -e " Launcher:  ${DESKTOP_DST}"
echo ""
echo -e " To launch: pkexec python3 ${INSTALL_BIN}"
echo -e "   — or search for 'axupdate' in the KDE application menu."
echo -e "${GREEN}════════════════════════════════════════════════════════${NC}"
