"""Qdrant 增量索引更新工具 - Git Hook 专用
轻量级增量更新脚本，设计用于 Git Hook 场景。

使用场景：
- post-commit: 提交代码后自动更新索引
- post-merge: 合并代码后同步索引
- CI/CD: 在持续集成流程中更新索引

特点：
- ✅ 轻量级：只处理指定的文件
- ✅ 快速：避免扫描整个仓库
- ✅ 非阻塞：失败不影响 Git 操作
- ✅ 静默模式：减少输出干扰

使用方式：
    # 更新单个文件
    python qdrant_incremental_update.py \
        --repo /path/to/repo \
        --files "src/main.py"

    # 更新多个文件（换行分隔）
    python qdrant_incremental_update.py \
        --repo /path/to/repo \
        --files "$(git diff-tree --no-commit-id --name-only -r HEAD)"

    # 静默模式
    python qdrant_incremental_update.py \
        --repo /path/to/repo \
        --files "src/main.py" \
        --quiet
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import List

from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from sentence_transformers import SentenceTransformer

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 支持的文件扩展名
SUPPORTED_EXTENSIONS = {
    ".py", ".rs", ".go", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".swift",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".xml", ".json"
}


class QuietMode:
    """静默模式上下文管理器"""

    def __enter__(self):
        self._original_level = logger.level
        logger.setLevel(logging.ERROR)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        logger.setLevel(self._original_level)


class QdrantIncrementalUpdater:
    """增量索引更新器 - Git Hook 专用"""

    def __init__(
        self,
        repo_path: Path,
        qdrant_path: Path,
        collection: str,
        model_name: str,
        quiet: bool = False,
    ):
        self.repo_path = repo_path.resolve()
        self.qdrant_path = qdrant_path.resolve()
        self.collection = collection
        self.quiet = quiet

        # Qdrant 客户端
        try:
            self.client = QdrantClient(path=str(qdrant_path))
        except Exception as e:
            self._log_error(f"无法连接 Qdrant: {e}")
            sys.exit(1)

        # 嵌入模型
        try:
            self._log_info(f"加载模型: {model_name}")
            self.model = SentenceTransformer(model_name)
        except Exception as e:
            self._log_error(f"无法加载模型: {e}")
            sys.exit(1)

        # 检查集合
        self._check_collection()

    def _log_info(self, msg: str) -> None:
        if not self.quiet:
            logger.info(msg)

    def _log_error(self, msg: str) -> None:
        logger.error(msg)

    def _check_collection(self) -> None:
        """检查集合是否存在"""
        try:
            collections = {c.name for c in self.client.get_collections().collections}
            if self.collection not in collections:
                raise RuntimeError(f"Collection '{self.collection}' not found")
        except Exception as e:
            self._log_error(f"集合检查失败: {e}")
            sys.exit(1)

    def _extract_fragments(self, file_path: Path, window: int = 80, stride: int = 60):
        """提取代码片段"""
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception:
            return []

        lines = text.splitlines()
        total_lines = len(lines)
        fragments = []
        idx = 0

        while idx < total_lines:
            segment = lines[idx : idx + window]
            if segment:
                snippet = "\n".join(segment)
                start = idx + 1
                end = min(idx + window, total_lines)

                frag_id = hashlib.md5(f"{file_path}:{start}:{end}".encode("utf-8")).hexdigest()

                fragments.append({
                    "id": frag_id,
                    "text": snippet,
                    "abs_path": str(file_path),
                    "rel_path": str(file_path.relative_to(self.repo_path)),
                    "language": file_path.suffix.lstrip("."),
                    "start_line": start,
                    "end_line": end,
                })
            idx += stride

        return fragments

    def update_files(self, file_paths: List[str]) -> dict:
        """更新指定的文件列表"""
        total_fragments = 0
        processed_files = 0
        skipped_files = 0

        for file_str in file_paths:
            if not file_str.strip():
                continue

            file_path = (self.repo_path / file_str).resolve()

            # 检查文件是否存在且支持
            if not file_path.exists():
                self._log_info(f"⊘ 跳过（不存在）: {file_str}")
                skipped_files += 1
                continue

            if file_path.suffix not in SUPPORTED_EXTENSIONS:
                self._log_info(f"⊘ 跳过（不支持）: {file_str}")
                skipped_files += 1
                continue

            try:
                self._log_info(f"→ 处理: {file_str}")

                # 提取片段
                fragments = self._extract_fragments(file_path)
                if not fragments:
                    self._log_info(f"  未提取到片段")
                    skipped_files += 1
                    continue

                # 生成向量
                texts = [frag["text"] for frag in fragments]
                embeddings = self.model.encode(
                    texts,
                    batch_size=64,
                    show_progress_bar=False,
                    normalize_embeddings=True
                )

                # Upsert 到 Qdrant
                self.client.upsert(
                    collection_name=self.collection,
                    points=rest.Batch(
                        ids=[frag["id"] for frag in fragments],
                        vectors=embeddings.tolist(),
                        payloads=[{
                            "path": frag["rel_path"],
                            "abs_path": frag["abs_path"],
                            "language": frag["language"],
                            "start_line": frag["start_line"],
                            "end_line": frag["end_line"],
                        } for frag in fragments],
                    ),
                )

                total_fragments += len(fragments)
                processed_files += 1
                self._log_info(f"  ✓ {len(fragments)} 个片段")

            except Exception as e:
                self._log_error(f"  ✗ 失败: {e}")
                skipped_files += 1

        return {
            "processed_files": processed_files,
            "skipped_files": skipped_files,
            "total_fragments": total_fragments,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qdrant 增量索引更新工具 - Git Hook 专用",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 更新单个文件
  python qdrant_incremental_update.py --repo . --files "src/main.py"

  # 更新 Git 变化的文件
  python qdrant_incremental_update.py --repo . \
    --files "$(git diff-tree --no-commit-id --name-only -r HEAD)"

  # 静默模式（适合 Git Hook）
  python qdrant_incremental_update.py --repo . --files "src/main.py" --quiet

Git Hook 集成:
  在 .git/hooks/post-commit 中添加:

    #!/bin/bash
    CHANGED_FILES=$(git diff-tree --no-commit-id --name-only -r HEAD)
    if [ -n "$CHANGED_FILES" ]; then
        python qdrant_incremental_update.py \\
            --repo "$(git rev-parse --show-toplevel)" \\
            --files "$CHANGED_FILES" \\
            --quiet || true
    fi
        """
    )
    parser.add_argument("--repo", required=True, help="Repository root path")
    parser.add_argument("--qdrant-path", default="./qdrant_storage", help="Qdrant storage directory")
    parser.add_argument("--collection", default="codebase", help="Collection name")
    parser.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2", help="Embedding model")
    parser.add_argument("--files", required=True, help="Files to update (newline-separated)")
    parser.add_argument("--quiet", "-q", action="store_true", help="Quiet mode (minimal output)")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    repo_path = Path(args.repo)
    if not repo_path.exists():
        logger.error(f"Repository not found: {repo_path}")
        sys.exit(1)

    # 解析文件列表
    file_list = [f.strip() for f in args.files.split('\n') if f.strip()]

    if not file_list:
        if not args.quiet:
            logger.info("没有文件需要更新")
        sys.exit(0)

    # 静默模式
    context = QuietMode() if args.quiet else type('obj', (object,), {'__enter__': lambda self: None, '__exit__': lambda self, *args: None})()

    with context:
        updater = QdrantIncrementalUpdater(
            repo_path=repo_path,
            qdrant_path=Path(args.qdrant_path),
            collection=args.collection,
            model_name=args.model,
            quiet=args.quiet,
        )

        logger.info(f"更新 {len(file_list)} 个文件...")
        result = updater.update_files(file_list)

        logger.info(f"✓ 完成: {result['processed_files']} 个文件, {result['total_fragments']} 个片段")
        if result['skipped_files'] > 0:
            logger.info(f"  跳过: {result['skipped_files']} 个文件")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n中断")
        sys.exit(130)
    except Exception as e:
        logger.error(f"错误: {e}")
        sys.exit(1)