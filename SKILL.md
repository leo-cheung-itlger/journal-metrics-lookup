---
name: journal-metrics-lookup
description: Use when looking up journal impact factors (JIF), JCR quartiles or Chinese Academy of Sciences partitions by DOI, journal name or ISSN/eISSN, including journal-tier assessment during literature search, paper review, literature reviews and evidence synthesis.
---

# Journal Metrics Lookup

通过独立的本地查询程序返回期刊指标。适用于任意科研项目；不依赖 Research OS 或特定癌种。Python 3.10+，仅标准库。

## 执行

`<SKILL_DIR>` 指本文件所在目录；从当前项目运行绝对路径，无需切换到科研项目外。

1. 输入优先 DOI（通过 Crossref 获取期刊与 ISSN/eISSN）、其次 ISSN/eISSN、最后完整期刊名称。DOI 元数据仅用于身份匹配，不核实期刊指标。
2. 首次使用运行 `status`。缺少数据库时运行 `update` 获取公开 CSV；已有可用快照直接查询，不能每篇论文重复下载数据库。
3. 在原有论文记录中保存完整结果为 `journal_tier`，把实验设计、样本量、独立重复、数据质量等论文审读另存为 `evidence_quality`。后者只能来自论文证据，期刊分区不能决定论文质量。

```powershell
python "<SKILL_DIR>/scripts/journal_metrics.py" status
python "<SKILL_DIR>/scripts/journal_metrics.py" update
python "<SKILL_DIR>/scripts/journal_metrics.py" lookup --doi 10.1002/path.5290
python "<SKILL_DIR>/scripts/journal_metrics.py" lookup --name "Journal of Pathology"
python "<SKILL_DIR>/scripts/journal_metrics.py" lookup --issn 1096-9896
```

`--data-dir <absolute-directory>` 放在 `status/update/lookup` 之前；也可设置 `JOURNAL_METRICS_DATA_DIR`。默认 Windows `%LOCALAPPDATA%/journal-metrics-lookup`，其他平台 `~/.cache/journal-metrics-lookup`。数据与 Skill/项目代码分开，不将整套 CSV 或缓存提交公开仓库。无需安装 ShowJCR GUI，不访问学校授权数据库。

## 结果解释

| 字段 | 含义 |
|---|---|
| `status` | `MATCHED` 只表示身份已匹配；缺失/歧义/失败为 `NOT_VERIFIED`，细节见 `reason` |
| `journal` / `match_basis` / `metadata` | 完整期刊名称、ISSN/eISSN、匹配依据及实际 Crossref 返回的 DOI 元数据 |
| `jif` | 数值、原始值、CSV 字段中的指标年；空白/N/A/非数值不转成 0 |
| `jcr.categories` | 每个学科的 Q1–Q4 与排名，保留全部学科；缺失分区为 `NOT_VERIFIED` |
| `cas` | CSV 行中的版本年、大类和全部小类分区，保留原始排名文本 |
| `official_verification` | 此数据源始终 `verified=false, status=NOT_VERIFIED`；第三方匹配成功不能升级为官方核实 |
| `provenance` | 仓库、固定 commit、公开文件 URL、SHA256、字段/行数、下载时间、README 发布声明及其未核实状态 |

ISSN 校验后精确匹配优先；名称仅做 HTML 实体、大小写、空格、标点、前导 `The` 和 `&/and` 规范化，不做模糊/缩写猜测。有不同 ISSN 的同名候选时返回 `AMBIGUOUS` 及候选，不择优选择；补充准确 ISSN 后重查。给定 ISSN 与有编号的源记录不符时不以名称强行覆盖。CAS 的合并 `ISSN/EISSN` 列不用于猜测印刷/电子类型。DOI 已解析而指标缺失时，仍保留 Crossref 提供的期刊名称和已知类型 ISSN，指标保持 `NOT_VERIFIED`。

`FOUND_THIRD_PARTY` 表示公开第三方表中有值。向用户报告数值时必须附年份、来源和“未官方核实”。默认返回本地快照中最新可用指标，不是论文发表当年的历史指标，也不保证是官方最新值。

CLI 成功处理查询（含无匹配）返回 0；数据库缺失/损坏或更新网络失败返回 2 和结构化 `NOT_VERIFIED`。DOI 接口失败见 `DOI_RESOLUTION_FAILED`；使用已有、来源明确的 ISSN 再查，不能猜期刊。损坏快照用 `update` 修复。

## 更新与验证

`update` 从 [ShowJCR](https://github.com/hitfyd/ShowJCR) 的公开文件树选择最新受支持 `JCR20xx-UTF8.csv` 和 `FQBJCR20xx-UTF8.csv`，固定到同一 commit。分别从 `IF(年份)`/学科列和 CAS `年份` 实读年，校验与文件名一致；README 的发布年月仅作为第三方声明保存。新 schema 或年份不一致时拒绝更新，保留旧 manifest；不会仅凭文件名标注年份。`update --ref <commit>` 可固定或恢复已有上游版本。

更新保存外部快照并原子切换 manifest；查询复核 SHA256、schema、年份与行数。公开文件可访问不代表其内容已获 Clarivate/中科院官方核实；本 Skill 不自动抓取授权库、不自动出具官方核验结论。

```powershell
python -m unittest discover -s "<SKILL_DIR>/tests" -v
```

测试使用合成小样本，覆盖 DOI 身份匹配、名称、两种 ISSN、同名歧义、多学科、缺失、损坏与年份一致性；真实 DOI 实查需网络与本地快照。
