# 全国知识产权案例库来源说明

更新日期：2026-08-28

本轮把既有 1,220 条全国索引扩展至 6,100 条（5 倍），新增 4,880 条。新增样本通过关键词筛选、案号/标题/正文哈希去重和手机号、身份证号、银行卡号脱敏后写入统一 JSON/SQLite 结构。

## 裁判文书网相关来源

- [中国裁判文书网](https://wenshu.court.gov.cn/website/wenshu/181217BMTKHNT2W0/index.html)：用户已登录会话用于确认公开检索入口；本项目不绕过登录、验证码、反爬或付费限制。
- [C3RD / MileCut](https://github.com/YeFD/MileCut)：数据说明称由中国裁判文书网公开民事文书构建；本轮去重后选入 1,097 条。项目只保留结构化索引，不随仓库重新分发 C3RD 原始压缩包。
- [TheFinAI corpus-shard-20](https://huggingface.co/datasets/TheFinAI/corpus-shard-20)：公开语料分片，页面标注 Apache-2.0；本轮下载 34 个分片文件并筛选，选入 3,783 条。每条保存分片路径和行号。
- [AppealCase](https://huggingface.co/datasets/ythuang02/AppealCase)：页面标注来源为裁判文书网、CC BY-NC 4.0；作为候选池完成筛选，本轮因目标已达到未进入最终 6,100 条。
- [ClaimGen-CN](https://huggingface.co/datasets/Josieeee/ClaimGen-CN)：页面标注来源为裁判文书网、CC BY-NC-SA 4.0；其内容是主张/事实片段而非完整裁判文书，仅作为候选池，未进入最终 6,100 条。

## 既有来源

既有 1,220 条继续保留人民法院案例库、最高人民法院年度典型案例、北大法宝检索索引、裁判文书网列表摘要、Figshare CC BY 4.0 研究数据及福建高院公开案例。明细见 [`source-registry.json`](source-registry.json) 与 [`references/expansion-sources.json`](../../references/expansion-sources.json)。

## 使用边界

新增记录全部标记为机器提取或待二次核验。`source_url` 是公开检索入口，`citations` 保存数据集文件、分片、行号等回溯信息；这些字段不能替代逐案打开来源原文。正式法律意见必须核对案号、程序、生效状态、权利基础、证据、裁判理由、主文、赔偿金额及当时有效法律。公开数据存在选择偏差，不得把本库统计当作真实胜诉率。

本项目代码按 MIT 发布；第三方数据集按各自页面许可和访问条款使用。发布包不包含第三方原始大文件，使用者应自行确认再利用、署名、非商业和数据保护义务。
