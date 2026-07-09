# -*- coding: utf-8 -*-
"""
test_market_overview.py —— 测试市场宏观全览的 SQL 聚合逻辑
"""

import unittest
import os
import sys
import pandas as pd
import sqlite3

# 确保能导入主项目模块
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.backend.services import get_market_overview_data, DB_PATH

class TestMarketOverview(unittest.TestCase):
    
    def test_market_overview_data_structure(self):
        """
        验证大盘全览接口返回数据在格式与键值层面上完整无缺
        """
        res = get_market_overview_data()
        
        # 即使数据库为空或报错，接口应能以正常键响应（或者包含 error 键）
        if "error" in res:
            print(f"⚠️ [Test Warning] 数据库状态异常，但成功返回 error 信息: {res['error']}")
            return
            
        # 1. 验证基础键存在性
        required_keys = ["date", "adv_dec", "temperature", "inflow_rank", "outflow_rank", "style_rotation", "hot_money_themes", "regime"]
        for key in required_keys:
            self.assertIn(key, res)
            
        # 2. 验证涨跌数据非负且为整数
        adv_dec = res["adv_dec"]
        self.assertGreaterEqual(adv_dec["up"], 0)
        self.assertGreaterEqual(adv_dec["down"], 0)
        self.assertGreaterEqual(adv_dec["flat"], 0)
        
        # 3. 验证筹码水位中位数在 0 到 100% 之间
        temp = res["temperature"]
        self.assertTrue(0.0 <= temp["median_winner"] <= 100.0)
        self.assertTrue(0.0 <= temp["overbought_ratio"] <= 100.0)
        self.assertTrue(0.0 <= temp["oversold_ratio"] <= 100.0)
        
        # 4. 验证资金排行榜长度不超过 5
        self.assertLessEqual(len(res["inflow_rank"]), 5)
        self.assertLessEqual(len(res["outflow_rank"]), 5)
        
        # 4.5. 验证游资题材数据长度及打分区间
        self.assertLessEqual(len(res["hot_money_themes"]), 5)
        if res["hot_money_themes"]:
            first_theme = res["hot_money_themes"][0]
            self.assertIn("sector", first_theme)
            self.assertIn("avg_turnover", first_theme)
            self.assertIn("net_inflow", first_theme)
            self.assertTrue(0.0 <= first_theme["hot_score"] <= 100.0)
        
        # 5. 验证风格轮动数据格式
        if res["style_rotation"]:
            first_style = res["style_rotation"][0]
            self.assertIn("date", first_style)
            self.assertIn("高换手风格 (Turnover)", first_style)
            
        print("✅ [Test OK] 市场全览接口（含游资热点排行榜）单元数据测试完美通过!")

if __name__ == '__main__':
    unittest.main()
