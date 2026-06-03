# 测试覆盖率

> 目的:**看清测试盲区**,为后续重构提供安全网依据。
> 当前不强制阈值(避免一上来就卡 CI),基线记录在此作为"不要倒退"的参照。

## 基线(2026-06-02)

| 范围 | 覆盖率 | 测试数 |
|---|---|---|
| 后端业务代码(排除 tests/migrations) | **63%** | 342 passed |
| 前端 src | **30%** | 39 passed |

## 怎么跑

### 后端

```powershell
cd backend
python -m pytest --cov=. --cov-report=term-missing
# 配置见 backend/.coveragerc(已排除 tests/ migrations/ 缓存)
# 生成 HTML 报告(可选):加 --cov-report=html,产物在 backend/htmlcov/(已 gitignore)
```

### 前端

```powershell
cd frontend
npm run test:coverage
# 配置见 frontend/vitest.config.ts 的 test.coverage(provider: v8)
# HTML 报告在 frontend/coverage/(已 gitignore)
```

## 已知盲区(优先补测的方向)

### 后端 0% / 极低覆盖

| 文件 | 覆盖率 | 说明 |
|---|---|---|
| `utils/mcp_client.py` | 0% | 旧版 MCP 客户端(qcc_mcp_client 是新版,有测试) |
| `utils/write_excel.py` | 0% | Excel 写入 |
| `utils/pdf_reader.py` | 0% | PDF 读取 |
| `utils/classifier.py` | 0% | 旧分类器(skills/classifier 是新版) |
| `utils/excel_merger.py` | ✅ 99%（v3.6.18 已补，原 7%） | 三台账合并核心逻辑——已补 30 个单测 |
| `utils/archiver.py` | 39% | 文件归档 |
| `utils/auth_request_drafter.py` | 65% | 授权请示起草 |
| `utils/qcc_mcp_client.py` | 57% | 企查查客户端 |

### 前端

- `src/skills` 0%(技能注册表,纯配置)
- `src/components` 27%——多数业务组件(各 Flow)无单测,靠 e2e 导航冒烟兜底

## 说明

- ~~**excel_merger.py 7%** 是最该补的~~ → **已于 v3.6.18 补到 99%**:新增 `tests/test_excel_merger.py` 30 个单测,覆盖编号归一化/表头探测/合计行跳过/匹配状态 8 分支/模糊匹配/一对多笛卡尔积/去重/优先级排序/统计计数,通过回读输出 xlsx 验证"合并算得对不对"。
- 覆盖率提升是独立的后续工作,本次只是把"统计能力"建起来 + 记录基线。
- 不纳入 CI 强制阈值:当前 CI 求快稳;若未来要防倒退,可在 CI 加 `--cov-fail-under=60`(后端)的软门禁。
