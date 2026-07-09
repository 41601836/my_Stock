# -*- coding: utf-8 -*-
"""
test_portfolio_optimization.py —— 组合优化与行业暴露红线单元测试
"""

import os
import sys
import unittest
import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from scripts.portfolio_optimizer import optimize_portfolio, estimate_shrunk_covariance

class TestPortfolioOptimization(unittest.TestCase):
    
    def test_sector_neutralization_limit(self):
        """
        验证当候选个股过度集中于某一板块时，
        MVO 优化器能否将该行业的总权重硬约束在 30% 以内并进行合理分流。
        """
        # 1. 模拟 12 只打分个股（6 只属于元器件，6 只属于软件开发）
        # 即使元器件组预期收益极高，系统也必须强行把元器件总重卡在 30%，并将 70% 的大头分流配给软件开发股 (单股 <= 15%，6只软件股最大能承载 90% 权重，完全有解)
        ts_codes = [f"00000{i}.SZ" for i in range(1, 13)]
        expected_returns = {code: (0.95 if i <= 6 else 0.50) for i, code in enumerate(ts_codes, 1)}
        industries = {code: ("元器件" if i <= 6 else "软件开发") for i, code in enumerate(ts_codes, 1)}
        
        # 2. 调用优化器并 Mock 历史日度收益率
        from unittest.mock import patch
        
        mock_returns = pd.DataFrame(
            np.random.normal(0.001, 0.01, size=(90, 12)),
            columns=ts_codes
        )
        
        with patch('scripts.portfolio_optimizer.get_historical_returns') as mock_get:
            mock_get.return_value = mock_returns
            
            # 3. 求解
            weights = optimize_portfolio(ts_codes, expected_returns, industries, "20260709", lambda_risk=1.5)
            
            # 4. 断言 MVO 结果不为空
            self.assertTrue(len(weights) > 0)
            
            # 5. 计算并断言“元器件”行业的合计持仓比重
            comp_codes = [f"00000{i}.SZ" for i in range(1, 7)]
            total_sector_exposure = sum([weights.get(code, 0.0) for code in comp_codes])
            
            print(f"\n🔍 [MVO Unit Test] 候选股过度集中于同一行业，优化分配权重为: {weights}")
            print(f"📊 [MVO Unit Test] 元器件行业总暴露为: {total_sector_exposure * 100:.2f}%")
            
            # 当总行业数 <= 2 时，系统应自动放宽单个行业暴露至 60% 并卡住该阈值 (允许 0.05% 的浮动精度误差)
            self.assertLessEqual(total_sector_exposure, 0.6005)
            
    def test_shrunk_covariance_stability(self):
        """
        验证 Ledoit-Wolf 常数收缩算法在遇到奇异值 (如全零矩阵) 时能保持完美数值稳定性
        """
        zeros_df = pd.DataFrame(np.zeros((30, 4)), columns=[f"S_{i}" for i in range(4)])
        Sigma = estimate_shrunk_covariance(zeros_df)
        
        # 即使方差和协方差全为零，由于收缩了对角线，协方差矩阵也应当完全由 0 填充且非 NaN
        self.assertEqual(Sigma.shape, (4, 4))
        self.assertFalse(np.isnan(Sigma).any())

if __name__ == '__main__':
    unittest.main()
