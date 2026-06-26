#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export PYTHONPYCACHEPREFIX="$SCRIPT_DIR/__pycache__"
export PYTHONUNBUFFERED=1

pause_if_interactive() {
    if [[ -t 0 ]]; then
        read -r -p "按回车键退出..."
    fi
}

install_python_packages() {
    local packages=("$@")
    if [[ -n "${VIRTUAL_ENV:-}" || -n "${CONDA_PREFIX:-}" ]]; then
        python3 -m pip install "${packages[@]}"
    else
        python3 -m pip install --user "${packages[@]}"
    fi
}

echo "=========================================="
echo "  人民法院案例库 - 民事案例增量更新"
echo "=========================================="
echo ""
echo "正在检查依赖..."

if ! command -v python3 &> /dev/null; then
    echo "错误：未找到 Python3，请安装后重试"
    pause_if_interactive
    exit 1
fi

if ! python3 -m pip --version &> /dev/null; then
    echo "错误：当前 Python3 缺少 pip，无法自动安装依赖"
    pause_if_interactive
    exit 1
fi

if [[ ! -f "$SCRIPT_DIR/scrape_rmfyalk_civil_cases.py" ]]; then
    echo "错误：缺少脚本文件 scrape_rmfyalk_civil_cases.py"
    pause_if_interactive
    exit 1
fi

echo "检查依赖包..."
if ! python3 -c "import requests, bs4, markdownify" 2>/dev/null; then
    echo "正在安装依赖包 (requests, beautifulsoup4, markdownify)..."
    install_python_packages requests beautifulsoup4 markdownify
fi

echo ""
echo "开始更新人民法院案例库民事案例数据..."
echo "=========================================="

python3 "$SCRIPT_DIR/scrape_rmfyalk_civil_cases.py"

echo ""
echo "=========================================="
echo "更新完成！"
echo "=========================================="
echo ""
pause_if_interactive
