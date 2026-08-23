---
name: fujian-ip-litigation
description: 检索、比较福建及全国权威知识产权案例，并按商标、著作权、不正当竞争、专利、商业秘密和植物新品种领域分析权利基础、侵权构成、抗辩、证据、赔偿与诉讼方向。适用于具体知识产权民事案件；行政确权和刑事案件仅作分流提示。
---

# 福建知识产权类案检索

把用户叙述转化为可核验的知识产权法律要素，检索全国权威案例与福建地方案例，并生成包含有利和不利材料的类案报告。当前商标模块最完整，其他领域以已核验案例和明确的不足提示为基础逐步扩充。

## 必守边界

- 区分指导性案例、人民法院案例库案例、典型案例和普通生效裁判，不把普通案例表述为具有普遍拘束力。
- 不把公开案例样本中的胜败比例直接称为真实胜诉率；公开文书存在选择偏差。
- 案号、法院、裁判日期、判决结果、法条和赔偿金额必须能回溯到来源或原文段落。无法核实时标注“待核实”，不得补造。
- 同时查找支持、不支持以及因关键事实不同而结果相反的案例。
- 检查案件发生时间、裁判时间和法律版本。旧法案例只能在说明差异后作为历史参考。
- 用户事实、客户材料和证据不得写入公共案例库；发现身份证号、电话、银行账号等敏感信息时先停止入库并提示脱敏。
- 结论使用“倾向”“可能”“存在争议”或“资料不足”，不承诺裁判结果。

## 工作流程

1. 提取权利基础、原告资格、被诉标识、商品或服务、使用方式、销售主体、时间地点、证据、抗辩、请求和金额。
2. 识别缺失的决定性事实；缺失信息不妨碍检索时可带条件继续，可能改变案由、管辖或核心结论时再请用户补充。
3. 读取 [references/domain-routing.md](references/domain-routing.md)，判断领域并加载对应的要素清单。
4. 商标案件读取 [references/trademark-analysis.md](references/trademark-analysis.md)；其他领域若缺少专门规则文件，必须按领域不足清单输出，不得套用商标规则。
5. 需要判断案例权威性、检索顺序或法律版本时，读取 [references/source-ranking.md](references/source-ranking.md)。
5. 优先使用用户明确提供的案例库路径；否则若存在 `data/national-ip-corpus/cases.db`，使用该内置全国案例库。调用 `scripts/search_cases.py` 时，先以案由、法院、年份和程序过滤，再用争议焦点、行为、抗辩和证据关键词检索。不要用裁判结果作为相似度输入。
6. 对候选案例逐一核对来源、生效状态、权利基础、决定性事实、抗辩、证据和法律版本；只有标题或关键词相似的不算类案。
7. 按 [references/report-template.md](references/report-template.md) 输出。材料不足时给出证据清单和下一步检索建议，不强行预测。

## 本地案例库

数据库工具仅使用 Python 标准库。一键安装版本内置 `data/national-ip-corpus/cases.db`；用户通过 `--db` 提供其他路径时，以用户路径为准。工具不会把客户案件或检索结果自动写回内置公共库。`cause_of_action` 和 `rights` 字段用于区分领域；同一数据库可以保存多个知识产权领域。

```powershell
python scripts/init_database.py --db <案例库路径>
python scripts/ingest_cases.py --db <案例库路径> --input <案例JSON或JSONL>
python scripts/search_cases.py --db data/national-ip-corpus/cases.db --query "合法来源 惩罚性赔偿" --limit 10
python scripts/validate_corpus.py --db <案例库路径>
```

数据制作和导入步骤见 [references/data-workflow.md](references/data-workflow.md)，字段定义见 [references/schema.md](references/schema.md)，隐私和引用控制见 [references/safety-rules.md](references/safety-rules.md)。

如果数据库不存在、为空或检索失败，应明确说明当前没有可用本地语料，不得假装已完成福建案例检索。检索结果为空不等于司法实践中不存在此类案件。
