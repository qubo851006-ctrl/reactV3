"""
单元测试：utils/qcc_debt_assessment.py 中的纯函数与评级逻辑
覆盖：_count_risk, _extract_key_persons, _calculate_rating, format_assessment_markdown
"""
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


# ── _count_risk ───────────────────────────────────────────────────────────


class CountRiskTests(unittest.TestCase):
    def _fn(self):
        from utils.qcc_debt_assessment import _count_risk
        return _count_risk

    def test_none_and_empty_returns_zero(self):
        fn = self._fn()
        for v in (None, {}, []):
            self.assertEqual(fn(v), 0, f"期望 0，输入：{v!r}")

    def test_error_dict_returns_zero(self):
        fn = self._fn()
        self.assertEqual(fn({"_error": "connection timeout"}), 0)

    def test_list_returns_length(self):
        fn = self._fn()
        self.assertEqual(fn([1, 2, 3]), 3)
        self.assertEqual(fn([{"id": 1}]), 1)

    def test_dict_with_total_key(self):
        fn = self._fn()
        self.assertEqual(fn({"total": 7, "list": [1, 2, 3]}), 7)

    def test_dict_with_count_key(self):
        fn = self._fn()
        self.assertEqual(fn({"count": 4}), 4)

    def test_dict_with_data_list(self):
        fn = self._fn()
        self.assertEqual(fn({"data": [1, 2, 3, 4]}), 4)

    def test_non_empty_dict_returns_one(self):
        fn = self._fn()
        self.assertEqual(fn({"key": "value"}), 1)

    def test_empty_total_falls_through_to_list(self):
        """total=0 不触发，继续用 list 长度。"""
        fn = self._fn()
        self.assertEqual(fn({"total": 0, "data": [1, 2]}), 2)


# ── _extract_key_persons ──────────────────────────────────────────────────


class ExtractKeyPersonsTests(unittest.TestCase):
    def _fn(self):
        from utils.qcc_debt_assessment import _extract_key_persons
        return _extract_key_persons

    def test_legal_rep_placed_first(self):
        fn = self._fn()
        personnel = [
            {"name": "王五", "position": "董事"},
            {"name": "张三", "position": "法定代表人"},
            {"name": "李四", "position": "监事"},
        ]
        persons = fn(personnel, None)
        self.assertEqual(persons[0], "张三")
        self.assertIn("王五", persons)

    def test_deduplication(self):
        fn = self._fn()
        personnel = [
            {"name": "张三", "position": "法定代表人"},
            {"name": "张三", "position": "董事"},
        ]
        self.assertEqual(fn(personnel, None).count("张三"), 1)

    def test_limits_to_three(self):
        fn = self._fn()
        personnel = [{"name": f"人{i}", "position": "董事"} for i in range(10)]
        self.assertLessEqual(len(fn(personnel, None)), 3)

    def test_empty_input_returns_empty(self):
        fn = self._fn()
        self.assertEqual(fn(None, None), [])
        self.assertEqual(fn([], None), [])

    def test_actual_controller_dict_supplements(self):
        fn = self._fn()
        persons = fn([], {"name": "实控人甲"})
        self.assertIn("实控人甲", persons)

    def test_actual_controller_list_supplements(self):
        fn = self._fn()
        persons = fn([], [{"name": "实控人乙"}, {"name": "实控人丙"}])
        self.assertIn("实控人乙", persons)


# ── _calculate_rating ─────────────────────────────────────────────────────


class CalculateRatingTests(unittest.TestCase):
    def _fn(self):
        from utils.qcc_debt_assessment import _calculate_rating
        return _calculate_rating

    @staticmethod
    def _dim1(status_text="存续", cancelled=False, bankrupt=False):
        return {
            "工商登记": {"name": "测试企业", "status": status_text},
            "财务数据": {},
            "注销备案": {"date": "2024-01-01"} if cancelled else {},
            "破产重整": [{"case": "test"}] if bankrupt else {},
        }

    @staticmethod
    def _dim3(**overrides):
        base = {
            "失信被执行": [],
            "被执行信息": [],
            "限制高消费": [],
            "终结执行": [],
            "债券违约": [],
            "对外担保": [],
            "欠税公告": [],
        }
        base.update(overrides)
        return base

    def test_clean_company_gets_s(self):
        fn = self._fn()
        rating, rng, _ = fn(self._dim1(), {}, self._dim3(), 1_000_000)
        self.assertEqual(rating, "S")
        self.assertGreaterEqual(rng[0], 60)

    def test_few_risks_gets_a(self):
        fn = self._fn()
        dim3 = self._dim3(
            失信被执行=[{}],
            被执行信息=[{}, {}],
        )
        rating, rng, _ = fn(self._dim1(), {}, dim3, 1_000_000)
        self.assertEqual(rating, "A")

    def test_many_risks_gets_c_or_d(self):
        fn = self._fn()
        dim3 = self._dim3(
            失信被执行=[{}] * 6,
            被执行信息=[{}] * 10,
            终结执行=[{}] * 5,
            限制高消费=[{}] * 2,
        )
        rating, rng, _ = fn(self._dim1(), {}, dim3, 1_000_000)
        self.assertIn(rating, ("C", "D"))
        self.assertLessEqual(rng[1], 30)

    def test_cancelled_company_always_d(self):
        fn = self._fn()
        rating, rng, note = fn(self._dim1(status_text="注销"), {}, self._dim3(), 0)
        self.assertEqual(rating, "D")
        self.assertLessEqual(rng[1], 10)

    def test_bankrupt_company_always_d(self):
        fn = self._fn()
        rating, rng, _ = fn(self._dim1(bankrupt=True), {}, self._dim3(), 0)
        self.assertEqual(rating, "D")

    def test_high_encumbered_assets_downgrades_s_to_a(self):
        """可执行资产大量被设定他项权利时，S 降为 A。"""
        fn = self._fn()
        dim2 = {
            "动产抵押": [{}],
            "股权出质": [{}],
            "土地抵押": [{}],
        }
        rating, _, _ = fn(self._dim1(), dim2, self._dim3(), 1_000_000)
        self.assertIn(rating, ("A", "B"))  # 不能仍是 S

    def test_recovery_range_never_negative(self):
        fn = self._fn()
        dim3 = self._dim3(
            失信被执行=[{}] * 20,
            被执行信息=[{}] * 20,
            终结执行=[{}] * 20,
        )
        dim2 = {k: [{}] for k in ("动产抵押", "股权出质", "土地抵押")}
        _, rng, _ = fn(self._dim1(), dim2, dim3, 0)
        self.assertGreaterEqual(rng[0], 0)
        self.assertGreaterEqual(rng[1], 0)


# ── format_assessment_markdown ────────────────────────────────────────────


class FormatAssessmentMarkdownTests(unittest.TestCase):
    def _make_result(self, rating="A", amount=5_000_000.0, dim5=None):
        return {
            "company_name": "测试科技有限公司",
            "claim_amount": amount,
            "rating": rating,
            "recovery_range": (45, 65),
            "rating_note": "存在少量司法事件，建议激进保全策略。",
            "dim1": {"工商登记": {"name": "测试科技"}},
            "dim2": {"动产抵押": []},
            "dim3": {"失信被执行": []},
            "dim5": dim5 or {},
        }

    def test_basic_render(self):
        from utils.qcc_debt_assessment import format_assessment_markdown
        md = format_assessment_markdown(self._make_result())
        self.assertIn("测试科技有限公司", md)
        self.assertIn("A 级", md)
        self.assertIn("积极追偿", md)
        self.assertIn("5,000,000", md)
        self.assertIn("推荐 Action", md)
        self.assertIn("企查查", md)

    def test_d_rating_render(self):
        from utils.qcc_debt_assessment import format_assessment_markdown
        result = {**self._make_result("D", 0), "recovery_range": (0, 10),
                  "rating_note": "企业已注销/破产，追偿路径极窄。"}
        md = format_assessment_markdown(result)
        self.assertIn("D 级", md)
        self.assertIn("不建议追偿", md)

    def test_zero_amount_hides_recovery_amount(self):
        from utils.qcc_debt_assessment import format_assessment_markdown
        md = format_assessment_markdown(self._make_result(amount=0))
        self.assertIn("未指定", md)

    def test_dim5_persons_rendered(self):
        from utils.qcc_debt_assessment import format_assessment_markdown
        dim5 = {
            "张三": {"个人失信": [], "个人被执行": [{"case": "test"}]},
        }
        md = format_assessment_markdown(self._make_result(dim5=dim5))
        self.assertIn("张三", md)
        self.assertIn("维度五", md)

    def test_all_rating_labels_exist(self):
        from utils.qcc_debt_assessment import format_assessment_markdown, _RATING_LABEL
        for rating, label in _RATING_LABEL.items():
            result = {**self._make_result(rating), "recovery_range": (10, 30)}
            md = format_assessment_markdown(result)
            self.assertIn(label, md, f"评级 {rating} 的标签 {label!r} 未在 Markdown 中出现")


if __name__ == "__main__":
    unittest.main()
