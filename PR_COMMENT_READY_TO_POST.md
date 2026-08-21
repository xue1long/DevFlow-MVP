# 复制即用的 PR 评论

## 主评论（PR description 用）

复制 `PR_DESCRIPTION_SHORT.md` 全部内容到 GitHub PR description 框。

---

## 评论（PR 提交后立即发，@ reviewer）

```markdown
@<reviewer1> @<reviewer2> 请 review 这个 PR，谢谢！

📦 **提交概览**
- 11 commits / 25 文件 / +5262 行
- 190 passed + 1 skipped (research + 全套回归)
- mypy: 0 errors（research 新文件）
- ruff DTZ005/TRY004/F401/F541/F841: 全清

🎯 **本次 PR 内容**
- v0.4.0: 引文式调研子能力（plan 阶段自动跑 research）
- v0.4.1: 真实环境诊断暴露的 3 个并发边界 bug 修复
- RFC 草案: v0.4.2 缓存 + v0.4.3 自动喂 plan（不是本次实装，仅评审 RFC）

⏱️ **5 分钟快速判断**（详见 [REVIEWER_CHECKLIST.md](./REVIEWER_CHECKLIST.md)）
1. research 子能力是否符合 DevFlow 纪律（§7 零业务逻辑）？
2. v0.4.1 修复的 3 个 bug 是否足够稳健？
3. 是否认可 RFC v0.4.2 / v0.4.3 的方向？

🔗 **关键文档链接**
- PR 描述（短版）：[PR_DESCRIPTION_SHORT.md](./PR_DESCRIPTION_SHORT.md)
- PR 描述（详细版）：[PR_DESCRIPTION_V0.4_RESEARCH.md](./PR_DESCRIPTION_V0.4_RESEARCH.md)
- Reviewer checklist：[REVIEWER_CHECKLIST.md](./REVIEWER_CHECKLIST.md)
- Release notes：[docs/release-notes-v0.4.1.md](./docs/release-notes-v0.4.1.md)
- 诊断报告（v0.4.1 为何而修）：[docs/post-v0.4-research-diagnosis.md](./docs/post-v0.4-research-diagnosis.md)
- RFC v0.4.2（缓存）：[docs/rfc-v0.4.2-research-cache.md](./docs/rfc-v0.4.2-research-cache.md)
- RFC v0.4.3（自动喂 plan）：[docs/rfc-v0.4.3-auto-fill-goals.md](./docs/rfc-v0.4.3-auto-fill-goals.md)

🧪 **本地验证命令**
```bash
pytest tests/test_research_*.py -v                  # research 套件
pytest tests/test_research_*.py tests/test_state_machine.py -v  # + 回归
python scripts/diagnose_research.py "test query"   # 真实环境诊断
```

⏳ **预期反馈时间**
- 如方便请 1-3 天内反馈
- 若无暇也可延后，我会按节奏继续其他工作
```

---

## 评论（提交后第 2 天，提醒 reviewer）

如果 24 小时后没有反馈，发这个：

```markdown
👋 ping @<reviewer1> @<reviewer2>

如果方便的话，期待 review 反馈：
- 5 分钟快速版（看 PR 描述 + checklist 即可）
- 2 小时深度版（含跑测试 + 看 RFC 草案）

如果最近没时间，也可以告诉我，让我知道大致窗口 🙏
```

---

## 评论（提交后第 5 天，再次提醒）

如果还没反馈，发这个：

```markdown
Hi @<reviewer1> @<reviewer2>

再次提醒一下，本 PR 已等 5 天。如果实在忙不过来，告诉我，我可以：
1. 等到你方便（最常见）
2. 找其他 reviewer
3. 自审合并（不推荐，但紧急时可以）

任何一种回复都很有帮助 🙏
```

---

## 你具体要做的事（按顺序）

### 第 1 步：打开 PR 创建链接
```
https://github.com/xue1long/DevFlow-MVP/pull/new/feat/v0.4-research
```

### 第 2 步：粘贴 PR description
- 复制 `PR_DESCRIPTION_SHORT.md`（90 行）全部内容
- 粘贴到 "Add a description" 框
- 确认 base = `main`, compare = `feat/v0.4-research`

### 第 3 步：点击 "Create pull request"

### 第 4 步：发主评论（@ reviewer）
复制上面的"主评论（@ reviewer）"完整粘贴到 PR 评论框
- 替换 `@<reviewer1>` 为实际 reviewer 名字（GitHub @username）
- 替换 `@<reviewer2>` 为第二个 reviewer
- 提交评论

### 第 5 步：等反馈
- 1-3 天内：reviewer 反馈 → 处理
- 第 5 天还没反馈：发提醒评论（上面有模板）

---

## 如何选 reviewer

**理想 reviewer 画像**：
- ✅ 熟悉 DevFlow 引擎（state_machine / runner / cli）
- ✅ 熟悉适配层纪律（§7 零业务逻辑）
- ✅ 能看 RFC 设计（不需要会所有细节，能指出大方向问题）

**备选方案**：
- 找不到合适 reviewer → 找任何熟悉 Python + Pydantic 的同事
- 没有同事可找 → 等你有空时自审（不推荐，但可行）

**避免**：
- ❌ @ 太多人（> 3 个）→ reviewer 互相推诿
- ❌ @ 完全不熟悉代码的人 → 反馈质量低

---

## 提交后的工作（你可以同时做）

reviewer反馈通常 1-3 天，这段时间你可以：

| 选项 | 时间投入 | 价值 |
|---|---|---|
| **A. 等反馈 + 准备 v0.4.2 实装（dogfooding）** | 0.5-1 天 | 中 |
| **B. 等反馈 + 写迁移指南** | 0.5 天 | 中（v0.4.1 是 bugfix，不需要迁移指南，但可准备） |
| **C. 等反馈 + 别的项目** | - | - |
| **D. 等反馈 + 复盘整个流程** | 1-2 小时 | 高（沉淀方法论） |

我推荐 **A** —— 趁热打铁，用 DevFlow 自己管 v0.4.2 的开发（dogfooding）。

具体步骤：
1. `git checkout -b feat/v0.4.2-cache` 从 main（不是 v0.4-research）
2. 用 `devflow start` 创建 v0.4.2 的 Spec
3. 用 `devflow plan` 拆任务（按 RFC §13 DAG）
4. 逐任务实现 + 测试
5. 走完整流程（start → brainstorm → plan → contract → implement → verify → review → finish）

这样 reviewer 在 review v0.4.0/v0.4.1 时，你已经在做 v0.4.2 了。

---

**准备好了吗？**

如果你准备好了，我可以帮你做下一步：
- **A. 帮你写 v0.4.2 的 Spec（用 DevFlow start + 编辑 YAML）**
- **B. 帮你写 v0.4.2 的 Task DAG（用 devflow plan + task-add）**
- **C. 直接进入 v0.4.2 实现**
- **D. 别的**