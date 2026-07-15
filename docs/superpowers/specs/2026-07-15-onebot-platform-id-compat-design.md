# OneBot 平台实例 ID 兼容修复设计

## 背景与目标

AstrBot 4.26.5 的主动消息接口按平台实例 ID 匹配发送适配器。当前插件生成的 UMO
以适配器类型 `aiocqhttp` 开头，而用户实际启用的唯一实例 ID 是 `default-qq`，因此
私聊和群聊主动消息都会返回 `cannot find platform`。

目标是在不要求用户重建已有目标或任务的前提下，让测试按钮、首次有房通知和后续
变化通知都通过当前唯一的 OneBot v11 实例发送。

## 数据模型与兼容策略

`NotificationTarget` 增加 `platform_id` 字段。新目标优先保存真实实例 ID；旧 JSON
缺少该字段时继续解释为旧适配器类型 `aiocqhttp`，不执行破坏性数据迁移。该做法遵循
AstrBot 官方主动消息指南：从事件取得并保存 `event.unified_msg_origin`，而不是自行假设
平台实例 ID。

- 从 QQ 指令绑定目标时，读取 `event.unified_msg_origin`，从中保存真实平台实例 ID、消息
  类型与会话 ID；本环境将保存 `default-qq`。
- 从 WebUI 手动添加时可填写平台实例 ID；留空使用兼容值 `aiocqhttp`，发送时自动解析。
- UMO 仍保持 `平台实例ID:消息类型:QQ号或群号` 的 AstrBot 标准格式。

## 发送流程

插件在调用 `context.send_message` 前解析 UMO，并沿用成熟主动消息插件的实例精确匹配方式：

1. 如果首段已经匹配在线平台实例 ID，原样发送。
2. 如果首段是适配器类型，并且在线平台中恰好只有一个同类型实例，则替换为该实例 ID。
3. 如果没有匹配或存在多个同类型实例，不做猜测，交由 AstrBot 返回失败并保留告警。

因此已有的 `aiocqhttp:FriendMessage:...` 和 `aiocqhttp:GroupMessage:...` 会在本环境自动
转换为 `default-qq:FriendMessage:...` 与 `default-qq:GroupMessage:...`。测试按钮和监控通知
共用同一发送函数，不会出现两套行为。

## WebUI

通知目标表单增加“平台实例 ID”输入框，默认留空，并提示可从 AstrBot 平台配置或日志中的
`default-qq(aiocqhttp)` 读取 `default-qq`。目标列表继续展示最终 UMO，便于核对。

## 错误处理与测试

保持现有投递追踪语义：发送成功后不再重发；返回失败或抛出异常时保留待重试事件。
测试覆盖：

- 私聊和群聊使用指定平台实例 ID 生成 UMO；
- 旧目标缺少 `platform_id` 时仍可加载；
- 唯一 OneBot 实例可自动修正旧 UMO；
- 已经正确的实例 ID 不被改写；
- QQ 指令创建的目标记录事件所属实例；
- WebUI 保存并回显平台实例 ID。

插件版本从 `0.1.1` 升至 `0.1.2`。
