"""Test page context extraction."""
import sys, os, time
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))
with open(os.path.join(os.path.dirname(__file__), "..", ".env")) as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from careerbridge.ixbrowser_connector import ix_open_profile
from careerbridge.cdp_executor import CDPExecutor

cdp_url = ix_open_profile(12)
cdp = CDPExecutor()
cdp.connect_ws(cdp_url)
cdp.navigate("https://www.16personalities.com/free-personality-test")
time.sleep(4)

ctx = cdp.eval_js(
    "Array.from(document.querySelectorAll("
    "   'h1,h2,h3,p,label,fieldset legend,"
    "    [class*=\"question\"],[class*=\"statement\"],[class*=\"prompt\"]'"
    ")).map(e=>e.innerText.trim()).filter(t=>t.length>4&&t.length<300)"
    ".slice(0,15).join('\\n')"
)
print("Context:", repr(ctx[:800]) if ctx else "EMPTY")

# Also test what the actual assessment_pipeline method returns
from careerbridge.assessment_pipeline import AssessmentPipeline, AssessmentConfig

class FakeProfile:
    name = "Test"
    email = "test@test.com"
    class big_five:
        openness = 0.5
        conscientiousness = 0.5
        extraversion = 0.5
        agreeableness = 0.5
        neuroticism = 0.5

cfg = AssessmentConfig(cdp_url=cdp_url, url="https://www.16personalities.com/free-personality-test",
                       profile=FakeProfile(), human_gate=False)
pipeline = AssessmentPipeline(cfg)
pipeline._cdp = cdp
ctx2 = pipeline._get_page_context()
print("\nPipeline context:", repr(ctx2[:800]) if ctx2 else "EMPTY")
cdp.disconnect()
