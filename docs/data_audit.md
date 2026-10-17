# 数据来源与质量审计

## 来源和真实性边界

Kevin Hillstrom 于 2008-03-20 发布了[原始说明页](https://blog.minethatdata.com/2008/03/minethatdata-e-mail-analytics-and-data.html)，其中直接链接 CSV，并说明约 64,000 名过去 12 个月购过物的客户被分入三组，邮件后观察两周。2026-10-17 从该页面链接所指的发布者域名，通过 HTTP 下载原始 CSV：

`http://www.minethatdata.com/Kevin_Hillstrom_MineThatData_E-MailAnalytics_DataMiningChallenge_2008.03.20.csv`

HTTPS 访问在本机 Python 中报 `SSL: CERTIFICATE_VERIFY_FAILED: self-signed certificate`；网页抓取该 HTTPS 链接超时。随后 HTTP 地址返回 `200 OK`、`Content-Type: text/csv`、`Content-Length: 3964977`，且响应标示 `Last-Modified: Fri, 21 Mar 2008 02:05:03 GMT`。因此未启用 scikit-uplift 备用源。文件保存在 `data/raw/`，没有改写内容。原始页面及域名、文件大小、字段与发布者说明相符，支持来源核查；没有发布者提供的独立签名或官方哈希，无法密码学地证明文件从 2008 年至今未被替换，也无法独立验证企业内部随机化及邮件实际投递。

| 项目 | 实际值 |
| --- | --- |
| 获取日期 | 2026-10-17（Asia/Shanghai） |
| 文件大小 | 3,964,977 字节 |
| SHA256 | `0e5893329d8b93cefecc571777672028290ab69865718020c78c7284f291aece` |
| 行列数 | 64,000 行 × 12 列 |

## 方法

`src/audit.py` 用 Pandas 读取原文件，不筛选或去重；检查字段、Pandas 类型、缺失、数值范围、枚举值、全字段重复、分组人数、历史消费分箱，以及结果字段逻辑。结果写入 `data/audit_summary.json`，可重复运行。分箱按左闭右开区间核查，最高档为 ≥ 1,000；这是对标签的明确解释，边界若有另一种原业务约定则需原始文档确认。

## 字段说明与实际范围

| 字段 | 类型 | 时点、含义 | 实际取值或范围 |
| --- | --- | --- | --- |
| `recency` | int64 | 实验前，距上次购买月数 | 1–12 |
| `history_segment` | object | 实验前，过去一年消费额分档 | 7 档：`1) $0 - $100` 至 `7) $1,000 +` |
| `history` | float64 | 实验前，过去一年消费额（美元） | 29.99–3345.93 |
| `mens` | int64 | 实验前，过去一年购买男装指示 | 0/1 |
| `womens` | int64 | 实验前，过去一年购买女装指示 | 0/1 |
| `zip_code` | object | 实验前，地区类别 | `Urban`、`Surburban`、`Rural` |
| `newbie` | int64 | 实验前，过去一年新客户指示 | 0/1 |
| `channel` | object | 实验前，过去一年购买渠道 | `Web`、`Phone`、`Multichannel` |
| `segment` | object | 处理分配：男装邮件、女装邮件、无邮件 | `Mens E-Mail`、`Womens E-Mail`、`No E-Mail` |
| `visit` | int64 | 实验后两周，是否访问网站 | 0/1 |
| `conversion` | int64 | 实验后两周，是否购买 | 0/1 |
| `spend` | float64 | 实验后两周，消费额（美元） | 0–499 |

原始说明页写的是 `Suburban`，CSV 的实际拼写为 `Surburban`。代码保留原值，不悄悄更正。

## 结果和问题

| 检查 | 结果 |
| --- | ---: |
| 任一字段缺失 | 0 |
| 全字段完全相同的后续记录数（`duplicated()`） | 6,562 |
| 非法实验组、recency、二元值、负 history/spend | 均 0 |
| `history_segment` 与 `history` 分档不一致 | 0 |
| `conversion=1` 且 `visit=0` | 0 |
| `spend>0` 且 `conversion=0` | 0 |
| `conversion=1` 且 `spend<=0` | 0 |
| `spend>0` 且 `visit=0` | 0 |

全字段重复只是记录相同；没有唯一用户 ID，不能判断这些记录是否为同一用户，也不能据此删除。`history` 最低为 29.99，与过去一年已购买客户的说明相容。最大消费额属于描述性范围，未获业务规则，不能据此断言异常。零缺失也不证明测量没有错误。`visit`、`conversion`、`spend` 的已检逻辑一致性不证明追踪完整。

### 实验组实际人数

| 组别 | 人数 | 占比 |
| --- | ---: | ---: |
| 男装邮件 | 21,307 | 33.2922% |
| 女装邮件 | 21,387 | 33.4172% |
| 无邮件对照 | 21,306 | 33.2906% |

## 数据的可用边界

数据含处理分配、实验前特征和两周结果，后续可在所述随机化成立等条件下估计组间增量消费、访问及购买差异，也可预先定义用户群体比较。公开文件不能证明随机分配执行、名单去重、邮件送达、交叉接触、结果追踪完整性或外部推广性。没有客户 ID，不能做真正的用户去重或连接其他记录；没有利润和邮件成本，不能计算真实 ROI。定向投放价值只能在明示成本、容量及可迁移性假设后做情景分析，不能当成已实现的业务回报。本轮不做假设检验或效果解释。
