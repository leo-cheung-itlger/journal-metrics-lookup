# 期刊指标查询 · Journal Metrics Lookup

供 Codex 调用的期刊指标查询 Skill。提供论文 DOI、准确 ISSN/eISSN 或完整期刊名，返回期刊影响因子、JCR 分区、中科院大类及小类分区，并保留年份和数据来源。

Python 3.10+，仅使用标准库，无需额外 pip 依赖。完整执行约定见 [SKILL.md](SKILL.md)。

## 安装到 Codex

可以将以下请求发给 Codex：

```text
请使用 skill-installer，从 https://github.com/leo-cheung-itlger/journal-metrics-lookup 安装期刊指标查询 Skill。Skill 位于仓库根目录，安装名使用 journal-metrics-lookup。
```

也可以首次安装时在 Windows PowerShell 中执行：

```powershell
git clone https://github.com/leo-cheung-itlger/journal-metrics-lookup.git "$env:USERPROFILE\.codex\skills\journal-metrics-lookup"
```

安装后，在 Codex 的下一轮对话中调用。首次查询需要联网准备数据；DOI 身份解析也需要网络。仓库只包含 Skill 与程序，期刊数据库在运行时单独下载并保存到本地缓存。

## 如何使用

将论文 DOI 交给 Codex，例如：

```text
使用 journal-metrics-lookup，查询 DOI 10.1002/path.5290 对应期刊的影响因子、JCR 分区和中科院分区，保留年份、来源及核实状态。
```

查询结果也可用于文献记录或报告引用。搭配报告生成 Skill 时，可要求将期刊指标、年份与来源标注在引用旁；报告的生成和排版由相应报告工作流完成。

## 直接运行程序

安装后在 Windows PowerShell 中运行：

```powershell
$journalSkillDir = "$env:USERPROFILE\.codex\skills\journal-metrics-lookup"
python "$journalSkillDir/scripts/journal_metrics.py" status
```

首次使用、尚无数据库时获取公开快照：

```powershell
python "$journalSkillDir/scripts/journal_metrics.py" update
```

已有快照时直接查询，按需更新：

```powershell
python "$journalSkillDir/scripts/journal_metrics.py" lookup --doi 10.1002/path.5290
python "$journalSkillDir/scripts/journal_metrics.py" lookup --issn 1096-9896
python "$journalSkillDir/scripts/journal_metrics.py" lookup --name "Journal of Pathology"
```

macOS/Linux 使用相同 Python 命令，将 `$journalSkillDir` 替换为实际 Skill 目录。程序输出 JSON。可通过 `--data-dir` 或 `JOURNAL_METRICS_DATA_DIR` 指定数据库位置；`--data-dir` 放在 `status`、`update` 或 `lookup` 子命令之前。

## 数据与结果说明

- DOI 元数据来自 Crossref，用于识别期刊。
- 期刊指标来自第三方 [ShowJCR](https://github.com/hitfyd/ShowJCR) 公开 CSV。程序固定来源 commit，校验文件哈希，记录数据字段年、下载时间及来源。
- 结果对应本地快照中的可用指标；官方最新值及论文发表当年的历史指标须另行核对。
- 第三方数据始终标为“未官方核实”。使用数值时保留年份、来源和核实状态。
- 缺失或歧义保持 `NOT_VERIFIED`，缺失值保留为空；同名期刊需要准确 ISSN 消歧。
- 期刊指标作为筛选参考，单篇论文的研究设计、样本量和数据质量需单独评估。

本仓库不打包原始数据库。上游数据的使用条件以其来源及权利方要求为准。

## 测试

在仓库根目录执行：

```powershell
python -m unittest discover -s tests -v
```

测试使用合成数据，覆盖身份匹配、多学科、同名歧义、缺失值、快照完整性及更新校验；真实 DOI 查询还需网络与本地快照。
