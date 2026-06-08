# team-lark —— 一个 Agent 化的团队

把团队的**意识同步、对齐、状态管理**全部 Agent 化的 Claude Code / lark-cli skill。

每个人 = 人 + 他的 agent = 一个节点；所有节点连到**飞书多维表格**这个共享状态层。你跟自己的 agent 对话，agent 替你读写团队的共享真相——查任务、发起/指派、交付、验收、看全局进度，全用一句话搞定。

## 核心理念

- **飞书多维表格 = 团队的共享真相**：任务/状态/交付物都在这，全团队随时看到同一份状态。
- **关系，而非身份**：没有老板/员工这种固定角色。每件事上只有 **发起人 / 负责人 / 验收人**，随事而定、随时流转。
- **每次进入先对齐**：每次运行 skill，先读一遍共享状态，出一份「今日简报」（今天做了什么 + 所有没做的 + 等我验收的）。
- **状态机**：`待领取 → 进行中 → 待验收 →（验收人）→ 已完成 / 打回 →（回到）进行中`。

## 依赖

- [Claude Code](https://claude.com/claude-code)（或任何支持 skill 的 agent 环境）
- [`lark-cli`](https://github.com/larksuite)（飞书命令行；各人用自己的 `lark-cli auth login` OAuth 身份）

## 安装

把本仓库克隆到你的 skills 目录：

```bash
git clone https://github.com/ericshang98/team-lark.git ~/.claude/skills/team-lark
```

然后在 Claude Code 里运行 `/team-lark` 即可。

## 配置（自建团队请改成你自己的 Base 坐标）

`SKILL.md` 顶部「配置」段里的 `BASE_TOKEN` / 成员表 / 任务表 / 视图 ID，是某个具体团队的飞书多维表格坐标。**自己用请换成你团队自己的 Base**：建一个含「成员表（姓名/open_id/人设/负责模块）」+「任务表（标题/详情/发起人/负责人/验收人/验收条件/状态/优先级/截止日/交付物/…）」的多维表格，把对应 token 填进去即可。

## 许可

MIT
