#!/usr/bin/env bash
#
# 一键启动入口（自动提权），等价于 sudo ./setup_schedule.sh
# 首次运行会装依赖、生成配置、注册每日定时任务；之后无需再管。
#
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ${EUID} -ne 0 ]]; then
    exec sudo -E "${DIR}/setup_schedule.sh" "$@"
fi
exec "${DIR}/setup_schedule.sh" "$@"
