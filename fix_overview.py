import re

file = '/Users/lyu/Documents/my_Stock/web/frontend/src/Overview.jsx'
with open(file, 'r') as f:
    lines = f.readlines()

def swap_colors(start, end):
    for i in range(start, end):
        line = lines[i]
        # swap #10b981 and #f43f5e
        line = line.replace('#10b981', '__TEMP_RED__')
        line = line.replace('#f43f5e', '#10b981')
        line = line.replace('__TEMP_RED__', '#f43f5e')
        # swap rgba(16,185,129 and rgba(244,63,94
        line = line.replace('16,185,129', '__TEMP_RGBA__')
        line = line.replace('244,63,94', '16,185,129')
        line = line.replace('__TEMP_RGBA__', '244,63,94')
        # swap 047857 and 9f1239 (dark gradients)
        line = line.replace('047857', '__TEMP_DARK__')
        line = line.replace('9f1239', '047857')
        line = line.replace('__TEMP_DARK__', '9f1239')
        lines[i] = line

# 赚钱效应 Pie Chart
swap_colors(117, 120)

# 上涨块 (approx lines 150-182)
swap_colors(150, 182)

# 下跌块 (approx lines 183-200)
swap_colors(183, 200)

# 筹码温度 过热/过冷 (approx 213-219)
swap_colors(213, 219)

# 净流入块 (approx 440-465)
swap_colors(440, 465)

# 净流出块 (approx 466-490)
swap_colors(466, 490)

with open(file, 'w') as f:
    f.writelines(lines)
