# -*- coding: utf-8 -*-
"""
reporter.py — 因子测试报告生成器
=================================================
生成自包含 HTML 报告，内嵌 ECharts 可交互图表。
两种报告模式:
  1. 单因子报告: IC/分层/回测/防过拟合全量图表 + 表格
  2. 多因子对比报告: 横向排名表
"""

import os
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime

from factor_lib.config import FactorTestConfig
from factor_lib.registry import FACTOR_REGISTRY


ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"

C_RED = "#e74c3c"
C_GREEN = "#2ecc71"
C_BLUE = "#3498db"
C_GRAY = "#95a5a6"
C_DARK = "#2c3e50"
C_ORANGE = "#f39c12"
C_PURPLE = "#9b59b6"


class FactorReporter:

    # ═══════════════════════════════════════════
    #  单因子报告
    # ═══════════════════════════════════════════

    def generate_single_report(
        self,
        factor_name: str,
        ic_result: dict,
        stratified_result,
        backtest_result,
        anti_overfit_result: dict,
        start_date: str = "",
        end_date: str = "",
        direction_check: dict = None,
    ) -> str:
        """生成自包含 HTML 单因子报告。"""
        meta = FACTOR_REGISTRY.get(factor_name)
        direction = meta.direction if meta else 1
        category = meta.category if meta else ""
        desc = meta.description if meta else ""

        sections = []
        sections.append(self._html_header(factor_name, direction, category, desc, start_date, end_date))
        # P0-1 方向一致性告警横幅（mismatch=红 / suspect=橙；ok 不渲染）
        banner = self._direction_banner(direction_check)
        if banner:
            sections.append(banner)
        sections.append(self._section_ic(ic_result))
        sections.append(self._section_stratified(stratified_result))
        sections.append(self._section_backtest(backtest_result))
        sections.append(self._section_anti_overfit(anti_overfit_result))
        sections.append(self._html_footer())

        return "\n".join(sections)

    # ═══════════════════════════════════════════
    #  多因子对比报告
    # ═══════════════════════════════════════════

    def generate_comparison_report(self, factor_results: List[dict]) -> str:
        """生成多因子对比 HTML 报告。"""
        rows = []
        for fr in factor_results:
            name = fr["factor_name"]
            meta = FACTOR_REGISTRY.get(name)
            direction = meta.direction if meta else 1

            ic_s = fr.get("ic_summary", {})
            bt_p = fr.get("backtest_performance", {})
            ao = fr.get("anti_overfit", {})

            perm = ao.get("permutation_test", {})
            sub = ao.get("subperiod_stability", {})

            score = self._compute_rating(ic_s, bt_p, perm, sub)

            rows.append({
                "factor": name,
                "category": meta.category if meta else "",
                "direction": "正向" if direction > 0 else "反向",
                "ic_mean": f"{ic_s.get('ic_mean', 0):.4f}",
                "icir": f"{ic_s.get('icir', 0):.4f}",
                "p_value": f"{ic_s.get('p_value', 1):.4f}",
                "sharpe": f"{bt_p.get('sharpe', 0):.4f}",
                "max_dd": f"{bt_p.get('max_drawdown', 0):.2%}",
                "annual_ret": f"{bt_p.get('annual_return', 0):.2%}",
                "mono_p": f"{fr.get('mono_pvalue', 1):.4f}",
                "perm_p": f"{perm.get('p_value', 1):.4f}",
                "sub_ratio": f"{sub.get('consistent_ratio', 0):.2%}",
                "rating": score,
            })

        rows.sort(key=lambda x: x["rating"], reverse=True)

        return self._html_comparison(rows)

    # ═══════════════════════════════════════════
    #  HTML 组件
    # ═══════════════════════════════════════════

    def _direction_banner(self, direction_check: Optional[dict]) -> str:
        """P0-1 方向一致性告警横幅；ok/None 不渲染。"""
        if not direction_check:
            return ""
        severity = direction_check.get("severity", "ok")
        if severity == "ok":
            return ""
        msg = direction_check.get("message", "")
        eff = direction_check.get("effective_ic")
        icir = direction_check.get("icir")
        if severity == "mismatch":
            bg, border, icon, title = "#fdecea", C_RED, "❌", "方向元数据疑似做反"
        else:
            bg, border, icon, title = "#fff8e1", C_ORANGE, "⚠️", "方向符号存疑（证据偏弱）"
        stats = ""
        if eff is not None and icir is not None:
            stats = f"<br><small>effective IC = {eff:+.4f}（ic_mean × direction），ICIR = {icir:+.2f}</small>"
        return f"""
<div style="margin:16px 0;padding:14px 18px;background:{bg};border-left:6px solid {border};
            border-radius:6px;color:{C_DARK};font-size:14px;line-height:1.6;">
  <strong style="color:{border};">{icon} {title}</strong><br>
  {msg}{stats}
</div>"""

    def _html_header(self, name, direction, category, desc, start, end):
        dir_text = "正向（值大越好）" if direction > 0 else "反向（值小越好）"
        dir_color = C_RED if direction > 0 else C_GREEN
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>因子测试报告 — {name}</title>
<script src="{ECHARTS_CDN}"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; background:#f5f6fa; color:{C_DARK}; padding:20px; }}
.container {{ max-width:1100px; margin:0 auto; }}
.header {{ background:linear-gradient(135deg,{C_DARK} 0%,#34495e 100%); color:#fff; padding:30px; border-radius:12px; margin-bottom:20px; }}
.header h1 {{ font-size:28px; margin-bottom:8px; }}
.header .meta {{ display:flex; flex-wrap:wrap; gap:15px; font-size:14px; opacity:0.9; }}
.badge {{ display:inline-block; padding:3px 10px; border-radius:4px; font-size:12px; font-weight:600; }}
.section {{ background:#fff; border-radius:12px; padding:25px; margin-bottom:20px; box-shadow:0 2px 8px rgba(0,0,0,0.06); }}
.section h2 {{ font-size:20px; margin-bottom:15px; padding-bottom:10px; border-bottom:2px solid #ecf0f1; }}
table {{ width:100%; border-collapse:collapse; margin:10px 0; font-size:14px; }}
th {{ background:#ecf0f1; padding:10px 12px; text-align:left; font-weight:600; border-radius:4px; }}
td {{ padding:8px 12px; border-bottom:1px solid #ecf0f1; }}
tr:hover {{ background:#f8f9fa; }}
.chart {{ width:100%; height:350px; margin:15px 0; }}
.chart-row {{ display:flex; gap:20px; flex-wrap:wrap; }}
.chart-half {{ flex:1; min-width:400px; }}
.pass {{ color:{C_RED}; font-weight:600; }}
.fail {{ color:{C_GREEN}; font-weight:600; }}
.summary-box {{ display:flex; gap:15px; flex-wrap:wrap; margin-bottom:15px; }}
.summary-card {{ flex:1; min-width:150px; background:#f8f9fa; border-radius:8px; padding:15px; text-align:center; }}
.summary-card .value {{ font-size:24px; font-weight:700; }}
.summary-card .label {{ font-size:12px; color:{C_GRAY}; margin-top:4px; }}
</style>
</head>
<body>
<div class="container">
<div class="header">
  <h1>因子测试报告 — {name}</h1>
  <div class="meta">
    <span>方向: <span class="badge" style="background:{dir_color}">{dir_text}</span></span>
    <span>分类: {category}</span>
    <span>描述: {desc}</span>
    <span>测试区间: {start} ~ {end or '最新'}</span>
    <span>生成时间: {now}</span>
  </div>
</div>
"""

    def _html_footer(self):
        return """</div>\n</body>\n</html>"""

    def _section_ic(self, ic_result: dict) -> str:
        rank_ic = ic_result.get("rank_ic_series")
        rank_summary = ic_result.get("rank_ic_summary", {})
        decay = ic_result.get("ic_decay")
        yearly = ic_result.get("yearly_stability")

        charts = []
        if rank_ic is not None and len(rank_ic) > 0:
            charts.append(self._chart_ic_series(rank_ic))
        if decay is not None and len(decay) > 0:
            charts.append(self._chart_ic_decay(decay))
        if rank_ic is not None and len(rank_ic) > 0:
            charts.append(self._chart_ic_cumulative(rank_ic))

        tables = []
        tables.append(self._table_ic_summary(rank_summary))
        if yearly is not None and len(yearly) > 0:
            tables.append(self._table_yearly_ic(yearly))

        return self._wrap_section("IC 分析", charts, tables)

    def _section_stratified(self, result) -> str:
        charts = []
        if result and len(result.group_nav) > 0:
            charts.append(self._chart_group_nav(result))
        if result and len(result.long_short_nav) > 0:
            charts.append(self._chart_long_short_nav(result))

        tables = []
        if result and len(result.group_returns) > 0:
            tables.append(self._table_group_returns(result))

        return self._wrap_section("分层测试", charts, tables)

    def _section_backtest(self, result) -> str:
        charts = []
        if result and len(result.nav) > 0:
            charts.append(self._chart_backtest_nav(result))

        tables = []
        if result and result.performance:
            tables.append(self._table_performance(result.performance, "组合绩效"))
        if result and len(result.yearly_returns) > 0:
            tables.append(self._table_yearly_returns(result.yearly_returns))

        return self._wrap_section("单因子回测 (Top-N 等权)", charts, tables)

    def _section_anti_overfit(self, ao: dict) -> str:
        tables = []

        is_oos = ao.get("in_sample_oos", {})
        if is_oos:
            tables.append(self._table_is_oos(is_oos))

        wf = ao.get("walk_forward", {})
        if wf and wf.get("n_windows", 0) > 0:
            tables.append(self._table_walk_forward(wf))

        perm = ao.get("permutation_test", {})
        if perm:
            tables.append(self._table_permutation(perm))

        sub = ao.get("subperiod_stability", {})
        if sub:
            tables.append(self._table_subperiod(sub))

        ac = ao.get("ic_autocorrelation", {})
        if ac:
            tables.append(self._table_autocorr(ac))

        charts = []
        if perm and perm.get("perm_distribution") is not None:
            charts.append(self._chart_permutation(perm))

        return self._wrap_section("防过拟合校验", charts, tables)

    def _wrap_section(self, title, charts, tables):
        html = f'<div class="section"><h2>{title}</h2>\n'
        for c in charts:
            html += c + "\n"
        for t in tables:
            html += t + "\n"
        html += "</div>\n"
        return html

    # ═══════════════════════════════════════════
    #  ECharts 图表
    # ═══════════════════════════════════════════

    def _make_chart(self, chart_id, option, height="350px"):
        opt = json.dumps(option, ensure_ascii=False, default=self._json_default)
        return f'<div id="{chart_id}" class="chart" style="height:{height}"></div>\n<script>var c=echarts.init(document.getElementById("{chart_id}"));c.setOption({opt});</script>'

    @staticmethod
    def _json_default(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, (np.ndarray,)):
            return o.tolist()
        if pd.isna(o):
            return None
        return str(o)

    def _downsample(self, series, n=500):
        if len(series) <= n:
            return series
        step = len(series) // n
        return series[::step]

    def _chart_ic_series(self, ic_series):
        s = self._downsample(ic_series.dropna())
        dates = [str(d) for d in s.index]
        vals = [round(float(v), 6) for v in s.values]
        option = {
            "title": {"text": "Rank IC 时序", "left": "center", "textStyle": {"fontSize": 14}},
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": dates, "axisLabel": {"rotate": 45, "fontSize": 10}},
            "yAxis": {"type": "value", "name": "IC"},
            "series": [{
                "type": "line", "data": vals, "symbol": "none",
                "lineStyle": {"color": C_BLUE, "width": 1},
                "areaStyle": {"opacity": 0.1},
            }],
            "dataZoom": [{"type": "inside"}, {"type": "slider"}],
        }
        return self._make_chart("ic_series", option)

    def _chart_ic_decay(self, decay):
        periods = [str(int(p)) for p in decay["period"]]
        means = [round(float(v), 6) for v in decay["ic_mean"]]
        option = {
            "title": {"text": "IC 衰减曲线", "left": "center", "textStyle": {"fontSize": 14}},
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": periods, "name": "持仓周期(天)"},
            "yAxis": {"type": "value", "name": "IC 均值"},
            "series": [{
                "type": "bar", "data": means,
                "itemStyle": {"color": C_ORANGE},
                "label": {"show": True, "position": "top", "formatter": "{c}"},
            }],
        }
        return self._make_chart("ic_decay", option)

    def _chart_ic_cumulative(self, ic_series):
        cum = ic_series.dropna().cumsum()
        s = self._downsample(cum)
        dates = [str(d) for d in s.index]
        vals = [round(float(v), 6) for v in s.values]
        option = {
            "title": {"text": "IC 累积曲线", "left": "center", "textStyle": {"fontSize": 14}},
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": dates, "axisLabel": {"rotate": 45, "fontSize": 10}},
            "yAxis": {"type": "value", "name": "累积 IC"},
            "series": [{
                "type": "line", "data": vals, "symbol": "none",
                "lineStyle": {"color": C_PURPLE, "width": 1.5},
                "areaStyle": {"opacity": 0.1},
            }],
            "dataZoom": [{"type": "inside"}, {"type": "slider"}],
        }
        return self._make_chart("ic_cum", option)

    def _chart_group_nav(self, result):
        nav = result.group_nav
        if "init" in nav.index:
            nav = nav.iloc[1:]
        dates = [str(d) for d in nav.index]
        series = []
        colors = [C_GREEN, "#1abc9c", C_GRAY, C_ORANGE, C_RED]
        for i, col in enumerate(nav.columns):
            s = self._downsample(nav[col])
            series.append({
                "name": col, "type": "line", "data": [round(float(v), 4) for v in s.values],
                "symbol": "none",
                "lineStyle": {"color": colors[i % len(colors)], "width": 1.5},
            })
        option = {
            "title": {"text": "分组净值曲线", "left": "center", "textStyle": {"fontSize": 14}},
            "tooltip": {"trigger": "axis"},
            "legend": {"top": 30},
            "xAxis": {"type": "category", "data": dates, "axisLabel": {"rotate": 45, "fontSize": 10}},
            "yAxis": {"type": "value", "name": "净值"},
            "series": series,
            "dataZoom": [{"type": "inside"}, {"type": "slider"}],
        }
        return self._make_chart("group_nav", option)

    def _chart_long_short_nav(self, result):
        nav = result.long_short_nav
        if "init" in nav.index:
            nav = nav.iloc[1:]
        s = self._downsample(nav)
        dates = [str(d) for d in s.index]
        vals = [round(float(v), 4) for v in s.values]
        option = {
            "title": {"text": "多空净值曲线 (扣成本)", "left": "center", "textStyle": {"fontSize": 14}},
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": dates, "axisLabel": {"rotate": 45, "fontSize": 10}},
            "yAxis": {"type": "value", "name": "净值"},
            "series": [{
                "type": "line", "data": vals, "symbol": "none",
                "lineStyle": {"color": C_RED, "width": 2},
                "areaStyle": {"opacity": 0.1},
            }],
            "dataZoom": [{"type": "inside"}, {"type": "slider"}],
        }
        return self._make_chart("ls_nav", option)

    def _chart_backtest_nav(self, result):
        nav = result.nav
        bnav = result.benchmark_nav
        if "init" in nav.index:
            nav = nav.iloc[1:]
        if "init" in bnav.index:
            bnav = bnav.iloc[1:]
        s_nav = self._downsample(nav)
        s_bnav = self._downsample(bnav)
        dates = [str(d) for d in s_nav.index]
        option = {
            "title": {"text": f"Top-{result.top_n} 组合 vs 基准净值", "left": "center", "textStyle": {"fontSize": 14}},
            "tooltip": {"trigger": "axis"},
            "legend": {"top": 30, "data": ["组合", "基准"]},
            "xAxis": {"type": "category", "data": dates, "axisLabel": {"rotate": 45, "fontSize": 10}},
            "yAxis": {"type": "value", "name": "净值"},
            "series": [
                {"name": "组合", "type": "line", "data": [round(float(v), 4) for v in s_nav.values],
                 "symbol": "none", "lineStyle": {"color": C_RED, "width": 2}},
                {"name": "基准", "type": "line", "data": [round(float(v), 4) for v in s_bnav.values],
                 "symbol": "none", "lineStyle": {"color": C_GRAY, "width": 1.5}},
            ],
            "dataZoom": [{"type": "inside"}, {"type": "slider"}],
        }
        return self._make_chart("bt_nav", option)

    def _chart_permutation(self, perm):
        dist = perm.get("perm_distribution", [])
        actual = perm.get("actual_ic_mean", 0)
        hist_data = [round(float(v), 6) for v in dist]
        option = {
            "title": {"text": "置换检验分布", "left": "center", "textStyle": {"fontSize": 14}},
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "value", "name": "置换 IC 均值"},
            "yAxis": {"type": "value", "name": "频次"},
            "series": [{
                "type": "histogram", "data": hist_data,
                "itemStyle": {"color": C_GRAY, "opacity": 0.7},
            }],
            "graphic": [{
                "type": "line",
                "shape": {"x1": actual, "y1": 0, "x2": actual, "y2": 100},
                "style": {"stroke": C_RED, "lineWidth": 2},
            }],
        }
        return self._make_chart("perm_dist", option)

    # ═══════════════════════════════════════════
    #  表格
    # ═══════════════════════════════════════════

    def _table_ic_summary(self, s: dict) -> str:
        rows = [
            ("IC 均值", f"{s.get('ic_mean',0):.6f}"),
            ("IC 标准差", f"{s.get('ic_std',0):.6f}"),
            ("ICIR", f"{s.get('icir',0):.4f}"),
            ("t 统计量", f"{s.get('t_stat',0):.4f}"),
            ("p 值", f"{s.get('p_value',0):.4e}"),
            ("IC 正比例", f"{s.get('positive_ratio',0):.2%}"),
            ("样本天数", f"{s.get('n_days',0)}"),
        ]
        return self._make_table("IC 统计摘要", ["指标", "值"], rows)

    def _table_yearly_ic(self, yearly: pd.DataFrame) -> str:
        headers = ["年份", "天数", "IC均值", "ICIR", "t值", "p值", "正比例"]
        rows = []
        for _, r in yearly.iterrows():
            rows.append([
                str(r["year"]), str(int(r["n_days"])),
                f"{r['ic_mean']:.6f}", f"{r['icir']:.4f}",
                f"{r['t_stat']:.4f}", f"{r['p_value']:.4e}",
                f"{r['positive_ratio']:.2%}",
            ])
        return self._make_table("分年度 IC 稳定性", headers, rows)

    def _table_group_returns(self, result) -> str:
        gr = result.group_returns
        headers = ["组别"] + [c for c in gr.columns]
        rows = []
        avg_row = ["平均收益"] + [f"{gr[c].mean():.6f}" for c in gr.columns]
        rows.append(avg_row)
        rows.append(["期数"] + [str(len(gr))] * len(gr.columns))
        return self._make_table(
            f"分组收益 (单调性: score={result.monotonicity_score:.4f}, p={result.monotonicity_pvalue:.4f}, 换手率={result.avg_turnover:.2%})",
            headers, rows
        )

    def _table_performance(self, p: dict, title: str = "绩效") -> str:
        rows = [
            ("总收益", f"{p.get('total_return',0):.2%}"),
            ("年化收益", f"{p.get('annual_return',0):.2%}"),
            ("年化波动", f"{p.get('annual_volatility',0):.2%}"),
            ("夏普", f"{p.get('sharpe',0):.4f}"),
            ("Sortino", f"{p.get('sortino',0):.4f}"),
            ("最大回撤", f"{p.get('max_drawdown',0):.2%}"),
            ("卡玛", f"{p.get('calmar',0):.4f}"),
            ("胜率", f"{p.get('win_rate',0):.2%}"),
            ("盈亏比", f"{p.get('profit_loss_ratio',0):.4f}"),
            ("期数", f"{p.get('n_periods',0)}"),
        ]
        return self._make_table(title, ["指标", "值"], rows)

    def _table_yearly_returns(self, yr: pd.DataFrame) -> str:
        headers = ["年份", "期数", "组合收益", "基准收益", "超额", "夏普", "胜率"]
        rows = []
        for _, r in yr.iterrows():
            rows.append([
                str(r["year"]), str(int(r["n_periods"])),
                f"{r['portfolio_return']:.2%}", f"{r['benchmark_return']:.2%}",
                f"{r['excess_return']:.2%}", f"{r['sharpe']:.4f}",
                f"{r['win_rate']:.2%}",
            ])
        return self._make_table("分年度收益", headers, rows)

    def _table_is_oos(self, is_oos: dict) -> str:
        rows = [
            ("训练期天数", str(is_oos.get("train_n_days", 0))),
            ("训练 IC 均值", f"{is_oos.get('train_ic_mean',0):.6f}"),
            ("训练 ICIR", f"{is_oos.get('train_icir',0):.4f}"),
            ("测试期天数", str(is_oos.get("test_n_days",0))),
            ("测试 IC 均值", f"{is_oos.get('test_ic_mean',0):.6f}"),
            ("测试 ICIR", f"{is_oos.get('test_icir',0):.4f}"),
            ("ICIR 衰减", f"{is_oos.get('icir_decay',0):.2%}"),
            ("方向一致", "✅" if is_oos.get("direction_consistent") else "❌"),
        ]
        return self._make_table("样本内外对比", ["指标", "值"], rows)

    def _table_walk_forward(self, wf: dict) -> str:
        res = wf.get("results")
        if res is None or len(res) == 0:
            return ""
        headers = ["窗口", "训练IC", "测试IC", "测试ICIR", "方向一致"]
        rows = []
        for _, r in res.iterrows():
            rows.append([
                str(int(r["window"])),
                f"{r['train_ic']:.6f}", f"{r['test_ic']:.6f}",
                f"{r['test_icir']:.4f}",
                "✅" if r["direction_consistent"] else "❌",
            ])
        return self._make_table(
            f"Walk-Forward (窗口数={wf.get('n_windows',0)}, 正比例={wf.get('ic_positive_ratio',0):.2%}, 方向一致={wf.get('direction_consistency_ratio',0):.2%})",
            headers, rows
        )

    def _table_permutation(self, perm: dict) -> str:
        sig = perm.get("significant", False)
        rows = [
            ("实际 IC 均值", f"{perm.get('actual_ic_mean',0):.6f}"),
            ("置换 IC 均值", f"{perm.get('perm_ic_mean',0):.6f}"),
            ("置换 IC 标准差", f"{perm.get('perm_ic_std',0):.6f}"),
            ("p 值", f"{perm.get('p_value',0):.4f}"),
            ("95% CI", f"[{perm.get('perm_2.5%',0):.6f}, {perm.get('perm_97.5%',0):.6f}]"),
            ("显著 (p<0.05)", "✅ 是" if sig else "❌ 否"),
            ("置换次数", str(perm.get("n_permutations",0))),
        ]
        return self._make_table("置换检验", ["指标", "值"], rows)

    def _table_subperiod(self, sub: dict) -> str:
        rows = [
            ("年数", str(sub.get("n_years",0))),
            ("整体 IC 均值", f"{sub.get('overall_ic_mean',0):.6f}"),
            ("方向一致率", f"{sub.get('consistent_ratio',0):.2%}"),
            ("通过 (≥70%)", "✅" if sub.get("pass") else "❌"),
        ]
        return self._make_table("子周期稳定性", ["指标", "值"], rows)

    def _table_autocorr(self, ac: dict) -> str:
        rows = [
            ("AC(1)", f"{ac.get('autocorr_lag1',0):.4f}"),
            ("AC(5)", f"{ac.get('autocorr_lag5',0):.4f}"),
            ("AC(10)", f"{ac.get('autocorr_lag10',0):.4f}"),
            ("有持续性 (|AC1|>0.1)", "✅" if ac.get("has_persistence") else "❌"),
        ]
        return self._make_table("IC 自相关", ["指标", "值"], rows)

    def _make_table(self, title, headers, rows):
        html = f'<h3 style="margin:15px 0 5px; font-size:16px;">{title}</h3>\n<table>\n<thead><tr>'
        for h in headers:
            html += f"<th>{h}</th>"
        html += "</tr></thead>\n<tbody>\n"
        for row in rows:
            html += "<tr>"
            for cell in row:
                html += f"<td>{cell}</td>"
            html += "</tr>\n"
        html += "</tbody>\n</table>\n"
        return html

    # ═══════════════════════════════════════════
    #  对比报告
    # ═══════════════════════════════════════════

    def _compute_rating(self, ic_s, bt_p, perm, sub):
        score = 0
        if abs(ic_s.get("icir", 0)) > 0.3:
            score += 2
        elif abs(ic_s.get("icir", 0)) > 0.15:
            score += 1
        if bt_p.get("sharpe", 0) > 0.5:
            score += 2
        elif bt_p.get("sharpe", 0) > 0:
            score += 1
        if perm.get("p_value", 1) < 0.05:
            score += 2
        elif perm.get("p_value", 1) < 0.1:
            score += 1
        if sub.get("consistent_ratio", 0) >= 0.7:
            score += 1
        return score

    def _html_comparison(self, rows):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        table_html = '<table>\n<thead><tr>'
        headers = ["排名", "因子", "分类", "方向", "IC均值", "ICIR", "IC p值",
                   "夏普", "最大回撤", "年化收益", "单调性p", "置换p", "子周期一致", "评级"]
        for h in headers:
            table_html += f"<th>{h}</th>"
        table_html += "</tr></thead>\n<tbody>\n"
        for i, r in enumerate(rows):
            rating_text = "★" * r["rating"] if r["rating"] > 0 else "-"
            table_html += (
                f'<tr><td>{i+1}</td><td>{r["factor"]}</td><td>{r["category"]}</td>'
                f'<td>{r["direction"]}</td><td>{r["ic_mean"]}</td><td>{r["icir"]}</td>'
                f'<td>{r["p_value"]}</td><td>{r["sharpe"]}</td><td>{r["max_dd"]}</td>'
                f'<td>{r["annual_ret"]}</td><td>{r["mono_p"]}</td><td>{r["perm_p"]}</td>'
                f'<td>{r["sub_ratio"]}</td><td>{rating_text}</td></tr>\n'
            )
        table_html += "</tbody>\n</table>\n"

        return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>多因子对比报告</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; background:#f5f6fa; color:{C_DARK}; padding:20px; }}
.container {{ max-width:1200px; margin:0 auto; }}
.header {{ background:linear-gradient(135deg,{C_DARK} 0%,#34495e 100%); color:#fff; padding:30px; border-radius:12px; margin-bottom:20px; }}
.header h1 {{ font-size:28px; margin-bottom:8px; }}
.section {{ background:#fff; border-radius:12px; padding:25px; margin-bottom:20px; box-shadow:0 2px 8px rgba(0,0,0,0.06); }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ background:#ecf0f1; padding:10px 8px; text-align:left; font-weight:600; }}
td {{ padding:8px; border-bottom:1px solid #ecf0f1; }}
tr:hover {{ background:#f8f9fa; }}
</style>
</head>
<body>
<div class="container">
<div class="header">
  <h1>多因子对比报告</h1>
  <p style="opacity:0.9; margin-top:5px;">生成时间: {now} | 共 {len(rows)} 个因子</p>
</div>
<div class="section">
{table_html}
</div>
</div>
</body>
</html>"""
