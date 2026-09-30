from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from agents import summarizer_agent, quiz_agent, weak_topic_agent
class State(TypedDict, total=False):   # shared state passed between agents
    stage: str; text: str; n: int; focus: list; style: str
    summary: dict; questions: list
    topic_rows: list; analysis: list; recommendations: list
def summarize(s): return {"summary": summarizer_agent.run(s["text"], s.get("style", "detailed"))}
def make_quiz(s):
    # Use original text for quiz generation (not the summary) for better question quality
    return {"questions": quiz_agent.generate(s["text"], s.get("n", 5), s.get("focus"))}
def track(s):
    a = weak_topic_agent.analyze(s["topic_rows"])
    return {"analysis": a, "recommendations": weak_topic_agent.recommend(a)}
def route(s): return {"summary": "summarize", "full": "summarize", "quiz": "quiz", "evaluate": "track"}[s["stage"]]
def after_summary(s): return "quiz" if s["stage"] == "full" else "end"
b = StateGraph(State)
b.add_node("summarize", summarize); b.add_node("quiz", make_quiz); b.add_node("track", track)
b.add_conditional_edges(START, route, {"summarize": "summarize", "quiz": "quiz", "track": "track"})
b.add_conditional_edges("summarize", after_summary, {"quiz": "quiz", "end": END})
b.add_edge("quiz", END); b.add_edge("track", END)
graph = b.compile()
