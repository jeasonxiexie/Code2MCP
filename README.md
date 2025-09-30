# Code2MCP

## Project Overview

![Code2MCP Workflow Overview](figs/overview.png)

Code2MCP is an automated workflow system that transforms existing code repositories into MCP (Model Context Protocol) services. The system follows a minimal intrusion principle, preserving the original repository's core code while only adding service-related files and tests.

## 🆕 Enhanced with Vector Semantic Search

This fork extends the original Code2MCP with **Qdrant-based vector semantic search capabilities**, enabling AI agents to understand and navigate codebases through natural language queries.

### What's New

- **🔍 Semantic Code Search**: Search codebases using natural language descriptions
- **🤖 AI-Powered Understanding**: Vector embeddings capture code semantics and relationships
- **🔄 Auto-Update System**: 4 strategies to keep your code index synchronized
- **⚡ Real-time Monitoring**: File changes trigger instant index updates
- **🎯 Git Integration**: Automatic index updates on commits and merges

**Use Cases**:
- "Find the MQTT message handling logic" → Locates relevant code instantly
- "Show me user authentication flow" → Identifies LoginViewModel, AuthRepository
- "How is error handling implemented?" → Discovers exception patterns across the codebase

## Core Features

1. **Intelligent Code Analysis**
   - LLM-powered deep code structure analysis
   - Automatic identification of core modules, functions, and classes
   - Smart generation of MCP service code

2. **MCP Service Generation**
   - Automatic generation of `mcp_service.py`, `adapter.py`, and other core files
   - Support for multiple project structures (src/, source/, root directory, etc.)
   - Intelligent handling of import paths and dependency relationships

3. **Workflow Automation**
   - Complete 7-node workflow: download → analysis → env → generate → run → review → finalize
   - Automatic environment configuration and test validation
   - Comprehensive logging and status tracking
   - Intelligent error recovery and retry mechanisms

4. **🆕 Vector Semantic Search** _(New in this fork)_
   - **Qdrant Vector Database**: Local-mode storage with 384-dimensional embeddings
   - **Natural Language Queries**: Search code using plain English descriptions
   - **MCP Integration**: Seamlessly works with Claude Code and other AI agents
   - **Auto-Update System**: 4 synchronization strategies (real-time, scheduled, Git hooks, manual)
   - **Incremental Indexing**: Hash-based change detection for efficient updates

## Quick Start

### 1. Environment Setup

Copy the environment variables template:
```bash
cp env_example.txt .env
```
Edit the `.env` file to configure necessary environment variables.

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run Workflow

```bash
# Basic usage
python main.py https://github.com/username/repo

# Specify output directory
python main.py https://github.com/username/repo --output ./my_output
```

### 4. 🆕 Quick Start: Vector Semantic Search

```bash
# Additional dependencies for vector search
pip install qdrant-client sentence-transformers watchdog

# Step 1: Index your codebase
python qdrant_codebase_indexer.py \
  --repo /path/to/your/repo \
  --collection my_project

# Step 2: Start MCP service with auto-update
python qdrant_codebase_mcp.py \
  --repo /path/to/your/repo \
  --collection my_project \
  --auto-update \
  --port 8890

# Step 3: Configure in Claude Code (~/.claude/mcp.json)
{
  "mcpServers": {
    "my-codebase-search": {
      "url": "http://localhost:8890/mcp"
    }
  }
}

# Now ask Claude: "Find the user login implementation"
```

## Workflow Process

1. **Download Node**: Clone repository to `workspace/{repo_name}/`
2. **Analysis Node**: LLM deep analysis of code structure and functionality
3. **Env Node**: Create isolated environment and validate original project
4. **Generate Node**: Intelligently generate MCP service code
5. **Run Node**: Execute service and perform functional validation
6. **Review Node**: Code quality review, error analysis, and automatic fixes
7. **Finalize Node**: Compile results and generate comprehensive report

## Output Structure

Complete structure for each converted project:

![Output Structure](figs/Output-Structure.png)

## Successfully Converted Project Examples

- **UFL**: Finite element symbolic language → MCP finite element analysis
- **dalle-mini**: Higher-quality, controllable text-to-image → MCP image generation
- **ESM**: Protein structure/variant scoring (real artifacts) → MCP protein analysis
- **deep-searcher**: Query rewrite, multi-hop, credible sources → MCP search
- **TextBlob**: Deterministic tokenize/POS/sentiment → MCP NLP preprocessing
- **dateutil**: Correct timezones/rrule edge cases → MCP time utilities
- **sympy**: Exact symbolic math/solve/codegen → MCP math reasoning

## 🔍 Vector Semantic Search (New Feature)

### Architecture

```
Code Repository
    ↓
[Indexer] → Extract code fragments (sliding window: 80 lines)
    ↓
[SentenceTransformer] → Generate 384-dim embeddings
    ↓
[Qdrant Local DB] → Store vectors + metadata
    ↓
[MCP Service] → Expose search API to AI agents
    ↓
Claude Code / Cursor → Natural language queries
```

### 4 Auto-Update Strategies

| Strategy | Latency | Resource | Use Case | Command |
|----------|---------|----------|----------|---------|
| **MCP Built-in** | 0-30 min | Low | Claude Code | `--auto-update --update-interval 30` |
| **Real-time Watcher** | <1 sec | High | Development | `python qdrant_auto_updater.py` |
| **Git Hooks** | On commit | Very Low | Team Collaboration | `./install_git_hooks.sh /path/to/repo` |
| **Manual Trigger** | Instant | Very Low | Flexible Control | Claude: "Update index" |

### Available MCP Tools

When you enable the vector search MCP service, these tools become available:

- **`search_code(query, top_k)`**: Semantic code search using natural language
- **`read_resource(path, start_line, end_line)`**: Read specific file content
- **`collection_info()`**: View index statistics and health
- **`trigger_index_update()`**: Manually trigger index refresh
- **`index_status()`**: Check auto-update configuration and timing

### Example Workflows

#### Scenario 1: Understanding a New Codebase
```
You: "How is database connection handled in this project?"
Claude: [Uses search_code] → Finds DBConnection class, connection pool logic
Claude: [Uses read_resource] → Shows complete implementation with context
```

#### Scenario 2: Debugging
```
You: "Find all error handling related to file operations"
Claude: [Uses search_code with "file operation error handling"]
        → Locates try-catch blocks, error classes, logging calls
```

#### Scenario 3: Refactoring
```
You: "Show me all authentication middleware"
Claude: [Uses search_code] → Identifies auth decorators, middleware classes
You: "Update the index after I modified auth.py"
Claude: [Uses trigger_index_update] → Index refreshed instantly
```

## Key Features

- **Smart Import Handling**: Automatic identification of correct module import paths
- **Professional Documentation**: Automatic generation of English README and comments
- **Comprehensive Test Coverage**: Includes basic functionality tests and health checks
- **Detailed Report Generation**: Provides complete conversion process reports
- **Intelligent Dependency Management**: Automatic handling of complex Python package dependencies

## Usage Example

```bash
# Original Code2MCP workflow
python main.py https://github.com/username/repo

# With vector semantic search
python qdrant_codebase_indexer.py --repo /path/to/repo
python qdrant_codebase_mcp.py --repo /path/to/repo --auto-update
```

## Using Converted MCP Services with Your AI Agent

You can configure MCP services converted by Code2MCP for use in your AI agent (e.g., Cursor). Below are instructions and some examples to help you get started.

### Example Pre-Converted MCP Services

Here are a few examples you can use right away:

-   **ESM**: For advanced protein analysis and structure prediction.
    ```json
    "esm": {
      "url": "https://kabuda777-Code2MCP-esm.hf.space/mcp"
    }
    ```

-   **SymPy**: For powerful symbolic and numerical mathematics.
    ```json
    "sympy": {
      "url": "https://kabuda777-Code2MCP-sympy.hf.space/mcp"
    }
    ```

### How to Configure in Cursor

1.  **Open MCP Configuration File**: Navigate to your AI agent's configuration file. For Cursor, this is located at: `c:\Users\[Username]\.cursor\mcp.json`.

2.  **Add Your New Tool**: In the `mcpServers` object, copy and paste the configuration snippet for the tool you want to add from the list above.

3.  **Reload Configuration**: Restart Cursor or use its reload function to apply the changes. Your new MCP tool will now be available.

-----

## 中文说明

### 🆕 向量语义搜索增强版

此 fork 在原版 Code2MCP 基础上增加了 **基于 Qdrant 的向量语义搜索功能**，让 AI 助手能够通过自然语言理解和检索代码库。

### 核心增强

- **🔍 语义代码搜索**：用自然语言描述需求，智能定位相关代码
- **🤖 AI 驱动理解**：向量嵌入捕获代码语义和关系
- **🔄 自动更新系统**：4 种策略保持索引同步
- **⚡ 实时监控**：文件变化触发即时索引更新
- **🎯 Git 集成**：提交和合并时自动更新索引

### 快速开始

```bash
# 1. 安装额外依赖
pip install qdrant-client sentence-transformers watchdog

# 2. 索引代码库
python qdrant_codebase_indexer.py \
  --repo /path/to/your/repo \
  --collection my_project

# 3. 启动 MCP 服务（带自动更新）
python qdrant_codebase_mcp.py \
  --repo /path/to/your/repo \
  --collection my_project \
  --auto-update \
  --port 8890

# 4. 在 Claude Code 配置 (~/.claude/mcp.json)
{
  "mcpServers": {
    "my-codebase-search": {
      "url": "http://localhost:8890/mcp"
    }
  }
}

# 5. 现在可以问 Claude："找到用户登录的实现"
```

### 4 种自动更新方案

| 方案 | 延迟 | 资源 | 适用场景 | 启动方式 |
|------|------|------|----------|----------|
| **MCP 内置** | 0-30 分钟 | 低 | Claude Code | `--auto-update --update-interval 30` |
| **实时监控** | <1 秒 | 高 | 开发环境 | `python qdrant_auto_updater.py` |
| **Git Hooks** | 提交时 | 极低 | 团队协作 | `./install_git_hooks.sh /path/to/repo` |
| **手动触发** | 立即 | 极低 | 灵活控制 | Claude: "更新索引" |

### 可用的 MCP 工具

启用向量搜索 MCP 服务后，以下工具可用：

- **`search_code(query, top_k)`**：使用自然语言进行语义代码搜索
- **`read_resource(path, start_line, end_line)`**：读取特定文件内容
- **`collection_info()`**：查看索引统计信息和健康状态
- **`trigger_index_update()`**：手动触发索引刷新
- **`index_status()`**：检查自动更新配置和时间

### 使用示例

#### 场景 1：理解新代码库
```
你："这个项目是如何处理数据库连接的？"
Claude：[使用 search_code] → 找到 DBConnection 类、连接池逻辑
Claude：[使用 read_resource] → 显示完整实现和上下文
```

#### 场景 2：调试
```
你："找到所有与文件操作相关的错误处理"
Claude：[使用 search_code 搜索 "文件操作错误处理"]
        → 定位 try-catch 块、错误类、日志调用
```

#### 场景 3：重构
```
你："显示所有认证中间件"
Claude：[使用 search_code] → 识别 auth 装饰器、中间件类
你："我修改了 auth.py 后更新索引"
Claude：[使用 trigger_index_update] → 索引立即刷新
```

### 技术架构

```
代码仓库
    ↓
[索引器] → 提取代码片段（滑动窗口：80 行）
    ↓
[SentenceTransformer] → 生成 384 维向量嵌入
    ↓
[Qdrant 本地数据库] → 存储向量 + 元数据
    ↓
[MCP 服务] → 向 AI 代理暴露搜索 API
    ↓
Claude Code / Cursor → 自然语言查询
```

### 核心特性

- **哈希校验**：MD5 文件指纹避免重复索引
- **增量更新**：只重新索引变化的文件
- **滑动窗口**：80 行窗口 / 60 行步长提取代码
- **防抖机制**：可配置防抖间隔避免频繁触发
- **向后兼容**：默认关闭自动更新，不影响原有功能

### 详细文档

查看 [`CLAUDE.md`](CLAUDE.md) 获取完整的实现细节、API 文档和最佳实践。

-----

## Citation

If you use Code2MCP in your research, please cite our paper:

```bibtex
@article{ouyang2025code2mcp,
  title={Code2MCP: A Multi-Agent Framework for Automated Transformation of Code Repositories into Model Context Protocol Services},
  author={Ouyang, Chaoqian and Yue, Ling and Di, Shimin and Zheng, Libin and Pan, Shaowu and Zhang, Min-Ling},
  journal={arXiv preprint arXiv:2509.05941},
  year={2025}
}
```



