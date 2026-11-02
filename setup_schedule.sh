#!/usr/bin/env bash
#
# 一键部署：安装依赖 + 生成配置 + 注册 systemd 定时任务。
# 装好之后无需再手动操作：每天固定时段自动跑指定时长，cookie 自动续期并落盘。
#
# 用法:
#   sudo ./setup_schedule.sh                        # 每天 08:17 开始，目标 60 分钟
#   sudo TARGET_MINUTES=45 RUN_TIME=21:30 ./setup_schedule.sh
#   sudo RUN_NOW=1 ./setup_schedule.sh              # 装完立刻先跑一次
#   sudo ./setup_schedule.sh --uninstall            # 卸载定时任务
#
set -euo pipefail

SERVICE_NAME="weread-bot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
TIMER_FILE="/etc/systemd/system/${SERVICE_NAME}.timer"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"
TARGET_MINUTES="${TARGET_MINUTES:-60}"
RUN_TIME="${RUN_TIME:-08:17}"
RUN_NOW="${RUN_NOW:-auto}"   # auto: 首次安装时立即跑一次；1: 总是立即跑；0: 不跑

log() { printf '✅ %s\n' "$*"; }
die() { printf '❌ %s\n' "$*" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || die "请用 root 运行（需要写入 /etc/systemd/system）"

if [[ "${1:-}" == "--uninstall" ]]; then
    systemctl disable --now "${SERVICE_NAME}.timer" 2>/dev/null || true
    rm -f "${SERVICE_FILE}" "${TIMER_FILE}"
    systemctl daemon-reload
    log "已卸载 ${SERVICE_NAME}.timer / ${SERVICE_NAME}.service"
    exit 0
fi

[[ -n "${PYTHON_BIN}" ]] || die "找不到 python3"
[[ -f "${REPO_DIR}/weread-bot.py" ]] || die "找不到 ${REPO_DIR}/weread-bot.py"

# ---------- 依赖：系统 Python 可用就直接用，否则建 .venv ----------
if ! "${PYTHON_BIN}" -c 'import httpx, yaml, croniter, requests' 2>/dev/null; then
    log "系统 Python 缺少依赖，改用项目 .venv"
    if [[ ! -x "${REPO_DIR}/.venv/bin/python" ]]; then
        "${PYTHON_BIN}" -m venv "${REPO_DIR}/.venv" \
            || die "创建 venv 失败，请先安装 python3-venv"
        "${REPO_DIR}/.venv/bin/pip" install -q --upgrade pip
        "${REPO_DIR}/.venv/bin/pip" install -q -r "${REPO_DIR}/requirements.txt" \
            || die "依赖安装失败"
    fi
    PYTHON_BIN="${REPO_DIR}/.venv/bin/python"
    "${PYTHON_BIN}" -c 'import httpx, yaml, croniter, requests' \
        || die "依赖仍不完整，请检查 ${REPO_DIR}/requirements.txt"
fi

# ---------- 参数校验 ----------
[[ "${RUN_TIME}" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]] \
    || die "RUN_TIME 格式应为 HH:MM，例如 08:17"
[[ "${TARGET_MINUTES}" =~ ^[1-9][0-9]*$ ]] \
    || die "TARGET_MINUTES 应为正整数（分钟）"

# ---------- 配置：不存在就生成，存在则同步目标时长 ----------
if [[ ! -f "${REPO_DIR}/config.yaml" ]]; then
    cat > "${REPO_DIR}/config.yaml" <<EOF
app:
  startup_mode: "immediate"
  startup_delay: "0-10"

curl_config:
  file_path: "curl_command.txt"

reading:
  target_duration: "${TARGET_MINUTES}-${TARGET_MINUTES}"
  reading_interval: "25-35"

network:
  timeout: 30
  retry_times: 2
  rate_limit: 10

notification:
  enabled: false

logging:
  level: "INFO"
  file: "logs/weread.log"
  console: true
EOF
    log "已生成 config.yaml"
elif grep -qE '^[[:space:]]*target_duration:' "${REPO_DIR}/config.yaml"; then
    sed -i -E "s/^([[:space:]]*target_duration:[[:space:]]*).*/\1\"${TARGET_MINUTES}-${TARGET_MINUTES}\"    # 每次目标记入时长（分钟）/" \
        "${REPO_DIR}/config.yaml"
elif ! grep -qE '^[[:space:]]*reading:' "${REPO_DIR}/config.yaml"; then
    printf '\nreading:\n  target_duration: "%s-%s"\n' "${TARGET_MINUTES}" "${TARGET_MINUTES}" \
        >> "${REPO_DIR}/config.yaml"
else
    die "config.yaml 的 reading 段缺少 target_duration，请手动添加后再运行"
fi
grep -q "target_duration: \"${TARGET_MINUTES}-${TARGET_MINUTES}\"" "${REPO_DIR}/config.yaml" \
    || die "未能设置 config.yaml 的 target_duration"
log "config.yaml 目标时长 = ${TARGET_MINUTES} 分钟"

# ---------- CURL：唯一需要人工提供一次的文件 ----------
[[ -f "${REPO_DIR}/curl_command.txt" ]] \
    || die "缺少 curl_command.txt：请在浏览器登录 weread.qq.com 后抓一份 /web/book/read 的 cURL 保存到 ${REPO_DIR}/curl_command.txt（只需一次）"

FIRST_INSTALL=0
[[ ! -f "${TIMER_FILE}" ]] && FIRST_INSTALL=1

# ---------- systemd unit ----------
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=WeRead daily auto-reading (${TARGET_MINUTES} min credit)
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=6h
StartLimitBurst=2

[Service]
Type=oneshot
WorkingDirectory=${REPO_DIR}
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONIOENCODING=utf-8
ExecStart=${PYTHON_BIN} ${REPO_DIR}/weread-bot.py --config ${REPO_DIR}/config.yaml
Restart=on-failure
RestartSec=10min
TimeoutStartSec=3h
Nice=10
EOF

cat > "${TIMER_FILE}" <<EOF
[Unit]
Description=Daily WeRead auto-reading at ${RUN_TIME}

[Timer]
OnCalendar=*-*-* ${RUN_TIME}:00
RandomizedDelaySec=600
AccuracySec=1min
Persistent=true
Unit=${SERVICE_NAME}.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.timer"
systemctl restart "${SERVICE_NAME}.timer"

log "定时任务已安装：每天 ${RUN_TIME} 启动，目标 ${TARGET_MINUTES} 分钟（随机延迟 0-10 分钟）"
systemctl list-timers "${SERVICE_NAME}.timer" --no-pager

# ---------- 首次安装可选立即跑一次 ----------
if [[ "${RUN_NOW}" == "1" ]] || [[ "${RUN_NOW}" == "auto" && ${FIRST_INSTALL} -eq 1 ]]; then
    systemctl start --no-block "${SERVICE_NAME}.service"
    log "已立即启动第一次阅读（可关闭终端，日志: journalctl -u ${SERVICE_NAME} -f）"
else
    echo
    echo "现在无需任何操作，到点会自动运行。"
fi

echo
echo "查看日志: journalctl -u ${SERVICE_NAME} -f"
echo "立即执行: systemctl start --no-block ${SERVICE_NAME}.service"
echo "卸载任务: ${REPO_DIR}/setup_schedule.sh --uninstall"
