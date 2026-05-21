# V3 后台任务化说明

## 当前范围

第一版只接入三台账合并，保留原同步接口不变：

- `POST /api/ledger-merge/merge-task`：提交三台账合并任务，立即返回 `task_id`。
- `GET /api/tasks/{task_id}`：查询任务状态、进度、结果或错误。
- `GET /api/tasks/{task_id}/events`：预留 SSE 进度流接口。
- `POST /api/ledger-merge/merge`：旧同步接口仍保留，避免影响已有调用。

## 状态字段

任务存储在主业务库 `background_tasks` 表中：

- `queued`：已提交，等待执行
- `running`：后台处理中
- `succeeded`：处理完成，`result` 内返回业务结果
- `failed`：处理失败，`error` 内返回简短错误
- `cancelled`：预留取消状态

## 三台账合并流程

1. 前端上传合同、采购、财务台账。
2. 后端校验文件后创建后台任务并返回 `task_id`。
3. 后台线程执行 Excel 合并、保存本次结果和 latest 文件。
4. 成功或失败后继续复用现有钉钉通知层。
5. 前端轮询 `/api/tasks/{task_id}`，完成后展示统计并允许下载。

## 部署注意

主业务库会在后端启动或运行 `python tools/check_main_db.py` 时自动创建 `background_tasks` 表。

本版后台任务是进程内线程池，适合当前单机部署。后续如果任务量上升，可把 `task_runner.py` 替换为 Redis/Celery/RQ 等队列，前端和业务接口不用大改。
