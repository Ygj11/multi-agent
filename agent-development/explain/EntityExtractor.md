# 实体抽取 entity_extractor.py

## 定义实体，正则抽取
1. 文件：`entity_patterns.yaml`
2. 加载 yaml 文件，得到 `list[EntityPattern]`（正则表达式，后期需要重新维护，如正则表达式、新增实体，修改 yaml 文件即可）
3. 对 `text` 进行 正则化提取，得到 `EntityBag`
4. 对长短期记忆（`extract_from_summary`） 和 最近返回进行（`extract_from_recent_turns`） 的 `content` 提取
5. 也就是说根据定义好的`entity_type`，对 `text` 就进行抽取。


## 实体的作用
1. EntityExtractor
   从文本里抽“有哪些实体”
   输出 EntityBag

2. LLM rewrite

3. intent recognition

4. AgentCard
   声明某个 Agent 关心哪些实体
   用于 Agent 选择打分

5. Skill
   声明某个具体流程必须要哪些实体
   缺失时 clarification

## 