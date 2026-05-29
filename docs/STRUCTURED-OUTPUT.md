# LLM 强 Schema 输出指南 (N2)

> 适用范围：所有需要从 LLM 拿到**结构化数据**(多字段对象)的业务场景
> 目的：彻底斩断"LLM 自由文本污染业务字段"这一类 bug

---

## 为什么需要这一层

V3 在 2026-05-22 之前的一周里,出现过 6 个同类 bug:

| 现象 | 根因 |
|---|---|
| 培训类别字段被填了整段 JSON | 业务方拿 `resp.choices[0].message.content` 直接当 string 写 |
| 首席合规官意见污染 | LLM 把相邻签署人和意见揉成一段返回 |
| 授权请示提取错乱 | LLM 在 JSON 外多写了一段解释 |

**共同模式**:业务方信任了 LLM 输出的"格式",但 LLM 偶尔会:
- 吐 Markdown code fence (` ```json `)
- 在 JSON 前后加解释 ("结果如下:")
- 漏字段、错类型、半截 JSON
- 干脆吐字符串或数组而不是对象

只要业务方拿到的不是**严格符合 schema 的 dict**,就有概率污染数据库。

---

## 两个工具

### 1. `extract_structured` — 同步,只做"安全解析"

适合:已经拿到 LLM 原始字符串、只想安全解析的场景(如离线脚本、迁移工具)。

```python
from pydantic import BaseModel
from utils.llm_extract import extract_structured

class TrainingMeta(BaseModel):
    topic: str
    category: str
    hours: int

result = extract_structured(
    raw_llm_output,           # 任意污染过的字符串都可以
    TrainingMeta,
    fallback=None,            # 解析失败时返回什么
    scene="training_meta",    # 日志里能看到是哪个业务场景出问题
)

if result is None:
    # 走人工 fallback 路径,或者标红让用户复核
    ...
else:
    # result 是严格的 TrainingMeta 实例,可以放心 .topic / .category / .hours
    ...
```

支持的污染场景(已被 10 个测试 case 锁住):

| 输入形态 | 行为 |
|---|---|
| 标准 JSON | ✅ 解析成功 |
| `` ```json {...} ``` `` Markdown 包裹 | ✅ 自动剥外壳 |
| `"结果: {...}"` 解释性前缀 | ✅ 剥前缀后解析 |
| `"....{...}...."` JSON 嵌在文本中 | ✅ 自动捞 JSON 块 |
| 缺必填字段 | ❌ 返回 fallback,不让半截对象流出 |
| 字段类型错(`"hours": "四个"`) | ❌ 返回 fallback |
| 多余字段 | ✅ 默认忽略多余字段 |
| 截断 JSON(`{"topic": "x", "ho` ) | ❌ 返回 fallback |
| 空 / None / 全空白 | ❌ 返回 fallback |
| 数组 / 标量根节点 | ❌ 返回 fallback |

### 2. `call_llm_structured` — 异步,"调用 + 解析"一体

适合:**新业务代码**。一行调用同时拿到:LLMClient 韧性 (重试 / 断路 / 降级) + 强 schema 解析。

```python
from llm_client import call_llm_structured
from pydantic import BaseModel

class ComplianceExtract(BaseModel):
    chief_officer_name: str
    chief_officer_opinion: str
    countersign_units: list[str]

result = await call_llm_structured(
    [
        {"role": "system", "content": "你是合规审查台账抽取助手,严格按 JSON 输出..."},
        {"role": "user", "content": doc_text},
    ],
    ComplianceExtract,
    scene="compliance_extract",
    fallback=None,
)

if result is None:
    # 走人工降级路径
    raise BusinessException("AI 抽取失败,请人工核对")
else:
    save_to_ledger(result.chief_officer_name, result.chief_officer_opinion, ...)
```

内部会:
1. 自动加 `response_format={"type": "json_object"}` 提示 LLM 输出 JSON
2. 如果模型不支持这个参数,自动重试一次去掉它(graceful 降级)
3. 走 LLMClient 完整重试 + 模型降级链(qwen → DeepSeek → GLM → Ollama)
4. 拿到响应后用 `extract_structured` 严格校验
5. 任何环节失败 → 返回 `fallback`,**永远不抛异常**到业务层

---

## 关键设计原则

### ① 错值比无值更危险

宁可 `result is None`(显式空,业务方必须处理),也不允许"半截对象"流出。

### ② 失败都打日志,带 scene

每个 fallback 路径都会写一条 `logger.warning(...)`,日志里带 `scene` 标签,方便事后排查"是哪个业务方在出错"。

### ③ 业务方必须显式处理 None

```python
# ❌ WRONG:错把 None 当对象用
result = await call_llm_structured(...)
save(result.topic)  # AttributeError on None

# ✅ CORRECT:显式判空
result = await call_llm_structured(...)
if result is None:
    return human_review_path()
save(result.topic)
```

---

## 与现有 `extract_short_text` 的关系

| 工具 | 何时用 |
|---|---|
| `extract_short_text` | LLM 只需要吐**一个短词**(类别 / 类型 / 风险等级) |
| `extract_structured` | LLM 需要吐**一个对象**(多字段) |

两个工具**互补**,不互相替代。短词场景继续用 `extract_short_text`(它的白名单兜底机制无可替代);多字段场景必须用 `extract_structured`。

---

## 迁移路径(从老代码迁过来)

**老代码模式**:
```python
client = AsyncOpenAI(...)
resp = await client.chat.completions.create(model="...", messages=[...])
text = resp.choices[0].message.content
data = json.loads(text)         # 可能炸
category = data["category"]      # 可能不存在
save_to_db(category)             # 可能是整段 JSON
```

**新模式**:
```python
class ExtractSchema(BaseModel):
    category: str

result = await call_llm_structured(
    [...],
    ExtractSchema,
    scene="my_business_scene",
    fallback=None,
)
if result is None:
    return human_review_path()
save_to_db(result.category)
```

---

## 测试覆盖

完整测试在 `backend/tests/test_llm_structured.py`,共 12 个 case + 6 个子测试,覆盖:

- 10 个 `extract_structured` 污染场景
- 2 个 `call_llm_structured` 网络层与解析层联动

```powershell
cd backend
python -m pytest tests/test_llm_structured.py -v
```

---

## 配置项

无新配置项 —— 复用 LLMClient 的所有现有 env 开关。

---

## 历史

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-05-29 | v3.6.7 | N2 落地: `extract_structured` + `call_llm_structured` |
