# Hillstrom Email Marketing Experiment

数据分析求职项目。第一阶段保存原始实验文件、核查出处、审计质量并写明设计；第二阶段按预先指定方法分析随机分组的总体效果。

## 复现

需要 Python 3.10+：`python -m pip install -r requirements.txt`。在项目目录运行 `./run_audit.ps1` 可重建第一阶段审计；运行 `./run_effect_analysis.ps1` 可重建第二阶段结果和图表。两个脚本都会运行 `unittest`。

## 文件

- `data/raw/`：未经修改的原始 CSV。
- `data/audit_summary.json`：由代码生成的描述性审计结果。
- `src/audit.py`：Pandas 审计代码。
- `tests/test_audit.py`：来源数据结构及核心一致性检查。
- `docs/data_audit.md`：来源与质量审计。
- `docs/experiment_design.md`：后续实验分析设计。
- `src/effect_analysis.py`、`data/effect_results.json`、`figures/`：第二阶段代码、结构化结果与图表。
- `docs/experiment_effect_report.md`：第二阶段中文报告。

原始发布页：[Kevin Hillstrom, 2008-03-20](https://blog.minethatdata.com/2008/03/minethatdata-e-mail-analytics-and-data.html)。
