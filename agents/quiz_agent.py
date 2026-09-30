import config
import re
import random
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
    """Generate a quiz using Gemini, with a local fallback if Gemini is unavailable.

    Returns (questions, source) where source is 'ai' or 'local'.
    """
    if config.DEMO:
        return DEMO[:n], "demo"

    f = f"Focus mainly on these weak topics: {', '.join(focus)}." if focus else ""
    text_limit = min(len(text), 30000)
    p = f"""You are a Quiz Generator Agent. Using ONLY the notes below, write {n} conceptual multiple-choice questions
(test understanding, do not copy sentences). {f} Exactly 4 options, one correct.
Return ONLY JSON: {{"questions":[{{"question","options":[4 strings],"answer":0-3 index,"topic":short topic name,"explanation"}}]}}
NOTES:
{text[:text_limit]}"""

    # Try AI generation
    try:
        result = _valid(ask(p), n)
        return result, "ai"
    except Exception:
        pass

    # Local fallback: generate questions from the material
    local = _generate_local_quiz(text, n, focus)
    if local:
        return local, "local"

    # If even local generation fails, return demo with a note
    return DEMO[:n], "demo"


def _generate_local_quiz(text, n=5, focus=None):
    """Generate quiz questions locally from the material text.

    Creates fill-in-the-blank and true/false questions based on
    key sentences and terms found in the notes.
    """
    if not text or not text.strip():
        return None

    sentences = _extract_sentences(text)
    if len(sentences) < 3:
        return None

    questions = []
    used_sentences = set()

    # Strategy 1: Fill-in-the-blank from key sentences
    for sent in sentences:
        if len(questions) >= n:
            break
        if len(used_sentences) >= len(sentences):
            break
        if sent in used_sentences:
            continue

        # Find a key term to blank out
        words = sent.split()
        if len(words) < 6:
            continue

        # Pick a significant word (longer than 4 chars, not first/last)
        candidates = [(i, w) for i, w in enumerate(words)
                      if len(w) > 4 and i > 0 and i < len(words) - 1
                      and w.isalpha()]
        if not candidates:
            continue

        idx, word = random.choice(candidates)
        blanked = words.copy()
        blanked[idx] = "_____"
        question_text = " ".join(blanked)

        # Generate options: correct word + 3 distractors
        distractors = _find_distractors(word, sentences, used_sentences)
        if len(distractors) < 3:
            continue

        options = [word] + distractors[:3]
        random.shuffle(options)
        answer_idx = options.index(word)

        topic = _guess_topic(sent, focus)
        questions.append({
            "question": f"Fill in the blank: {question_text}",
            "options": options,
            "answer": answer_idx,
            "topic": topic,
            "explanation": f'The correct answer is "{word}".',
        })
        used_sentences.add(sent)

    # Strategy 2: True/False questions from statements
    for sent in sentences:
        if len(questions) >= n:
            break
        if sent in used_sentences:
            continue
        if len(sent.split()) < 5:
            continue

        # Create a true statement
        topic = _guess_topic(sent, focus)
        questions.append({
            "question": f"True or False: {sent}",
            "options": ["True", "False", "Cannot be determined", "None of the above"],
            "answer": 0,
            "topic": topic,
            "explanation": "This statement is directly from your study material.",
        })
        used_sentences.add(sent)

    return questions[:n] if questions else None


def _extract_sentences(text):
    """Extract meaningful sentences from text."""
    # Split on sentence boundaries
    sentences = re.split(r'[.!?]\s+', text)
    # Clean and filter
    result = []
    for s in sentences:
        s = s.strip().replace("\n", " ")
        # Keep sentences with 5-25 words
        words = s.split()
        if 5 <= len(words) <= 25 and re.search(r'[a-zA-Z]{3}', s):
            result.append(s)
    return result


def _find_distractors(word, sentences, used):
    """Find similar-looking words from other sentences as distractors."""
    distractors = []
    word_lower = word.lower()
    for sent in sentences:
        if sent in used:
            continue
        for w in sent.split():
            w_clean = w.strip(".,;:!?()[]").lower()
            if (len(w_clean) > 3 and
                    w_clean != word_lower and
                    w_clean not in distractors and
                    abs(len(w_clean) - len(word_lower)) <= 3):
                distractors.append(w.strip(".,;:!?()[]"))
                if len(distractors) >= 3:
                    return distractors
    return distractors


def _guess_topic(sentence, focus):
    """Guess the topic of a sentence based on focus keywords or content."""
    if focus:
        for f in focus:
            if f.lower() in sentence.lower():
                return f
    # Extract capitalized words as potential topic
    words = sentence.split()
    for w in words:
        w_clean = w.strip(".,;:!?()[]")
        if len(w_clean) > 3 and w_clean[0].isupper():
            return w_clean
    return "General"
