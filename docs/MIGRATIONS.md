# 数据库迁移指南 (alembic)

> 适用范围：**主库**(reactv3，由 `backend/models.py` 定义的 7 张表)
> baseline 已 stamp 于 2026-05-29，版本号 `37d6fb9c6e53`
> llm_audit 子系统(`llm_traces` / `llm_traces_archive`)**不在此 alembic 管辖范围**，由 `include_object` 主动跳过

---

## 当前管辖的表

| 表 | 来源 |
|---|---|
| users / sessions / audit_logs / notification_logs / dingtalk_sync_logs / background_tasks | `backend/models.py` |

不包含：`llm_traces` / `llm_traces_archive`(llm_audit 子系统自管，sqlite/PG 都用 `create_all`)

---

## 常用命令(在 `backend/` 目录下执行)

```powershell
# 查看当前数据库版本
python -m alembic current

# 查看完整迁移历史
python -m alembic history

# 升级到最新版本(执行所有未应用的 migration)
python -m alembic upgrade head

# 降级到上一版(危险，会执行 downgrade 函数)
python -m alembic downgrade -1
```

---

## 加字段的"三步走"

假设要给 `users` 表加一个 `phone` 字段：

### 1. 改 ORM 模型

`backend/models.py`：
```python
class User(Base):
    # ... existing fields ...
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
```

### 2. 生成 migration

```powershell
cd backend
python -m alembic revision --autogenerate -m "add phone to users"
```

生成的脚本会在 `backend/migrations/versions/xxxxxx_add_phone_to_users.py`，**务必人工 review** 一遍：
- 检查 `upgrade()` 函数里只有你想要的改动
- 检查 `downgrade()` 函数能正确回退
- SQLite 兼容性：默认已开 `render_as_batch`，ALTER COLUMN 类操作会自动用 batch_alter_table 包

### 3. 应用到数据库

```powershell
# 本地 / MVP 环境
python -m alembic upgrade head

# 生产环境(配置 APP_DATABASE_URL 指向生产 PG 后执行)
$env:APP_DATABASE_URL="postgresql://..."
python -m alembic upgrade head
```

---

## SQLite vs PostgreSQL 兼容性

| 操作 | SQLite | PG | 注意 |
|---|---|---|---|
| `op.add_column` | ✅ | ✅ | 默认安全 |
| `op.drop_column` | ✅(batch) | ✅ | 默认开 batch |
| `op.alter_column`(改类型/nullable) | ✅(batch) | ✅ | 默认开 batch |
| `op.drop_constraint` | ❌(batch 也救不了某些约束) | ✅ | 大表慎用 |
| `op.create_index` | ✅ | ✅ | |

> **核心规则：所有 ALTER 都用 `with op.batch_alter_table("xxx") as batch_op:` 包裹。env.py 默认开启 `render_as_batch=True`，但手写时也请遵循该惯例。**

---

## 数据库连接配置

URL 来源(按优先级)：
1. `APP_DATABASE_URL` (推荐用于多数据库隔离)
2. `DATABASE_URL`     (向后兼容)
3. `sqlite:///data/auth.db` (本地默认)

`alembic.ini` **不**配置 `sqlalchemy.url`，由 `migrations/env.py` 启动时从 `db.get_database_url()` 注入。

---

## 历史里程碑

| 日期 | 版本号 | 动作 |
|---|---|---|
| 2026-05-29 | `37d6fb9c6e53` | baseline — 主库接管 alembic，stamp 现网 PG 为初版 |

---

## 故障速查

| 现象 | 原因 | 解决 |
|---|---|---|
| `UnicodeDecodeError` 启动失败 | `alembic.ini` 含中文 | 注释必须用 ASCII |
| `unable to open database file` | SQLite 路径用了 `/tmp/` | 改用 `data/xxx.db` 项目内路径 |
| autogenerate 想 DROP `llm_traces*` | `include_object` 过滤失效 | 检查 `migrations/env.py` 里 `LLM_AUDIT_TABLES` 集合是否被改 |
| 生产误跑 `upgrade` 报 "table already exists" | baseline 没 stamp 就 upgrade | 先 `alembic stamp head`，再继续 |
