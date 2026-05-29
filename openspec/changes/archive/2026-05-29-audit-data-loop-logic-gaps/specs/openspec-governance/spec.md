## ADDED Requirements

### Requirement: OpenSpec 证据必须与实现完成状态一致

系统 SHALL 在 OpenSpec change 完成前，保证该 change 的 review、测试、coverage、wiki 和归档证据与实际完成状态一致。若相关已完成变更仍存在 stale 失败记录或未归档状态，完成报告 SHALL 显示修复、归档或跳过原因。

#### Scenario: 当前 change 完成前 review 无 stale failure

- **GIVEN** 当前 change 已完成实现和验证
- **WHEN** 执行完成归档前检查
- **THEN** `review.md` SHALL 不得保留已修复但未更新的失败测试结论
- **AND** `task-reviews.md` SHALL 不得保留未关闭的 Alignment Review 或 Security Review finding
- **AND** 完成证据 SHALL 记录最终测试和 coverage 结果。

#### Scenario: 相关 active change 的状态被明确处理

- **GIVEN** 当前 change 依赖或修正另一个 active change 的行为或证据
- **WHEN** 当前 change 进入 completion 阶段
- **THEN** 完成证据 SHALL 记录该相关 active change 的处理结果
- **AND** 如果无法归档相关 change，完成证据 SHALL 记录明确 skip reason
- **AND** 不得在最终汇报中声称 OpenSpec 已全部闭环。

#### Scenario: Wiki 与实现和 spec 对齐

- **GIVEN** 当前 change 通过实现和 review
- **WHEN** 生成或更新 wiki 页面
- **THEN** wiki SHALL 说明用户可观察行为、数据证据链、分数/状态语义和验证结果
- **AND** wiki SHALL 不得描述未实现或未验证的行为为已完成。
