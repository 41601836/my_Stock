# -*- coding: utf-8 -*-
"""
run_agent.py —— 因子自适应 Agent 系统主入口 (自适应自动巡航版)
========================================================================
1. 解析命令行参数：
   - --mode quick   : 因子效能衰减监测校验 + 104周快速超额收益回测
   - --mode search  : 实验特征因子池有效性与共线相关性挖掘
   - --mode full    : 校验+搜索+自适应组合平行超额回测比对 (208周深度测试)
   - --auto         : 因子自适应自动巡航优化调优模式 (寻找超额卡玛 >= 0.50 的最佳策略)
   - --approve      : 人工确认暂存的优化权重组合正式生效
2. 自动巡航逻辑：
   - 进入无限寻优循环，最大尝试 100 次，最大时限 24 小时。
   - 每一轮如果卡玛未达标，则在内存中调谐参数 (微调 top_n) 并物理重写 config.yaml。
   - 休眠 60 秒后进入下一轮，一旦超额卡玛 >= 0.50 自动批准权重退出。
"""

import os
import sys
import time
import glob
import argparse
import json
import shutil
import pickle
import threading
import yaml
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.paths import PATHS, startup_check

startup_check()

from agent.validator import validate_factors
from agent.searcher import search_new_factors, generate_factor_combinations
from agent.recommender import recommend_adaptive_portfolio
from agent.backtester import run_portfolio_backtest

def parse_args():
    parser = argparse.ArgumentParser(description="因子自适应决策 Agent 系统")
    parser.add_argument(
        "--mode", 
        type=str, 
        choices=["quick", "full", "search", "simulation", "jack"], 
        default="quick",
        help="运行模式 (quick: 仅校验超额回测 | full: 全流程超额卡玛平行测试 | search: 仅挖掘新因子 | simulation: 实盘仿真模拟验证 | jack: 模拟游资/Jack追涨抄底路由测试)"
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="开启 Agent 自动巡航自适应参数调优寻优模式"
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="人工确认暂存的优化权重配置 models/regime_weights_proposed.pkl 正式生效"
    )
    # 支持自定义 auto 寻优时的休眠时间，测试时可调小
    parser.add_argument(
        "--sleep-seconds",
        type=int,
        default=60,
        help="自动巡航未达标时的每轮休眠秒数 (默认 60 秒)"
    )
    return parser.parse_args()

def handle_approval():
    """
    人工确认逻辑：覆盖 models/regime_weights.pkl
    """
    proposed_path = PATHS.models.regime_weights_proposed
    official_path = PATHS.models.regime_weights
    
    print("=" * 60)
    print("🔔 因子 Agent 人工配置确认程序")
    print("=" * 60)
    
    if not os.path.exists(proposed_path):
        print(f"❌ 错误: 未能找到待确认的新推荐权重配置 {proposed_path}，请先运行 --mode full 搜索最优组合。")
        return
        
    try:
        # 读取待确认的权重
        with open(proposed_path, "rb") as f:
            data = pickle.load(f)
            
        print(f"ℹ️ 待确认生效的新组合特征子集: {data['range_factors']}")
        print(f"ℹ️ 待确认生效的因子自适应分配权重 (已包含方向符号):")
        for k, v in data["range_weights"].items():
            print(f"   - {k:<24} : {v:.4f}")
            
        # 覆盖复制
        shutil.copy(proposed_path, official_path)
        print(f"\n✅ 【人工确认成功】新因子自适应配置权重已被正式写入并覆盖至: {official_path}！")
    except Exception as e:
        print(f"❌ 确认失败，发生错误: {e}")
    print("=" * 60)

def run_single_full_process(config_path, weeks_to_test=208):
    """
    执行一次完整的模式验证 + 搜索 + 推荐流程，返回决策报告
    """
    val_report, df_aligned = validate_factors(config_path)
    active_base_factors = [f for f, det in val_report.items() if not f.startswith("_") and det["status"] in ["VALID", "WARNING"]]
    
    search_report, new_factors = search_new_factors(df_aligned, active_base_factors, config_path)
    rec_report = recommend_adaptive_portfolio(
        df_aligned, val_report, search_report, new_factors, 
        weeks_to_test=weeks_to_test, config_path=config_path
    )
    return rec_report, val_report, search_report

def load_resume_checkpoint(project_root):
    """
    P2 断点续跑：读取最近一次巡航报告。
    仅当上次会话「未达标即中断」时返回断点；若上次已达标部署(success=True)则全新开始。
    返回: {"tested_keys": {(因子组合tuple, top_n)}, "best": {...}|None, "traj_results": {(combo, top_n): 超额卡玛}}
    """
    reports = glob.glob(os.path.join(project_root, "agent", "auto_cruise_report_*.json"))
    if not reports:
        return None
    latest = max(reports, key=os.path.getmtime)
    try:
        with open(latest, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"⚠️ [Resume] 读取断点报告失败，将全新开始: {e}")
        return None
    if data.get("success_target_reached"):
        return None
    traj = data.get("search_trajectory") or []
    if not traj:
        return None
    tested_keys = set()
    traj_results = {}  # P1-3: {(因子组合tuple, top_n): excess_calmar} 供跨 top_n 稳健性闸门评定
    for t in traj:
        params = t.get("tested_params") or {}
        combo_key = tuple(t.get("factor_combination") or [])
        top_n = params.get("top_n")
        tested_keys.add((combo_key, top_n))
        cal = t.get("excess_calmar_ratio")
        if cal is not None:
            traj_results[(combo_key, top_n)] = float(cal)
    best = None
    best_calmar = data.get("best_overall_excess_calmar")
    if best_calmar is not None and data.get("best_overall_combination") and data.get("best_overall_factors"):
        best = {
            "factor_combination": data["best_overall_combination"],
            "params": data.get("best_overall_params") or {},
            "excess_calmar": float(best_calmar),
            "factors": data["best_overall_factors"],
            "weights": data["best_overall_weights"] or {},
        }
    print(f"🔄 [Resume] 检测到未达标中断的巡航断点: {os.path.basename(latest)} | 已测 {len(tested_keys)} 组参数网格 | 历史最优超额卡玛: {best_calmar}")
    return {"tested_keys": tested_keys, "best": best, "traj_results": traj_results}


def run_auto_cruise(config_path="agent/config.yaml", sleep_seconds=60):
    """
    自动巡航调优流程
    """
    print("\n" + "=" * 80)
    print("🚀 启动 Agent 自动巡航自适应参数调优寻优模式")
    print("=" * 80)
    
    # 备份原始配置文件
    backup_path = config_path + ".bak"
    shutil.copy(config_path, backup_path)
    print(f"ℹ️ 原始配置已备份至: {backup_path}")
    
    import signal
    # 注册系统终止信号处理器，防 kill / SIGTERM 终止时备份文件丢失或配置损坏
    def handle_signal(signum, frame):
        print(f"\n⚠️ [Signal] 接收到系统终止信号 {signum}。开始执行安全清理并退出...")
        if os.path.exists(backup_path):
            shutil.copy(backup_path, config_path)
            os.remove(backup_path)
            print("ℹ️ 本地 config.yaml 已成功恢复为初始设置。")
        try:
            os.remove(heartbeat_path)  # 优雅退出：清除心跳，后端状态回归 IDLE
        except Exception:
            pass
        sys.exit(0)
        
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGHUP"):
        # P1: 终端关闭/断开连接会向进程组发送 SIGHUP，未处理会导致进程秒死且无清理
        signal.signal(signal.SIGHUP, handle_signal)
    
    # 1. 因子组合生成器生成 25 组候选因子组合
    candidate_path = PATHS.config.candidate_factors
    combinations = generate_factor_combinations(config_path, candidate_path, num_combinations=25)
    print(f"📊 因子组合生成器已成功生成 {len(combinations)} 组进化候选因子组合。")
    
    # 2. 超参数网格定义 (multiplier 仅对 special_boost.factors 生效，当前候选组合不含特权因子，维度已移除提速)
    param_grid = []
    for top_n in [20, 10, 30]:
        param_grid.append({"top_n": top_n})

    # P1-3: 跨 top_n 稳健性闸门配置（巡航开始时 config.yaml 为原始状态；巡航期物理重写为 yaml 往返，cruise 节保留）
    with open(config_path, "r", encoding="utf-8") as _f:
        _cruise_cfg = yaml.safe_load(_f) or {}
    _gate_cfg = ((_cruise_cfg.get("cruise") or {}).get("robustness_gate") or {})
    gate_enabled = bool(_gate_cfg.get("enabled", True))
    gate_min_calmar = float(_gate_cfg.get("min_excess_calmar", 0.0))
    print(f"🛡️ [稳健性闸门] enabled={gate_enabled} | 三档 top_n={[p['top_n'] for p in param_grid]} | 超额卡玛最小值阈值={gate_min_calmar}（关闭时恢复旧行为：单点最优即可部署）")

    # P1-3: 每个组合三档 top_n 的超额卡玛汇集（本次会话新测 + 续跑历史轨迹）
    combo_results = {}

    def eval_robustness(combo_key):
        """跨 top_n 稳健性评定。返回 (passed, status, per_topn)。
        status: 'disabled'（闸门关闭）| 'pass' | 'fail'（三档齐活但最小值<阈值）| 'pending'（三档未齐）"""
        if not gate_enabled:
            return True, "disabled", {}
        per = {}
        for p in param_grid:
            tn = p["top_n"]
            if tn in combo_results.get(combo_key, {}):
                per[tn] = combo_results[combo_key][tn]
        if len(per) < len(param_grid):
            return False, "pending", per
        if min(per.values()) >= gate_min_calmar:
            return True, "pass", per
        return False, "fail", per

    max_loops = 100
    timeout_hours = 24
    start_time = time.time()
    
    run_date = datetime.now().strftime("%Y%m%d")
    trace_report_path = f"agent/auto_cruise_report_{run_date}.json"
    
    search_history = []
    success = False
    best_overall_run = None
    best_overall_excess_calmar = -999.0

    def gate_summary():
        """P1-3: 汇总各组合跨 top_n 稳健性评定结果（含续跑历史组合），随轨迹报告落盘供观测。"""
        if not gate_enabled:
            return {"enabled": False}
        combos = []
        for ck, per in combo_results.items():
            _passed, _status, _ = eval_robustness(ck)
            combos.append({
                "factor_combination": list(ck),
                "per_topn_excess_calmar": {str(tn): round(v, 4) for tn, v in per.items()},
                "status": _status,
                "passed": _passed,
            })
        return {
            "enabled": True,
            "min_excess_calmar": gate_min_calmar,
            "required_topn": [p["top_n"] for p in param_grid],
            "combos": combos,
        }

    def write_trace_report():
        """增量原子导出寻优轨迹报告：每轮网格测试后实时落盘，保证前端面板与巡航进度同步。"""
        report = {
            "run_date": run_date,
            "success_target_reached": success,
            "best_overall_excess_calmar": best_overall_excess_calmar if best_overall_excess_calmar > -999.0 else None,
            "best_overall_combination": best_overall_run["factor_combination"] if best_overall_run else None,
            "best_overall_params": best_overall_run["params"] if best_overall_run else None,
            # P2: 持久化历史最优的因子/权重，断点续跑时作为全局最优种子参与兜底部署
            "best_overall_factors": best_overall_run["rec_report"]["new_portfolio"]["factors"] if best_overall_run else None,
            "best_overall_weights": best_overall_run["rec_report"]["new_portfolio"]["weights"] if best_overall_run else None,
            "total_loops_tried": len(search_history),
            "robustness_gate": gate_summary(),
            "search_trajectory": search_history
        }
        tmp_path = trace_report_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=4, ensure_ascii=False)
        os.replace(tmp_path, trace_report_path)

    # P2: 断点续跑 —— 上次未达标中断时，跳过已测参数并继承历史最优
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    checkpoint = load_resume_checkpoint(project_root)
    tested_keys = checkpoint["tested_keys"] if checkpoint else set()
    # P1-3: 历史轨迹格点灌入 combo_results，供整组跳过时的闸门评定
    if checkpoint and checkpoint.get("traj_results"):
        for (_ck, _tn), _cal in checkpoint["traj_results"].items():
            combo_results.setdefault(_ck, {})[_tn] = _cal
    if checkpoint and checkpoint["best"]:
        b = checkpoint["best"]
        # P1-3: 历史最优种子必须通过跨 top_n 稳健性闸门复核，否则弃用重评
        _seed_passed, _seed_status, _seed_per = eval_robustness(tuple(b["factor_combination"]))
        if gate_enabled and not _seed_passed:
            print(f"🛡️ [稳健性闸门·续跑] 历史最优组合 {b['factor_combination']} 未通过闸门（status={_seed_status}，三档={ {k: round(v, 4) for k, v in _seed_per.items()} }）→ 弃用历史最优种子，重新评选")
        else:
            if gate_enabled:
                print(f"🛡️ [稳健性闸门·续跑] 历史最优组合通过闸门（三档={ {k: round(v, 4) for k, v in _seed_per.items()} }）")
            best_overall_excess_calmar = b["excess_calmar"]
            best_overall_run = {
                "factor_combination": b["factor_combination"],
                "params": b["params"],
                "rec_report": {"new_portfolio": {"factors": b["factors"], "weights": b["weights"]}}
            }

    # 巡航启动即落盘初始报告，覆盖同日旧会话残留，避免前端读到过期战果
    write_trace_report()

    # P0: 活性心跳 —— 独立心跳文件 (mtime 即活性)，后端据此判定 RUNNING/已中断；kill -9 等硬死亡会留下过期心跳
    heartbeat_path = os.path.join(project_root, "agent", "cruise_heartbeat")

    def write_heartbeat():
        with open(heartbeat_path, "w", encoding="utf-8") as f:
            f.write(f"pid={os.getpid()}|time={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    def _heartbeat_loop():
        while True:
            time.sleep(30)
            try:
                write_heartbeat()
            except Exception:
                pass

    write_heartbeat()
    threading.Thread(target=_heartbeat_loop, daemon=True).start()

    try:
        # 外循环：因子组合进化
        for combo_idx, combo in enumerate(combinations, 1):
            elapsed_hours = (time.time() - start_time) / 3600.0
            if elapsed_hours >= timeout_hours:
                print(f"\n⚠️ [熔断退出] 已运行 {elapsed_hours:.2f} 小时，超过超时时限 {timeout_hours} 小时。")
                break
            if len(search_history) >= max_loops:
                print(f"\n⚠️ [熔断退出] 已尝试超过 {max_loops} 次测试网格。安全熔断。")
                break

            # P2: 该组合全部参数网格已在上次会话测试过 → 整组跳过
            if tested_keys and all((tuple(combo), p["top_n"]) in tested_keys for p in param_grid):
                print(f"\n⏭️ [Resume] 第 {combo_idx:02d} 组因子组合的 {len(param_grid)} 组参数已全部测试过，整组跳过。")
                if gate_enabled:
                    _hp, _hs, _hper = eval_robustness(tuple(combo))
                    if _hs == "pass":
                        print(f"🛡️ [稳健性闸门·历史] ✅ 通过：三档超额卡玛 { {k: round(v, 4) for k, v in _hper.items()} }（历史组合仅记录观测，部署以本次会话评选为准）")
                    else:
                        print(f"🛡️ [稳健性闸门·历史] ❌ status={_hs}：三档超额卡玛 { {k: round(v, 4) for k, v in _hper.items()} } → 不进入全局最优评选")
                continue

            print(f"\n" + "=" * 70)
            print(f"🧬 【第 {combo_idx:02d} 组因子组合进化】尝试因子: {combo}")
            print("=" * 70)
            
            # 内循环：在该组合下网格搜索最优超参数
            best_combo_excess_calmar = -999.0
            best_combo_params = None
            best_combo_rec_report = None
            
            for param_idx, params in enumerate(param_grid, 1):
                if len(search_history) >= max_loops:
                    break

                # P2: 断点续跑 —— 跳过上次会话已测试过的 (组合, 参数) 对
                if (tuple(combo), params["top_n"]) in tested_keys:
                    print(f"   ↳ [Resume] 跳过已测参数网格 [{param_idx}/{len(param_grid)}]: top_n = {params['top_n']}")
                    continue

                # 物理重写 config.yaml 副本
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg_data = yaml.safe_load(f)

                cfg_data["factors"]["custom_new_factors"] = combo
                cfg_data["backtest"]["top_n_stocks"] = params["top_n"]

                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(cfg_data, f, allow_unicode=True)

                # 运行 208 周平行平行路由测试
                try:
                    rec_report, val_report, search_report = run_single_full_process(config_path, weeks_to_test=208)
                    new_ex_calmar = rec_report["new_portfolio"]["metrics"]["excess_calmar_ratio"]
                except Exception as e:
                    print(f"⚠️ [Error] 组合回测失败 {combo} with params {params}: {str(e)}")
                    continue

                print(f"   ↳ 参数网格 [{param_idx}/{len(param_grid)}]: top_n = {params['top_n']} ➡️ 路由合并超额卡玛 = {new_ex_calmar:.4f}")

                # P1-3: 汇集该组合各档 top_n 超额卡玛，供跨 top_n 稳健性闸门评定
                combo_results.setdefault(tuple(combo), {})[params["top_n"]] = new_ex_calmar

                # 记录
                search_history.append({
                    "combo_index": combo_idx,
                    "factor_combination": combo,
                    "tested_params": params,
                    "excess_calmar_ratio": new_ex_calmar,
                    "absolute_calmar_ratio": rec_report["new_portfolio"]["metrics"]["calmar_ratio"]
                })

                if new_ex_calmar > best_combo_excess_calmar:
                    best_combo_excess_calmar = new_ex_calmar
                    best_combo_params = params
                    best_combo_rec_report = rec_report

                # P1-3: 闸门开启时单点不直接入选全局最优，待该组合三档 top_n 齐活后统一评定；关闭时保持旧行为
                if not gate_enabled and new_ex_calmar > best_overall_excess_calmar:
                    best_overall_excess_calmar = new_ex_calmar
                    best_overall_run = {
                        "factor_combination": combo,
                        "params": params,
                        "rec_report": rec_report
                    }

                # 每轮网格测试后实时同步寻优轨迹报告
                write_trace_report()
                    
            # 防崩溃：整组参数全部回测失败或全部被跳过时，best_combo_params 为 None，直接进入下一组
            if best_combo_params is None:
                print(f"⚖️ 第 {combo_idx:02d} 组因子组合无有效测试结果 (全部失败或已跳过)，进入下一组。")
                continue

            print(f"🔥 组合最佳表现 ➡️ top_n = {best_combo_params['top_n']} ➡️ 最佳超额卡玛 = {best_combo_excess_calmar:.4f}")

            # ===== P1-3: 跨 top_n 稳健性闸门 =====
            if gate_enabled:
                _g_passed, _g_status, _g_per = eval_robustness(tuple(combo))
                _g_view = {k: round(v, 4) for k, v in _g_per.items()}
                if _g_status == "pass":
                    print(f"🛡️ [稳健性闸门] ✅ 通过：三档 top_n 超额卡玛 {_g_view}，最小值 {min(_g_per.values()):.4f} ≥ 阈值 {gate_min_calmar}")
                    if best_combo_excess_calmar > best_overall_excess_calmar:
                        best_overall_excess_calmar = best_combo_excess_calmar
                        best_overall_run = {
                            "factor_combination": combo,
                            "params": best_combo_params,
                            "rec_report": best_combo_rec_report
                        }
                elif _g_status == "fail":
                    print(f"🛡️ [稳健性闸门] ❌ 未通过：三档超额卡玛 {_g_view}，最小值 {min(_g_per.values()):.4f} < 阈值 {gate_min_calmar} → 不进入全局最优/达标部署")
                    continue
                else:
                    print(f"🛡️ [稳健性闸门] ⏳ 三档结果未齐 {_g_view}，暂不入选（断点续跑补齐后再评定）")
                    continue
            # ===== P1-3 end =====

            # 进化决策判定
            if best_combo_excess_calmar >= 0.50:
                print(f"\n🎉 🔥 【达标成功】在第 {combo_idx:02d} 组因子组合寻找到达标组合！")
                print(f"   - 因子组合: {combo}")
                print(f"   - 最佳参数: top_n_stocks = {best_combo_params['top_n']}")
                print(f"   - 最佳超额卡玛: {best_combo_excess_calmar:.4f}")

                # 保存 proposed 临时权重
                proposed_path = PATHS.models.regime_weights_proposed
                with open(proposed_path, "wb") as f:
                    pickle.dump({
                        "range_factors": best_combo_rec_report["new_portfolio"]["factors"],
                        "range_weights": best_combo_rec_report["new_portfolio"]["weights"]
                    }, f)

                # 写回主 config.yaml
                shutil.copy(backup_path, config_path)
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg_final = yaml.safe_load(f)
                cfg_final["factors"]["custom_new_factors"] = combo
                cfg_final["backtest"]["top_n_stocks"] = best_combo_params["top_n"]
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.dump(cfg_final, f, allow_unicode=True)
                    
                shutil.copy(config_path, backup_path)
                handle_approval()
                success = True
                break
                
        # 兜底：若全跑完仍未达标，则自动部署全局最优
        if not success and best_overall_run is not None:
            print(f"\n⚖️ 【全尝试未达标】所有因子组合尝试完毕。自动部署全局最优解：")
            best_combo = best_overall_run["factor_combination"]
            best_p = best_overall_run["params"]
            best_rep = best_overall_run["rec_report"]
            
            print(f"   - 最优因子组合: {best_combo}")
            print(f"   - 最优参数配置: top_n_stocks = {best_p['top_n']}")
            print(f"   - 最优超额卡玛: {best_overall_excess_calmar:.4f}")

            proposed_path = PATHS.models.regime_weights_proposed
            with open(proposed_path, "wb") as f:
                pickle.dump({
                    "range_factors": best_rep["new_portfolio"]["factors"],
                    "range_weights": best_rep["new_portfolio"]["weights"]
                }, f)

            shutil.copy(backup_path, config_path)
            with open(config_path, "r", encoding="utf-8") as f:
                cfg_final = yaml.safe_load(f)
            cfg_final["factors"]["custom_new_factors"] = best_combo
            cfg_final["backtest"]["top_n_stocks"] = best_p["top_n"]
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg_final, f, allow_unicode=True)
                
            shutil.copy(config_path, backup_path)
            handle_approval()
            success = True
        elif not success and gate_enabled:
            print("\n🛡️ [稳健性闸门] 无任何因子组合通过跨 top_n 稳健性评定（三档超额卡玛最小值均未达阈值），本次巡航不部署权重。")
            print("   （旧行为为自动部署单点最优，已由 P1-3 闸门拦截；各组合三档明细见轨迹报告 robustness_gate 节）")

    except KeyboardInterrupt:
        print("\n👋 [Auto] 检测到人工 Ctrl+C 中断。正在安全退出...")
    finally:
        # 恢复原始配置文件，保障系统一致性
        if os.path.exists(backup_path):
            shutil.copy(backup_path, config_path)
            os.remove(backup_path)
        print("ℹ️ 本地 config.yaml 已成功恢复为初始设置。")
        
        # 导出寻优轨迹历史报告 (最终状态)
        write_trace_report()
        print(f"📝 自动组合进化轨迹历史报告已导出至: {trace_report_path}")

        # 优雅退出：清除心跳文件，后端状态回归 IDLE (硬死亡时心跳保留 → 显示"已中断")
        try:
            os.remove(heartbeat_path)
        except Exception:
            pass
        
    print("\n" + "=" * 80)
    print("      自动因子组合进化寻优流运行完毕。")
    print("=" * 80)

def main():
    args = parse_args()
    
    # 1. 优先处理 approval 人工确认
    if args.approve:
        handle_approval()
        return
        
    # 2. 自动巡航自适应参数寻优模式
    if args.auto:
        run_auto_cruise("agent/config.yaml", sleep_seconds=args.sleep_seconds)
        return
        
    mode = args.mode
    run_date = datetime.now().strftime("%Y%m%d")
    report_name = f"agent/report_{run_date}.json"
    
    print("=" * 80)
    print(f"🤖  因子自适应 Agent 系统运行中 | 模式: {mode.upper()} | 日期: {run_date}")
    print("=" * 80)
    
    config_path = PATHS.config.agent
    
    # 3. 正常 quick/search/full 分流
    if mode == "quick":
        val_report, df_aligned = validate_factors(config_path)
        active_base_factors = [f for f, det in val_report.items() if not f.startswith("_") and det["status"] in ["VALID", "WARNING"]]
        
        if not active_base_factors:
            print("⚠️ [Warning] 基础验证因数据期不足全部判定失效，回退使用全量测试因子...")
            active_base_factors = [f for f in val_report.keys() if not f.startswith("_")]
            if not active_base_factors:
                active_base_factors = ["turnover_rate"] # Extreme fallback
        
        base_weights = {}
        for f in active_base_factors:
            base_weights[f] = val_report[f]["baseline_ic"]
        sum_abs = sum(abs(v) for v in base_weights.values())
        if sum_abs > 1e-6:
            base_weights = {k: v / sum_abs for k, v in base_weights.items()}
        else:
            base_weights = {f: 1.0/len(active_base_factors) for f in active_base_factors}
            
        metrics, _ = run_portfolio_backtest(df_aligned, active_base_factors, base_weights, weeks_to_backtest=104, config_path=config_path)
        
        final_report = {
            "run_mode": mode,
            "run_date": run_date,
            "validation_summary": {
                "total_monitored": len(val_report),
                "active_count": len(active_base_factors),
                "detailed_validation": val_report
            },
            "recommendation_summary": {
                "decision_status": "RETAIN_ORIGINAL_COMBINATION",
                "decision_message": "Quick 模式仅做基础超额回测验证。",
                "old_portfolio": {
                    "factors": active_base_factors,
                    "weights": base_weights,
                    "metrics": metrics
                }
            }
        }
        
    elif mode == "search":
        val_report, df_aligned = validate_factors(config_path)
        active_base_factors = [f for f, det in val_report.items() if not f.startswith("_") and det["status"] in ["VALID", "WARNING"]]
        search_report, new_factors = search_new_factors(df_aligned, active_base_factors, config_path)
        
        final_report = {
            "run_mode": mode,
            "run_date": run_date,
            "search_summary": {
                "searched_count": len(search_report),
                "new_factors_found": new_factors,
                "detailed_search": search_report
            }
        }
        
    elif mode == "full":
        print(f"\n⚙️  [Full Mode] 启动全历史自适应重组与 208 周平行超额测试...")
        rec_report, val_report, search_report = run_single_full_process(config_path, weeks_to_test=208)
        
        # 提取并打印多轨路由回测说明
        routed_info = rec_report.get("routed_portfolio", {})
        if routed_info:
            r_sum = routed_info.get("route_summary", {})
            r_met = routed_info.get("metrics", {})
            print("\n" + "=" * 60)
            print("🔀 状态权重路由合并回测表现说明")
            print("=" * 60)
            print(f"📊 回测时间跨度: {r_sum.get('total_weeks', 208)} 周")
            print(f"   - 使用 Range 核心模型周期 : {r_sum.get('range_weeks', 0)} 周")
            print(f"   - 使用 Bull 专轨模型周期   : {r_sum.get('bull_weeks', 0)} 周")
            print(f"   - 空仓规避 (Dark/Bear) 周期  : {r_sum.get('empty_weeks', 0)} 周")
            print("-" * 60)
            print(f"📈 路由合并绝对卡玛比率 : {r_met.get('calmar_ratio', 0.0):.4f}")
            print(f"📈 路由合并超额卡玛比率 : {r_met.get('excess_calmar_ratio', 0.0):.4f}")
            print(f"📈 路由合并超额年化收益 : {r_met.get('excess_annual_return', 0.0)*100:.2f}%")
            print(f"📈 路由合并超额最大回撤 : {r_met.get('excess_max_drawdown', 0.0)*100:.2f}%")
            print("=" * 60)
            
        if rec_report["recommendation_triggered"]:
            proposed_path = PATHS.models.regime_weights_proposed
            os.makedirs("models", exist_ok=True)
            
            with open(proposed_path, "wb") as f:
                pickle.dump({
                    "range_factors": rec_report["new_portfolio"]["factors"],
                    "range_weights": rec_report["new_portfolio"]["weights"]
                }, f)
                
            print(f"\n🔥 [Agent Highlight] 发现满足准入超额卡玛门槛（> 0.5）且更为出色的新因子自适应组合！")
            print(f"   - 新组合权重已暂存至: {proposed_path}")
            print(f"   - 请人工执行 `python3 agent/run_agent.py --approve` 批准权重正式生效！")
            
        final_report = {
            "run_mode": mode,
            "run_date": run_date,
            "validation_summary": {
                "detailed_validation": val_report
            },
            "search_summary": {
                "new_factors_found": list(search_report.keys()),
                "detailed_search": search_report
            },
            "recommendation_summary": rec_report
        }
        
    elif mode == "simulation":
        print(f"\n⚙️  [Simulation Mode] 启动实盘模拟验证 (回测最近 52 周)...")
        val_report, df_aligned = validate_factors(config_path)
        from agent.backtester import run_routed_portfolio_backtest
        routed_metrics, _, route_summary = run_routed_portfolio_backtest(df_aligned, weeks_to_backtest=52, config_path=config_path)
        
        print("\n" + "=" * 60)
        print("🎯 实盘模拟验证结果 (最近 52 周)")
        print("=" * 60)
        print(f"📊 模拟时间跨度: {route_summary.get('total_weeks', 52)} 周")
        print(f"   - 使用 Range 核心模型周期 : {route_summary.get('range_weeks', 0)} 周")
        print(f"   - 使用 Bull 专轨模型周期   : {route_summary.get('bull_weeks', 0)} 周")
        print(f"   - 空仓规避 (Dark/Bear) 周期  : {route_summary.get('empty_weeks', 0)} 周")
        print("-" * 60)
        print(f"📈 模拟绝对卡玛比率 : {routed_metrics.get('calmar_ratio', 0.0):.4f}")
        print(f"📈 模拟超额卡玛比率 : {routed_metrics.get('excess_calmar_ratio', 0.0):.4f}")
        print(f"📈 模拟年化绝对收益 : {routed_metrics.get('annualized_return', 0.0)*100:.2f}%")
        print(f"📈 模拟年化超额收益 : {routed_metrics.get('excess_annual_return', 0.0)*100:.2f}%")
        print(f"📈 模拟绝对最大回撤 : {routed_metrics.get('max_drawdown', 0.0)*100:.2f}%")
        print(f"📈 模拟超额最大回撤 : {routed_metrics.get('excess_max_drawdown', 0.0)*100:.2f}%")
        print("=" * 60)
        
        final_report = {
            "run_mode": mode,
            "run_date": run_date,
            "simulation_metrics": routed_metrics,
            "route_summary": route_summary
        }
        
    elif mode == "jack":
        print(f"\n⚙️  [Jack Mode] 启动游资/散户自适应模拟路由回测 (回测最近 52 周)...")
        val_report, df_aligned = validate_factors(config_path)

        # 数据完整性闸门阻断: 若 validate_factors 检测到违例且 block=true, 则跳过回测
        integrity = val_report.get("_data_integrity", {})
        if integrity and not integrity.get("passed", True):
            cfg_block = integrity.get("block_backtest_on_violation", True)
            if cfg_block:
                print("=" * 60)
                print("⛔ [Jack Mode] 回测因数据完整性违例已阻断，跳过本次回测")
                print(f"   原因: {integrity.get('summary', '未知')}")
                print("   请先运行 python3 scripts/repair_adj_factor.py 修复数据")
                print("=" * 60)
                final_report = {
                    "run_mode": mode, "run_date": run_date,
                    "blocked": True, "data_integrity": integrity
                }
                os.makedirs("agent", exist_ok=True)
                with open(report_name, "w", encoding="utf-8") as f:
                    json.dump(final_report, f, indent=4, ensure_ascii=False)
                print(f"\n✅ Agent 流程结束，阻断报告已导出: {report_name}")
                return

        from agent.backtester import run_jack_portfolio_backtest
        jack_metrics, route_summary = run_jack_portfolio_backtest(df_aligned, weeks_to_backtest=52, config_path=config_path)
        
        print("\n" + "=" * 60)
        print("🎯 游资/散户模式 (Jack Mode) 回测结果 (最近 52 周)")
        print("=" * 60)
        print(f"📊 回测时间跨度: {route_summary.get('total_weeks', 52)} 周")
        print(f"   - 使用 Range 抄底模型周期 : {route_summary.get('range_weeks', 0)} 周")
        print(f"   - 使用 Bull 追涨模型周期   : {route_summary.get('bull_weeks', 0)} 周")
        print(f"   - 空仓防守避险周期         : {route_summary.get('empty_weeks', 0)} 周")
        print("-" * 60)
        print(f"📈 模拟绝对卡玛比率 : {jack_metrics.get('calmar_ratio', 0.0):.4f}")
        print(f"📈 模拟超额卡玛比率 : {jack_metrics.get('excess_calmar_ratio', 0.0):.4f}")
        print(f"📈 模拟年化绝对收益 : {jack_metrics.get('annualized_return', 0.0)*100:.2f}%")
        print(f"📈 模拟年化超额收益 : {jack_metrics.get('excess_annual_return', 0.0)*100:.2f}%")
        print(f"📈 模拟绝对最大回撤 : {jack_metrics.get('max_drawdown', 0.0)*100:.2f}%")
        print(f"📈 模拟超额最大回撤 : {jack_metrics.get('excess_max_drawdown', 0.0)*100:.2f}%")
        print("=" * 60)
        
        final_report = {
            "run_mode": mode,
            "run_date": run_date,
            "simulation_metrics": jack_metrics,
            "route_summary": route_summary
        }
        
    # 导出 json 报告
    os.makedirs("agent", exist_ok=True)
    with open(report_name, "w", encoding="utf-8") as f:
        json.dump(final_report, f, indent=4, ensure_ascii=False)
    print(f"\n✅ Agent 流程结束，报告已成功导出为: {report_name}")

if __name__ == "__main__":
    main()
