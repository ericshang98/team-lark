# GitHub 自动同步部署

服务器调用 `scripts/server_sync.py`，只需要 Python 标准库和 `gh`；用应用身份访问飞书，不复制个人 OAuth token。看板仍由 `software.py` 的相同状态规则维护，不写阅读记录、不代填工作说明。

## 凭据与启用

在目标私有仓库配置 Actions secrets：`FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`SOFTWARE_BOARD_CONFIG`（已有团队 JSON）。仓库 `GITHUB_TOKEN` 只授予 contents、pull-requests、checks、statuses 读取权限。机器人开通 `base:field:read`、`base:record:read`、`base:record:retrieve`、`base:record:create`、`base:record:update` 并发布生效，成为目标 Base 的可编辑文档应用；不需要删除记录或管理 Base 的权限。用户身份已有权限不代表机器人有权限。凭据只用 stdin 写入 secrets，不打印、不提交；公开 Skill 仓库不放团队配置。

Base 开启高级权限时，普通协作者授权还不够。建立仅可编辑 works/events 两张表的自定义角色，其他表设为无权限；通过仅含现有管理员与该机器人的私有权限群加入角色。核实群成员，限制后续拉人，避免授权扩散。不要关闭高级权限或把应用提升为 Base 管理员。

工作流从默认分支检出，并将本 Skill 固定到已经评审的完整提交 SHA。`pull_request_target` 只把事件当触发信号；禁止检出或执行 PR head/merge 分支、下载 PR artifact、将 PR 标题/正文拼入命令。`workflow_dispatch` 也只运行默认分支代码。所有 PR 的任何路径均影响团队状态，因此事件范围不能按产品目录缩窄。

先 dispatch `check` 验证机器人读取，再 dispatch `sync` 验证真实写入并回读；最后将仓库变量 `SOFTWARE_BOARD_SYNC_MODE` 设为 `github-actions`。此前保持原有本地流程，不声称服务端已启用。切换后仓库 Agent 钩子只返回「已交由 GitHub 自动同步」，不能把返回 0 当成飞书已经完成。

## 触发与恢复

监听 opened、reopened、synchronize、edited、ready_for_review、converted_to_draft、closed；网页/API/CLI 操作一视同仁。每小时全量核对已登记 PR、全部 open PR 和上次核实以来更新的 PR，补齐暂时失败、自动操作未触发事件、评审/CI 后续变化。GitHub 定时任务可能延迟，不能保证严格实时。

仓库内共用一个 concurrency group，后续运行可取消旧运行。每次都重查当前事实，不重放 event 的旧状态。查找范围从最早核实时间前一天开始，覆盖中断和离线期间；达到 GitHub 1000 条发现上限时失败告警，需分批人工回补。GitHub Actions 失败为红色；可 rerun 或 dispatch `sync`，下一次事件/每小时核对也会重试。读取有限重试，未知结果的写入不盲目重试；下次先回读工作键、补齐缺失动态。Base 不提供跨表事务和唯一约束，发现重复会明确停止，不能承诺每一个短暂中间状态都留下事件。

此脚本暂限定一个仓库一个配置（可与该仓库多人共用看板），不接受事件指定 Base/凭据/任意仓库。人工 summary、协调说明、任务关联仍用个人 Skill 维护；自动化永远不标已读。启用后更新团队 Skill 与仓库流程，避免旧版 Agent 自动钩子与服务端同时写表。
