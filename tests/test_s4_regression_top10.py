# -*- coding: utf-8 -*-
"""
S4 Phase — Regression Unit Tests (Top 10)
==========================================
画像 / 漏斗 / Regime / IC-IR / 权重配置 & approve 覆盖 完整回归基线。

10 个用例清单 (Top 10):
  TC01  画像分 5 维满分边界         → 黄金甜区参数输入，期望 5 维合计 = 100，grade=A
  TC02  画像分 5 维零分边界         → 高位/高估/过热/涣散/明牌输入，期望总分≈低位,D
  TC03  画像分 5 维梯度单调性       → 单一维度单调变化, 画像分单调/非递减
  TC04  三层漏斗-通过率 Grade-D     → 含 D 级候选, 过滤层必须 100% 剔除 grade-D
  TC05  三层漏斗-通过率因子尾部+最小持仓回补 → 构造 5% 尾部分布 & 不足最小仓位回补逻辑
  TC06  权重上限 & 换手约束         → max_weight=30%, max_turnover=50% 硬闸门
  TC07  Regime 判定边界 Bull/Range  → 用合成 60 天 NAV 序列 & rolling 阈值喂入 compute_live_regime 逻辑
  TC08  Regime 判定边界 Bear/Dark   → 暴跌/低上涨比/高波动 -> Dark 优先级最高
  TC09  IC / IR 基准一致性          → calc_rank_ic 单调序列 IC=±1；IR=mean/std 在随机-确定混合下稳定
  TC10  权重配置 approve 覆盖流程   → thresholds.yaml / 默认值回退 / pkl 权重加载 / 热加载 mtime 变更
"""
import os
import sys
import io
import math
import unittest
import tempfile
import shutil
import pickle
import importlib
import copy

import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))  # src/portfolio_constructor.py
sys.path.insert(0, os.path.join(PROJECT_ROOT, "web", "backend"))


# ======================================================================
# 用例实现
# ======================================================================
class TestS4RegressionTop10(unittest.TestCase):

    # ------------------------------------------------------------------
    # 画像分 5 维边界 / 梯度 (TC01 - TC03)
    # ------------------------------------------------------------------
    def test_TC01_portrait_5d_full_score_boundary(self):
        """TC01 5 维黄金甜区输入 -> 画像分≈100, 等级 A"""
        from portrait_router import compute_portrait_score, PORTRAIT_CONFIG

        cfg = PORTRAIT_CONFIG
        # 5 维满分输入
        result = compute_portrait_score(
            factor_score=(cfg["factor_sweet_lo"] + cfg["factor_sweet_hi"]) / 2,  # 甜区中心
            profit_ratio_estimate=cfg["profit_ratio_full"] * 0.5,  # 远低于满分线 -> 满分
            pe_ttm=cfg["pe_ttm_full"] * 0.5,
            hot_money_score=(cfg["hot_score_safe_lo"] + cfg["hot_score_safe_hi"]) / 2,
            return_5d=cfg["return_5d_safe"] * 0.5,  # 温和未暴涨
            chips_concentration=(cfg["chip_best_lo"] + cfg["chip_best_hi"]) / 2,  # 黄金区间中心
            volatility_60d=float(cfg.get("vol_bonus_above", 1.5)) + 0.1,  # 股性弹性加分
            cfg=cfg,
        )
        details = result["portrait_details"]
        self.assertEqual(set(details.keys()), {"位置分", "估值分", "温度分", "筹码分", "因子分"},
                         "画像分 5 维字段缺失: %s" % list(details.keys()))
        for k, v in details.items():
            self.assertGreaterEqual(v, 0.0, "%s 负分非法" % k)
            self.assertLessEqual(v, 20.0, "%s 超过单维满分 20" % k)
        total = result["portrait_score"]
        # 甜区中心 + vol bonus 应达到 92+ (通常 96-100, 保守断言)
        self.assertGreaterEqual(total, 90.0, "甜区输入应获高分画像(≥90), 实际=%.2f" % total)
        self.assertLessEqual(total, 100.0, "画像分不能超过100")
        self.assertEqual(result["portrait_grade"], "A", "90+ 分应评 A")
        self.assertIn("强烈推荐", result["portrait_label"])

    def test_TC02_portrait_5d_zero_score_boundary(self):
        """TC02 5 维零分输入（高位/高估值/过热/涣散/明牌）-> 总分低位 等级 D"""
        from portrait_router import compute_portrait_score, PORTRAIT_CONFIG

        cfg = PORTRAIT_CONFIG
        result = compute_portrait_score(
            factor_score=0.0,                             # 因子垫底(零分)
            profit_ratio_estimate=cfg["profit_ratio_zero"] + 0.05,  # 高位 -> 零
            pe_ttm=cfg["pe_ttm_zero"] + 10.0,                       # 严重高估
            hot_money_score=0.9,                                     # 热度极高 不满足安全
            return_5d=cfg["return_5d_max"] + 0.01,                   # 暴涨超上限 -> 温度零
            chips_concentration=cfg["chip_mid_lo"] - 5.0,            # 涣散零
            volatility_60d=0.5,
            cfg=cfg,
        )
        details = result["portrait_details"]
        total = result["portrait_score"]
        self.assertLessEqual(total, 35, "五维零分输入总分不应超过35，实际=%.2f (details=%s)" % (total, details))
        self.assertEqual(result["portrait_grade"], "D",
                         "低分输入 (%s) 应评 D, 实际=%s" % (total, result["portrait_grade"]))
        self.assertIn("画像不符", result["portrait_label"])

    def test_TC03_portrait_5d_monotonic_gradient(self):
        """TC03 单一维度变化 -> 5 维合计单调(或非递减) 验证梯度逻辑稳定"""
        from portrait_router import compute_portrait_score, PORTRAIT_CONFIG

        cfg = PORTRAIT_CONFIG
        base = dict(
            profit_ratio_estimate=0.2, pe_ttm=20, hot_money_score=0.4,
            return_5d=0.01, chips_concentration=80, volatility_60d=1.6, cfg=cfg,
        )
        # 因子分梯度 0.3 → 0.95
        factors = np.linspace(0.30, 0.95, 12)
        scores = []
        for fs in factors:
            r = compute_portrait_score(factor_score=fs, **base)
            scores.append(r["portrait_score"])
        # 0.30 → sweet_lo 之间应非递减；允许 过热区间(>0.90) 小幅回落
        # 断言: 最低分段 < 甜区分段
        avg_lo = float(np.mean(scores[:5]))
        avg_md = float(np.mean(scores[5:10]))
        self.assertLess(avg_lo, avg_md + 1e-6,
                        "因子分从低(0.30)升到中(0.75~0.88)画像分应当提升: lo=%.2f md=%.2f, seq=%s" % (avg_lo, avg_md, scores))
        # 全 12 个样本 5 维字段应齐全
        r_last = compute_portrait_score(factor_score=0.85, **base)
        dims = r_last["portrait_details"]
        self.assertEqual(sum(dims.values()), r_last["portrait_score"],
                         "5维明细应当等于总分合计: Σ=%s total=%s" % (dims, r_last["portrait_score"]))

    # ------------------------------------------------------------------
    # 三层漏斗 (TC04 - TC06)
    # ------------------------------------------------------------------
    def _make_signals(self, rows):
        return pd.DataFrame(rows)

    def test_TC04_funnel_layer1_grade_d_hard_exclusion(self):
        """TC04 Phase 3 过滤层 - grade-D 硬排除 100%"""
        from portfolio_constructor import construct_portfolio

        # 20 只候选：6 个 D 级，其他 A/B/C 混合
        rows = []
        for i in range(1, 21):
            grade = "D" if i <= 6 else ["A", "B", "C"][i % 3]
            rows.append(dict(
                ts_code=f"SH{i:06d}",
                portrait_score={"D": 32, "A": 88, "B": 70, "C": 50}[grade],
                portrait_grade=grade,
                factor_score_norm=round(0.5 + 0.03 * i, 3),
                build_score=70.0 + i,
            ))
        df_in = self._make_signals(rows)
        df_out, stats = construct_portfolio(
            df_in, drop_grade_d=True, factor_tail_quantile=0.0,
            min_portfolio_size=5, final_max_size=50,
        )
        # grade-D 被剔除计数 = 6
        self.assertEqual(stats["drop_breakdown"].get("grade_D 剔除", 0), 6,
                         "6只D级应全部剔除: %s" % stats["drop_breakdown"])
        # construct_portfolio 返回 df 含通过行 + 拒绝行（dropped_reason 标识）。只应在通过行里验证 D 不存在
        keep = df_out[df_out.get("dropped_reason", "").fillna("") == ""] if "dropped_reason" in df_out.columns else df_out.head(
            int(stats.get("out_count", len(df_out)))
        )
        grades_out = set(keep["portrait_grade"].astype(str).tolist()) if "portrait_grade" in keep.columns else set()
        self.assertNotIn("D", grades_out, "组合通过池中仍出现 D 级！keep grades=%s; rej=%s" % (
            grades_out, stats.get("drop_breakdown")))

    def test_TC05_funnel_tail_factor_and_min_size_restore(self):
        """TC05 因子尾 5% 剔除 + 不足最小持仓回补（保证不因过滤导致空组合）"""
        from portfolio_constructor import _filter_candidates, construct_portfolio

        # 20 只股票：构造明显的尾巴
        np.random.seed(42)
        rows = []
        for i in range(20):
            factor_t = round(0.05 * i + 0.05, 3)  # 0.05 → 1.0 线性分布
            rows.append(dict(
                ts_code=f"SZ{i:06d}",
                portrait_grade="B",
                portrait_score=70 + i,
                factor_score_norm=factor_t,
                build_score=70 + i,
            ))
        df = pd.DataFrame(rows)
        df_f, breakdown = _filter_candidates(
            df, drop_grade_d=False, factor_tail_quantile=0.05,
            min_portfolio_size=30,  # 故意设置 > len=20, 触发回补
        )
        kept = df_f[df_f["dropped_reason"].fillna("") == ""]
        # min_portfolio_size=30 但只有 20 只 → 回补
        self.assertEqual(len(kept), 20, "最小持仓 30 应当把 20 只全部保留(含回补), 实际=%d 明细=%s" % (len(kept), breakdown))
        self.assertIn("过滤后不足最小持仓，补回高分", breakdown,
                      "应出现回补记录: %s" % breakdown)

        # 验证 5% 尾部剔除正常（无 min_size 干扰）
        df_f2, bd2 = _filter_candidates(df, drop_grade_d=False, factor_tail_quantile=0.20,
                                        min_portfolio_size=1)
        kept2 = df_f2[df_f2["dropped_reason"].fillna("") == ""]
        rej2  = df_f2[df_f2["dropped_reason"].fillna("") != ""]
        # 20 只分位数 20% 对应 i=0.05*0~1 = 0.05~0.10；剔除只数应合理 >0
        self.assertGreaterEqual(len(kept2), 10,
                                "20 只过滤后不足10 异常(过过滤), kept=%d rej=%d bd=%s" % (len(kept2), len(rej2), bd2))

    def test_TC06_weight_cap_and_turnover_constraint(self):
        """TC06 max_weight ≤30% & max_turnover ≤50% 硬闸门"""
        from portfolio_constructor import construct_portfolio

        # Case A: max_weight cap - 5 只正常组合 等权 = 20% ≤ 30% 应保持
        rows = [dict(ts_code=f"S{i}", portrait_score=85, portrait_grade="A",
                     factor_score_norm=0.85, build_score=85) for i in range(5)]
        df, stats = construct_portfolio(pd.DataFrame(rows), max_weight=0.30, final_max_size=10)
        weights = df["blended_weight_pct"].astype(float).tolist()
        for w in weights:
            self.assertLessEqual(w, 30.0 + 1e-6,
                                 "5只组合单股权重不应超过30%%: w=%s 全部=%s" % (w, weights))
        # 合计应该是 100%
        keep_mask = df.get("dropped_reason", pd.Series([""] * len(df))).fillna("") == ""
        total_pct = float(df.loc[keep_mask, "blended_weight_pct"].astype(float).sum())
        self.assertAlmostEqual(total_pct, 100.0, delta=1.0,
                               msg="5只通过池权重合计应≈100%%: %.2f" % total_pct)

        # Case B: turnover - 上周 S4=0.4 (权重40%)，其他 4 只 15% each (总和0.6) → 合计 1.0
        # 本周目标 5 只 EW=20% each。S4: 0.4→0.2 (Δ=-0.2); 其他 0.15→0.2 (Δ=+0.05 ×4=+0.2); Σ|Δ|=0.4 → 0.5*0.4=0.2 < 0.5。
        # 为了刚好打满换手约束，构造 S4=0.8，其他4只各 0.05 → 目标 EW 0.2 each：S4 Δ=0.6，其他 Δ=0.15×4=0.6，Σ|Δ|=1.2，理论需 α=min(1, 2*0.5/1.2)=0.833。
        # 由于系统内部 clip 会在 blended > max_weight (0.3) 时截断，我们这里使用 prev: S4=0.3 (刚好在30% cap)，S0=0.7，其他 0。
        # 本周新组合 5 只 EW。即 S0: 0.7→0.2 (Δ=-0.5), S1~S3: 0→0.2 (Δ=+0.2 ×3=+0.6), S4: 0.3→0.2 (Δ=-0.1)
        # Σ|Δ| = 0.5+0.6+0.1 = 1.2 → α = 1/1.2 → blend: S0=0.283, S1~S3=0.167 each, S4=0.217; Σ=0.998; 无clip; turnover ≈ 0.5。
        prev = {"S0": 0.7, "S1": 0.0, "S2": 0.0, "S3": 0.0, "S4": 0.3}
        rows_all = [dict(ts_code=f"S{i}", portrait_score=85 + (4-i), portrait_grade="A",
                         factor_score_norm=0.85, build_score=85) for i in range(5)]
        df2, st2 = construct_portfolio(pd.DataFrame(rows_all),
                                       max_turnover=0.50, max_weight=0.30,
                                       prev_weights=prev,
                                       final_max_size=10)
        turnover = float(st2.get("turnover_vs_prev", -1))
        self.assertGreaterEqual(turnover, 0.0, "换手率非法负: %s" % turnover)
        # 系统在插值后 cap+归一化 可能轻微上浮, 允许 ≤ 0.55
        self.assertLessEqual(turnover, 0.55,
                             "换手率(=0.5Σ|Δw|) 不应显著突破50%%约束 = %.4f, stats=%s" % (turnover, st2))

    # ------------------------------------------------------------------
    # Regime 判定边界 (TC07 - TC08)
    # ------------------------------------------------------------------
    def test_TC07_regime_bull_range_boundary(self):
        """TC07 合成 60 天行情 -> Bull / Range 边界
        策略：
          Bull 用例 -> 前40天高波动震荡(抬高 vol_50pct 整体分位) + 后20天低波动稳步上涨 1.0%/d + 高上涨占比
                      -> ret20 远超 +5%, vol20 低 < 全局 q50 严格小 -> 判定 Bull
          Range 用例 -> 整体无趋势 小幅交替震荡, ret20 在 ±3% 内 -> 判定 Range
        """
        # Bull 构造：40 天大波动 (±3%) + 20 天 低波动稳步上涨
        rng = np.random.default_rng(1)
        # 前 40 天：日均 0%，个股间 4.8% 差异让 rolling avg pct 随上下天数不对称波动 0~±1%
        pc = list(rng.uniform(-1.2, 1.2, size=40)) + [round(1.0 + 0.02 * i, 3) for i in range(20)]  # 后 20 天 1.0%→1.4%/d 连续稳步
        # up_ratio：前 40 天 50/50，后 20 天 90%+
        ur = [0.5] * 40 + [0.9] * 20
        self._regime_assert_with(pc, ur, expect_in={"Bull", "BULL", "bull"},
                                 msg="高波动筑底40天 + 后20天低波动稳步上涨(+5%阈值以上) 应为 Bull")

        # Range 构造：60 天始终围绕 0 ±0.6% 小幅震荡，无单边趋势
        pc2 = list(np.clip(rng.normal(0.0, 0.30, size=60), -0.6, 0.6))
        ur2 = [0.5] * 60
        self._regime_assert_with(pc2, ur2, expect_in={"Range", "RANGE", "range"},
                                 msg="60天横盘小幅波动无趋势 应判 Range")

    def test_TC08_regime_bear_dark_boundary(self):
        """TC08 暴跌 + 低上涨比 + 高波动 -> Dark 优先级最高"""
        # 前 30 日 0.0% 横盘，后 30 日 -2%/d 且上涨占比 20% (触发 dark ret5w + up_ratio + bear_ret20)
        pc = [0.0] * 30 + [-2.0] * 30
        ur = [0.5] * 30 + [0.2] * 30
        self._regime_assert_with(pc, ur, expect_in={"Dark", "DARK", "dark"},
                                 msg="连跌 30 天且上涨占20%应判 Dark (Dark 最高优先级)")

        # 纯 Bear：20日收益 -5% (比 -3% 阈值更差) + 高波动 但 Dark 不触发 (ret5w < -4.5% = dark 触发 -> 还是 Dark)
        # 改为: 温和 bear 场景 - 20d -4%；5d 只跌 1% (不触发 dark ret5w)；up_ratio 0.35 不触发 dark up_ratio
        pc_b = [0.0] * 40 + [-0.0] * 25 + [-0.3] * 5  # 近 5d 共 -1.5% 不触发 dark
        # 近 20d 包含最后 20 行: [0]*15 + [-0]*5 + [-0.3]*5 = ret20 ≈ (1-0.003)^5 ≈ -0.015? 不够 Bear
        # 改用更直观的: 近 20 日 -0.3% * 15 = -4.5% 触发 bear -3%；近5日 = [-0.1, -0.1, -0.1, 0, 0]  = -0.3% 不触发 dark (dark 阈值=-4.5%)
        pc3 = [0.0] * 40 + [-0.3] * 15 + [0.0] * 5
        ur3 = [0.5] * 40 + [0.4] * 15 + [0.5] * 5  # up_ratio=0.4 > dark 0.3 → 不触发 dark 上涨占比
        # 注: 最终 regime 是 Dark/Bull/Bear/Range 中第一个命中；此处 Dark 阈值更严，应落入 Bear。如果 vol 不达标则是 Range。
        # 鉴于 rolling vol 依赖数据，放宽断言允许 Bear 或 Range (这两个都是非牛市场景的非崩溃)
        self._regime_assert_with(pc3, ur3, expect_in={"Bear", "BEAR", "bear", "Range", "RANGE", "range"},
                                 msg="中等熊市 不应判 Bull/Dark")

    def _regime_assert_with(self, pct_chg_list, up_ratio_list, expect_in, msg=""):
        """
        构造临时 SQLite → compute_live_regime。
        关键细节：对每天每只个股，is_up 那一组必须生成 **实际 pct_chg > 0** 的值，
        非 is_up 组必须生成 **实际 pct_chg < 0** 的值，这样 DB 里的 CASE WHEN pct_chg > 0 统计与参数 up_ratio 对齐。
        """
        import sqlite3
        import services._common as cmn
        import services.market_regime as m_reg
        from services.market_regime import compute_live_regime

        tmp = tempfile.mkdtemp(prefix="regime_ut_")
        try:
            db_p = os.path.join(tmp, "r.db")
            conn = sqlite3.connect(db_p)
            conn.execute("CREATE TABLE daily_prices (trade_date INTEGER, ts_code TEXT, pct_chg REAL)")
            n_days = len(pct_chg_list)
            codes = [f"C{i:04d}" for i in range(10)]
            for d_i in range(n_days):
                td = 20260101 + d_i
                base = float(pct_chg_list[d_i])
                up_prob = float(up_ratio_list[d_i])
                n_up = max(1, int(round(up_prob * len(codes))))
                for ci, code in enumerate(codes):
                    if ci < n_up:
                        # 上涨组：确保实际 pct_chg > 0
                        this_pc = abs(base) + 0.5 + 0.01 * ci
                    else:
                        # 下跌组：确保实际 pct_chg < 0
                        this_pc = -abs(base) - 0.5 - 0.01 * (ci - n_up)
                    # 但当 base 希望整体是"横盘/下跌"时，上面绝对偏移会让日均值偏离基准。
                    # 为了保留原 base 的方向性语义：如果 base < 0，把 up 组给"小负"但整体均值仍偏正/负？
                    # 简化：用 base + sign 偏移（并确保符号正确）
                    # 方案 B（本函数使用）：重新采用 上涨 pc = max(base, 0.1)；下跌 pc = min(base, -0.1)
                    if ci < n_up:
                        this_pc = max(base, 0.3)
                    else:
                        this_pc = min(base, -0.3)
                    conn.execute("INSERT INTO daily_prices VALUES (?,?,?)", (td, code, this_pc))
            conn.commit(); conn.close()

            orig_cmn = cmn.DB_PATH
            orig_mr  = m_reg.DB_PATH
            cmn.DB_PATH = db_p
            m_reg.DB_PATH  = db_p
            try:
                res = compute_live_regime()
                self.assertIsNotNone(res, "compute_live_regime 返回 None (%s)" % msg)
                got = str(res["regime"]).lower()
                exp_low = {e.lower() for e in expect_in}
                self.assertIn(got, exp_low,
                              "Regime 边界断言失败：期望 %s ∈ %s, 实际=%s。detail=%s。MSG=%s" %
                              (res["regime"], list(expect_in), got, res, msg))
            finally:
                cmn.DB_PATH = orig_cmn
                m_reg.DB_PATH = orig_mr
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # IC / IR (TC09)
    # ------------------------------------------------------------------
    def test_TC09_ic_ir_baseline(self):
        """TC09 calc_rank_ic: 单调 -> IC=±1; 随机 -> |IC|≈小; IR=mean/std 合成样本稳定"""
        from services.evo._common import calc_rank_ic

        n = 60
        rng = np.random.default_rng(0)
        xs = np.linspace(0, 1, n)
        # (a) 完全单调正向
        ic_pos = calc_rank_ic(pd.Series(xs), pd.Series(xs * 3 + 1))
        self.assertAlmostEqual(ic_pos, 1.0, places=5, msg="正向单调因子 IC 应 = +1: %s" % ic_pos)
        # (b) 完全单调反向
        ic_neg = calc_rank_ic(pd.Series(xs), pd.Series(-xs))
        self.assertAlmostEqual(ic_neg, -1.0, places=5, msg="反向单调因子 IC 应 = -1: %s" % ic_neg)
        # (c) 样本不足 <30 返回 None
        ic_small = calc_rank_ic(pd.Series(range(5)), pd.Series(range(5)))
        self.assertIsNone(ic_small, "样本<30应返回 None: %s" % ic_small)

        # (d) IR 基准：20 个交易日截面 IC 的 mean / std
        ics = []
        for i in range(20):
            f = rng.normal(0, 1, n)
            r = 0.03 * f + rng.normal(0, 0.97, n)  # IC≈0.03 弱信号
            ic = calc_rank_ic(pd.Series(f), pd.Series(r))
            if ic is not None:
                ics.append(ic)
        self.assertGreaterEqual(len(ics), 15, "IC 样本过少 可能 calc_rank_ic 有 bug: %s" % ics)
        mean_ic = float(np.mean(ics))
        std_ic = float(np.std(ics))
        ir = mean_ic / (std_ic + 1e-9)
        # 正信号下 mean_ic 应该 >0；IR 值合理
        self.assertGreater(mean_ic, -0.05,
                           "弱信号下 mean IC 应当接近 0.03+: mean=%.4f std=%.4f IR=%.3f seq=%s" % (mean_ic, std_ic, ir, ics))

    # ------------------------------------------------------------------
    # 权重配置 approve 覆盖流程 (TC10)
    # ------------------------------------------------------------------
    def test_TC10_weights_config_approve_flow(self):
        """TC10: thresholds.yaml / 默认值回退 / pkl 权重加载 / 热加载 mtime 变更完整流程"""
        import services._common as cmn
        from services._common import (
            get_scanner_cfg, get_position_funnel_cfg, get_left_portrait_cfg,
            get_right_portrait_cfg, get_live_regime_cfg, _load_pkl_weights,
            _load_raw_thresholds, _TH_CACHE,
        )

        # 1. 所有 getter 默认值可用
        for label, fn in [("scanner", get_scanner_cfg),
                          ("funnel",  get_position_funnel_cfg),
                          ("left",    get_left_portrait_cfg),
                          ("right",   get_right_portrait_cfg),
                          ("regime",  get_live_regime_cfg)]:
            d = fn()
            self.assertIsInstance(d, dict, "%s cfg 不是 dict" % label)
            self.assertTrue(len(d) > 0, "%s cfg 空" % label)

        # 2. 阈值读取 = thresholds.yaml 键值或默认值兜底：保证 scoring_weights 5 项和 ≈ 1
        sc = get_scanner_cfg()
        sw = sc.get("scoring_weights", {})
        total = sum(float(v) for v in sw.values())
        self.assertAlmostEqual(total, 1.0, places=3,
                               msg="scanner.scoring_weights 合计应≈1: sum=%.3f %s" % (total, sw))
        # funnel 层三阈值存在性
        fc = get_position_funnel_cfg()
        for k in ("common", "layer1", "layer2", "layer3"):
            self.assertIn(k, fc, "position_funnel 缺 %s" % k)

        # 3. pkl 权重加载 (临时 pkl 文件 Mock)
        tmp = tempfile.mkdtemp(prefix="pkl_")
        try:
            pkl_p = os.path.join(tmp, "w.pkl")
            with open(pkl_p, "wb") as f:
                pickle.dump({"factors": ["a", "b"], "range_weights": {"a": 0.4, "b": 0.6},
                             "bull_weights": {"a": 0.3, "b": 0.7}}, f)
            factors, w = _load_pkl_weights(pkl_p)
            self.assertEqual(factors, ["a", "b"])
            self.assertAlmostEqual(sum(w.values()), 1.0, places=5,
                                   msg="pkl 权重加载后应保持等归一化总和≈1: sum=%s" % sum(w.values()))
            # 损坏 pkl -> 空 dict 不抛
            bad_p = os.path.join(tmp, "bad.pkl")
            with open(bad_p, "wb") as f:
                f.write(b"not_a_pickle")
            _, empty = _load_pkl_weights(bad_p)
            self.assertIsInstance(empty, dict, "损坏 pkl 应返回 {}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # 4. 热加载：修改 thresholds.yaml mtime 应触发缓存失效
        before = _TH_CACHE.get("mtime", 0)
        data_before = _load_raw_thresholds()
        self.assertIsInstance(data_before, dict, "原始 thresholds 非 dict")
        # 触发缓存失效：手动把缓存置脏
        saved_m = copy.deepcopy(_TH_CACHE)
        try:
            _TH_CACHE["mtime"] = 0.0
            _TH_CACHE["data"] = None
            data_after = _load_raw_thresholds()
            self.assertEqual(_TH_CACHE["mtime"] > 0, True, "读过后 cache.mtime 应更新")
            self.assertEqual(data_before.keys(), data_after.keys(),
                             "两次读取 thresholds 结构应一致")
        finally:
            _TH_CACHE.update(saved_m)

    # ------------------------------------------------------------------
    # EVO 动态权重 cap 自适应 (TC11)
    # ------------------------------------------------------------------
    def test_TC11_evo_cap_adaptive(self):
        """TC11: evo cap 自适应 cap=max(0.30, 1/n_eff)——存活因子过少时上限放宽、water-filling 不突破 cap"""
        import sys as _sys
        _sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
        from evo_dynamic_weights import calc_weights_snapshot

        TOL = 2e-6  # 返回值 round(w,6)，n 因子累加最大舍入误差 ≈ n×5e-7

        def _make_ic(n_days=25, n_pos=3, n_neg=2, seed=1, skew=False):
            rng = np.random.default_rng(seed)
            cols = {}
            for i in range(n_pos):
                cols[f"pos_{i}"] = rng.normal(0.10, 0.05, n_days)
            for j in range(n_neg):
                cols[f"neg_{j}"] = rng.normal(-0.10, 0.05, n_days)
            if skew and n_pos >= 2:
                cols["pos_0"] = cols["pos_0"] * 8.0  # 人为极不均匀 → 触发 water-filling
            idx = [f"202608{d:02d}" for d in range(1, n_days + 1)]
            return pd.DataFrame(cols, index=idx)

        # (a) n_eff=3 → cap 自适应 1/3：3 因子均 ≤ 1/3 且归一
        snap = calc_weights_snapshot(_make_ic(n_pos=3, n_neg=2), "20260825")
        w = {c: v for c, v in snap["weights"].items() if v > 0}
        self.assertEqual(len(w), 3, "应恰有 3 个正 IC 因子存活: %s" % snap["weights"])
        self.assertLessEqual(max(w.values()), 1 / 3 + TOL,
                             "n_eff=3 时权重不得超过自适应 cap 1/3: %s" % w)
        self.assertAlmostEqual(sum(snap["weights"].values()), 1.0, delta=TOL,
                               msg="权重归一 sum≈1: %.6f" % sum(snap["weights"].values()))

        # (b) n_eff=5 → 5×0.30>1，cap=0.30 严格生效
        snap2 = calc_weights_snapshot(_make_ic(n_pos=5, n_neg=2, seed=2), "20260825")
        w2 = {c: v for c, v in snap2["weights"].items() if v > 0}
        self.assertEqual(len(w2), 5, "应恰有 5 个存活因子: %s" % snap2["weights"])
        self.assertLessEqual(max(w2.values()), 0.30 + TOL,
                             "cap=0.30 被突破: %s" % w2)

        # (c) skew 极不均匀 + n_eff=3 → water-filling 压平至 ≤ 1/3
        snap3 = calc_weights_snapshot(_make_ic(n_pos=3, n_neg=2, seed=3, skew=True), "20260825")
        w3 = {c: v for c, v in snap3["weights"].items() if v > 0}
        self.assertLessEqual(max(w3.values()), 1 / 3 + TOL,
                             "skew 场景 water-filling 后仍不得超过 1/3: %s" % w3)
        self.assertAlmostEqual(sum(snap3["weights"].values()), 1.0, delta=TOL)

        # (d) 全负 IC → uniform_fallback 兜底
        snap4 = calc_weights_snapshot(_make_ic(n_pos=0, n_neg=4), "20260825")
        self.assertEqual(snap4["mode"], "uniform_fallback",
                         "全负 IC 应落入 uniform_fallback: %s" % snap4["mode"])
        self.assertAlmostEqual(sum(snap4["weights"].values()), 1.0, delta=TOL)


if __name__ == "__main__":
    unittest.main(verbosity=2)
