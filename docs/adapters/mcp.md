# DevFlow MCP Server 配置指南

> v0.3 集成面之 MCP（v0.3.3 起，B 阶段实施）
> 状态：✅ 已落地（B1 阶段，2026-08-20）

## 概述

DevFlow 引擎可通过 **MCP Server** 暴露给任意 MCP Host（Claude Desktop、Cursor、Continue.dev、Zed 等）。所有 CLI 命令自动派生为 MCP tools，**无需手写 manifest**。

## 安装

```bash
# 安装 MCP Server 依赖（fastmcp 是 optional 依赖）
pip install 'devflow[mcp]'

# 或一次性装所有可选依赖
pip install 'devflow[all]'
```

验证：

```bash
devflow-mcp-server --help
# 启动后进入 stdio 模式，无 --help 输出是正常的
```

## MCP Host 配置

### Claude Desktop

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`（macOS）
或 `%APPDATA%\Claude\claude_desktop_config.json`（Windows）：

```json
{
  "mcpServers": {
    "devflow": {
      "command": "devflow-mcp-server",
      "args": []
    }
  }
}
```

### Cursor

编辑 `~/.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "devflow": {
      "command": "devflow-mcp-server"
    }
  }
}
```

### Continue.dev

编辑 `~/.continue/config.json`：

```json
{
  "experimental": {
    "modelContextProtocolServers": [
      {
        "name": "devflow",
        "command": "devflow-mcp-server"
      }
    ]
  }
}
```

## 使用方式

配置完成后，MCP Host 会自动发现 DevFlow 的 24 个 tools（如 `devflow.status`、`devflow.review`、`devflow.commit` 等）。

LLM 调用示例：

```
用户：请查看当前工作流状态
Claude：[调用 devflow.status tool]
      [返回 JSON 状态]
Claude：当前在 Stage 0 (intake)，无活跃 Spec。
```

## 工作目录

`devflow-mcp-server` 默认在**当前工作目录**（`cwd`）作为 DevFlow workspace 启动。**启动 MCP Host 时确保 `cwd` 是 DevFlow 工作区根目录**（含 `sop.yaml`、`specs/`、`plans/`、`progress.yaml`）。

## 可用 tools

所有 DevFlow CLI 命令自动注册为 MCP tools。当前 24 个：

| Tool 名 | 对应 CLI 命令 | 用途 |
|---------|--------------|------|
| `devflow.init` | `devflow init` | 初始化工作区 |
| `devflow.start` | `devflow start` | 创建 Spec 草稿 |
| `devflow.approve` | `devflow approve` | 校验 Spec 字段 |
| `devflow.next` | `devflow next` | 推进到下一阶段 |
| `devflow.status` | `devflow status` | 查看当前状态 |
| `devflow.review` | `devflow review` | 执行双轴评审 |
| `devflow.fix` | `devflow fix` | 修复违规 |
| `devflow.commit` | `devflow commit` | 提交 task |
| `devflow.audit` | `devflow audit` | 执行红线审计 |
| ... | ... | （其余 15 个命令自动派生） |

**所有 manifest 由 `build_manifests_from_cli()` 自动派生**——CLI 加命令后 MCP tools 自动同步，零手写。

## 故障排查

### 入口脚本找不到

```bash
# 验证 pip 安装位置
python -m pip show -f devflow

# 应看到：
#   ..\..\Scripts\devflow-mcp-server.exe
```

如未找到，重装：

```bash
pip install --force-reinstall --no-deps 'devflow[mcp]'
```

### fastmcp 未安装

```bash
pip install 'devflow[mcp]'
# 或单独安装
pip install 'fastmcp>=0.4.0'
```

### 工作目录错误

MCP Server 在启动时的 `cwd` 启动。如果 Claude Desktop / Cursor 在用户目录启动 MCP，DevFlow 会找不到 `sop.yaml`。

**解决方法**：在 MCP Host 配置中显式设置 `cwd`（Claude Desktop 不支持，Cursor 支持）：

```json
{
  "mcpServers": {
    "devflow": {
      "command": "devflow-mcp-server",
      "cwd": "/path/to/devflow-workspace"
    }
  }
}
```

或使用 `bash -c` 包装：

```json
{
  "mcpServers": {
    "devflow": {
      "command": "bash",
      "args": ["-c", "cd /path/to/devflow-workspace && devflow-mcp-server"]
    }
  }
}
```

## 实现细节

| 组件 | 路径 | 说明 |
|------|------|------|
| `EngineInvoker` 抽象 | `src/devflow/adapters/invoker.py` | 统一调用接口 |
| `InProcessEngineInvoker` | 同上 | 同进程 typer app 调用（MCP Server 用） |
| `CliEngineInvoker` | 同上 | subprocess 调用（C2 阶段实现） |
| `build_manifests_from_cli` | `src/devflow/adapters/manifest_builder.py` | CLI → manifest 自动派生 |
| `create_server` | `src/devflow/adapters/mcp_server.py` | MCP Server 工厂 |
| `_build_tool_fn` | 同上 | manifest → MCP tool 动态函数 |

## v0.3 纪律

- ✅ Manifest 必须从 cli.py 自动派生（v0.3 INDEX 教训）
- ✅ 适配层不实现业务逻辑
- ✅ devflow 编排 Agent，不实现 Agent
- ✅ 平台差异在 detect() 层处理（**B 阶段扩展：detect() 待 SDD/MCP Host 真实用户出现时再做**）

## 相关文档

- [架构文档 §6 双集成面](../devflow-architecture-v0.1.md)
- [v0.3 落地实施方案 v4](../../graphify-out/memory/v0.3-implementation-v4.md)