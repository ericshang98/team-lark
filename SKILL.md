---
name: team-lark
description: Pinclaw 团队协作系统（Agent 化的团队）。当用户想用一条命令掌握项目——查"我的任务/今天要做什么/有什么活"、发起或指派任务、交付任务、验收或打回、看项目进度/全局状态时使用。每个人跑它都会先与团队当前状态同频，再看到分给自己的任务并逐个交付。任务和状态全部存在飞书多维表格。触发词：team-lark、项目状态、我的任务、今天要做什么、发起任务/指派任务、交付、验收、打回、看进度、团队任务、我负责啥、谁在做什么、pinclaw team、team lark。
---

# Pinclaw Lark Team —— 一个 Agent 化的团队

这套 skill 把团队的**意识同步、对齐、状态管理**全部 Agent 化。每个人 = 人 + 他的 agent = 一个节点；所有节点连到飞书这个共享状态层。你跟自己的 agent 做事，agent 替你读写团队的共享真相。

## 心智模型（务必先懂）

- **飞书多维表格是团队的共享真相**：任务/状态/交付物都在这；每个 agent 读写它，全团队随时看到同一份状态。
- **关系，而非身份**：没有老板/员工这种固定角色。每件事上只有关系——**发起人 / 负责人 / 验收人**，随事而定、随时流转。谁都能发起、被指派、验收。
- **人设**：成员表里每人一段"人设"，只描述他擅长什么、负责哪块，用来让 agent 更懂他（不是权力）。
- **每次进入先对齐**：每次被调用，先读一遍共享状态，让用户立刻知道项目到哪了、自己今天有什么。
- 状态机：`待领取 → 进行中 → 待验收 →（验收人）→ 已完成 / 打回 →（回到）进行中`。交付只到"待验收"，验收人确认才"已完成"。

## 配置（Base 坐标，全团队共用，勿改）

```
BASE_TOKEN = <YOUR_BASE_TOKEN>
成员表     = <MEMBER_TABLE_ID>   （字段：姓名 open_id 人设 负责模块）
任务表     = <TASK_TABLE_ID>   （字段：标题 详情 发起人 负责人 验收人 验收条件 状态 优先级 截止日 交付物 交付说明 打回意见 创建时间 更新时间）
全局看板   = <BOARD_VIEW_ID> （kanban，按状态分组）
待验收     = <REVIEW_VIEW_ID> （grid，筛选 状态=待验收）
排期       = <SCHEDULE_VIEW_ID> （grid，按截止日↑ 排序 —— 看排期用这个）
排期甘特   = <GANTT_VIEW_ID> （gantt，创建时间→截止日 时间条）
Base 链接  = https://<your-tenant>.feishu.cn/base/<YOUR_BASE_TOKEN>
```
所有 `lark-cli base` 命令都带 `--as user --base-token <YOUR_BASE_TOKEN>`。

## 第 0 步：先对齐（每次会话第一件事）

```bash
# 1) 我是谁
lark-cli contact +get-user
# 2) 查成员表拿人设 + 负责模块
lark-cli base +record-search --as user --base-token <YOUR_BASE_TOKEN> --table-id <MEMBER_TABLE_ID> \
  --json '{"keyword":"<我的open_id>","search_fields":["open_id"],"select_fields":["姓名","人设","负责模块"],"limit":1}'
# 3) (可选) 部门：lark-cli contact +search-user --as user --query "<我的姓名>"
```
拿到后：**用"人设"那段作为自己的扮演设定**，然后**必出一份「今日简报」**（不要只说一句话；用人设口吻、给表单）。读全局看板（见"看全局进度"）+ 我负责的任务，整理成下面三块给用户，看完即知道今天怎么动：

> **今日简报模板（每次运行 skill 必出）**
> 原则：**今天做了的 + 所有没做的 全都列出来**，不要只显示今天到期的。任务多、很多没排期，所以**不能只靠截止日过滤**——没截止日的任务也必须显示，别丢。
>
> **1. ✅ 今天做了什么** —— 我负责、且「更新时间 = 今天」状态推进到 待验收/已完成 的任务（今天的产出）。没有就写"今天暂无完成记录"。
> **2. 📋 还没做的（全部未完成）** —— 表格：`任务 | 状态 | 优先级 | 截止日`，列出我负责且状态∈{进行中,打回,待领取}的**全部**任务（不按日期筛！没截止日的写「未排期」照样列）。排序：有截止日的按 截止日↑ 在前、再按优先级；**未排期的单独成组**放下方，方便我补排期。今天/逾期标 🔴，打回的念"打回意见"。
> **3. 🔔 等我验收 / 团队动向** —— "待验收人是我、正等我点验收"的任务（提醒去验收/打回）；外加近 1-2 天他人的变化（谁交付/谁被打回/新任务）。都没有就写"无"。
>
> 简报末尾：一句行动建议 + 主动指出「未排期」任务并问要不要现在补截止日 + 提示「加任务/改状态直接说就行」。

- **加任务/改状态零摩擦**：用户随口说"加个任务…"/"这个做完了"/"验收 X"，直接用下面对应命令写 Base，别让他手填 id（自己用标题搜 record_id）。
- 成员表查不到自己 → 提示用户还没入驻，让团队里任何人把他加进成员表（写一行：姓名/open_id/人设/负责模块）。

## 能做什么（对所有人一样，按关系而非身份）

### 看我的任务（最常见，默认动作）
```bash
lark-cli base +record-search --as user --base-token <YOUR_BASE_TOKEN> --table-id <TASK_TABLE_ID> \
  --json '{"keyword":"<我的姓名>","search_fields":["负责人"],"select_fields":["标题","详情","验收条件","状态","优先级","截止日","打回意见"],"limit":50}'
```
列出我负责且状态∈{进行中,打回,待领取}的，按优先级+截止日排，用人设口吻讲。打回的把"打回意见"念出来。

### 看全局进度（任何人都能看，团队透明）
```bash
lark-cli base +record-list --as user --base-token <YOUR_BASE_TOKEN> --table-id <TASK_TABLE_ID> --view-id <BOARD_VIEW_ID> --limit 200
```
按 负责人/状态 给出中文小结：谁在做什么、谁待验收、谁卡住。

### 发起 / 指派任务（任何人都能）
先把负责人姓名解析成 open_id：`lark-cli contact +search-user --as user --query "<姓名>"`。发起人=自己；默认验收人=发起人（除非指定别人）。
```bash
lark-cli base +record-upsert --as user --base-token <YOUR_BASE_TOKEN> --table-id <TASK_TABLE_ID> \
  --json '{"标题":"<标题>","详情":"<上下文>","发起人":[{"id":"ou_我"}],"负责人":[{"id":"ou_负责人"}],"验收人":[{"id":"ou_我"}],"验收条件":"<明确的DoD>","状态":"进行中","优先级":"中","截止日":"2026-06-10"}'
```
- 发起任务务必带"验收条件"，否则交付没法判定。截止日 `YYYY-MM-DD`。优先级∈{高,中,低}。
- 指派给自己也行（负责人=发起人）。

### 领取（待领取 → 进行中）
```bash
lark-cli base +record-upsert --as user --base-token <YOUR_BASE_TOKEN> --table-id <TASK_TABLE_ID> \
  --record-id <rec> --json '{"状态":"进行中"}'
```

### 交付（→ 待验收）
只改自己负责的任务：
```bash
lark-cli base +record-upsert --as user --base-token <YOUR_BASE_TOKEN> --table-id <TASK_TABLE_ID> \
  --record-id <rec> --json '{"状态":"待验收","交付物":"<链接/文档/说明>","交付说明":"<做了什么、怎么验>"}'
```
交付后提示：已提交待验收，等验收人确认。

### 验收 / 打回（由该任务的验收人或发起人做）
```bash
# 通过
lark-cli base +record-upsert --as user --base-token <YOUR_BASE_TOKEN> --table-id <TASK_TABLE_ID> \
  --record-id <rec> --json '{"状态":"已完成"}'
# 打回
lark-cli base +record-upsert --as user --base-token <YOUR_BASE_TOKEN> --table-id <TASK_TABLE_ID> \
  --record-id <rec> --json '{"状态":"打回","打回意见":"<还差什么>"}'
```

## 定位某条任务的 record_id
```bash
lark-cli base +record-search --as user --base-token <YOUR_BASE_TOKEN> --table-id <TASK_TABLE_ID> \
  --json '{"keyword":"<标题关键词>","search_fields":["标题"],"limit":5}'
```
取返回里的 `record_id`；有歧义就列出来让用户选。

## 问题反馈（让工具进化 —— 重要）

本工具要**不断进化**。用户遇到卡点/别扭/低效，或说"把这个问题记到反馈文档"、"反馈一下"、"这个不好用"时，追加进反馈文档（一行一条）：
```
反馈文档 = <YOUR_FEEDBACK_DOC_TOKEN>
链接 = https://<your-tenant>.feishu.cn/docx/<YOUR_FEEDBACK_DOC_TOKEN>
```
```bash
lark-cli docs +update --api-version v2 --doc <YOUR_FEEDBACK_DOC_TOKEN> --command append \
  --content '<callout emoji="📝" background-color="gray"><p>YYYY-MM-DD · <反馈人姓名> · <问题/建议> · <期望怎样更好> · 待处理</p></callout>'
```
- 主动一点：发现某步让用户明显费劲（反复出错、手填 id 等），建议"要不要我记进反馈文档，下次优化掉？"

## 看排期 / 周计划

- **看排期**：用户问"排期/时间线/什么时候做什么" → 读 `排期` 视图（按截止日↑），用表格讲清先后；想要时间条就给 `排期甘特` 视图链接。
```bash
lark-cli base +record-list --as user --base-token <YOUR_BASE_TOKEN> --table-id <TASK_TABLE_ID> --view-id <SCHEDULE_VIEW_ID> --limit 200
```
- **周计划/补排期**：用户说"排个期/做周计划/把没排期的安排一下" → 捞出我负责且**截止日为空**的任务，逐条问/建议一个截止日，确认后用 `record-upsert` 写回 `截止日`（`YYYY-MM-DD`）。一次性把"未排期"清空是这个动作的目标。

## 状态变更自动通知（飞书 DM —— 默认必做，不是可选）

**凡是改动涉及"别人"的任务流转，操作成功后立刻给当事人发一条飞书私信**（别让人靠主动跑 skill 才知道）。当事人 open_id 从任务的人员字段或成员表取。命令：
```bash
lark-cli im +messages-send --as user --user-id <对方open_id> --text "<一句话>"
```
触发与收件人：
| 动作 | 通知谁 | 内容要点 |
| --- | --- | --- |
| 发起/指派任务给**别人**（负责人≠自己） | 负责人 | 新任务「X」+ 验收条件 + 截止日 |
| 交付（→待验收） | 验收人 | 「X」待你验收 + 交付物链接 |
| 验收通过（→已完成） | 负责人 | 「X」已验收通过 |
| 打回 | 负责人 | 「X」被打回，意见：… |

- 负责人/验收人 = 自己时**不用**通知自己。
- 群里 @ 提醒（可选，需 chat_id）：`lark-im` 发到对应群，用 `<at user_id="ou_xxx"></at>`。

## 主动模式（Ambient / 被定时器触发）

**这是被外部时钟（cron / launchd 定时器，或飞书定时自动化）拉起、无头、无交互用户的运行路径。** 触发方式形如 `claude -p "/team-lark 主动模式"`（安装见 README「主动模式」一节）。和正常会话最大的区别：**没有"当前登录用户"**，所以不走「第 0 步对齐」，改走**团队级遍历**——为每个成员各算一份、各发一条。

> **排程绝不内置在本 skill。** 这里不写、也永远不要写任何 cron / setTimeout / 轮询计时。skill 只管"被叫起来跑一轮"，到点叫醒交给系统定时器。

**铁律**：本模式**只读 + 发 DM**，**绝不**改任何任务的状态/字段（不领取、不交付、不验收、不打回）。

**步骤（全部复用本文件已有命令与模板）：**

1. **取全员**（替代"我是谁"锚点）：
   ```bash
   lark-cli base +record-list --as user --base-token <YOUR_BASE_TOKEN> --table-id <MEMBER_TABLE_ID> --limit 200
   ```
   得每人 `{姓名, open_id, 人设, 负责模块}`。
2. **取团队上下文**（只读一次缓存，循环里切分）：全局看板 + 任务表，对照今天算逾期 / 本周硬 deadline。
3. **for each 成员**：用其姓名按「负责人」搜出任务，算他的：逾期 / 今日该做 / 待验收 / 阻塞别人的。套本文件「今日简报」模板：并行多轨者走**全景态**、单线成员走**聚焦态**，用该成员人设口吻。
4. **私聊 DM 给本人**（成员表 `open_id` 即收件人）：
   ```bash
   lark-cli im +messages-send --as user --user-id <该成员open_id> \
     --markdown "<该成员的个人简报>" --idempotency-key "proactive-<YYYY-MM-DD-HH>-<open_id>"
   ```
   **长简报必须主动分片**：飞书单条 markdown 约 **1.5KB 上限**，超了报 `99992402 field validation failed`。发前按段落切成多条（每条 ≤1.2KB）依次发——**别先发整条等报错再重试，更绝不发"测试/探针"短消息试长度**。每片用**不同** key：`proactive-<YYYY-MM-DD-HH>-<open_id>-<片号>`（同 key 后续片会被飞书去重吞掉）。
5. **团队群摘要**（给了群 chat_id 才发）：待验收积压 / 无人认领 / 逼近 deadline。

**降噪**：每轮触发每人最多一条 DM；某成员**无可推进项**时**跳过不打扰**；查不到 open_id 的人不发也不中断整轮。
**演练**：触发提示里带「演练 / dry-run」时**只算只打印、跳过第 4/5 步所有 `messages-send`**，不发任何消息。上线前先演练一轮看简报对不对。
**权限**：主动模式靠 `lark-cli im +messages-send` 给全员发私信 —— 应用必须开通「发送单聊消息」权限（见 README §需要哪些权限），否则会 permission denied。

## 规则
- 不确定字段名/选项就先 `lark-cli base +field-list --as user --base-token <YOUR_BASE_TOKEN> --table-id <表>`。
- 单选字段（状态/优先级）写选项名字符串；人员字段（发起人/负责人/验收人）写 `[{"id":"ou_xxx"}]`。
- 只改自己负责的任务的状态/交付字段；验收由该任务的验收人/发起人做，别替别人乱改。
- 每次操作后用当前人的"人设"口吻讲清结果，并给出下一步可做的动作。
