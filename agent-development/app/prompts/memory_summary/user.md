previous_summary:
{previous_summary}

current_turn:
{current_turn}

要求：
1. 输出一段中文自然语言摘要。
2. 不要输出 JSON。
3. 不要输出 Markdown。
4. 不要编造不存在的保单号、请求ID、错误码、理赔号、接口名。
5. 摘要需要承接 previous_summary，而不是只总结当前轮。
6. 摘要需要保留当前任务、关键业务实体、已知结论和尚未解决的问题。
7. 如果用户下一轮说“这个/那个/继续/谁的问题”，应能根据摘要判断指代对象。
8. 摘要长度控制在 150～300 字之间。
