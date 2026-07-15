import re

def swap(file, patterns):
    with open(file, 'r') as f:
        content = f.read()
    
    for p_find, p_replace in patterns:
        content = re.sub(p_find, p_replace, content)
        
    with open(file, 'w') as f:
        f.write(content)

# Dashboard.jsx
dashboard = '/Users/lyu/Documents/my_Stock/web/frontend/src/Dashboard.jsx'
swap(dashboard, [
    (r'totalProfit >= 0 \? \'text-emerald-400\' : \'text-rose-400\'', 
     r'totalProfit >= 0 ? \'text-rose-400\' : \'text-emerald-400\''),
    (r'avgChange >= 0 \? \'text-emerald-400\' : \'text-rose-400\'',
     r'avgChange >= 0 ? \'text-rose-400\' : \'text-emerald-400\''),
    (r'benchmark_return >= 0 \? \'text-emerald-400\' : \'text-rose-400\'',
     r'benchmark_return >= 0 ? \'text-rose-400\' : \'text-emerald-400\'')
])

# JackMode.jsx
jackmode = '/Users/lyu/Documents/my_Stock/web/frontend/src/JackMode.jsx'
swap(jackmode, [
    (r'item\.status === \'up\' \? \'bg-emerald-500\' : \'bg-rose-500\'',
     r'item.status === \'up\' ? \'bg-rose-500\' : \'bg-emerald-500\''),
    (r'item\.status === \'up\' \? \'text-emerald-400\' : \'text-rose-400\'',
     r'item.status === \'up\' ? \'text-rose-400\' : \'text-emerald-400\'')
])
