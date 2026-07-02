# L3 条件路由自动审核 实现计划

## 目标

在 `_act()` 阶段实现分级审批路由，每一步都通过 `print()` 输出到运行日志窗口。

## L3 路由规则

| 风险等级 | 审批动作 | 通知方式 |
|---|---|---|
| 低风险（无异常 + 浓度合格 + 天气正常） | ✅ 自动通过，标记"已审批" | 仅入库，不推送 |
| 一般 | ⏳ 推送主管审批，标记"待审批" | 入库 + 钉钉通知主管 |
| 较大 / 重大 | 🚫 禁止作业，标记"已驳回" | 入库 + 钉钉预警 |

## 修改文件

### 1. `agent_core.py` — SecuritySheetData 新增字段

```python
approval_status: Optional[str] = Field(None, description="审批状态：自动通过/待审批/已驳回")
approval_level: Optional[str] = Field(None, description="审批路由：自动通过/主管审批/禁止作业")
```

### 2. `agent_core.py` — 重构 `_act()` 方法

将当前的 `_act()` 拆分为清晰的 L3 步骤，每步 `print()` + `mem.remember()`：

```
[Agent Act] ⚡ 执行 L3 条件路由审批...
[Agent Act] ① 天气检查 → 正常/异常
[Agent Act] ② 风险评估 → 低风险/一般/较大/重大
[Agent Act] ③ L3 路由决策 → 自动通过/主管审批/禁止作业
[Agent Act] ④ 生成审批建议 → LLM 调用
[Agent Act] ⑤ 数据入库 → SQLite
[Agent Act] ⑥ 分级通知 → 根据路由结果选择通知渠道
```

### 3. `agent_core.py` — `save_to_db()` 新增列

自动迁移补 `approval_status` 和 `approval_level` 列。

### 4. `agent_core.py` — `_report()` 增加审批状态输出

在决策链报告中显示最终审批结果。

### 5. `components.py` — KPI 卡片新增审批状态

在 `render_ticket_kpis()` 中新增一个审批状态指标卡（第6个），颜色映射：
- 自动通过 → 绿色
- 待审批 → 蓝色
- 已驳回 → 红色

### 6. `frontend.py` — 通知消息增加审批状态

钉钉通知消息中增加 `审批状态` 字段。

## 验证

1. 启动应用，上传一张正常作业票 → 日志应显示完整的 L3 六步，最终"自动通过"
2. 上传一张有隐患的作业票 → 日志应显示"禁止作业"或"主管审批"，触发通知
3. 检查 KPI 卡片是否正确显示审批状态
4. 检查 SQLite 数据库新列是否有值
