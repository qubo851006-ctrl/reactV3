# -*- coding: utf-8 -*-
"""
seed_proj_mgmt.py
一键建库、建表、灌入项目/合同/工程变更/付款假数据
依赖：pip install asyncpg --user
用法：python seed_proj_mgmt.py
"""

import asyncio
import asyncpg
import random
from decimal import Decimal
from datetime import date, timedelta

# ── 连接配置 ──────────────────────────────────────────────────────
PG_HOST = "192.168.9.226"
PG_PORT = 5432
PG_USER = "admin"
PG_PASS = "gh100999"
DB_NAME = "proj_mgmt"

# ── DDL ───────────────────────────────────────────────────────────
DDL = """
CREATE TABLE IF NOT EXISTS projects (
    id              SERIAL PRIMARY KEY,
    project_no      VARCHAR(30)   NOT NULL UNIQUE,
    project_name    VARCHAR(200)  NOT NULL,
    owner           VARCHAR(100)  NOT NULL,
    location        VARCHAR(100),
    total_budget    NUMERIC(15,2) NOT NULL,
    start_date      DATE,
    planned_end     DATE,
    actual_end      DATE,
    status          VARCHAR(20)   NOT NULL
        CHECK (status IN ('在建','已完工','暂停','已取消')),
    project_manager VARCHAR(50),
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contracts (
    id              SERIAL PRIMARY KEY,
    contract_no     VARCHAR(50)   NOT NULL UNIQUE,
    project_id      INT           NOT NULL REFERENCES projects(id),
    contract_name   VARCHAR(200)  NOT NULL,
    contract_type   VARCHAR(30)   NOT NULL
        CHECK (contract_type IN ('施工','监理','设计','采购','咨询')),
    party_b         VARCHAR(100)  NOT NULL,
    original_amount NUMERIC(15,2) NOT NULL,
    current_amount  NUMERIC(15,2) NOT NULL,
    sign_date       DATE,
    start_date      DATE,
    end_date        DATE,
    status          VARCHAR(20)   NOT NULL
        CHECK (status IN ('执行中','已完成','已解除','暂停')),
    remarks         TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contract_changes (
    id              SERIAL PRIMARY KEY,
    change_no       VARCHAR(50)   NOT NULL UNIQUE,
    contract_id     INT           NOT NULL REFERENCES contracts(id),
    change_type     VARCHAR(20)   NOT NULL
        CHECK (change_type IN ('增项','减项','工期延误','设计变更')),
    change_reason   TEXT          NOT NULL,
    change_amount   NUMERIC(15,2) NOT NULL,
    original_amount NUMERIC(15,2) NOT NULL,
    new_amount      NUMERIC(15,2) NOT NULL,
    apply_date      DATE,
    approved_date   DATE,
    approved_by     VARCHAR(50),
    status          VARCHAR(20)   NOT NULL
        CHECK (status IN ('待审批','已批准','已拒绝')),
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contract_payments (
    id              SERIAL PRIMARY KEY,
    payment_no      VARCHAR(50)   NOT NULL UNIQUE,
    contract_id     INT           NOT NULL REFERENCES contracts(id),
    payment_type    VARCHAR(20)   NOT NULL
        CHECK (payment_type IN ('预付款','进度款','结算款','质保金退还')),
    amount          NUMERIC(15,2) NOT NULL,
    payment_date    DATE,
    plan_date       DATE,
    payment_method  VARCHAR(20)   DEFAULT '银行转账'
        CHECK (payment_method IN ('银行转账','承兑汇票','现金')),
    bank_account    VARCHAR(50),
    approved_by     VARCHAR(50),
    status          VARCHAR(20)   NOT NULL
        CHECK (status IN ('待审批','已付款','已退回','逾期未付')),
    remarks         TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);
"""

# ── 假数据素材 ─────────────────────────────────────────────────────
OWNERS = [
    "华润置业有限公司", "中国建筑股份有限公司", "万科企业股份有限公司",
    "绿地集团", "碧桂园控股有限公司", "招商蛇口工业区控股",
    "保利发展控股集团", "龙湖集团控股有限公司",
]
CONTRACTORS = [
    "中建三局集团有限公司", "上海建工集团股份有限公司",
    "北京城建集团有限责任公司", "中铁建工集团有限公司",
    "广州建筑股份有限公司", "四川华西集团有限公司",
    "中天建设集团有限公司", "苏中建设集团股份有限公司",
    "腾达建设集团股份有限公司", "东方建设集团有限公司",
]
SUPERVISORS = [
    "国检集团工程咨询有限公司", "北京中咨工程管理咨询有限公司",
    "上海同济工程咨询有限公司", "中国建设监理协会培训中心",
]
DESIGNERS = [
    "华东建筑设计研究院有限公司", "北京市建筑设计研究院有限公司",
    "中国建筑西南设计研究院有限公司", "广州市设计院集团有限公司",
]
LOCATIONS = [
    "北京市朝阳区", "上海市浦东新区", "广州市天河区",
    "深圳市南山区", "成都市高新区", "武汉市江汉区",
    "杭州市滨江区", "南京市建邺区",
]
MANAGERS  = ["张伟", "李强", "王芳", "刘洋", "陈静", "赵磊", "孙敏", "周鹏", "吴婷", "郑浩"]
APPROVERS = ["王总", "李总监", "张副总", "刘主任", "陈部长"]
CHANGE_REASONS = [
    "业主要求增加地下室层数，导致基础工程量增加",
    "地质勘察与实际不符，需增加桩基深度",
    "设计优化调整，减少部分外立面装饰材料",
    "政府规划要求变更建筑外立面风格",
    "材料价格上涨，合同价格按约定进行调差",
    "施工过程中发现隐蔽管线，需绕行处理",
    "建设单位要求增加智能化系统配置",
    "受疫情影响工期顺延，相应费用补偿",
    "减少部分景观绿化工程量以控制总投资",
    "增加消防改造工程内容",
]

# (编号, 名称, 状态, 预算(万元), 开始日期, 计划竣工)
PROJECTS_RAW = [
    ("PRJ-2022-001", "智慧园区综合体建设项目",    "在建",   8500,  "2022-03-01", "2024-12-31"),
    ("PRJ-2022-002", "数据中心机房改造工程",        "已完工", 3200,  "2022-06-15", "2023-09-30"),
    ("PRJ-2022-003", "配电系统升级改造项目",        "已完工", 1800,  "2022-04-01", "2023-03-31"),
    ("PRJ-2023-001", "研发楼新建工程",              "在建",   12000, "2023-01-10", "2025-06-30"),
    ("PRJ-2023-002", "办公楼装修改造项目",          "在建",   2600,  "2023-05-20", "2024-08-31"),
    ("PRJ-2023-003", "仓储物流中心建设工程",        "暂停",   5400,  "2023-03-01", "2025-03-31"),
    ("PRJ-2023-004", "生产线自动化升级改造",        "在建",   9800,  "2023-08-01", "2025-12-31"),
    ("PRJ-2024-001", "停车场扩建及智能化改造项目",  "在建",   1500,  "2024-01-15", "2024-12-31"),
    ("PRJ-2024-002", "员工宿舍楼新建项目",          "在建",   7200,  "2024-03-01", "2026-06-30"),
    ("PRJ-2024-003", "厂区道路及绿化综合提升工程",  "已取消", 980,   "2024-02-01", "2024-10-31"),
]


def rdate(start: str, end: str) -> date:
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    delta = (e - s).days
    return s + timedelta(days=random.randint(0, max(delta, 0)))


def dec(v: float) -> Decimal:
    return Decimal(str(round(v, 2)))


# ── 建库（连 postgres 系统库创建新库）────────────────────────────
async def create_database():
    try:
        conn = await asyncpg.connect(
            host=PG_HOST, port=PG_PORT,
            user=PG_USER, password=PG_PASS,
            database="postgres"
        )
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname=$1", DB_NAME
        )
        if exists:
            print(f"[跳过] 数据库 {DB_NAME} 已存在")
        else:
            await conn.execute(f'CREATE DATABASE "{DB_NAME}" ENCODING=\'UTF8\'')
            print(f"[创建] 数据库 {DB_NAME} 已创建")
        await conn.close()
    except Exception as e:
        print(f"[错误] 建库失败：{e}")
        raise


# ── 主流程 ────────────────────────────────────────────────────────
async def seed():
    await create_database()

    conn = await asyncpg.connect(
        host=PG_HOST, port=PG_PORT,
        user=PG_USER, password=PG_PASS,
        database=DB_NAME
    )

    async with conn.transaction():
        # 建表
        await conn.execute(DDL)
        print("[建表] 4 张表创建/确认完成")

        # ── 插项目 ──────────────────────────────────────────────
        project_ids = []   # (id, budget_float, start_str, end_str, status)
        for no, name, status, budget_w, start, planned_end in PROJECTS_RAW:
            budget = dec(budget_w * 10000)
            actual_end = None
            if status == "已完工":
                actual_end = date.fromisoformat(planned_end) + timedelta(days=random.randint(-30, 60))

            pid = await conn.fetchval("""
                INSERT INTO projects
                  (project_no, project_name, owner, location, total_budget,
                   start_date, planned_end, actual_end, status, project_manager)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT (project_no) DO UPDATE SET project_no=EXCLUDED.project_no
                RETURNING id
            """,
                no, name,
                random.choice(OWNERS), random.choice(LOCATIONS),
                budget,
                date.fromisoformat(start), date.fromisoformat(planned_end),
                actual_end, status, random.choice(MANAGERS),
            )
            project_ids.append((pid, float(budget), start, planned_end, status))

        print(f"[项目] 写入 {len(project_ids)} 条")

        # ── 插合同 ──────────────────────────────────────────────
        contract_ids = []   # (id, current_amount_float, sign_str, end_str, status)
        c_seq = 1
        for proj_id, proj_budget, proj_start, proj_end, proj_status in project_ids:
            c_status = (
                "已完成" if proj_status == "已完工" else
                "已解除" if proj_status == "已取消" else
                "执行中"
            )
            sign = rdate(proj_start, proj_start[:4] + "-12-31")
            end  = date.fromisoformat(proj_end) + timedelta(days=random.randint(0, 90))

            # 施工合同
            amt = round(proj_budget * random.uniform(0.55, 0.75), 2)
            cno = f"CT-{c_seq:04d}"; c_seq += 1
            cid = await conn.fetchval("""
                INSERT INTO contracts
                  (contract_no, project_id, contract_name, contract_type,
                   party_b, original_amount, current_amount,
                   sign_date, start_date, end_date, status)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ON CONFLICT (contract_no) DO UPDATE SET contract_no=EXCLUDED.contract_no
                RETURNING id
            """, cno, proj_id, "主体施工总承包合同", "施工",
                random.choice(CONTRACTORS),
                dec(amt), dec(amt),
                sign, date.fromisoformat(proj_start), end, c_status,
            )
            contract_ids.append((cid, amt, str(sign), str(end), c_status))

            # 监理合同
            sup_amt = round(proj_budget * random.uniform(0.015, 0.03), 2)
            cno2 = f"CT-{c_seq:04d}"; c_seq += 1
            cid2 = await conn.fetchval("""
                INSERT INTO contracts
                  (contract_no, project_id, contract_name, contract_type,
                   party_b, original_amount, current_amount,
                   sign_date, start_date, end_date, status)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ON CONFLICT (contract_no) DO UPDATE SET contract_no=EXCLUDED.contract_no
                RETURNING id
            """, cno2, proj_id, "工程监理服务合同", "监理",
                random.choice(SUPERVISORS),
                dec(sup_amt), dec(sup_amt),
                sign, date.fromisoformat(proj_start), end, c_status,
            )
            contract_ids.append((cid2, sup_amt, str(sign), str(end), c_status))

            # 大项目加设计合同
            if proj_budget > 50_000_000:
                des_amt = round(proj_budget * random.uniform(0.01, 0.02), 2)
                cno3 = f"CT-{c_seq:04d}"; c_seq += 1
                cid3 = await conn.fetchval("""
                    INSERT INTO contracts
                      (contract_no, project_id, contract_name, contract_type,
                       party_b, original_amount, current_amount,
                       sign_date, start_date, end_date, status)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    ON CONFLICT (contract_no) DO UPDATE SET contract_no=EXCLUDED.contract_no
                    RETURNING id
                """, cno3, proj_id, "工程设计服务合同", "设计",
                    random.choice(DESIGNERS),
                    dec(des_amt), dec(des_amt),
                    sign, date.fromisoformat(proj_start), end, c_status,
                )
                contract_ids.append((cid3, des_amt, str(sign), str(end), c_status))

        print(f"[合同] 写入 {len(contract_ids)} 条")

        # ── 插工程变更 ────────────────────────────────────────────
        ch_seq = 1; change_count = 0
        for c_id, c_amt, c_sign, c_end, c_status in contract_ids:
            if c_status == "已解除":
                continue
            running = c_amt
            for _ in range(random.randint(1, 3)):
                delta = round(running * random.uniform(0.02, 0.12) * (1 if random.random() < 0.7 else -1), 2)
                new_amt = round(running + delta, 2)
                apply_d = rdate(c_sign, c_end)
                ch_status = random.choices(["已批准","待审批","已拒绝"], weights=[70,20,10])[0]
                ch_no = f"CHG-{ch_seq:04d}"; ch_seq += 1

                await conn.execute("""
                    INSERT INTO contract_changes
                      (change_no, contract_id, change_type, change_reason,
                       change_amount, original_amount, new_amount,
                       apply_date, approved_date, approved_by, status)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    ON CONFLICT (change_no) DO NOTHING
                """,
                    ch_no, c_id,
                    "增项" if delta > 0 else "减项",
                    random.choice(CHANGE_REASONS),
                    dec(delta), dec(running), dec(new_amt),
                    apply_d,
                    apply_d + timedelta(days=random.randint(7,30)) if ch_status != "待审批" else None,
                    random.choice(APPROVERS) if ch_status != "待审批" else None,
                    ch_status,
                )
                if ch_status == "已批准":
                    running = new_amt
                    await conn.execute(
                        "UPDATE contracts SET current_amount=$1 WHERE id=$2",
                        dec(running), c_id
                    )
                change_count += 1

        print(f"[变更] 写入 {change_count} 条")

        # ── 插付款记录 ────────────────────────────────────────────
        pay_seq = 1; pay_count = 0
        for c_id, c_amt, c_sign, c_end, c_status in contract_ids:
            if c_status == "已解除":
                continue
            cur_amt_row = await conn.fetchrow("SELECT current_amount FROM contracts WHERE id=$1", c_id)
            total = float(cur_amt_row["current_amount"])

            # 预付款
            pre_pct = random.uniform(0.10, 0.30)
            pre_amt = round(total * pre_pct, 2)
            pre_d   = date.fromisoformat(c_sign) + timedelta(days=random.randint(7, 30))

            payments = [("预付款", pre_amt, pre_d, "已付款")]
            paid = pre_pct

            # 进度款
            for i in range(random.randint(2, 4)):
                if paid >= 0.85:
                    break
                pct = min(random.uniform(0.10, 0.20), 0.85 - paid)
                p_d = pre_d + timedelta(days=random.randint(60, 180) * (i + 1))
                ps = "已付款" if p_d < date.today() else "待审批"
                if ps == "待审批" and random.random() < 0.15:
                    ps = "逾期未付"
                payments.append(("进度款", round(total * pct, 2), p_d, ps))
                paid += pct

            # 结算款 + 质保金（已完成合同）
            if c_status == "已完成":
                rem = round(0.95 - paid, 4)
                if rem > 0:
                    s_d = date.fromisoformat(c_end) + timedelta(days=random.randint(30, 90))
                    payments.append(("结算款", round(total * rem, 2), s_d, "已付款"))
                qb_d = date.fromisoformat(c_end) + timedelta(days=random.randint(365, 730))
                payments.append(("质保金退还", round(total * 0.05, 2), qb_d,
                                  "已付款" if qb_d < date.today() else "待审批"))

            for p_type, p_amt, p_date, p_status in payments:
                pay_no = f"PAY-{pay_seq:04d}"; pay_seq += 1
                await conn.execute("""
                    INSERT INTO contract_payments
                      (payment_no, contract_id, payment_type, amount,
                       payment_date, plan_date, payment_method,
                       bank_account, approved_by, status)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                    ON CONFLICT (payment_no) DO NOTHING
                """,
                    pay_no, c_id, p_type, dec(p_amt),
                    p_date, p_date - timedelta(days=random.randint(0, 15)),
                    random.choices(["银行转账","承兑汇票"], weights=[85,15])[0],
                    f"****{random.randint(1000,9999)}",
                    random.choice(APPROVERS),
                    p_status,
                )
                pay_count += 1

        print(f"[付款] 写入 {pay_count} 条")

    # 统计
    print("=" * 50)
    print("  全部完成！数据库摘要：")
    for tbl in ["projects", "contracts", "contract_changes", "contract_payments"]:
        cnt = await conn.fetchval(f"SELECT COUNT(*) FROM {tbl}")
        print(f"  {tbl:<28} {cnt:>4} 条")
    print("=" * 50)

    await conn.close()


if __name__ == "__main__":
    random.seed(42)
    asyncio.run(seed())
