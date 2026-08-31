# 全国知识产权案例库（5 倍扩充版）

## 当前规模

- 共 **6,100 条**全国知识产权案例索引，是 1,220 条既有库的 5 倍；本轮净增加 4,880 条。
- 主要来源构成：最高人民法院年度典型案例 395 条、人民法院案例库 326 条、Figshare CC BY 4.0 样本 241 条、裁判文书网列表摘要 233 条、北大法宝索引 22 条，以及裁判文书网衍生公开研究语料 4,880 条。
- 六大核心领域均有覆盖；领域标签允许交叉归类，因此各领域数量之和可能大于总量。按主标签计：商标 1,670 条、著作权 2,974 条、专利（含外观设计）516 条、不正当竞争（含交叉）249 条、商业秘密 260 条、植物新品种 129 条。
- `case_id` 与正文哈希均全局唯一；SQLite `cases` 表与 JSON 数量一致，结构错误为 0。
- 新增记录均保留来源入口、数据集分片/行号引用和机器提取状态；不得把索引摘要直接当作完整裁判理由或判决主文。

## 文件

- `cases.json`：6,100 条结构化案例索引。
- `cases.db`：可直接检索的轻量 SQLite 数据库；为控制分发体积未附带三元组 FTS，`search_cases.py` 使用可解释的结构化关键词评分。
- `collection-summary.json`：数量、领域和来源统计。
- `expansion-audit.json`：5 倍扩容、去重、质量检查和限制。
- `quality-audit.json`：标题/法院字段污染、案号/日期占位、文书类型、来源链接和敏感信息审计结果。
- `source-registry.json`、`provenance.md`：来源、许可和回溯边界。

## 检索示例

```powershell
python ../../scripts/search_cases.py --db .\cases.db --query "软件 著作权" --limit 10
python ../../scripts/validate_corpus.py --db .\cases.db
python ../../scripts/audit_case_fields.py --db .\cases.db --out .\quality-audit.json
```

正式使用前请回到来源原文核对案号、程序、法律版本、生效状态和裁判主文。
