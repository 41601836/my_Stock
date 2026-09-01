# -*- coding: utf-8 -*-
"""诊断 Jack 游资策略模拟页数据: backtest_results_jack.csv"""
import pandas as pd

df = pd.read_csv('backtest_results_jack.csv')
print('rows:', len(df), '| range:', df.trade_date.min(), '~', df.trade_date.max())

eq_p, eq_b, eq_e = [1.0], [1.0], [1.0]
for _, r in df.iterrows():
    eq_p.append(eq_p[-1] * (1 + r.portfolio_return))
    eq_b.append(eq_b[-1] * (1 + r.benchmark_return))
    eq_e.append(eq_e[-1] * (1 + r.excess_return))
print('final NAV  P=%.4f B=%.4f E=%.4f' % (eq_p[-1], eq_b[-1], eq_e[-1]))

k = len(df)
ann = lambda eq: eq[-1] ** (52 / k) - 1
mdd = lambda eq: ((pd.Series(eq) - pd.Series(eq).cummax()) / pd.Series(eq).cummax()).min()
print('P ann=%.2f%% mdd=%.2f%% calmar=%.2f' % (ann(eq_p)*100, mdd(eq_p)*100, ann(eq_p)/abs(mdd(eq_p))))
print('E ann=%.2f%% mdd=%.2f%% calmar=%.2f' % (ann(eq_e)*100, mdd(eq_e)*100, ann(eq_e)/abs(mdd(eq_e))))
print('win: P %.1f%% / E %.1f%%' % ((df.portfolio_return > 0).mean()*100, (df.excess_return > 0).mean()*100))
print('regime counts:', df.regime.value_counts().to_dict())
print('mean weekly cost drag check: P_mean=%.4f' % df.portfolio_return.mean())

print('\n--- tail 8 weeks ---')
print(df.tail(8).to_string(index=False))

print('\n--- worst 6 excess weeks ---')
print(df.nsmallest(6, 'excess_return')[['trade_date','portfolio_return','benchmark_return','excess_return','regime','model_used']].to_string(index=False))

print('\n--- worst 5 portfolio weeks ---')
print(df.nsmallest(5, 'portfolio_return')[['trade_date','portfolio_return','benchmark_return','regime','model_used']].to_string(index=False))

print('\n--- best 3 benchmark weeks ---')
print(df.nlargest(3, 'benchmark_return')[['trade_date','portfolio_return','benchmark_return','regime','model_used']].to_string(index=False))

print('\nby-model mean ret:')
print(df.groupby('model_used')[['portfolio_return','benchmark_return']].agg(['mean','count']).round(4).to_string())

# 风控止损触发统计
stop = df[df.model_used.str.contains('Risk_Stop')]
print('\nRisk_Stop weeks:', len(stop))
if len(stop):
    print(stop[['trade_date','benchmark_return','regime','model_used']].to_string(index=False))
