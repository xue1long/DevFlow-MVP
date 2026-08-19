# DevFlow 文档规范（v0.1）

> 本文件约定 DevFlow 项目的文档命名、归档、版本号管理。
> 适用于 `docs/` 目录下所有内容，以及代码注释中引用的外部文档链接。

## 1. 命名风格

### 1.1 文件名规则

| 规则 | 说明 | 示例 |
|------|------|------|
| **主用英文** | 文件名优先英文（kebab-case），便于 grep / 国际化 | `review-loop-v0.2-design.md` |
| **中文别名可选** | 重要中文文档可在文件名后加中文别名（便于人读） | `audit-ledger.md`（主）+ README 注明"审计整改台账" |
| **kebab-case** | 多个单词用 `-` 连接，不使用空格或下划线 | ✅ `code-review-guide.md`，❌ `code_review_guide.md` |

### 1.2 文件名组成

```
{主题}-{子主题?}-{版本?}-{类型?}.md
```

- **主题**：必选，单词或短语（如 `review-loop` / `audit-ledger` / `devflow-mvp-brief`）
- **子主题**：可选，进一步限定（如 `review-loop-stagnation`）
- **版本**：可选，格式 `-v0.X`（仅在内容强依赖版本时使用）
- **类型**：可选，常用类型后缀

### 1.3 类型后缀

| 后缀 | 含义 | 示例 |
|------|------|------|
| `-design.md` | 设计文档 | `review-loop-v0.2-design.md` |
| `-guide.md` | 使用指南 | `devflow-cli-guide.md` |
| `-brief.md` | 简报/摘要 | `devflow-mvp-brief.md` |
| `-report.md` | 报告/审计 | `audit-ledger.md`（台账是周期性报告） |
| `-guidelines.md` | 规范/约定 | `docs-guidelines.md`（本文件） |
| `-index.md` | 索引/目录 | `docs-index.md` |

## 2. 归档目录

### 2.1 一级目录

```
docs/                          ← 所有项目文档（含设计、报告、规范、归档）
├── README.md                  ← docs/ 索引（子目录文档列表）
├── DOCS_GUIDELINES.md         ← 本文件（文档规范）
├── CHANGELOG.md               ← 全项目变更日志（含代码+文档）
└── {主题}-{子主题?}-...md     ← 具体文档
```

### 2.2 docs/ 索引文件

- 必含 `docs/README.md` 作为入口索引，列出所有文档 + 一句话说明
- 文档内部用相对路径交叉引用（如 `[MVP 简报](./devflow-mvp-brief.md)`）
- README 引用文档时用 `docs/` 前缀（如 `[设计文档](./docs/devflow-architecture-v0.1.md)`）

### 2.3 仓库外文档

- **禁止**：`D:\5-Project\20260819\` 等仓库根目录直接放文档（不进 git，新会话不可见）
- **必须**：所有文档归档到 `docs/`，随代码进 git

## 3. 版本号约定

### 3.1 何时在文件名中带版本

| 场景 | 是否带版本 | 理由 |
|------|------------|------|
| 设计文档（涉及 API/接口） | ✅ 必带 | 不同版本可能不兼容 |
| 简报/总结 | ❌ 不带 | 内容稳定，更新频率低 |
| 规范/指南 | ✅ 必带 | 规则可能演进 |
| 报告/审计（台账） | ❌ 不带 | append-only，版本信息在内容中 |
| CHANGELOG | ❌ 不带 | 自身就是版本日志 |

### 3.2 版本号格式

- 使用 `-v0.X`（X 为整数，如 `-v0.2`、`-v0.3`）
- 跟随项目主版本（如 DevFlow v0.2 → 设计文档 `-v0.2-design`）
- 同一主题不兼容版本共存：保留旧版，新版单独命名

## 4. 文档内容规范

### 4.1 文档开头模板

```markdown
# {标题}

> **类型**：{设计/简报/规范/报告/...}  **版本**：{v0.X 或 N/A}  **最后更新**：{YYYY-MM-DD}

---

## 摘要（一段话）

{本文档的核心结论或目的，1-2 句话}

## 目录
1. ...
2. ...

## 正文
...
```

### 4.2 状态标记

| 标记 | 含义 | 使用 |
|------|------|------|
| `✅ 已修复` | 审计问题已修复 | 整改记录 |
| `📌 登记残余风险` | 暂不修复但有补偿措施 | 残余清单 |
| `⏳ 待处理` | 已识别但未处理 | 新发现的问题 |
| `❌ 已废弃` | 不再生效（保留以追溯） | 旧方案 |

### 4.3 链接约定

- 文档内部链接用相对路径：`[审计台账](./audit-ledger.md)`
- 跨文档引用代码：`[FSBackend](../src/devflow/storage/fs_backend.py)`
- 外部 URL 必须配 markdown 链接文本：`[GitHub](https://github.com/xue1long/DevFlow-MVP)`

## 5. CHANGELOG 约定

### 5.1 文件位置

`docs/CHANGELOG.md`（与代码 git commit 独立的人类可读变更日志）

### 5.2 格式（Keep a Changelog 风格）

```markdown
# Changelog

所有值得用户注意的变更都记录在这里。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

## [v0.2.1] - 2026-XX-XX

### Added（新增）
- 新增 `plan` / `task-add` / `contract-add` CLI 命令
- 新增 README.md 上手指南

### Changed（变更）
- status 命令返回 Spec/Plan 摘要
- cross_module_import 红线改用正则精确解析

### Fixed（修复）
- 修复账本并发写竞态（P0-2 文件锁）
- 修复 review 报告可被覆写问题（P1-14）

### Deprecated（废弃）
- （暂无）

### Removed（移除）
- （暂无）

### Security（安全）
- 命令执行增加危险模式拦截（P0-7）
- git commit 增加敏感文件检查（P0-8）

[v0.2.1]: https://github.com/xue1long/DevFlow-MVP/compare/v0.2.0...v0.2.1
```

### 5.3 维护时机

- 每次 git 推送前：人工填写 CHANGELOG "Unreleased" 段落
- 推送完成后：将 "Unreleased" 改为具体版本号（如 `v0.2.1`）+ 日期
- **禁止**：仅靠 git commit 信息（机器可读但不利于扫读）

## 6. 命名迁移映射

| 旧文件名（仓库外） | 新文件名（docs/） |
|---|---|
| `D:\5-Project\20260819\开发工作流引擎架构文档.md` | `docs/devflow-architecture-v0.1.md` |
| `D:\5-Project\20260819\DevFlow-MVP-实现简报.md` | `docs/devflow-mvp-brief.md` |
| `D:\5-Project\20260819\DevFlow-MVP-首轮审计报告.md` | `docs/devflow-first-audit-report-v0.1.md` |
| `D:\5-Project\20260819\MVP-门禁降级矩阵.md` | `docs/mvp-gate-degradation-matrix-v0.1.md` |
| `D:\5-Project\20260819\审计整改台账.md` | `docs/audit-ledger.md` |
| 仓库内 `docs\方案审核闭环-v0.2设计.md` | `docs/review-loop-v0.2-design.md` |
| 仓库内 `docs\审计流程提示词.md` | `docs/audit-prompt-template-v0.1.md` |

## 7. 文档归档 SOP

新增文档时：

```
1. 命名：按 §1 规则
2. 位置：docs/ 下（除非是 README）
3. 头部：按 §4.1 模板
4. 索引：在 docs/README.md 添加一行链接
6. CHANGELOG：在 §5 的 Unreleased 段落记录
5. 提交：git commit -m "docs: 新增 <文件>"6. 推送：git push origin main
```

---

**本规范版本**：v0.1（2026-XX-XX）
**维护者**：DevFlow 项目主控
**下次审视**：v0.3 发布前