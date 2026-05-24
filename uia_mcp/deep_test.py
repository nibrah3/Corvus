import sys
sys.path.insert(0, 'D:/cb-core')
from uia_mcp.server import find_elements, focused_window

win = focused_window()
print(f"Window: {win.get('title','?')} | {win.get('process_name','?')}")

r = find_elements(interactive_only=False, max_depth=12)
if 'error' in r:
    print('ERROR:', r['error'])
else:
    print(f"Total elements at depth 12: {r['element_count']}")
    for e in r['elements'][:25]:
        rect = e.get('rect', {})
        print(f"  [{e['id']:3}] {e['type']:12} cx={rect.get('cx','?'):5} cy={rect.get('cy','?'):5}  {repr(e['name'][:45])}")
    if r['element_count'] > 25:
        print(f"  ... +{r['element_count']-25} more")
