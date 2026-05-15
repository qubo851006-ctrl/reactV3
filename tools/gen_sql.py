# -*- coding: utf-8 -*-
"""
gen_sql.py
生成可直接在 psql 中执行的 SQL 文件
用法：python gen_sql.py > seed.sql
"""

import random
from datetime import date, timedelta
from decimal import Decimal

random.seed(42)

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


def q(s):
    """SQL 单引号转义"""
    if s is None:
        return "NULL"
    return "'" + str(s).replace("'", "''") + "'"


def qd(d):
    return f"'{d}'" if d else "NULL"


def rdate(start: str, end: str) -> date:
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    delta = (e - s).days
    return s + timedelta(days=random.randint(0, max(delta, 0)))


lines = []

# ── DDL ───────────────────────────────────────────────────────────
lines.append("""-- =============================================
-- 项目合同管理数据库初始化脚本
-- 数据库：qubotest
-- =============================================
SET client_encoding = 'UTF8';

-- 建表
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
""")

# ── 插项目 ────────────────────────────────────────────────────────
lines.append("-- ── 项目数据 ──")
proj_info = []  # (no, budget_float, start, planned_end, status)
for no, name, status, budget_w, start, planned_end in PROJECTS_RAW:
    budget = round(budget_w * 10000, 2)
    actual_end = None
    if status == "已完工":
        actual_end = date.fromisoformat(planned_end) + timedelta(days=random.randint(-30, 60))
    lines.append(
        f"INSERT INTO projects (project_no,project_name,owner,location,total_budget,"
        f"start_date,planned_end,actual_end,status,project_manager) VALUES ("
        f"{q(no)},{q(name)},{q(random.choice(OWNERS))},{q(random.choice(LOCATIONS))},"
        f"{budget},{qd(start)},{qd(planned_end)},{qd(actual_end)},"
        f"{q(status)},{q(random.choice(MANAGERS))});"
    )
    proj_info.append((no, budget, start, planned_end, status))

# ── 插合同 ────────────────────────────────────────────────────────
lines.append("\n-- ── 合同数据 ──")
contract_info = []  # (no, amt, sign, end, status)
c_seq = 1
for proj_no, proj_budget, proj_start, proj_end, proj_status in proj_info:
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
    lines.append(
        f"INSERT INTO contracts (contract_no,project_id,contract_name,contract_type,"
        f"party_b,original_amount,current_amount,sign_date,start_date,end_date,status) VALUES ("
        f"{q(cno)},(SELECT id FROM projects WHERE project_no={q(proj_no)}),"
        f"{q('主体施工总承包合同')},{q('施工')},"
        f"{q(random.choice(CONTRACTORS))},{amt},{amt},"
        f"{qd(sign)},{qd(proj_start)},{qd(end)},{q(c_status)});"
    )
    contract_info.append((cno, amt, str(sign), str(end), c_status))

    # 监理合同
    sup_amt = round(proj_budget * random.uniform(0.015, 0.03), 2)
    cno2 = f"CT-{c_seq:04d}"; c_seq += 1
    lines.append(
        f"INSERT INTO contracts (contract_no,project_id,contract_name,contract_type,"
        f"party_b,original_amount,current_amount,sign_date,start_date,end_date,status) VALUES ("
        f"{q(cno2)},(SELECT id FROM projects WHERE project_no={q(proj_no)}),"
        f"{q('工程监理服务合同')},{q('监理')},"
        f"{q(random.choice(SUPERVISORS))},{sup_amt},{sup_amt},"
        f"{qd(sign)},{qd(proj_start)},{qd(end)},{q(c_status)});"
    )
    contract_info.append((cno2, sup_amt, str(sign), str(end), c_status))

    # 大项目加设计合同
    if proj_budget > 50_000_000:
        des_amt = round(proj_budget * random.uniform(0.01, 0.02), 2)
        cno3 = f"CT-{c_seq:04d}"; c_seq += 1
        lines.append(
            f"INSERT INTO contracts (contract_no,project_id,contract_name,contract_type,"
            f"party_b,original_amount,current_amount,sign_date,start_date,end_date,status) VALUES ("
            f"{q(cno3)},(SELECT id FROM projects WHERE project_no={q(proj_no)}),"
            f"{q('工程设计服务合同')},{q('设计')},"
            f"{q(random.choice(DESIGNERS))},{des_amt},{des_amt},"
            f"{qd(sign)},{qd(proj_start)},{qd(end)},{q(c_status)});"
        )
        contract_info.append((cno3, des_amt, str(sign), str(end), c_status))

# ── 插工程变更 ────────────────────────────────────────────────────
lines.append("\n-- ── 工程变更数据 ──")
ch_seq = 1
for cno, c_amt, c_sign, c_end, c_status in contract_info:
    if c_status == "已解除":
        continue
    running = c_amt
    for _ in range(random.randint(1, 3)):
        delta = round(running * random.uniform(0.02, 0.12) * (1 if random.random() < 0.7 else -1), 2)
        new_amt = round(running + delta, 2)
        apply_d = rdate(c_sign, c_end)
        ch_status = random.choices(["已批准","待审批","已拒绝"], weights=[70,20,10])[0]
        approved_d = apply_d + timedelta(days=random.randint(7,30)) if ch_status != "待审批" else None
        approved_by = random.choice(APPROVERS) if ch_status != "待审批" else None
        ch_no = f"CHG-{ch_seq:04d}"; ch_seq += 1
        lines.append(
            f"INSERT INTO contract_changes (change_no,contract_id,change_type,change_reason,"
            f"change_amount,original_amount,new_amount,apply_date,approved_date,approved_by,status) VALUES ("
            f"{q(ch_no)},(SELECT id FROM contracts WHERE contract_no={q(cno)}),"
            f"{q('增项' if delta>0 else '减项')},{q(random.choice(CHANGE_REASONS))},"
            f"{delta},{running},{new_amt},"
            f"{qd(apply_d)},{qd(approved_d)},{q(approved_by)},{q(ch_status)});"
        )
        if ch_status == "已批准":
            running = new_amt
            lines.append(
                f"UPDATE contracts SET current_amount={running} WHERE contract_no={q(cno)};"
            )

# ── 插付款记录 ────────────────────────────────────────────────────
lines.append("\n-- ── 付款记录数据 ──")
pay_seq = 1
for cno, c_amt, c_sign, c_end, c_status in contract_info:
    if c_status == "已解除":
        continue
    # 用变更后金额（近似用 c_amt 的 1.05 倍模拟）
    total = c_amt

    pre_pct = random.uniform(0.10, 0.30)
    pre_amt = round(total * pre_pct, 2)
    pre_d   = date.fromisoformat(c_sign) + timedelta(days=random.randint(7, 30))
    pay_no  = f"PAY-{pay_seq:04d}"; pay_seq += 1
    lines.append(
        f"INSERT INTO contract_payments (payment_no,contract_id,payment_type,amount,"
        f"payment_date,plan_date,payment_method,bank_account,approved_by,status) VALUES ("
        f"{q(pay_no)},(SELECT id FROM contracts WHERE contract_no={q(cno)}),"
        f"{q('预付款')},{pre_amt},"
        f"{qd(pre_d)},{qd(pre_d - timedelta(days=random.randint(0,15)))},"
        f"{q('银行转账')},{q(f'****{random.randint(1000,9999)}')},"
        f"{q(random.choice(APPROVERS))},{q('已付款')});"
    )

    paid = pre_pct
    for i in range(random.randint(2, 4)):
        if paid >= 0.85:
            break
        pct = min(random.uniform(0.10, 0.20), 0.85 - paid)
        p_amt = round(total * pct, 2)
        p_d   = pre_d + timedelta(days=random.randint(60, 180) * (i + 1))
        ps    = "已付款" if p_d < date.today() else "待审批"
        if ps == "待审批" and random.random() < 0.15:
            ps = "逾期未付"
        pay_no = f"PAY-{pay_seq:04d}"; pay_seq += 1
        method = random.choices(["银行转账","承兑汇票"], weights=[85,15])[0]
        lines.append(
            f"INSERT INTO contract_payments (payment_no,contract_id,payment_type,amount,"
            f"payment_date,plan_date,payment_method,bank_account,approved_by,status) VALUES ("
            f"{q(pay_no)},(SELECT id FROM contracts WHERE contract_no={q(cno)}),"
            f"{q('进度款')},{p_amt},"
            f"{qd(p_d)},{qd(p_d - timedelta(days=random.randint(0,15)))},"
            f"{q(method)},{q(f'****{random.randint(1000,9999)}')},"
            f"{q(random.choice(APPROVERS))},{q(ps)});"
        )
        paid += pct

    if c_status == "已完成":
        rem = round(0.95 - paid, 4)
        if rem > 0:
            s_d = date.fromisoformat(c_end) + timedelta(days=random.randint(30, 90))
            pay_no = f"PAY-{pay_seq:04d}"; pay_seq += 1
            lines.append(
                f"INSERT INTO contract_payments (payment_no,contract_id,payment_type,amount,"
                f"payment_date,plan_date,payment_method,bank_account,approved_by,status) VALUES ("
                f"{q(pay_no)},(SELECT id FROM contracts WHERE contract_no={q(cno)}),"
                f"{q('结算款')},{round(total*rem,2)},"
                f"{qd(s_d)},{qd(s_d - timedelta(days=10))},"
                f"{q('银行转账')},{q(f'****{random.randint(1000,9999)}')},"
                f"{q(random.choice(APPROVERS))},{q('已付款')});"
            )
        qb_d = date.fromisoformat(c_end) + timedelta(days=random.randint(365, 730))
        pay_no = f"PAY-{pay_seq:04d}"; pay_seq += 1
        lines.append(
            f"INSERT INTO contract_payments (payment_no,contract_id,payment_type,amount,"
            f"payment_date,plan_date,payment_method,bank_account,approved_by,status) VALUES ("
            f"{q(pay_no)},(SELECT id FROM contracts WHERE contract_no={q(cno)}),"
            f"{q('质保金退还')},{round(total*0.05,2)},"
            f"{qd(qb_d)},{qd(qb_d - timedelta(days=10))},"
            f"{q('银行转账')},{q(f'****{random.randint(1000,9999)}')},"
            f"{q(random.choice(APPROVERS))},"
            f"{q('已付款' if qb_d < date.today() else '待审批')});"
        )

lines.append("\n-- 统计验证")
for tbl in ["projects", "contracts", "contract_changes", "contract_payments"]:
    lines.append(f"SELECT '{tbl}' AS 表名, COUNT(*) AS 条数 FROM {tbl};")

output = "\n".join(lines)
# 写文件
with open("seed.sql", "w", encoding="utf-8") as f:
    f.write(output)

print(f"已生成 seed.sql，共 {len(lines)} 行")
print(f"  项目: {len(proj_info)} 条")
print(f"  合同: {len(contract_info)} 条")
