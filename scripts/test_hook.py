"""Test the hook_block_js_clicks.py hook."""
import subprocess, json, sys

HOOK = r"C:\Python314\python.exe"
HOOK_SCRIPT = r"D:\cb-core\hooks\hook_block_js_clicks.py"

cases = [
    # Should BLOCK
    ("el.click()",            'document.querySelector("button").click()',                True),
    (".click(event)",         "els[i].click(event)",                                    True),
    ("dispatch+MouseEvent",   'el.dispatchEvent(new MouseEvent("click",{bubbles:true}))', True),
    ("dispatch+PointerEvent", 'el.dispatchEvent(new PointerEvent("pointerdown"))',       True),
    ("standalone MouseEvent", 'new MouseEvent("click", {bubbles:true})',                 True),
    ("standalone PointerEvent",'new PointerEvent("pointerdown")',                        True),
    ("form.submit",           "document.forms[0].submit()",                              True),
    # Should ALLOW
    ("safe getBCR",           "el.getBoundingClientRect()",                              False),
    ("safe innerText",        "document.body.innerText.slice(0,200)",                    False),
    ("safe href",             "window.location.href",                                    False),
    ("safe axtree read",      "document.querySelectorAll('[role=radio]').length",         False),
    ("react input event",     "el.dispatchEvent(new Event('input',{bubbles:true}))",     False),
    ("react change event",    "el.dispatchEvent(new Event('change',{bubbles:true}))",    False),
]

all_pass = True
for name, expr, should_block in cases:
    payload = json.dumps({"tool_input": {"expression": expr}}).encode("utf-8")
    proc = subprocess.run([HOOK, HOOK_SCRIPT], input=payload, capture_output=True)
    blocked = proc.returncode == 2
    ok = blocked == should_block
    status = "PASS" if ok else "FAIL"
    expected = "block" if should_block else "allow"
    got = "blocked" if blocked else f"allowed(exit={proc.returncode})"
    print(f"[{status}] {name:<24} expected={expected:<6} got={got}")
    if not ok:
        all_pass = False
        if proc.stderr:
            print(f"       stderr: {proc.stderr.decode(errors='replace')[:100]}")

print()
print("All tests passed!" if all_pass else "FAILURES DETECTED")
sys.exit(0 if all_pass else 1)
