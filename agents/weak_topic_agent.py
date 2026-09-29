import config
from agents.llm import ask
MIN_ANSWERS = 3  # need accumulated evidence before labelling a topic
def analyze(rows):
    out = []
    for r in rows:
        t, c = r["total"], r["correct"] or 0
        acc = c / t
        s = "Not enough data" if t < MIN_ANSWERS else "Strong" if acc >= .75 else "Improving" if acc >= .5 else "Needs Revision"
        out.append({"topic": r["topic"], "total": t, "correct": c, "accuracy": round(acc * 100), "status": s})
    return out
def recommend(analysis):
    weak = [a["topic"] for a in analysis if a["status"] == "Needs Revision"]
    if not weak:
        return [f"No confirmed weak topics yet. Topics need {MIN_ANSWERS}+ answers before they are classified; keep practising."]
    rule = [f"Revisit '{t}' in your summary, then take a targeted quiz." for t in weak]
    if config.DEMO: return rule
    try:
        r = ask(f'You are a study coach. Weak topics: {weak}. Return ONLY JSON {{"recommendations":[3-5 short, encouraging revision tips]}}')
        return r.get("recommendations") or rule
    except Exception:
        return rule
