from app.services.parser import parse_query


class TestParseBudget:
    def test_basic_number(self):
        slots = parse_query("预算25")
        assert slots.budget_max == 25.0

    def test_number_with_yuan(self):
        slots = parse_query("25元")
        assert slots.budget_max == 25.0

    def test_number_with_yinei(self):
        slots = parse_query("30以内")
        assert slots.budget_max == 30.0

    def test_number_with_zuoyou(self):
        slots = parse_query("20左右")
        assert slots.budget_max == 20.0

    def test_number_with_yusuan_prefix(self):
        slots = parse_query("预算50")
        assert slots.budget_max == 50.0

    def test_number_in_full_query(self):
        slots = parse_query("清水河，预算25，一个人想吃清淡的")
        assert slots.budget_max == 25.0

    def test_budget_over_500_ignored(self):
        """超过 500 的预算视为无效输入"""
        slots = parse_query("预算999")
        assert slots.budget_max is None

    def test_no_budget(self):
        slots = parse_query("想吃辣的")
        assert slots.budget_max is None


class TestParseLocation:
    def test_qingshuihe(self):
        slots = parse_query("清水河")
        assert slots.location == "清水河"

    def test_qingshui_alias(self):
        slots = parse_query("清水")
        assert slots.location == "清水河"

    def test_shahe(self):
        slots = parse_query("沙河")
        assert slots.location == "沙河"

    def test_location_in_full_query(self):
        slots = parse_query("沙河 聚餐 吃辣")
        assert slots.location == "沙河"

    def test_no_location(self):
        slots = parse_query("想吃清淡的")
        assert slots.location is None


class TestParseTaste:
    def test_qingdan(self):
        slots = parse_query("清淡的")
        assert slots.taste == "清淡"

    def test_bula(self):
        slots = parse_query("不辣的")
        assert slots.taste == "清淡"

    def test_mala(self):
        slots = parse_query("麻辣")
        assert slots.taste == "麻辣"

    def test_zhongkou(self):
        slots = parse_query("重口")
        assert slots.taste == "麻辣"

    def test_xianmei(self):
        slots = parse_query("鲜美的")
        assert slots.taste == "鲜美"

    def test_no_taste(self):
        slots = parse_query("清水河")
        assert slots.taste is None


class TestParseScene:
    def test_yigeren(self):
        slots = parse_query("一个人")
        assert slots.scene == "一个人"

    def test_suibian(self):
        """随便 → 一个人场景"""
        slots = parse_query("随便吃点")
        assert slots.scene == "一个人"

    def test_ganshijian(self):
        """赶时间 → 一个人场景（配置与代码同步验证）"""
        slots = parse_query("赶时间")
        assert slots.scene == "一个人"

    def test_jianshencan(self):
        """健身餐 → 一个人场景（配置与代码同步验证）"""
        slots = parse_query("健身餐")
        assert slots.scene == "一个人"

    def test_jucan(self):
        slots = parse_query("同学聚餐")
        assert slots.scene == "同学聚餐"

    def test_sushe_jucan(self):
        """宿舍聚餐 → 同学聚餐（配置中定义的别名）"""
        slots = parse_query("宿舍聚餐")
        assert slots.scene == "同学聚餐"

    def test_yuefan(self):
        """约饭 → 同学聚餐"""
        slots = parse_query("约饭")
        assert slots.scene == "同学聚餐"

    def test_yuehui(self):
        slots = parse_query("约会")
        assert slots.scene == "约会"

    def test_no_scene(self):
        slots = parse_query("麻辣重口")
        assert slots.scene is None


class TestParseTime:
    def test_zaocan(self):
        slots = parse_query("早餐")
        assert slots.time == "早餐"

    def test_zaoshang(self):
        """早上 → 早餐"""
        slots = parse_query("早上")
        assert slots.time == "早餐"

    def test_wucan(self):
        slots = parse_query("午饭")
        assert slots.time == "午餐"

    def test_wancan(self):
        slots = parse_query("晚饭")
        assert slots.time == "晚餐"

    def test_yexiao(self):
        slots = parse_query("宵夜")
        assert slots.time == "夜宵"

    def test_no_time(self):
        slots = parse_query("麻辣重口")
        assert slots.time is None


class TestParseEdgeCases:
    def test_empty_query(self):
        slots = parse_query("")
        assert slots.budget_max is None
        assert slots.location is None
        assert slots.scene is None
        assert slots.taste is None
        assert slots.time is None

    def test_mixed_query(self):
        """多维度同时提取"""
        slots = parse_query("沙河 晚餐 聚餐 预算30 吃辣")
        assert slots.budget_max == 30.0
        assert slots.location == "沙河"
        assert slots.scene == "同学聚餐"
        assert slots.taste == "麻辣"
        assert slots.time == "晚餐"
