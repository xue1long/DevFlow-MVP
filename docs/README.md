# DevFlow 文档索引

> DevFlow 项目的全部文档入口。所有变更记录在 [`CHANGELOG.md`](./CHANGELOG.md)。

## 核心文档

| 文档 | 类型 | 版本 | 说明 |
|------|------|------|------|
| [README.md](../README.md) | 上手指南 | — | 安装、5 分钟上手、CLI 速查、架构图 |
| [DOCS_GUIDELINES.md](./DOCS_GUIDELINES.md) | 规范 | v0.1 | 文档命名 + 归档 + 版本号约定 |
| [CHANGELOG.md](./CHANGELOG.md) | 变更日志 | — | v0.1 / v0.2 / v0.2.1 完整变更 |

## 设计文档

| 文档 | 版本 | 说明 |
|------|------|------|
| [devflow-architecture-v0.1.md](./devflow-architecture-v0.1.md) | v0.1 | 整体架构设计（分层、模块、CLI） |
| [devflow-mvp-brief.md](./devflow-mvp-brief.md) | — | MVP 实现简报（功能清单 + 验收） |
| [review-loop-v0.2-design.md](./review-loop-v0.2-design.md) | v0.2 | 审核闭环 v0.2 设计（review/fix/历史） |
| [mvp-gate-degradation-matrix-v0.1.md](./mvp-gate-degradation-matrix-v0.1.md) | v0.1 | MVP 阶段门禁降级矩阵 |

## 审计与流程

| 文档 | 类型 | 说明 |
|------|------|------|
| [devflow-first-audit-report-v0.1.md](./devflow-first-audit-report-v0.1.md) | 审计报告 | 第 1 轮首轮审计（独立第三方） |
| [audit-ledger.md](./audit-ledger.md) | 审计台账 | 全部轮次审计 + 整改 + 复评 + 残余风险 |
| [audit-prompt-template-v0.1.md](./audit-prompt-template-v0.1.md) | 提示词模板 | 4 角色评审 + 复核 + 整改 SOP |

## 项目结构

```
devflow/
├── README.md              ← 项目入口
├── docs/                  ← 本目录
│   ├── README.md          ← 本文件（索引）
│   ├── DOCS_GUIDELINES.md ← 文档规范
│   ├── CHANGELOG.md       ← 变更日志
│   ├── audit-ledger.md    ← 审计整改台账
│   ├── audit-prompt-template-v0.1.md
│   ├── devflow-architecture-v0.1.md
│   ├── devflow-mvp-brief.md
│   ├── devflow-first-audit-report-v0.1.md
│   ├── mvp-gate-degradation-matrix-v0.1.md
│   └── review-loop-v0.2-design.md
├── src/devflow/           ← 源代码
├── tests/                 ← 测试
├── config/                ← SOP 默认配置
└── pyproject.toml
```

## 文档更新 SOP

新增/修改文档时：

1. 命名按 [`DOCS_GUIDELINES.md`](./DOCS_GUIDELINES.md) 规则
2. 修改后**必须**同步：
   - 本索引（README.md）添加/更新链接
   - [`CHANGELOG.md`](./CHANGELOG.md) Unreleased 段落记录
3. `git commit -m "docs: <变更摘要>"`
4. `git push origin main`