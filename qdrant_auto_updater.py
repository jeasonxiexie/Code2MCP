"""Qdrant 自动索引更新器 - 实时文件监控版
基于 watchdog 监控代码库文件变化，实时更新 Qdrant 向量索引。

使用场景：
- 开发环境：代码保存即更新索引
- 实时协作：多人同时修改代码时保持索引同步
- 调试阶段：快速验证代码搜索效果

技术栈：
- watchdog: 跨平台文件系统事件监控
- Qdrant: 向量数据库（增量 upsert）
- SentenceTransformer: 代码嵌入模型

使用方式：
    python qdrant_auto_updater.py \
        --repo /path/to/repo \
        --qdrant-path ./qdrant_storage \
        --collection codebase \
        --debounce 3  # 3 秒防抖

特性：
- ✅ 真正的实时更新（文件保存即索引）
- ✅ 智能防抖（避免频繁触发）
- ✅ 增量更新（只索引变化的文件）
- ✅ 哈希校验（避免重复索引）
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Dict, Set

from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from sentence_transformers import SentenceTransformer
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 支持的文件扩展名
SUPPORTED_EXTENSIONS = {
    ".py", ".rs", ".go", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".swift",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".xml", ".json"
}


class QdrantAutoUpdater(FileSystemEventHandler):
    """实时文件监控 + 自动索引更新"""

    def __init__(
        self,
        repo_path: Path,
        qdrant_path: Path,
        collection: str,
        model_name: str,
        debounce_seconds: float = 2.0,
    ):
        self.repo_path = repo_path.resolve()
        self.qdrant_path = qdrant_path.resolve()
        self.collection = collection
        self.model_name = model_name
        self.debounce_seconds = debounce_seconds

        # Qdrant 客户端
        self.client = QdrantClient(path=str(qdrant_path))

        # 嵌入模型
        logger.info(f"📦 加载嵌入模型: {model_name}")
        self.model = SentenceTransformer(model_name)
        logger.info("✓ 模型加载完成")

        # 文件哈希缓存
        self.hash_cache_file = qdrant_path / f"{collection}_watcher_hashes.json"
        self.file_hashes: Dict[str, str] = self._load_hash_cache()

        # 防抖机制：记录待处理的文件
        self.pending_files: Set[Path] = set()
        self.last_trigger_time: float = 0

        # 检查集合
        self._check_collection()

    def _check_collection(self) -> None:
        """检查 Qdrant 集合是否存在"""
        collections = {c.name for c in self.client.get_collections().collections}
        if self.collection not in collections:
            raise RuntimeError(
                f"Collection '{self.collection}' not found. Run qdrant_codebase_indexer.py first."
            )
        logger.info(f"✓ 集合已找到: {self.collection}")

    def _load_hash_cache(self) -> Dict[str, str]:
        """加载文件哈希缓存"""
        if self.hash_cache_file.exists():
            try:
                with open(self.hash_cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"无法加载哈希缓存: {e}")
        return {}

    def _save_hash_cache(self) -> None:
        """保存文件哈希缓存"""
        try:
            with open(self.hash_cache_file, 'w') as f:
                json.dump(self.file_hashes, f, indent=2)
        except Exception as e:
            logger.error(f"保存哈希缓存失败: {e}")

    def _compute_file_hash(self, file_path: Path) -> str:
        """计算文件 MD5 哈希"""
        hasher = hashlib.md5()
        try:
            with open(file_path, 'rb') as f:
                hasher.update(f.read())
            return hasher.hexdigest()
        except Exception:
            return ""

    def _should_process_file(self, file_path: Path) -> bool:
        """判断文件是否应该被处理"""
        if not file_path.exists() or not file_path.is_file():
            return False

        if file_path.suffix not in SUPPORTED_EXTENSIONS:
            return False

        # 跳过隐藏目录
        if any(part.startswith(".") for part in file_path.parts):
            return False

        # 检查哈希
        current_hash = self._compute_file_hash(file_path)
        if not current_hash:
            return False

        file_str = str(file_path)
        if file_str in self.file_hashes and self.file_hashes[file_str] == current_hash:
            return False  # 文件未变化

        return True

    def _extract_fragments(self, file_path: Path, window: int = 80, stride: int = 60):
        """提取代码片段（滑动窗口）"""
        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
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

    def _index_file(self, file_path: Path) -> int:
        """索引单个文件"""
        try:
            logger.info(f"📝 处理文件: {file_path.relative_to(self.repo_path)}")

            # 提取片段
            fragments = self._extract_fragments(file_path)
            if not fragments:
                logger.warning(f"   未提取到代码片段，跳过")
                return 0

            # 生成向量
            texts = [frag["text"] for frag in fragments]
            embeddings = self.model.encode(
                texts,
                batch_size=64,
                show_progress_bar=False,
                normalize_embeddings=True
            )

            # 增量 upsert 到 Qdrant
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

            # 更新哈希缓存
            file_str = str(file_path)
            self.file_hashes[file_str] = self._compute_file_hash(file_path)

            logger.info(f"   ✅ 已更新 {len(fragments)} 个代码片段")
            return len(fragments)

        except Exception as e:
            logger.error(f"   ❌ 索引失败: {e}")
            return 0

    def process_pending_files(self) -> None:
        """处理待处理的文件队列"""
        if not self.pending_files:
            return

        current_time = time.time()
        if current_time - self.last_trigger_time < self.debounce_seconds:
            # 还在防抖期间，稍后再处理
            return

        logger.info(f"🔄 处理 {len(self.pending_files)} 个待更新文件...")

        total_fragments = 0
        files_to_process = list(self.pending_files)
        self.pending_files.clear()

        for file_path in files_to_process:
            if self._should_process_file(file_path):
                fragments_count = self._index_file(file_path)
                total_fragments += fragments_count

        if total_fragments > 0:
            self._save_hash_cache()
            logger.info(f"✅ 索引更新完成: {total_fragments} 个片段")

        self.last_trigger_time = current_time

    # ========== Watchdog 事件处理 ==========

    def on_modified(self, event: FileSystemEvent) -> None:
        """文件修改事件"""
        if event.is_directory:
            return

        file_path = Path(event.src_path)
        if file_path.suffix in SUPPORTED_EXTENSIONS:
            logger.debug(f"🔔 检测到文件修改: {file_path.name}")
            self.pending_files.add(file_path)

    def on_created(self, event: FileSystemEvent) -> None:
        """文件创建事件"""
        if event.is_directory:
            return

        file_path = Path(event.src_path)
        if file_path.suffix in SUPPORTED_EXTENSIONS:
            logger.debug(f"🔔 检测到新文件: {file_path.name}")
            self.pending_files.add(file_path)

    def start_watching(self) -> None:
        """启动文件监控"""
        logger.info("=" * 60)
        logger.info("🚀 Qdrant 自动索引更新器")
        logger.info("=" * 60)
        logger.info(f"📂 监控目录: {self.repo_path}")
        logger.info(f"🗄️  Qdrant 集合: {self.collection}")
        logger.info(f"🧠 嵌入模型: {self.model_name}")
        logger.info(f"⏱️  防抖间隔: {self.debounce_seconds} 秒")
        logger.info("=" * 60)

        observer = Observer()
        observer.schedule(self, str(self.repo_path), recursive=True)
        observer.start()

        logger.info("👀 文件监控已启动，等待代码变化...")
        logger.info("按 Ctrl+C 停止")

        try:
            while True:
                time.sleep(1)
                self.process_pending_files()
        except KeyboardInterrupt:
            logger.info("\n🛑 收到停止信号...")
            observer.stop()

        observer.join()
        logger.info("✓ 监控已停止")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qdrant 自动索引更新器 - 实时文件监控",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基础用法
  python qdrant_auto_updater.py --repo /path/to/repo --collection codebase

  # 自定义防抖时间（5 秒）
  python qdrant_auto_updater.py --repo /path/to/repo --collection codebase --debounce 5

依赖:
  pip install qdrant-client sentence-transformers watchdog
        """
    )
    parser.add_argument("--repo", required=True, help="Path to repository root")
    parser.add_argument("--qdrant-path", default="./qdrant_storage", help="Qdrant storage directory")
    parser.add_argument("--collection", default="codebase", help="Collection name")
    parser.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2", help="Embedding model")
    parser.add_argument("--debounce", type=float, default=2.0, help="Debounce interval in seconds")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    repo_path = Path(args.repo)
    if not repo_path.exists():
        raise SystemExit(f"❌ Repository not found: {repo_path}")

    updater = QdrantAutoUpdater(
        repo_path=repo_path,
        qdrant_path=Path(args.qdrant_path),
        collection=args.collection,
        model_name=args.model,
        debounce_seconds=args.debounce,
    )

    updater.start_watching()


if __name__ == "__main__":
    main()