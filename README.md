# team-lark —— 一个 Agent 化的团队

把团队的**意识同步、对齐、状态管理**全部 Agent 化的 Claude Code / lark-cli skill。

每个人 = 人 + 他的 agent = 一个节点；所有节点连到**飞书多维表格**这个共享状态层。你跟自己的 agent 对话，agent 替你读写团队的共享真相——查任务、发起/指派、交付、验收、看全局进度，全用一句话搞定。

## 核心理念

- **飞书多维表格 = 团队的共享真相**：任务/状态/交付物都在这，全团队随时看到同一份状态。
- **关系，而非身份**：没有老板/员工这种固定角色。每件事上只有 **发起人 / 负责人 / 验收人**，随事而定、随时流转。
- **每次进入先对齐**：每次运行 skill，先读一遍共享状态，出一份「今日简报」（今天做了什么 + 所有没做的 + 等我验收的）。
- **状态机**：`待领取 → 进行中 → 待验收 →（验收人）→ 已完成 / 打回 →（回到）进行中`。

---

## 快速开始

### 1. 装依赖

- [Claude Code](https://claude.com/claude-code)（或任何支持 skill 的 agent 环境）
- [`lark-cli`](https://github.com/larksuite/cli)：`npm i -g @larksuite/cli`（或按官方 README）

### 2. 装 skill

```bash
git clone https://github.com/ericshang98/team-lark.git ~/.claude/skills/team-lark
```

### 3. 建一个飞书自建应用（团队只需建一个，全员共用）

> 这一步是给 `lark-cli` 一个 OAuth 客户端 + 权限容器。**整个团队一个应用就够**，每个人各自登录时仍是自己的身份。

1. 去 [飞书开放平台](https://open.feishu.cn/) → 创建**企业自建应用**（比如就叫 `team-lark`）。
2. 开通**机器人**能力（之后想做群通知/@人会用到）。
3. 加权限（scope），最小集：
   - 通讯录**只读**：`contact:user.base:readonly`、`contact:user.employee_id:readonly`（用来按姓名/open_id 认人）
   - 多维表格**读写**：`bitable:app`（读写任务表）
   - （可选，群通知）即时通讯：`im:message`、`im:chat`
4. 设**可用范围 = 团队成员**，然后**发布版本**（管理员审批通过才生效）。

### 4. 每个成员各自登录

```bash
lark-cli auth login   # 浏览器 OAuth，各自以本人飞书身份登录
```

> ⚠️ 飞书是**两层权限**，都要过：① 上面应用的 scope（管理员审批一次）② **每个人对那张具体 Base 文档有编辑权**（在 Base 右上角「分享」里把成员加为可编辑）。缺任一层，写入会 permission denied。

### 5. 建团队的多维表格（Base）

新建一个多维表格，建两张表：

**成员表** —— 每人一行：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| 姓名 | 文本 | |
| open_id | 文本 | 飞书 open_id（`lark-cli contact +get-user` 可查自己的） |
| 人设 | 文本 | 只写**擅长什么/负责哪块**，别写老板/员工等身份 |
| 负责模块 | 文本 | |

**任务表** —— 每个任务一行：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| 标题 | 文本 | |
| 详情 | 文本 | 上下文 |
| 发起人 / 负责人 / 验收人 | **人员** | 三个人员字段（关系，随事流转） |
| 验收条件 | 文本 | 明确的 DoD |
| 状态 | **单选** | 选项：`待领取` `进行中` `待验收` `已完成` `打回` |
| 优先级 | **单选** | 选项：`高` `中` `低` |
| 截止日 | 日期 | |
| 交付物 / 交付说明 / 打回意见 | 文本 | |
| 创建时间 / 更新时间 | 自动（创建时间 / 更新时间） | |

再建两个视图：**全局看板**（看板，按「状态」分组）、**待验收**（表格，筛选 `状态 = 待验收`）。

### 6. 把坐标填进 SKILL.md

打开 Base，从浏览器地址栏取 token / id，填进 `~/.claude/skills/team-lark/SKILL.md` 顶部「配置」段：

```
https://<your-tenant>.feishu.cn/base/<BASE_TOKEN>?table=<TABLE_ID>&view=<VIEW_ID>
                                      └ BASE_TOKEN    └ 表ID         └ 视图ID
```

- `BASE_TOKEN`：URL 里 `/base/` 后那一串
- `成员表 / 任务表` 的 `TABLE_ID`：点到对应表后地址栏的 `table=tbl...`
- `全局看板 / 待验收` 的 `VIEW_ID`：点到对应视图后的 `view=vew...`

把这些替换掉 SKILL.md 里的 `<YOUR_BASE_TOKEN>` / `<MEMBER_TABLE_ID>` / `<TASK_TABLE_ID>` / `<BOARD_VIEW_ID>` / `<REVIEW_VIEW_ID>`。
（`<YOUR_FEEDBACK_DOC_TOKEN>` 可选：建一个飞书文档收集"工具反馈"，填它的 docx token；不需要就把"问题反馈"那段删掉。）

### 7. 跑起来

把成员表先填上你自己（姓名/open_id/人设/负责模块），然后在 Claude Code 里运行 `/team-lark`。

---

## 许可

MIT
