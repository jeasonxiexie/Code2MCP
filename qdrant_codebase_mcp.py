"""Felo Search Android 代码库智能索引 MCP 服务
基于 Qdrant 向量数据库的语义代码搜索服务，为 Claude Code 提供代码理解能力。

核心能力：
- 语义搜索：用自然语言描述需求，智能定位相关代码
- 精确读取：获取完整文件或指定行范围的代码
- 索引状态：查看代码库覆盖情况和健康状态
- 🆕 自动更新：检测代码变化并自动更新索引

技术栈：
- 向量数据库：Qdrant (本地模式)
- 嵌入模型：sentence-transformers/all-MiniLM-L6-v2 (384维)
- 相似度计算：余弦相似度
- 通信协议：SSE (Server-Sent Events)

使用方式：
1. 运行索引器建立代码库索引
2. 启动 MCP 服务（支持自动更新）：

    python qdrant_codebase_mcp.py \
        --repo /Users/you/Documents/workspace/felo-search-android \
        --qdrant-path ./qdrant_storage \
        --collection felo_android \
        --port 8890 \
        --auto-update \
        --update-interval 30  # 30 分钟检查一次

3. 在 ~/.claude/mcp.json 中注册服务端点 (http://localhost:8890/mcp)

索引覆盖：
- felo-search-android: 7703+ 代码片段
- 支持 Kotlin, Java, XML, JSON 等多语言
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from fastmcp import FastMCP
from qdrant_client import QdrantClient
from qdrant_client.http import models as rest
from qdrant_client.http.models import Distance
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

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


class QdrantCodebaseService:
    def __init__(
        self,
        repo_path: Path,
        qdrant_path: Path,
        collection: str,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        auto_update: bool = False,
        update_interval_minutes: int = 30,
    ) -> None:
        self.repo_path = repo_path.resolve()
        self.qdrant_path = qdrant_path.resolve()
        self.client = QdrantClient(path=str(self.qdrant_path))
        self.collection = collection
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        self.mcp = FastMCP("qdrant-codebase")

        # 自动更新配置
        self.auto_update = auto_update
        self.update_interval = update_interval_minutes * 60  # 转换为秒
        self.last_check_time: datetime | None = None
        self.update_task: asyncio.Task | None = None

        # 文件哈希缓存
        self.hash_cache_file = self.qdrant_path / f"{collection}_file_hashes.json"
        self.file_hashes: Dict[str, str] = self._load_hash_cache()

        self._check_collection()
        self._register_tools()

        if auto_update:
            logger.info(f"🔄 自动更新已启用，间隔: {update_interval_minutes} 分钟")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _check_collection(self) -> None:
        collections = {c.name for c in self.client.get_collections().collections}
        if self.collection not in collections:
            raise RuntimeError(
                f"Collection '{self.collection}' not found. Was the indexer run?"
            )

        info = self.client.get_collection(self.collection)
        vectors = info.config.params.vectors
        if vectors is None or vectors.distance != Distance.COSINE:
            raise RuntimeError(
                "Collection distance must be COSINE to match query embeddings."
            )

    def _encode(self, text: str) -> List[float]:
        vector = self.model.encode([text], normalize_embeddings=True)[0]
        return vector.tolist()

    def _resolve_path(self, payload_path: str | None, payload_abs: str | None) -> Path:
        if payload_abs:
            abs_path = Path(payload_abs)
            if abs_path.exists():
                return abs_path
        if payload_path:
            candidate = (self.repo_path / payload_path).resolve()
            if candidate.exists():
                return candidate
        return self.repo_path / (payload_path or "")

    def _read_snippet(self, payload: Dict[str, Any]) -> str:
        file_path = self._resolve_path(payload.get("path"), payload.get("abs_path"))
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return "(file not found)"

        start = max(payload.get("start_line", 1) - 1, 0)
        end = payload.get("end_line") or start + 1
        snippet = "\n".join(lines[start:end])
        return snippet

    # ------------------------------------------------------------------
    # Auto-update helpers
    # ------------------------------------------------------------------
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

    def _iter_source_files(self) -> List[Path]:
        """遍历源代码文件"""
        files = []
        for path in self.repo_path.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            # 跳过隐藏目录
            if any(part.startswith(".") for part in path.parts):
                continue
            files.append(path)
        return files

    def _find_modified_files(self) -> List[Path]:
        """查找修改过的文件"""
        modified_files = []
        all_files = self._iter_source_files()

        for file_path in all_files:
            file_str = str(file_path)
            current_hash = self._compute_file_hash(file_path)

            if not current_hash:
                continue

            # 检查是否有变化
            if file_str not in self.file_hashes or self.file_hashes[file_str] != current_hash:
                modified_files.append(file_path)
                self.file_hashes[file_str] = current_hash

        return modified_files

    def _extract_fragments(self, file_path: Path, window: int = 80, stride: int = 60) -> List[Dict[str, Any]]:
        """从单个文件提取代码片段（滑动窗口方式）"""
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

                # 生成唯一 ID
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

    async def _incremental_update(self) -> Dict[str, Any]:
        """执行增量索引更新"""
        logger.info("🔍 检查代码变化...")
        self.last_check_time = datetime.now()

        modified_files = self._find_modified_files()

        if not modified_files:
            logger.info("✓ 代码无变化")
            return {"updated": False, "files_count": 0, "fragments_count": 0}

        logger.info(f"📝 发现 {len(modified_files)} 个文件有更新")

        # 提取所有变化文件的片段
        all_fragments = []
        for file_path in modified_files:
            fragments = self._extract_fragments(file_path)
            all_fragments.extend(fragments)

        if not all_fragments:
            return {"updated": False, "files_count": len(modified_files), "fragments_count": 0}

        # 生成向量
        logger.info(f"🧠 生成向量嵌入 ({len(all_fragments)} 个片段)...")
        texts = [frag["text"] for frag in all_fragments]
        embeddings = self.model.encode(texts, batch_size=64, show_progress_bar=False, normalize_embeddings=True)

        # 增量 upsert 到 Qdrant
        logger.info("☁️  更新向量数据库...")
        batch_size = 64
        for i in range(0, len(all_fragments), batch_size):
            batch = all_fragments[i : i + batch_size]
            vecs = embeddings[i : i + batch_size].tolist()

            self.client.upsert(
                collection_name=self.collection,
                points=rest.Batch(
                    ids=[frag["id"] for frag in batch],
                    vectors=vecs,
                    payloads=[{
                        "path": frag["rel_path"],
                        "abs_path": frag["abs_path"],
                        "language": frag["language"],
                        "start_line": frag["start_line"],
                        "end_line": frag["end_line"],
                    } for frag in batch],
                ),
            )

        # 保存哈希缓存
        self._save_hash_cache()

        logger.info(f"✅ 索引更新完成: {len(all_fragments)} 个片段")
        return {
            "updated": True,
            "files_count": len(modified_files),
            "fragments_count": len(all_fragments),
            "updated_files": [str(f.relative_to(self.repo_path)) for f in modified_files]
        }

    async def _auto_update_loop(self) -> None:
        """后台自动更新循环"""
        logger.info(f"🚀 启动自动更新循环 (间隔: {self.update_interval / 60:.1f} 分钟)")

        while True:
            try:
                await asyncio.sleep(self.update_interval)
                result = await self._incremental_update()

                if result["updated"]:
                    logger.info(f"🔄 自动更新完成: {result['fragments_count']} 个片段")
            except Exception as e:
                logger.error(f"❌ 自动更新失败: {e}")

    # ------------------------------------------------------------------
    # MCP tool registration
    # ------------------------------------------------------------------
    def _register_tools(self) -> None:
        @self.mcp.tool()
        async def search_code(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
            """语义搜索代码库 - 使用自然语言描述功能需求，智能定位相关代码片段。

            适用场景：
            - "MQTT 消息发送逻辑" → 找到消息发布、订阅、连接相关代码
            - "用户登录流程" → 定位 LoginViewModel, AuthRepository 等
            - "主题颜色管理" → 找到 Theme.kt, CustomColor.kt
            - "多步骤 Agent 执行流程" → 定位完整的执行链路

            与传统工具的区别：
            - Grep: 精确文本匹配 (已知关键字)
            - Glob: 文件名模式匹配 (已知路径)
            - search_code: 语义理解搜索 (用需求描述找实现)
            """

            vector = self._encode(query)
            hits = self.client.search(
                collection_name=self.collection,
                query_vector=vector,
                limit=top_k,
                with_payload=True,
            )

            results: List[Dict[str, Any]] = []
            for hit in hits:
                payload = hit.payload or {}
                snippet = self._read_snippet(payload)
                results.append(
                    {
                        "score": float(hit.score),
                        "path": payload.get("path"),
                        "abs_path": payload.get("abs_path"),
                        "language": payload.get("language"),
                        "start_line": payload.get("start_line"),
                        "end_line": payload.get("end_line"),
                        "snippet": snippet,
                    }
                )
            return results

        @self.mcp.tool()
        async def read_resource(path: str, start_line: int = 1, end_line: int | None = None) -> Dict[str, Any]:
            """精确读取代码文件 - 获取指定文件的完整代码或特定行范围。

            用途：
            - 配合 search_code 使用：先语义搜索定位，再精确读取完整上下文
            - 查看完整文件内容：不指定行号范围
            - 读取特定代码段：指定 start_line 和 end_line

            示例：
            - read_resource("app/src/main/java/...SearchViewModel.kt") → 完整文件
            - read_resource("...Theme.kt", start_line=30, end_line=50) → 30-50行
            """

            file_path = self._resolve_path(path, None).resolve()
            if not file_path.exists():
                return {"error": f"File not found: {file_path}"}

            text = file_path.read_text(encoding="utf-8")
            if end_line is None and start_line <= 1:
                return {"path": str(file_path), "content": text}

            lines = text.splitlines()
            start = max(start_line - 1, 0)
            end = end_line if end_line is not None else len(lines)
            snippet = "\n".join(lines[start:end])
            return {
                "path": str(file_path),
                "start_line": start_line,
                "end_line": end_line or len(lines),
                "content": snippet,
            }

        @self.mcp.tool()
        async def collection_info() -> Dict[str, Any]:
            """查看代码索引状态 - 返回 Qdrant 向量数据库的健康状态和统计信息。

            包含信息：
            - points_count: 已索引的代码片段数量
            - vectors_count: 向量数量
            - vector_size: 向量维度 (384维语义向量)
            - distance_metric: 距离计算方式 (余弦相似度)
            - collection_status: 集合健康状态

            用途：
            - 检查索引是否完整
            - 了解代码库覆盖范围
            - 诊断搜索问题
            """

            info = self.client.get_collection(self.collection)
            description = info.dict()
            return json.loads(json.dumps(description, default=str))

        @self.mcp.tool()
        async def trigger_index_update() -> Dict[str, Any]:
            """🔄 手动触发索引更新 - 立即检查代码变化并更新向量库。

            用途：
            - 在大量修改代码后立即同步索引
            - 不想等待自动更新间隔时手动触发
            - 验证索引更新功能是否正常工作

            返回：
            - updated: 是否有更新
            - files_count: 更新的文件数量
            - fragments_count: 更新的代码片段数量
            - updated_files: 更新的文件列表

            示例使用场景：
            - 用户: "我刚修改了 LoginViewModel，帮我更新一下索引"
            - Claude: [调用 trigger_index_update] 索引已更新，包含 3 个文件的 42 个代码片段
            """

            logger.info("📢 收到手动更新请求")
            result = await self._incremental_update()
            return result

        @self.mcp.tool()
        async def index_status() -> Dict[str, Any]:
            """📊 查看索引更新状态 - 返回自动更新配置和运行状态。

            包含信息：
            - auto_update_enabled: 自动更新是否启用
            - update_interval_minutes: 更新检查间隔（分钟）
            - last_check_time: 最后检查时间
            - next_check_in_seconds: 距离下次检查的秒数
            - total_indexed_files: 已索引的文件总数
            - total_vectors: 向量总数

            用途：
            - 了解自动更新配置
            - 查看最后更新时间
            - 预估下次更新时间
            - 调试索引问题

            示例使用场景：
            - 用户: "索引多久更新一次？"
            - Claude: [调用 index_status] 自动更新已启用，每 30 分钟检查一次，上次检查在 15 分钟前
            """

            info = self.client.get_collection(self.collection)

            next_check_seconds = None
            if self.auto_update and self.last_check_time:
                elapsed = (datetime.now() - self.last_check_time).total_seconds()
                next_check_seconds = max(0, self.update_interval - elapsed)

            return {
                "auto_update_enabled": self.auto_update,
                "update_interval_minutes": self.update_interval / 60,
                "last_check_time": self.last_check_time.isoformat() if self.last_check_time else None,
                "next_check_in_seconds": next_check_seconds,
                "total_indexed_files": len(self.file_hashes),
                "total_vectors": info.points_count,
                "model_name": self.model_name,
                "collection_name": self.collection,
            }

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------
    def serve(self, port: int) -> None:
        async def run_service():
            host = "0.0.0.0"
            logger.info(f"🚀 启动 Qdrant Codebase MCP 服务")
            logger.info(f"   服务地址: http://{host}:{port}/mcp")
            logger.info(f"   代码库: {self.repo_path}")
            logger.info(f"   集合: {self.collection}")
            logger.info(f"   模型: {self.model_name}")

            if self.auto_update:
                logger.info(f"   自动更新: 已启用 (间隔: {self.update_interval / 60:.0f} 分钟)")
                # 启动后台更新任务
                self.update_task = asyncio.create_task(self._auto_update_loop())
            else:
                logger.info("   自动更新: 未启用")

            logger.info("=" * 60)
            logger.info("可用工具:")
            logger.info("  - search_code: 语义搜索代码")
            logger.info("  - read_resource: 读取文件内容")
            logger.info("  - collection_info: 查看索引状态")
            logger.info("  - trigger_index_update: 手动触发更新")
            logger.info("  - index_status: 查看更新状态")
            logger.info("=" * 60)

            # 使用 SSE 传输模式
            await self.mcp.run(transport="sse", host=host, port=port)

        asyncio.run(run_service())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run MCP server backed by Qdrant with auto-update support",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 启动服务（无自动更新）
  python qdrant_codebase_mcp.py --repo /path/to/repo --collection codebase

  # 启动服务并启用自动更新（每 30 分钟）
  python qdrant_codebase_mcp.py --repo /path/to/repo --collection codebase --auto-update

  # 自定义更新间隔（每 10 分钟）
  python qdrant_codebase_mcp.py --repo /path/to/repo --collection codebase --auto-update --update-interval 10
        """
    )
    parser.add_argument("--repo", required=True, help="Path to repository root used during indexing")
    parser.add_argument("--qdrant-path", default="./qdrant_storage", help="Directory where Qdrant local data lives")
    parser.add_argument("--collection", default="codebase", help="Collection name")
    parser.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2", help="Embedding model (must match indexer)")
    parser.add_argument("--port", type=int, default=8890, help="HTTP port for MCP server")
    parser.add_argument("--auto-update", action="store_true", help="Enable automatic index updates")
    parser.add_argument("--update-interval", type=int, default=30, help="Auto-update interval in minutes (default: 30)")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    repo_path = Path(args.repo)
    if not repo_path.exists():
        raise SystemExit(f"Repository not found: {repo_path}")

    service = QdrantCodebaseService(
        repo_path=repo_path,
        qdrant_path=Path(args.qdrant_path),
        collection=args.collection,
        model_name=args.model,
        auto_update=args.auto_update,
        update_interval_minutes=args.update_interval,
    )
    service.serve(args.port)


if __name__ == "__main__":
    main()
