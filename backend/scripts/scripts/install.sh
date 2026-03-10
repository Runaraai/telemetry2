#!/usr/bin/env bash
# install.sh - One-shot setup for the Runara telemetry agent.
#
# Run once on your GPU instance:
#   bash install.sh
#
# What it does:
#   1. Checks Python 3.9+
#   2. Creates a local venv (.venv) and installs deps there
#   3. Prompts for Runara API token + API URL (+ optional web URL)
#   4. Saves config to ~/.runara/config and creates ./run.sh helper

set -euo pipefail

RESET='\033[0m'
BOLD='\033[1m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
CYAN='\033[36m'

ok()   { echo -e "  ${GREEN}✓${RESET}  $*"; }
warn() { echo -e "  ${YELLOW}!${RESET}  $*"; }
fail() { echo -e "  ${RED}x${RESET}  $*"; }
info() { echo -e "  ${CYAN}·${RESET}  $*"; }
head() { echo -e "\n${BOLD}$*${RESET}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo -e "${BOLD}======================================================${RESET}"
echo -e "${BOLD}  Runara Agent Setup${RESET}"
echo -e "${BOLD}======================================================${RESET}"

head "Step 1 - Python"

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 9 ]; then
            PYTHON="$cmd"
            ok "Python $VER found ($cmd)"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    fail "Python 3.9+ not found. Install Python 3.9 or newer."
    exit 1
fi

head "Step 1.5 - Virtual environment"
VENV_DIR="$SCRIPT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    info "Creating venv at $VENV_DIR ..."
    if ! "$PYTHON" -m venv "$VENV_DIR"; then
        fail "Could not create venv. Install python3-venv and retry."
        exit 1
    fi
fi

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"
PYTHON="$VENV_DIR/bin/python"
PIP="$PYTHON -m pip"
ok "Using venv Python: $PYTHON"

head "Step 2 - Python dependencies"

install_pkg() {
    local import_name="$1"
    local pkg_name="$2"
    if "$PYTHON" -c "import $import_name" >/dev/null 2>&1; then
        ok "$import_name already installed"
    else
        info "Installing $pkg_name ..."
        if $PIP install --quiet "$pkg_name"; then
            ok "$pkg_name installed"
        else
            fail "Failed to install $pkg_name - try: $PIP install $pkg_name"
            return 1
        fi
    fi
}

install_pkg pynvml nvidia-ml-py3
install_pkg requests requests
install_pkg aiohttp aiohttp

head "Step 3 - Runara config"

CONFIG_DIR="$HOME/.runara"
CONFIG_FILE="$CONFIG_DIR/config"

EXISTING_TOKEN=""
EXISTING_BASE=""
EXISTING_WEB_BASE=""
EXISTING_MODEL=""

if [ -f "$CONFIG_FILE" ]; then
    EXISTING_TOKEN=$("$PYTHON" -c "import json, pathlib; p=pathlib.Path('$CONFIG_FILE'); print(json.loads(p.read_text()).get('api_token','') if p.exists() else '')" 2>/dev/null || true)
    EXISTING_BASE=$("$PYTHON" -c "import json, pathlib; p=pathlib.Path('$CONFIG_FILE'); print(json.loads(p.read_text()).get('api_base','') if p.exists() else '')" 2>/dev/null || true)
    EXISTING_WEB_BASE=$("$PYTHON" -c "import json, pathlib; p=pathlib.Path('$CONFIG_FILE'); print(json.loads(p.read_text()).get('web_base','') if p.exists() else '')" 2>/dev/null || true)
    EXISTING_MODEL=$("$PYTHON" -c "import json, pathlib; p=pathlib.Path('$CONFIG_FILE'); print(json.loads(p.read_text()).get('default_model','') if p.exists() else '')" 2>/dev/null || true)
fi

if [ -n "$EXISTING_TOKEN" ]; then
    info "Existing token found in $CONFIG_FILE"
    read -rp "  Keep existing token? [Y/n]: " KEEP_TOKEN
    KEEP_TOKEN="${KEEP_TOKEN:-Y}"
    if [[ "$KEEP_TOKEN" =~ ^[Nn] ]]; then
        EXISTING_TOKEN=""
    fi
fi

if [ -z "$EXISTING_TOKEN" ]; then
    info "Get token from Runara dashboard -> Account -> Create token"
    while true; do
        read -rp "  Enter API token (rt_...): " INPUT_TOKEN
        INPUT_TOKEN="${INPUT_TOKEN// /}"
        if [[ "$INPUT_TOKEN" == rt_* ]] && [ "${#INPUT_TOKEN}" -gt 10 ]; then
            EXISTING_TOKEN="$INPUT_TOKEN"
            break
        fi
        warn "Token must start with rt_ and be at least 10 chars."
    done
fi

if [ -n "$EXISTING_BASE" ]; then
    info "Existing API base: $EXISTING_BASE"
    read -rp "  Keep existing API base? [Y/n]: " KEEP_BASE
    KEEP_BASE="${KEEP_BASE:-Y}"
    if [[ "$KEEP_BASE" =~ ^[Nn] ]]; then
        EXISTING_BASE=""
    fi
fi

if [ -z "$EXISTING_BASE" ]; then
    read -rp "  Enter Runara API base URL (https://...execute-api...): " INPUT_BASE
    EXISTING_BASE="${INPUT_BASE// /}"
fi

if [ -n "$EXISTING_WEB_BASE" ]; then
    info "Existing website URL: $EXISTING_WEB_BASE"
    read -rp "  Keep existing website URL? [Y/n]: " KEEP_WEB
    KEEP_WEB="${KEEP_WEB:-Y}"
    if [[ "$KEEP_WEB" =~ ^[Nn] ]]; then
        EXISTING_WEB_BASE=""
    fi
fi

if [ -z "$EXISTING_WEB_BASE" ]; then
    read -rp "  Enter Runara website URL for dashboard links (optional): " INPUT_WEB
    EXISTING_WEB_BASE="${INPUT_WEB// /}"
fi

if [ -z "$EXISTING_MODEL" ]; then
    EXISTING_MODEL="Qwen/Qwen2.5-3B-Instruct"
fi
read -rp "  Default model for auto-start [${EXISTING_MODEL}]: " INPUT_MODEL
DEFAULT_MODEL="${INPUT_MODEL:-$EXISTING_MODEL}"

mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
cat > "$CONFIG_FILE" <<JSONEOF
{
  "api_token": "${EXISTING_TOKEN}",
  "api_base": "${EXISTING_BASE}",
  "web_base": "${EXISTING_WEB_BASE}",
  "default_model": "${DEFAULT_MODEL}"
}
JSONEOF
chmod 600 "$CONFIG_FILE"
ok "Config saved to $CONFIG_FILE"

RUN_HELPER="$SCRIPT_DIR/run.sh"
cat > "$RUN_HELPER" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/.venv/bin/activate"
exec python "$SCRIPT_DIR/agent.py" "$@"
EOF
chmod +x "$RUN_HELPER"
ok "Created helper script: $RUN_HELPER"

head "Step 4 - Environment check"

cd "$SCRIPT_DIR"

if command -v nvidia-smi >/dev/null 2>&1; then
    GPU_INFO=$(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null | head -1 || echo "")
    if [ -n "$GPU_INFO" ]; then
        ok "GPU detected: $GPU_INFO"
    else
        warn "nvidia-smi found but no GPU info returned"
    fi
else
    warn "nvidia-smi not found - NVIDIA driver may not be installed"
fi

if "$PYTHON" -c "import sys; sys.path.insert(0, '.'); from telemetry import AutoGpuBackend" >/dev/null 2>&1; then
    ok "telemetry package importable"
else
    warn "Could not import telemetry package - run from the runara-agent directory"
fi

head "Step 5 - vLLM check"

VLLM_OK=false

# Check native vllm CLI or Python module
if command -v vllm >/dev/null 2>&1; then
    ok "vLLM found: $(command -v vllm)"
    VLLM_OK=true
elif python3 -c "import vllm" >/dev/null 2>&1 || python -c "import vllm" >/dev/null 2>&1; then
    ok "vLLM importable from system Python"
    VLLM_OK=true
fi

# Check Docker fallback
if [ "$VLLM_OK" = false ] && command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    ok "vLLM not installed natively — will use Docker (vllm/vllm-openai) automatically"
    VLLM_OK=true
fi

if [ "$VLLM_OK" = false ]; then
    warn "vLLM not found and Docker not available"
    info "Install vLLM (run OUTSIDE this .venv):"
    echo -e "  ${CYAN}\$${RESET} deactivate"
    echo -e "  ${CYAN}\$${RESET} pip install vllm"
    echo -e "  ${CYAN}\$${RESET} source ${VENV_DIR}/bin/activate"
    info "OR install Docker: https://docs.docker.com/engine/install/"
    info "The agent will auto-start vLLM via Docker if Docker is available."
fi

echo ""
echo -e "${BOLD}======================================================${RESET}"
echo -e "${GREEN}${BOLD}  Setup complete!${RESET}"
echo ""
echo -e "  Start profiling:"
echo -e "  ${CYAN}\$${RESET} ./run.sh --model ${DEFAULT_MODEL}               # standard run"
echo -e "  ${CYAN}\$${RESET} ./run.sh --model ${DEFAULT_MODEL} --mode full   # standard + kernel"
echo -e "  ${CYAN}\$${RESET} ./run.sh --model ${DEFAULT_MODEL} --skip-dcgm   # if Docker/DCGM unavailable"
echo ""
if [ -n "$EXISTING_WEB_BASE" ]; then
    echo -e "  Dashboard: ${EXISTING_WEB_BASE%/}/dashboard"
else
    echo -e "  Dashboard: open your Runara website /dashboard"
    echo -e "  (API base is for uploads only; set web_base in ~/.runara/config for direct run links.)"
fi
echo -e "${BOLD}======================================================${RESET}"
echo ""
