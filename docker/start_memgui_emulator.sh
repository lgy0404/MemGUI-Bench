#!/bin/bash
set -euo pipefail

LOCK_FILE="${MEMGUI_EMULATOR_LOCK_FILE:-/tmp/start_memgui_emulator.lock}"
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "Another MemGUI emulator startup is already running; waiting for it to finish"
  flock 9
fi

export ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-/root/.android}"
export ANDROID_HOME="${ANDROID_HOME:-$ANDROID_SDK_ROOT}"
export AVD_NAME="${AVD_NAME:-MemGUI-AVD-260614}"
export EMULATOR_NAME="${EMULATOR_NAME:-$AVD_NAME}"
export PATH="/root/.local/bin:${ANDROID_SDK_ROOT}/emulator:${ANDROID_SDK_ROOT}/tools:${ANDROID_SDK_ROOT}/tools/bin:${ANDROID_SDK_ROOT}/platform-tools:${PATH}"
export ADB_VENDOR_KEYS="${ADB_VENDOR_KEYS:-/root/.android/adbkey}"

CONSOLE_PORT="${EMULATOR_CONSOLE_PORT:-5554}"
ADB_PORT="${EMULATOR_ADB_PORT:-5555}"
GRPC_PORT="${EMULATOR_GRPC_PORT:-8554}"
MEMORY="${EMULATOR_MEMORY:-8192}"
TIMEOUT="${EMULATOR_TIMEOUT:-1200}"
MAX_START_ATTEMPTS="${MEMGUI_EMULATOR_START_ATTEMPTS:-4}"
UNAUTHORIZED_RESTART_SECONDS="${MEMGUI_UNAUTHORIZED_RESTART_SECONDS:-90}"
BOOT_SNAPSHOT="${MEMGUI_BOOT_SNAPSHOT:-}"
INIT_SNAPSHOT="${MEMGUI_INIT_SNAPSHOT:-}"
DEVICE_ID="emulator-${CONSOLE_PORT}"
AVD_DIR="${ANDROID_SDK_ROOT}/avd/${AVD_NAME}.avd"

cleanup_existing_emulator() {
  echo "Cleaning existing emulator processes for ${EMULATOR_NAME} on ports ${CONSOLE_PORT},${ADB_PORT}"
  adb devices | awk '/emulator/ {print $1}' | xargs -r -I {} adb -s "{}" emu kill || true
  sleep 2

  local pattern="@${EMULATOR_NAME}|-ports ${CONSOLE_PORT},${ADB_PORT}|-grpc ${GRPC_PORT}"
  local pids
  pkill -f "authorize_adb_grpc.py .*--device ${DEVICE_ID}" 2>/dev/null || true
  pids="$(pgrep -f "${pattern}" || true)"
  if [ -n "${pids}" ]; then
    echo "Stopping stale emulator/qemu process(es): ${pids}"
    kill ${pids} 2>/dev/null || true
    sleep 5
    pids="$(pgrep -f "${pattern}" || true)"
    if [ -n "${pids}" ]; then
      echo "Force-killing stale emulator/qemu process(es): ${pids}"
      kill -9 ${pids} 2>/dev/null || true
      sleep 2
    fi
  fi

  find "${AVD_DIR}" -name '*.lock' -type f -delete 2>/dev/null || true
  rm -f /tmp/android-*/emu-crash-*.db.lock 2>/dev/null || true
}

set_avd_modem() {
  local modem_enabled="${MEMGUI_ENABLE_GSM_MODEM:-true}"
  local modem_value="true"
  local avd_file

  if [ "${modem_enabled}" = "false" ] || [ "${modem_enabled}" = "0" ]; then
    modem_value="false"
  fi

  for avd_file in "${AVD_DIR}/config.ini" "${AVD_DIR}/hardware-qemu.ini"; do
    if [ ! -f "${avd_file}" ]; then
      continue
    fi
    if grep -q '^hw\.gsmModem' "${avd_file}"; then
      sed -i "s/^hw\\.gsmModem.*/hw.gsmModem = ${modem_value}/" "${avd_file}"
    else
      printf '\nhw.gsmModem = %s\n' "${modem_value}" >> "${avd_file}"
    fi
  done
  echo "AVD GSM modem enabled: ${modem_value}"
}

preauthorize_adb_key() {
  local adb_public_key="${ADB_VENDOR_KEYS}.pub"
  local adb_dir="${AVD_DIR}/data/misc/adb"
  local adb_keys="${adb_dir}/adb_keys"

  if [ ! -f "${adb_public_key}" ]; then
    echo "ADB public key not found at ${adb_public_key}; falling back to UI authorization"
    return
  fi

  mkdir -p "${adb_dir}"
  cp "${adb_public_key}" "${adb_keys}"
  chmod 700 "${adb_dir}" || true
  chmod 640 "${adb_keys}" || true
  echo "Pre-authorized ADB key at ${adb_keys}"
}

activate_adb_keyboard() {
  local package="com.android.adbkeyboard"
  local ime="com.android.adbkeyboard/.AdbIME"
  local current_ime

  if adb -s "${DEVICE_ID}" shell pm list packages "${package}" 2>/dev/null | grep -F -q "${package}"; then
    adb -s "${DEVICE_ID}" shell ime enable "${ime}" || true
    adb -s "${DEVICE_ID}" shell ime set "${ime}" || true
    current_ime="$(adb -s "${DEVICE_ID}" shell settings get secure default_input_method 2>/dev/null | tr -d '\r' || true)"
    echo "Default input method: ${current_ime:-<empty>}"
  else
    echo "ADB Keyboard is not installed; runtime will fall back to adb shell input text"
  fi
}

configure_android_proxy() {
  local upstream="${HTTP_PROXY:-${http_proxy:-${HTTPS_PROXY:-${https_proxy:-}}}}"
  local local_proxy_port="${LOCAL_PROXY_PORT:-38888}"

  if [ -z "${upstream}" ]; then
    adb -s "${DEVICE_ID}" shell settings put global http_proxy :0 || true
    adb -s "${DEVICE_ID}" shell settings delete global global_http_proxy_host >/dev/null 2>&1 || true
    adb -s "${DEVICE_ID}" shell settings delete global global_http_proxy_port >/dev/null 2>&1 || true
    echo "Android proxy disabled"
    return
  fi

  pkill -f "/app/docker/proxy_chain.py" 2>/dev/null || true
  UPSTREAM_PROXY="${upstream}" LOCAL_PORT="${local_proxy_port}" \
    nohup /usr/bin/python3 /app/docker/proxy_chain.py \
    > /var/log/proxy_chain.log 2>&1 &
  sleep 1

  adb -s "${DEVICE_ID}" shell settings put global http_proxy "10.0.2.2:${local_proxy_port}"
  adb -s "${DEVICE_ID}" shell settings put global global_http_proxy_host "10.0.2.2"
  adb -s "${DEVICE_ID}" shell settings put global global_http_proxy_port "${local_proxy_port}"
  echo "Android proxy enabled: 10.0.2.2:${local_proxy_port} (chain -> ${upstream})"
}

start_emulator_process() {
  echo "Starting MemGUI emulator: emulator ${options[*]}"
  nohup emulator "${options[@]}" >/tmp/memgui-emulator.nohup 2>&1 &
}

start_adb_authorizer() {
  if [ "${AUTO_AUTHORIZE_ADB:-true}" = "false" ] || [ "${AUTO_AUTHORIZE_ADB:-true}" = "0" ]; then
    return
  fi

  (
    cd /app/service
    .venv/bin/python /app/docker/authorize_adb_grpc.py \
      --device "${DEVICE_ID}" \
      --grpc-port "${GRPC_PORT}" \
      --timeout "${TIMEOUT}" \
      --tap-always-allow
  ) >> /var/log/adb-auth.log 2>&1 &
}

cleanup_existing_emulator
adb kill-server >/dev/null 2>&1 || true
adb start-server >/dev/null
set_avd_modem
preauthorize_adb_key

options=(
  "@${EMULATOR_NAME}"
  -no-window
  -no-boot-anim
  -no-audio
  -no-metrics
  -memory "${MEMORY}"
  -ports "${CONSOLE_PORT},${ADB_PORT}"
  -grpc "${GRPC_PORT}"
  -skip-adb-auth
  -gpu swiftshader_indirect
)

if [ -n "${BOOT_SNAPSHOT}" ] && [ "${BOOT_SNAPSHOT}" != "none" ] && [ "${BOOT_SNAPSHOT}" != "false" ]; then
  options+=(-snapshot "${BOOT_SNAPSHOT}" -no-snapshot-save)
else
  options+=(-no-snapshot-load -no-snapshot-save)
fi

if grep -E -q '(vmx|svm)' /proc/cpuinfo; then
  options+=(-accel on)
else
  options+=(-accel off)
fi

start_emulator_process
start_adb_authorizer

start_time="$(date +%s)"
start_attempt=1
unauthorized_since=0
spinner=( "..." "...." "....." )
i=0
while true; do
  state="$(adb -s "${DEVICE_ID}" get-state 2>&1 || true)"
  boot_completed="$(adb -s "${DEVICE_ID}" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)"

  if [ "${boot_completed}" = "1" ]; then
    echo "Emulator is ready: ${DEVICE_ID}"
    adb -s "${DEVICE_ID}" shell input keyevent 82 || true
    adb -s "${DEVICE_ID}" shell "settings put global window_animation_scale 0.0" || true
    adb -s "${DEVICE_ID}" shell "settings put global transition_animation_scale 0.0" || true
    adb -s "${DEVICE_ID}" shell "settings put global animator_duration_scale 0.0" || true
    adb -s "${DEVICE_ID}" shell "settings put global hidden_api_policy_pre_p_apps 1; settings put global hidden_api_policy_p_apps 1; settings put global hidden_api_policy 1" || true
    configure_android_proxy
    adb -s "${DEVICE_ID}" root || true
    activate_adb_keyboard
    if [ -n "${INIT_SNAPSHOT}" ] && [ "${INIT_SNAPSHOT}" != "none" ] && [ "${INIT_SNAPSHOT}" != "false" ]; then
      echo "Saving MemGUI init snapshot: ${INIT_SNAPSHOT}"
      adb -s "${DEVICE_ID}" emu avd snapshot delete "${INIT_SNAPSHOT}" >/dev/null 2>&1 || true
      adb -s "${DEVICE_ID}" emu avd snapshot save "${INIT_SNAPSHOT}"
    fi
    adb devices -l
    exit 0
  fi

  if [[ "${state}" == *"unauthorized"* ]]; then
    now="$(date +%s)"
    if [ "${unauthorized_since}" -eq 0 ]; then
      unauthorized_since="${now}"
    fi
    unauthorized_elapsed="$((now - unauthorized_since))"
    if [ "${unauthorized_elapsed}" -ge "${UNAUTHORIZED_RESTART_SECONDS}" ]; then
      if [ "${start_attempt}" -lt "${MAX_START_ATTEMPTS}" ]; then
        start_attempt="$((start_attempt + 1))"
        echo "ADB stayed unauthorized for ${unauthorized_elapsed}s; restarting emulator (attempt ${start_attempt}/${MAX_START_ATTEMPTS})"
        cleanup_existing_emulator
        adb kill-server >/dev/null 2>&1 || true
        adb start-server >/dev/null
        set_avd_modem
        preauthorize_adb_key
        start_emulator_process
        start_adb_authorizer
        unauthorized_since=0
        continue
      fi
      echo "ADB stayed unauthorized for ${unauthorized_elapsed}s, but max emulator start attempts (${MAX_START_ATTEMPTS}) is exhausted"
    fi
  else
    unauthorized_since=0
  fi

  elapsed="$(( $(date +%s) - start_time ))"
  if [ "${elapsed}" -gt "${TIMEOUT}" ]; then
    echo "Timeout waiting for emulator after ${TIMEOUT}s"
    echo "Last adb state: ${state}"
    echo "--- emulator nohup tail ---"
    tail -120 /tmp/memgui-emulator.nohup 2>/dev/null || true
    echo "--- adb auth tail ---"
    tail -120 /var/log/adb-auth.log 2>/dev/null || true
    exit 1
  fi

  echo "Waiting for ${DEVICE_ID}: state=${state}, boot=${boot_completed:-<empty>} ${spinner[$((i % 3))]}"
  i="$((i + 1))"
  sleep 4
done
