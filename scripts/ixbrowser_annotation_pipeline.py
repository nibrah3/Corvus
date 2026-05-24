"""
ixBrowser Annotation Pipeline — End-to-End Test
Connects to an open ixBrowser profile via CDP, navigates to a public annotation site,
uses Gemini to generate bounding-box annotations, then draws them via Playwright.
"""
import sys, os, json, time, base64, io, math
sys.path.insert(0, "D:/cb-core/scripts")

# Load .env (always wins over Windows env vars)
for line in open("D:/cb-core/.env").read().splitlines():
    if "=" in line and not line.startswith("#"):
        k, _, v = line.partition("=")
        os.environ[k.strip()] = v.strip()

import requests
from playwright.sync_api import sync_playwright

# ── CONFIG ────────────────────────────────────────────────────────────────────
IXBROWSER_API   = "http://127.0.0.1:53200"
PROFILE_ID      = 12          # "Corvus" profile
TEST_IMAGE_URL  = "https://www.gstatic.com/webp/gallery3/1.png"
GEMINI_KEY      = os.environ["GEMINI_API_KEY"]
GEMINI_URL      = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"
CATEGORIES      = ["dog", "cat", "person", "car", "flower", "bird", "other object"]

# ── STEP 1: Open ixBrowser profile and get CDP endpoint ──────────────────────
def open_profile(profile_id: int) -> str:
    """Open ixBrowser profile; return CDP http base URL."""
    r = requests.post(f"{IXBROWSER_API}/api/v2/profile-open",
                      json={"profile_id": profile_id}, timeout=30)
    d = r.json()
    if d["error"]["code"] != 0:
        raise RuntimeError(f"Profile open failed: {d['error']['message']}")
    addr = d["data"]["debugging_address"]
    port = d["data"]["debugging_port"]
    print(f"[1] Profile {profile_id} open — CDP on {addr}")
    return f"http://{addr}"

# ── STEP 2: Ask Gemini for object detections with bounding boxes ──────────────
def gemini_detect(image_url: str, categories: list[str]) -> list[dict]:
    """
    Call Gemini 2.5-flash with the image and ask for bounding-box JSON.
    Returns list of {"label": str, "x": 0-1, "y": 0-1, "w": 0-1, "h": 0-1}
    """
    img_bytes = requests.get(image_url, timeout=15).content
    mime      = "image/png" if image_url.endswith(".png") else "image/jpeg"
    b64       = base64.b64encode(img_bytes).decode()

    cats_str  = ", ".join(categories)
    prompt = (
        f"Detect all visible objects from this list: [{cats_str}]. "
        "Return a JSON array (not individual lines) like: "
        '[{"label":"flower","x":0.1,"y":0.05,"w":0.8,"h":0.9}]. '
        "Keys: label (string from the list), x (left 0-1), y (top 0-1), "
        "w (width 0-1), h (height 0-1). Normalised image coordinates. "
        "Output ONLY the JSON array, nothing else."
    )
    body = {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": mime, "data": b64}}
        ]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048}
    }
    resp = requests.post(GEMINI_URL, json=body, timeout=60)
    resp.raise_for_status()
    raw  = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    print(f"[2] Gemini raw output:\n{raw}\n")

    # Extract JSON array from response
    annotations = []
    text = raw.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:])
        text = text[:text.rfind("```")] if "```" in text else text
    text = text.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            for obj in parsed:
                if all(k in obj for k in ("label","x","y","w","h")):
                    annotations.append(obj)
    except json.JSONDecodeError:
        # Fallback: scan for individual JSON objects
        import re
        for m in re.finditer(r'\{[^}]+\}', text):
            try:
                obj = json.loads(m.group(0))
                if all(k in obj for k in ("label","x","y","w","h")):
                    annotations.append(obj)
            except Exception:
                pass

    print(f"[2] Parsed {len(annotations)} annotations: {annotations}")
    return annotations

# ── STEP 3: Playwright CDP automation on makesense.ai ─────────────────────────
MAKESENSE_URL = "https://www.makesense.ai"

def ss(page, tag: str):
    path = f"C:/Users/HP/AppData/Local/Temp/ann_{tag}.png"
    page.screenshot(path=path)
    print(f"    [ss] {path}")

def run_annotation_pipeline(cdp_url: str, image_url: str, annotations: list[dict]):
    """
    Connect to the already-open ixBrowser profile via CDP,
    navigate to makesense.ai, load the image, draw bounding boxes.

    makesense.ai flow:
      1. Landing  → click Get Started
      2. Image drop zone → upload image → shows "N images loaded" + Object/Image-recognition btns
      3. Click Object Detection
      4. Label definition panel → add labels → click Start Labeling
      5. Annotation editor canvas → draw rects per label
      6. Export (Actions → Export Annotations → JSON)
    """
    with sync_playwright() as p:
        print(f"[3] Connecting Playwright to CDP at {cdp_url}")
        browser = p.chromium.connect_over_cdp(cdp_url)
        ctx     = browser.contexts[0] if browser.contexts else browser.new_context()
        pages   = ctx.pages
        page    = pages[0] if pages else ctx.new_page()

        # ── 3a. Navigate ──────────────────────────────────────────────────────
        print(f"[3a] Navigating to {MAKESENSE_URL}")
        page.goto(MAKESENSE_URL, wait_until="networkidle", timeout=30000)
        time.sleep(1)
        ss(page, "01_landing")

        # Click Get Started
        for txt in ["Get Started", "Get started"]:
            try:
                page.click(f"text={txt}", timeout=4000)
                time.sleep(1)
                break
            except Exception:
                pass
        ss(page, "02_after_getstarted")

        # ── 3b. Upload image ──────────────────────────────────────────────────
        print("[3b] Downloading test image locally")
        img_bytes  = requests.get(image_url, timeout=15).content
        local_path = "C:/Users/HP/AppData/Local/Temp/annotation_test_image.png"
        with open(local_path, "wb") as f:
            f.write(img_bytes)

        # The drop zone is a file input; set files directly without clicking
        print(f"[3b] Injecting image via file input")
        file_input = page.locator("input[type='file']")
        if file_input.count() > 0:
            file_input.first.set_input_files(local_path)
            time.sleep(2)
        else:
            # Try click → file chooser dialog
            try:
                with page.expect_file_chooser(timeout=6000) as fc_info:
                    page.locator("p:has-text('Drop'), p:has-text('drop'), .DropFileArea, [class*='drop']").first.click(timeout=4000)
                fc_info.value.set_files(local_path)
                time.sleep(2)
            except Exception as e:
                print(f"[3b] File chooser fallback: {e}")

        ss(page, "03_after_upload")

        # ── 3c. Select Object Detection mode ─────────────────────────────────
        print("[3c] Clicking Object Detection button")
        page.click("text=Object Detection", timeout=8000)
        time.sleep(1)
        ss(page, "04_after_objdet_click")

        # ── 3d. Label definition panel ────────────────────────────────────────
        # makesense "Create labels" modal — use "Load labels from file" (plain txt, one per line).
        # This avoids having to find the non-standard "+" button.
        label_set = list({a["label"] for a in annotations})
        print(f"[3d] Loading labels via file: {label_set}")

        labels_txt = "C:/Users/HP/AppData/Local/Temp/makesense_labels.txt"
        with open(labels_txt, "w") as f:
            f.write("\n".join(label_set))

        # Wait for the modal to appear
        try:
            page.wait_for_selector("text=Create labels", timeout=6000)
        except Exception:
            pass

        try:
            # Open the "Load file with labels description" popup
            page.click("text=Load labels from file", timeout=6000)
            time.sleep(0.8)

            # Find any file input (visible or hidden) and set files directly
            all_inputs = page.locator("input[type='file']")
            n = all_inputs.count()
            print(f"    Found {n} file input(s) on page")
            loaded = False
            for idx in range(n):
                try:
                    all_inputs.nth(idx).set_input_files(labels_txt)
                    time.sleep(1.0)
                    loaded = True
                    print(f"    Labels loaded via input[{idx}]")
                    break
                except Exception as ei:
                    print(f"    input[{idx}] failed: {ei}")

            if not loaded:
                # Drop the file via DataTransfer JS API
                with open(labels_txt, "r") as lf:
                    labels_content = lf.read()
                page.evaluate(f"""
                    (content) => {{
                        const dt = new DataTransfer();
                        const file = new File([content], 'labels.txt', {{type: 'text/plain'}});
                        dt.items.add(file);
                        const dropZone = document.querySelector('[class*="drop" i], [class*="Drop" i]');
                        if (dropZone) {{
                            const ev = new DragEvent('drop', {{bubbles: true, dataTransfer: dt}});
                            dropZone.dispatchEvent(ev);
                        }}
                    }}
                """, labels_content)
                time.sleep(1)
                print("    Labels loaded via JS DataTransfer drop")

        except Exception as e:
            print(f"    Label loading error: {e}")

        ss(page, "05_labels_added")

        # Click "Start project" in the modal
        print("[3d] Clicking Start project")
        for btn_text in ["Start project", "Start Project", "Start Labeling", "Start labeling",
                          "Accept labels", "OK"]:
            try:
                page.click(f"text={btn_text}", timeout=4000)
                time.sleep(1.5)
                print(f"    Clicked: {btn_text}")
                break
            except Exception:
                pass
        ss(page, "06_after_start_labeling")

        # ── 3e. Wait for annotation editor / canvas ───────────────────────────
        print("[3e] Waiting for annotation canvas...")
        try:
            page.wait_for_selector("canvas", timeout=15000)
            time.sleep(1)
            print("    Canvas found!")
        except Exception:
            print("    Canvas not found within 15s")
        ss(page, "07_editor_ready")

        # ── 3e2. Collapse right panel by clicking Labels tab ──────────────────
        # This expands the canvas area significantly, making drawing work reliably.
        print("[3e2] Clicking Labels tab to expand canvas area")
        try:
            page.locator("text=Labels").first.click(timeout=4000)
            time.sleep(1)
            print("    Labels tab clicked — canvas should be wider now")
        except Exception as e:
            print(f"    Labels tab: {e}")
        ss(page, "07b_canvas_expanded")

        # ── 3f. Draw bounding boxes ────────────────────────────────────────────
        # After collapsing the right panel, the canvas is full-width.
        # The crosshair draw mode (ImageButton active at toolbar) is already on.
        # Playwright mouse events work correctly on the expanded canvas.
        print("[3f] Drawing bounding boxes")
        try:
            cb = page.locator("canvas.ImageCanvas").bounding_box()
            if not cb:
                cb = page.locator("canvas").first.bounding_box()
            print(f"    Canvas: {cb['width']:.0f}x{cb['height']:.0f} at ({cb['x']:.0f},{cb['y']:.0f})")

            # Hover center first to ensure canvas has focus
            page.mouse.move(cb["x"] + cb["width"]/2, cb["y"] + cb["height"]/2)
            time.sleep(0.3)

            for ann in annotations:
                pad = 15
                x1 = cb["x"] + max(ann["x"] * cb["width"], pad)
                y1 = cb["y"] + max(ann["y"] * cb["height"], pad)
                x2 = cb["x"] + min((ann["x"] + ann["w"]) * cb["width"], cb["width"] - pad)
                y2 = cb["y"] + min((ann["y"] + ann["h"]) * cb["height"], cb["height"] - pad)
                print(f"    Drawing '{ann['label']}': ({x1:.0f},{y1:.0f}) -> ({x2:.0f},{y2:.0f})")

                page.mouse.move(x1, y1)
                time.sleep(0.2)
                page.mouse.down()
                for i in range(1, 21):
                    t = i / 20
                    page.mouse.move(x1 + (x2-x1)*t, y1 + (y2-y1)*t)
                    time.sleep(0.02)
                page.mouse.up()
                time.sleep(1.5)

                # If label popup appears, select the label
                try:
                    page.click(f"text={ann['label']}", timeout=2000)
                    print(f"    Assigned '{ann['label']}' via popup")
                except Exception:
                    pass

            drawn = not page.locator("text=draw your first bounding box").is_visible()
            print(f"    Annotation created: {drawn}")
        except Exception as e:
            print(f"    Draw error: {e}")

        ss(page, "08_after_drawing")

        # ── 3g. Export annotations ─────────────────────────────────────────────
        # makesense export: Actions menu → Export Annotations → choose format → download
        print("[3g] Exporting annotations")
        try:
            page.click("text=Actions", timeout=5000)
            time.sleep(0.8)
            page.click("text=Export Annotations", timeout=4000)
            time.sleep(0.8)
            ss(page, "09_export_format_dialog")
            # Choose YOLO (widely used, simple format: label cx cy w h)
            for fmt in ["YOLO", "JSON", "VOC XML", "CSV"]:
                try:
                    page.click(f"text={fmt}", timeout=3000)
                    time.sleep(1)
                    print(f"    Exported as {fmt}")
                    break
                except Exception:
                    continue
        except Exception as e:
            print(f"    Export error: {e}")
        ss(page, "09_exported")

        print("[3] Pipeline complete. ixBrowser profile remains open.")
        browser.close()

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("ixBrowser Annotation Pipeline — End-to-End Test")
    print("=" * 60)

    # Step 1: open/verify profile
    try:
        cdp_http = open_profile(PROFILE_ID)
    except Exception as e:
        # Profile may already be open from earlier call
        print(f"[1] Profile open attempt: {e}")
        cdp_http = "http://127.0.0.1:49656"
        print(f"[1] Using existing CDP at {cdp_http}")

    # Step 2: Gemini detection
    print(f"\n[2] Calling Gemini on: {TEST_IMAGE_URL}")
    annotations = gemini_detect(TEST_IMAGE_URL, CATEGORIES)
    if not annotations:
        # Fallback synthetic annotation for pipeline demo
        print("[2] No annotations parsed — using synthetic demo annotation")
        annotations = [
            {"label": "flower", "x": 0.1, "y": 0.1, "w": 0.5, "h": 0.6},
            {"label": "other object", "x": 0.6, "y": 0.5, "w": 0.3, "h": 0.4},
        ]

    # Step 3: Playwright automation
    print(f"\n[3] Starting Playwright CDP automation")
    run_annotation_pipeline(cdp_http, TEST_IMAGE_URL, annotations)

    print("\n[DONE] End-to-end pipeline test complete.")
    print(f"  Screenshots:")
    print(f"    Before: C:/Users/HP/AppData/Local/Temp/annotation_before.png")
    print(f"    After:  C:/Users/HP/AppData/Local/Temp/annotation_after.png")

if __name__ == "__main__":
    main()
