import config
from agents.llm import ask
_D = [("What does a model learn from in supervised learning?", ["Labeled examples", "Only rewards", "Random noise", "Nothing"], 0, "Supervised Learning", "It maps inputs to known outputs."),
 ("Which situation signals overfitting?", ["High train, low test accuracy", "Low train accuracy", "Equal accuracies", "No data"], 0, "Overfitting", "Memorising training data hurts generalisation."),
 ("Which helps reduce overfitting?", ["Regularisation", "Fewer samples", "Ignoring test set", "Bigger learning rate"], 0, "Overfitting", "Regularisation penalises complexity."),
 ("Gradient descent updates weights by moving...", ["Against the gradient", "With the gradient", "Randomly", "Never"], 0, "Gradient Descent", "It minimises loss."),
 ("A too-large learning rate may cause...", ["Divergence", "Perfect fit", "Less compute", "Labels"], 0, "Gradient Descent", "Steps overshoot the minimum.")]
DEMO = [{"question": a, "options": b, "answer": c, "topic": d, "explanation": e + " (DEMO)"} for a, b, c, d, e in _D]
def _valid(d, n):
    out = []
    for q in d.get("questions", []):
        o = q.get("options")
        if q.get("question") and isinstance(o, list) and len(o) == 4 and q.get("answer") in (0, 1, 2, 3):
            out.append({"question": str(q["question"]), "options": [str(x) for x in o], "answer": q["answer"],
                        "explanation": str(q.get("explanation", "")), "topic": str(q.get("topic", "General"))})
    if len(out) < max(1, n // 2): raise ValueError("too few valid questions")
    return out[:n]
def generate(text, n=5, focus=None):
    if config.DEMO: return DEMO[:n]
    f = f"Focus mainly on these weak topics: {', '.join(focus)}." if focus else ""
    # Use more text for better question generation, but stay within limits
    text_limit = min(len(text), 30000)
    p = f"""You are a Quiz Generator Agent. Using ONLY the notes below, write {n} conceptual multiple-choice questions
(test understanding, do not copy sentences). {f} Exactly 4 options, one correct.
Return ONLY JSON: {{"questions":[{{"question","options":[4 strings],"answer":0-3 index,"topic":short topic name,"explanation"}}]}}
NOTES:
{text[:text_limit]}"""
    err = None
    for _ in range(2):  # controlled retry on malformed output
        try: return _valid(ask(p), n)
        except Exception as e: err = e
    raise RuntimeError(f"Quiz generation failed: {err}")
