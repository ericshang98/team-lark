# team-lark —— 一个 Agent 化的团队

把团队的**意识同步、对齐、状态管理**全部 Agent 化的 Claude Code / lark-cli skill。

每个人 = 人 + 他的 agent = 一个节点；所有节点连到**飞书多维表格**这个共享状态层。你跟自己的 agent 对话，agent 替你读写团队的共享真相——查任务、发起/指派、交付、验收、看全局进度，全用一句话搞定。

还能开**主动模式**：一个定时器每天自动跑一遍，给每个人私信发当天的个人简报，没人需要先开口（见下方「主动模式」）。

> **为什么用飞书：** 同类的「AI 团队同事」（如 Anthropic Claude Tag）绑死 Slack，国内团队基本用不上。本工具接的是**飞书**——国内团队的标配，配上 `lark-cli` + Claude，国内就能真正落地。

## 核心理念

- **飞书多维表格 = 团队的共享真相**：任务/状态/交付物都在这，全团队随时看到同一份状态。
- **关系，而非身份**：没有老板/员工这种固定角色。每件事上只有 **发起人 / 负责人 / 验收人**，随事而定、随时流转。
- **每次进入先对齐**：每次运行 skill，先读一遍共享状态，出一份「今日简报」（今天做了什么 + 所有没做的 + 等我验收的）。
- **状态机**：`待领取 → 进行中 → 待验收 →（验收人）→ 已完成 / 打回 →（回到）进行中`。

---

## 需要哪些权限（看这张表就够）

飞书是**两层权限**，两层都要过，缺任一层就 `permission denied`：

**第一层 · 应用 scope**（管理员在自建应用「权限管理」里开通一次，全团队共用一个应用）：

| 你要它干什么 | 在应用「权限管理」里开通 | 审批 | 必须 |
| --- | --- | --- | --- |
| 读「人设/部门/职位」生成扮演设定 | 以普通用户身份读取通讯录：`contact:user.department:readonly`、`contact:user.employee:readonly` | **免审** | ✅ |
| 读写任务表 / 成员表 | 多维表格（bitable）查看与编辑 | 免审 | ✅ |
| **发私信**（状态变更通知 + **主动模式**每日简报） | **发送单聊消息**（im，以用户身份发消息） | 免审 | ✅（主动模式必须） |
| （可选）群里 @ 提醒 / 群通知 | 获取与发送群组消息（im 群） | 免审 | 可选 |

> ⚠️ **别用** `contact:contact:readonly`（高敏感、要管理员审核）——上面两个免审通讯录权限就够。

**第二层 · Base 文档编辑权**：每个成员还要对那张**具体的多维表格**有编辑权（在 Base 右上角「分享」里把成员加为可编辑）。
> 读出来部门是 `0`、职位为空 = scope 通了但通讯录后台没填，请管理员补部门/职位。

---

## 快速开始

### 1. 装依赖

- [Claude Code](https://claude.com/claude-code)（或任何支持 skill 的 agent 环境）
- [`lark-cli`](https://github.com/larksuite/cli)：`npm i -g @larksuite/cli`（或按官方 README）

### 2. 装 skill

```bash
git clone https://github.com/ericshang98/team-lark.git ~/.claude/skills/team-lark
```

### 3. 建一个飞书自建应用（团队只需建一个，全员共用 · 管理员做一次）

> 给 `lark-cli` 一个 OAuth 客户端 + 权限容器。本工具走**用户身份 `user_access_token`**——每人各自登录时仍是自己的身份。**整个团队一个应用就够。**

1. 去 [飞书开放平台](https://open.feishu.cn/) → 创建**企业自建应用**（比如就叫 `team-lark`）。
2. 开通**机器人**能力（群通知 / @人会用到）。
3. 「权限管理」→ 按上方 **§需要哪些权限** 那张表，逐项开通（通讯录两项 + 多维表格 + 发送单聊消息；要群通知再加群消息）。
4. 设**可用范围 = 团队成员**，**创建版本 → 发布上线**（管理员审批通过才生效）。

### 4. 每个成员各自登录（⚠️ 必须带 `--scope`，这是最大的坑）

`lark-cli` 默认登录**不会**请求细粒度通讯录权限 → 不带 `--scope` 就读不到部门/职位、人设会残。**复制整条（一行，别断行）**：

```bash
lark-cli auth login --domain all --scope "contact:contact.base:readonly,contact:department.base:readonly,contact:department.organize:readonly,contact:job_title:readonly,contact:user.base:readonly,contact:user.department:readonly,contact:user.department_path:readonly,contact:user.email:readonly,contact:user.employee:readonly,contact:user.employee_id:readonly,contact:user.phone:readonly,contact:user:search"
```

终端会打印授权链接，**原样**复制到浏览器、用**你自己的飞书账号**同意。看到 `本次新授予 ... contact:user.department:readonly contact:user.employee:readonly` 即成功。

> - 报 `scope list contains invalid or malformed scopes`？个别较新的 scope 名当前 CLI 版本不认 → 精简到只留 `contact:user.department:readonly,contact:user.employee:readonly` 两个即可。
> - 报 `99991679 权限不足` / `本次新授予:（空）`？多半是没带 `--scope` 或拼错了。
> - **发 DM / 主动模式报权限不足？** 去应用「权限管理」补「发送单聊消息」权限、重新发布版本，再 `lark-cli auth login`。

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

把这些替换掉 SKILL.md 里的 `<YOUR_BASE_TOKEN>` / `<MEMBER_TABLE_ID>` / `<TASK_TABLE_ID>` / `<BOARD_VIEW_ID>` / `<REVIEW_VIEW_ID>`。
（`<YOUR_FEEDBACK_DOC_TOKEN>` 可选：建一个飞书文档收集"工具反馈"，填它的 docx token；不需要就把"问题反馈"那段删掉。）

### 7. 跑起来

把成员表先填上你自己（姓名/open_id/人设/负责模块），然后在 Claude Code 里运行 `/team-lark`。

---

## 主动模式：让它每天自动发简报（无需有人触发）

平时 `/team-lark` 是「你叫它，它才跑」。**主动模式**是反过来——一个**系统定时器**每天自动拉起一次无头 Claude，遍历成员表，给每个人私信发当天的个人简报（逾期 / 今天该做 / 待验收），没人需要先开口。

要点：

- **排程在系统定时器，不在 skill。** skill 只管「被叫起来跑一轮」，到点叫醒交给 cron / launchd。这样 skill 本体保持干净。
- **只读 + 发 DM**，绝不改任何任务状态。
- **降噪**：每人每轮最多一条；当天没活的人自动跳过不打扰。
- **额外权限**：要开通「发送单聊消息」（见 §需要哪些权限）。

### 装法

`ambient/run-proactive.sh` 就是被定时器调用的脚本。先**演练**一轮（只算只打印、不发任何消息），确认简报对：

```bash
chmod +x ambient/run-proactive.sh
./ambient/run-proactive.sh --dry-run    # 看 ~/.team-lark/proactive.log
```

没问题再挂上每天定时（去掉 `--dry-run` 即正式发）：

**Linux（cron，每天 9:00）：**
```cron
0 9 * * *  /bin/bash ~/.claude/skills/team-lark/ambient/run-proactive.sh
```

**macOS（launchd，每天 9:00）：** 写 `~/Library/LaunchAgents/team-lark-daily.plist`，`ProgramArguments` 指向 `run-proactive.sh`，`StartCalendarInterval` 设 `Hour=9 Minute=0`，然后 `launchctl load`。

> **中国大陆**：claude 本身要能连上 Anthropic。若你走代理，在脚本环境里设 `CLAUDE_PROXY=http://user:pass@host:port` 即可（脚本会自动注入 `https_proxy`）。**团队协作仍全程在飞书**——这正是本工具在国内能落地的原因。

---

## 许可

MIT
