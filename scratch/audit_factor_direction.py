# -*- coding: utf-8 -*-
"""
audit_factor_direction.py — 因子方向元数据审计（P0-1 证据脚本）
=================================================================
对 registry 中全部因子计算三段窗口的 RankIC(factor, fwd_ret_5d)：
  - full   : 全样本 (2020-01 ~ 最新)
  - base   : 基准期 (≤ 20241231，与 agent/validator 口径一致)
  - recent : 近期   (≥ 20250101)
判定：
  effective_ic = ic_mean * direction   （按注册方向做多时的实际 IC）
  FLIP  : effective_ic < 0 且 |icir| ≥ 0.30（factor_lib 配置的 icir_min）
  WEAK  : |ic_mean| < 0.02 且 |icir| < 0.15（无统计证据，方向不动）
  KEEP  : 其余
只读数据库，不写任何业务表。
"""
import os, sys, time, gc, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from factor_lib.loader import FactorDataLoader
from factor_lib.ic_engine import ICEngine
from factor_lib.registry import FACTOR_REGISTRY, get_classic_factor_names, get_evo_factor_names

ICIR_MIN = 0.30
WEAK_IC, WEAK_ICIR = 0.02, 0.15

def ic_on_window(df, factor, eng, lo=None, hi=None):
    d = df
    if lo: d = d[d["trade_date"] >= lo]
    if hi: d = d[d["trade_date"] <= hi]
    s = eng.compute_ic_series(d, factor, "rank", "fwd_ret_5d")
    r = eng.compute_ic_summary(s)
    return r["n_days"], r["ic_mean"], r["icir"]

def main():
    loader = FactorDataLoader()
    eng = ICEngine()
    rows = []
    groups = [("classic", get_classic_factor_names()), ("evo", get_evo_factor_names())]
    all_names = [(t, f) for t, names in groups for f in names]
    for table_tag, f in all_names:
        t0 = time.time()
        try:
            df = loader.load_factor_values([f])
            df = loader.compute_forward_returns(df, [5])
            if f not in df.columns:
                rows.append(dict(factor=f, note="NO COLUMN")); continue
            n_full, ic_full, ir_full = ic_on_window(df, f, eng)
            n_base, ic_base, ir_base = ic_on_window(df, f, eng, hi="20241231")
            n_rec,  ic_rec,  ir_rec  = ic_on_window(df, f, eng, lo="20250101")
            meta = FACTOR_REGISTRY[f]
            eff_full = ic_full * meta.direction
            if n_full < 50:
                verdict = "INSUFFICIENT"
            elif abs(ic_full) < WEAK_IC and abs(ir_full) < WEAK_ICIR:
                verdict = "WEAK"
            elif eff_full < 0 and abs(ir_full) >= ICIR_MIN:
                verdict = "FLIP"
            else:
                verdict = "KEEP"
            rows.append(dict(
                factor=f, cat=meta.category, dir=meta.direction, table=table_tag,
                ic_full=round(ic_full, 4), ir_full=round(ir_full, 3),
                ic_base=round(ic_base, 4), ir_base=round(ir_base, 3),
                ic_rec=round(ic_rec, 4), ir_rec=round(ir_rec, 3),
                verdict=verdict,
            ))
            print(f"  {f:28s} ic={ic_full:+.4f} ir={ir_full:+.3f} -> {verdict} ({time.time()-t0:.0f}s)", flush=True)
            del df; gc.collect()
        except Exception as e:
            print(f"  {f}: ERROR {e}")
            traceback.print_exc()

    rdf = pd.DataFrame(rows)
    pd.set_option("display.width", 200); pd.set_option("display.max_rows", 60)
    print("\n=== FLIP candidates ===")
    print(rdf[rdf.verdict == "FLIP"].to_string(index=False))
    print("\n=== WEAK (no evidence) ===")
    print(rdf[rdf.verdict == "WEAK"][["factor","cat","dir","ic_full","ir_full","ic_rec","ir_rec"]].to_string(index=False))
    print("\n=== KEEP ===")
    print(rdf[rdf.verdict == "KEEP"][["factor","cat","dir","ic_full","ir_full","ic_base","ir_base","ic_rec","ir_rec"]].to_string(index=False))
    print("\n=== other ===")
    print(rdf[~rdf.verdict.isin(["FLIP","WEAK","KEEP"])].to_string(index=False))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit_direction_result.csv")
    rdf.to_csv(out, index=False)
    print(f"\nsaved: {out}")

if __name__ == "__main__":
    main()
