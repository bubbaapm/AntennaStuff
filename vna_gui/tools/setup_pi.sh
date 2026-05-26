#!/usr/bin/env bash
set -euo pipefail

# Raspberry Pi desktop setup for LibreVNA characterization runs.
#
# Run from the repo root:
#   bash vna_gui/tools/setup_pi.sh
#
# Optional overrides:
#   LIBREVNA_GUI_ZIP_URL=https://.../LibreVNA-GUI-RPi5-v1.6.5.zip bash vna_gui/tools/setup_pi.sh
#   VENV_DIR=/path/to/.venv bash vna_gui/tools/setup_pi.sh

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VNA_GUI_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd -- "${VNA_GUI_DIR}/.." && pwd)"

VENV_DIR="${VENV_DIR:-${VNA_GUI_DIR}/.venv}"
LIBREVNA_GUI_VERSION="${LIBREVNA_GUI_VERSION:-v1.6.5}"
LIBREVNA_GUI_ZIP_NAME="${LIBREVNA_GUI_ZIP_NAME:-LibreVNA-GUI-RPi5-${LIBREVNA_GUI_VERSION}.zip}"
LIBREVNA_GUI_ZIP_URL="${LIBREVNA_GUI_ZIP_URL:-https://github.com/jankae/LibreVNA/releases/download/${LIBREVNA_GUI_VERSION}/${LIBREVNA_GUI_ZIP_NAME}}"
LIBREVNA_GUI_DIR="${LIBREVNA_GUI_DIR:-${SCRIPT_DIR}/librevna}"
UDEV_RULE_URL="${UDEV_RULE_URL:-https://raw.githubusercontent.com/jankae/LibreVNA/master/Software/PC_Application/51-vna.rules}"
UDEV_RULE_DEST="${UDEV_RULE_DEST:-/etc/udev/rules.d/51-vna.rules}"

APT_PACKAGES=(
  python3
  python3-venv
  python3-pip
  git
  tmux
  curl
  wget
  unzip
  qt6-base-dev
  libqt6svg6
  libgl1
  libegl1
  libxcb-cursor0
  libxkbcommon-x11-0
)

info() {
  printf '\n[setup-pi] %s\n' "$*"
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    printf '[setup-pi] Missing required command: %s\n' "$1" >&2
    exit 1
  }
}

run_sudo() {
  if [[ "${EUID}" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

install_apt_packages() {
  info "Updating apt package metadata"
  run_sudo apt-get update

  info "Installing system packages"
  run_sudo apt-get install -y "${APT_PACKAGES[@]}"
}

install_udev_rule() {
  need_cmd curl

  info "Installing LibreVNA udev rule"
  tmp_rule="$(mktemp)"
  curl -fsSL "${UDEV_RULE_URL}" -o "${tmp_rule}"
  run_sudo install -m 0644 "${tmp_rule}" "${UDEV_RULE_DEST}"
  rm -f "${tmp_rule}"

  info "Reloading udev rules"
  run_sudo udevadm control --reload-rules
  run_sudo udevadm trigger
}

install_librevna_gui() {
  need_cmd curl
  need_cmd unzip

  info "Downloading LibreVNA-GUI ${LIBREVNA_GUI_VERSION}"
  mkdir -p "${LIBREVNA_GUI_DIR}"
  zip_path="${SCRIPT_DIR}/${LIBREVNA_GUI_ZIP_NAME}"
  curl -fL "${LIBREVNA_GUI_ZIP_URL}" -o "${zip_path}"

  info "Unpacking LibreVNA-GUI into ${LIBREVNA_GUI_DIR}"
  rm -rf "${LIBREVNA_GUI_DIR:?}/"*
  unzip -q "${zip_path}" -d "${LIBREVNA_GUI_DIR}"
  rm -f "${zip_path}"

  info "Making LibreVNA-GUI executable"
  find "${LIBREVNA_GUI_DIR}" -type f \( -name 'LibreVNA-GUI' -o -name '*.sh' -o -name '*.AppImage' \) -exec chmod +x {} +

  gui_binary="$(find "${LIBREVNA_GUI_DIR}" -type f -name 'LibreVNA-GUI' -perm -111 | head -n 1 || true)"
  if [[ -z "${gui_binary}" ]]; then
    printf '[setup-pi] Could not identify LibreVNA-GUI after unzip. Check %s\n' "${LIBREVNA_GUI_DIR}" >&2
    exit 1
  fi

  printf '[setup-pi] LibreVNA-GUI executable: %s\n' "${gui_binary}"
}

install_python_env() {
  info "Creating Python virtual environment at ${VENV_DIR}"
  python3 -m venv "${VENV_DIR}"

  # shellcheck disable=SC1091
  source "${VENV_DIR}/bin/activate"

  info "Upgrading pip tooling"
  python -m pip install --upgrade pip setuptools wheel

  info "Installing vna_gui Python requirements"
  python -m pip install -r "${VNA_GUI_DIR}/requirements.txt"
}

main() {
  need_cmd apt-get
  need_cmd python3

  printf '[setup-pi] Repo root: %s\n' "${REPO_ROOT}"
  printf '[setup-pi] vna_gui:   %s\n' "${VNA_GUI_DIR}"

  install_apt_packages
  install_udev_rule
  install_librevna_gui
  install_python_env

  info "Done"
  printf '[setup-pi] Activate the environment with: source %s/bin/activate\n' "${VENV_DIR}"
  printf '[setup-pi] Try a smoke test from vna_gui with: python -m vna_tester.tools.characterize --dut \"Pi smoke test\" --kind load --start 2.3e9 --stop 2.6e9 --points 501 --count 3 --out characterization_runs/pi_smoke_test\n'
  printf '[setup-pi] If LibreVNA USB access fails after the udev rule install, reboot the Pi.\n'
}

main "$@"
