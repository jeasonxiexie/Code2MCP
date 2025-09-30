#!/bin/bash
# Qdrant 向量索引自动更新 - Git Hook 安装脚本
#
# 功能：
# - 自动安装 post-commit 和 post-merge Hook
# - 在代码提交/合并时自动更新向量索引
# - 支持多仓库安装
#
# 使用方式：
#   ./install_git_hooks.sh /path/to/repo [collection_name]
#
# 示例：
#   ./install_git_hooks.sh ~/workspace/my-project my_project

set -e

# ==================== 配置 ====================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPDATER_SCRIPT="$SCRIPT_DIR/qdrant_incremental_update.py"
QDRANT_PATH="$SCRIPT_DIR/qdrant_storage"
PYTHON_CMD="${PYTHON_CMD:-python3}"

# ==================== 颜色输出 ====================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

success() {
    echo -e "${GREEN}✓${NC} $1"
}

warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

error() {
    echo -e "${RED}✗${NC} $1"
}

# ==================== 参数解析 ====================
if [ $# -lt 1 ]; then
    error "用法: $0 <repo_path> [collection_name]"
    echo ""
    echo "示例:"
    echo "  $0 ~/workspace/my-project"
    echo "  $0 ~/workspace/my-project my_collection"
    exit 1
fi

REPO_PATH="$1"
COLLECTION_NAME="${2:-codebase}"

# 检查仓库是否存在
if [ ! -d "$REPO_PATH" ]; then
    error "仓库不存在: $REPO_PATH"
    exit 1
fi

# 检查是否是 Git 仓库
if [ ! -d "$REPO_PATH/.git" ]; then
    error "不是有效的 Git 仓库: $REPO_PATH"
    exit 1
fi

# 检查更新脚本是否存在
if [ ! -f "$UPDATER_SCRIPT" ]; then
    error "找不到更新脚本: $UPDATER_SCRIPT"
    exit 1
fi

# ==================== 生成 Hook 内容 ====================
generate_post_commit_hook() {
    cat <<'HOOK_END'
#!/bin/bash
# Qdrant 向量索引自动更新 - post-commit Hook
# 在每次 git commit 后自动更新变化文件的索引

REPO_ROOT=$(git rev-parse --show-toplevel)
HOOK_END

    # 插入配置变量
    echo "UPDATER_SCRIPT=\"$UPDATER_SCRIPT\""
    echo "QDRANT_PATH=\"$QDRANT_PATH\""
    echo "COLLECTION=\"$COLLECTION_NAME\""
    echo "PYTHON_CMD=\"$PYTHON_CMD\""
    echo ""

    cat <<'HOOK_END'
# 获取本次提交变化的文件
CHANGED_FILES=$(git diff-tree --no-commit-id --name-only -r HEAD)

if [ -z "$CHANGED_FILES" ]; then
    echo "📚 [Qdrant] 无文件变化，跳过索引更新"
    exit 0
fi

echo "📚 [Qdrant] 更新向量索引..."

# 调用更新脚本（静默模式）
$PYTHON_CMD "$UPDATER_SCRIPT" \
    --repo "$REPO_ROOT" \
    --qdrant-path "$QDRANT_PATH" \
    --collection "$COLLECTION" \
    --files "$CHANGED_FILES" \
    --quiet || {
        echo "⚠️  [Qdrant] 索引更新失败（已忽略，不影响提交）"
    }

exit 0
HOOK_END
}

generate_post_merge_hook() {
    cat <<'HOOK_END'
#!/bin/bash
# Qdrant 向量索引自动更新 - post-merge Hook
# 在每次 git merge 后自动更新变化文件的索引

REPO_ROOT=$(git rev-parse --show-toplevel)
HOOK_END

    # 插入配置变量
    echo "UPDATER_SCRIPT=\"$UPDATER_SCRIPT\""
    echo "QDRANT_PATH=\"$QDRANT_PATH\""
    echo "COLLECTION=\"$COLLECTION_NAME\""
    echo "PYTHON_CMD=\"$PYTHON_CMD\""
    echo ""

    cat <<'HOOK_END'
# 获取合并前的 commit
PREVIOUS_HEAD=$(git rev-parse ORIG_HEAD)
CURRENT_HEAD=$(git rev-parse HEAD)

# 获取两次 commit 之间变化的文件
CHANGED_FILES=$(git diff-tree --no-commit-id --name-only -r $PREVIOUS_HEAD $CURRENT_HEAD)

if [ -z "$CHANGED_FILES" ]; then
    echo "📚 [Qdrant] 无文件变化，跳过索引更新"
    exit 0
fi

echo "📚 [Qdrant] 合并后更新向量索引..."

# 调用更新脚本（静默模式）
$PYTHON_CMD "$UPDATER_SCRIPT" \
    --repo "$REPO_ROOT" \
    --qdrant-path "$QDRANT_PATH" \
    --collection "$COLLECTION" \
    --files "$CHANGED_FILES" \
    --quiet || {
        echo "⚠️  [Qdrant] 索引更新失败（已忽略）"
    }

exit 0
HOOK_END
}

# ==================== 安装 Hook ====================
install_hook() {
    local hook_name=$1
    local hook_path="$REPO_PATH/.git/hooks/$hook_name"
    local backup_path="${hook_path}.backup.$(date +%s)"

    info "安装 $hook_name Hook..."

    # 备份现有 Hook
    if [ -f "$hook_path" ]; then
        warn "发现现有 Hook，备份到: $backup_path"
        cp "$hook_path" "$backup_path"
    fi

    # 生成并写入 Hook
    if [ "$hook_name" = "post-commit" ]; then
        generate_post_commit_hook > "$hook_path"
    elif [ "$hook_name" = "post-merge" ]; then
        generate_post_merge_hook > "$hook_path"
    fi

    # 设置执行权限
    chmod +x "$hook_path"

    success "$hook_name Hook 已安装"
}

# ==================== 主流程 ====================
echo "════════════════════════════════════════════════════════════"
echo "  Qdrant 向量索引自动更新 - Git Hook 安装器"
echo "════════════════════════════════════════════════════════════"
echo ""
info "仓库路径: $REPO_PATH"
info "集合名称: $COLLECTION_NAME"
info "更新脚本: $UPDATER_SCRIPT"
info "Qdrant 路径: $QDRANT_PATH"
echo ""

# 检查 Python 和依赖
info "检查 Python 环境..."
if ! command -v $PYTHON_CMD &> /dev/null; then
    error "未找到 Python ($PYTHON_CMD)"
    exit 1
fi
success "Python: $($PYTHON_CMD --version)"

# 检查必要的 Python 包
$PYTHON_CMD -c "import qdrant_client; import sentence_transformers" 2>/dev/null || {
    warn "未检测到所需 Python 包"
    echo "  请运行: pip install qdrant-client sentence-transformers"
    read -p "  是否继续安装 Hook？(y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
}

# 安装 Hooks
echo ""
install_hook "post-commit"
install_hook "post-merge"

echo ""
echo "════════════════════════════════════════════════════════════"
success "Git Hooks 安装完成！"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "📝 接下来的步骤："
echo ""
echo "1. 确保已构建初始索引:"
echo "   python qdrant_codebase_indexer.py \\"
echo "     --repo \"$REPO_PATH\" \\"
echo "     --qdrant-path \"$QDRANT_PATH\" \\"
echo "     --collection \"$COLLECTION_NAME\""
echo ""
echo "2. 提交代码时索引会自动更新:"
echo "   cd \"$REPO_PATH\""
echo "   git add ."
echo "   git commit -m \"Update code\""
echo "   # 索引自动更新"
echo ""
echo "3. 如需禁用自动更新:"
echo "   git commit --no-verify"
echo ""
echo "4. 如需卸载 Hooks:"
echo "   rm \"$REPO_PATH/.git/hooks/post-commit\""
echo "   rm \"$REPO_PATH/.git/hooks/post-merge\""
echo ""

exit 0