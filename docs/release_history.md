# 公开发布的历史引用说明

2026-10-17，首次公开发布前，项目将本地历史提交的 Author 和 Committer 邮箱替换为账户设置页确认的 GitHub 官方 noreply 邮箱。保留原作者姓名、提交日期、说明、顺序、父子拓扑和每个提交的项目树。由于提交元数据改变，提交哈希也改变；原分析正文及冻结方案不为此改写。

早期报告中出现的旧哈希属于邮箱替换前的内部历史。下表只公开哈希对应关系，不包含私人邮箱、旧提交对象、备份或凭据。

| 历史节点 | 发布前内部哈希 | 公开历史对应哈希 |
| --- | --- | --- |
| 第二阶段检查点 | `f707acc34434ade80a0ac41f959ec3042b455293` | `8de12a3774bea701953caa4a8c6228903b9f4319` |
| 第三阶段检查点 | `6e1af8de9e035731e0e20e477762e67397fc4e1a` | `16d88ec1e0a2acc85de44316633ca747637baefa` |
| 第四阶段冻结方案 | `8bb40a5ce168841c08046d9fed10a6ccd04920f0` | `64b69f32ed9cf8caf2769457407f8c2a28bcfb2c` |
| 第四阶段成果与项目说明 | `ed1fd6db97bc919118fc15bbeead2f9a827dea5a` | `5fa40b3fd256fcf1c39699c347f1c98d64779f39` |
| 获奖论文参考后的补充分析 | `8e520d82fefc5e50ec1842fd3c94d56b79ff648c` | `c30e665967514a742b434188ed13e0857b094844` |

[公开冻结方案提交](https://github.com/1049988042/hillstrom-marketing-experiment/commit/64b69f32ed9cf8caf2769457407f8c2a28bcfb2c)中的 `docs/policy_evaluation_plan.md` 与当前文件的 SHA256 均为：

`2b52aee5cc79b4011a1f26b2cfc3ab6997821e3d1e3fa32aedee3983d625284b`

该冻结提交是[正式第四阶段成果提交](https://github.com/1049988042/hillstrom-marketing-experiment/commit/5fa40b3fd256fcf1c39699c347f1c98d64779f39)的祖先。Git 祖先关系能够证明**方案提交早于成果提交**；Git 历史不能独立证明程序首次读取验证集消费结果的真实时间。第二阶段已使用全样本，内部留出验证的解释限制依然成立。

公开发布仅添加本说明、README 导航和文本换行属性。`.gitattributes` 指定 Markdown 为 LF，防止 Windows 克隆的换行转换改变冻结方案的字节哈希；分析方法、结果、固定分割和 `candidate_rule=null` 均保持不变。原始 CSV 不进入公开历史，仍需依照 README 单独准备。
