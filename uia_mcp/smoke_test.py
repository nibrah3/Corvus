"""UIA MCP smoke test — dumps interactive elements from the foreground window."""
import sys
sys.path.insert(0, 'D:/cb-core')

from uia_mcp.server import find_elements, focused_window

print("Foreground window:")
win = focused_window()
for k, v in win.items():
    if k != "rect":
        print(f"  {k}: {v}")
if "rect" in win:
    r = win["rect"]
    print(f"  rect: {r['left']},{r['top']} → {r['right']},{r['bottom']}  ({r['width']}×{r['height']}px)")

print("\nInteractive elements:")
result = find_elements(interactive_only=True)
if "error" in result:
    print(f"  ERROR: {result['error']}")
else:
    print(f"  Window: {result['window']}")
    print(f"  Found:  {result['element_count']} interactive elements\n")
    for el in result["elements"][:20]:   # show first 20
        r = el.get("rect", {})
        print(f"  [{el['id']:3d}] {el['type']:12s}  cx={r.get('cx','?'):4}  cy={r.get('cy','?'):4}  \"{el['name'][:50]}\"")
    if result["element_count"] > 20:
        print(f"  ... and {result['element_count']-20} more")
