"""Study Planner Agent (the fourth agent) — Hybrid AI + Rule-Based Engine.

The planner works in two modes:
  MODE A (AI-enhanced):  Gemini personalizes the plan when available.
  MODE B (Smart Planning): A deterministic rule-based engine always works,
                         even when Gemini is completely unavailable.

Gemini is an enhancement, NEVER a critical dependency. The rule-based engine
uses real user data: topics, quiz performance, weak topics, exam dates, and
study preferences to build a genuine study schedule.
"""
import logging
import re
from datetime import date, timedelta

import config
from agents.llm import ask

log = logging.getLogger(__name__)

MAX_TEXT = 12000
MAX_TOPICS = 25
ACTIVITIES = ("read", "revise", "practice", "quiz")
PRIORITIES = ("high", "medium", "low")

# ── Priority time allocations (minutes) ────────────────────────────────
# Each topic gets: initial study + revision + optional practice
PRIORITY_ALLOCATION = {
    "high":   {"initial": 50, "revision": 30, "practice": 20},
    "medium": {"initial": 35, "revision": 20, "practice": 10},
    "low":    {"initial": 25, "revision": 15, "practice": 0},
}

# Accuracy thresholds for priority calculation
ACCURACY_HIGH = 0.50    # below 50% → HIGH priority
ACCURACY_MEDIUM = 0.75  # 50-75% → MEDIUM, above 75% → LOW


# ══════════════════════════════════════════════════════════════════════
# TOPIC EXTRACTION
# ══════════════════════════════════════════════════════════════════════

def extract_topics_with_ai(text):
    """Try to extract topics using Gemini. Returns list or None on failure."""
    if config.DEMO:
        return None
    try:
        p = f"""You are a Study Planner Agent. From the study material below, extract the main topics a student must learn, in the order they should be studied.
Return ONLY JSON: {{"topics": ["short topic name", ...]}}
Use 4-12 topics, each 2-6 words. Do NOT invent topics that are not in the material.
MATERIAL:
{text[:MAX_TEXT]}"""
        r = ask(p)
        topics = [str(t).strip() for t in r.get("topics", []) if str(t).strip()]
        return topics[:MAX_TOPICS] if topics else None
    except Exception as e:
        log.warning("AI topic extraction failed: %s", e)
        return None


def extract_topics_locally(text):
    """Extract topics from text using rule-based patterns.

    Inspects the actual content for:
    - Markdown headings (# ## ###)
    - Numbered sections (1. 2. 3. or 1) 2) 3))
    - Bullet-point section titles
    - Lines with title-like formatting (short, capitalized, no ending period)
    - Common academic heading patterns
    """
    if not text or not text.strip():
        return []

    topics = []
    lines = text.split("\n")
    seen = set()

    # Pattern 1: Markdown headings
    for line in lines:
        m = re.match(r"^#{1,4}\s+(.+)", line.strip())
        if m:
            topic = _clean_topic(m.group(1))
            if topic and topic.lower() not in seen:
                topics.append(topic)
                seen.add(topic.lower())

    # Pattern 2: Numbered sections (e.g., "1. Topic" or "1) Topic" or "1.1 Topic")
    if len(topics) < 3:
        for line in lines:
            m = re.match(r"^\d+[\.\)]\s+(.+)", line.strip())
            if m:
                topic = _clean_topic(m.group(1))
                if topic and topic.lower() not in seen:
                    topics.append(topic)
                    seen.add(topic.lower())

    # Pattern 3: Bullet-point section titles (short lines starting with •, -, *)
    if len(topics) < 3:
        for line in lines:
            m = re.match(r"^[\•\-\*]\s+(.{3,60})", line.strip())
            if m:
                candidate = m.group(1).strip()
                # Title-like: no ending period, not too long, has letters
                if (not candidate.endswith(".") and
                        len(candidate) < 60 and
                        re.search(r"[a-zA-Z]", candidate)):
                    topic = _clean_topic(candidate)
                    if topic and topic.lower() not in seen:
                        topics.append(topic)
                        seen.add(topic.lower())

    # Pattern 4: Common academic heading patterns
    if len(topics) < 3:
        heading_patterns = [
            r"^(Chapter|Unit|Module|Section|Part|Topic|Lesson)\s+\d+[\s\:\-]+(.{3,50})",
            r"^(Introduction|Overview|Fundamentals?|Basics?|Advanced?|Applications?|Summary|Conclusion|Review)\s*[:\-]?\s*(.{0,50})",
        ]
        for line in lines:
            for pat in heading_patterns:
                m = re.match(pat, line.strip(), re.IGNORECASE)
                if m:
                    topic = _clean_topic(m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1))
                    if topic and topic.lower() not in seen:
                        topics.append(topic)
                        seen.add(topic.lower())

    # Pattern 5: Short title-like lines (fallback)
    if len(topics) < 2:
        for line in lines:
            stripped = line.strip()
            if (3 < len(stripped) < 50 and
                    not stripped.endswith((".", ",", ";", ":")) and
                    not stripped.startswith(("#", "•", "-", "*", "1", "2", "3", "4", "5", "6", "7", "8", "9")) and
                    re.search(r"[a-zA-Z]{3}", stripped)):
                topic = _clean_topic(stripped)
                if topic and topic.lower() not in seen:
                    topics.append(topic)
                    seen.add(topic.lower())
                    if len(topics) >= 5:
                        break

    return topics[:MAX_TOPICS]


def _clean_topic(text):
    """Clean a topic string: remove markdown, extra whitespace, numbering."""
    text = text.strip()
    text = re.sub(r"^#+\s*", "", text)
    text = re.sub(r"^\d+[\.\)]\s*", "", text)
    text = re.sub(r"\*\*", "", text)
    text = re.sub(r"\*", "", text)
    text = re.sub(r"^[\•\-\*]\s*", "", text)
    text = text.strip(" \t\n\r:-")
    if len(text) < 2 or len(text) > 80:
        return None
    return text


def parse_user_topics(raw):
    """Parse user-provided topic text into individual topics.

    Supports:
    - Comma-separated: "Arrays, Linked Lists, Trees"
    - Newline-separated: "Arrays\nLinked Lists\nTrees"
    - Semicolon-separated: "Arrays; Linked Lists; Trees"
    - Numbered lists: "1. Arrays\n2. Linked Lists"
    - Bullet points: "- Arrays\n- Linked Lists"
    - List input: ["Arrays", "Linked Lists", "Trees"]

    Also normalizes common variations:
    - "Array" → "Arrays"
    - "Linked list" → "Linked Lists"
    - "Two pointer" → "Two Pointers"
    """
    # Handle list input (from JSON request)
    if isinstance(raw, list):
        parts = [str(item) for item in raw if str(item).strip()]
    elif not raw or not str(raw).strip():
        return []
    else:
        # Split on commas, semicolons, or newlines
        parts = re.split(r"[,;\n]+", str(raw))

    topics = []
    seen = set()
    for part in parts:
        # Remove leading bullets, numbers, whitespace
        cleaned = re.sub(r"^[\s\-\*\•\d\.\)\]]+", "", part).strip()
        # Remove trailing punctuation
        cleaned = cleaned.strip(" \t\n\r:-")
        if not cleaned or len(cleaned) < 2:
            continue

        # Normalize common variations
        cleaned = _normalize_topic(cleaned)

        if cleaned and cleaned.lower() not in seen:
            topics.append(cleaned)
            seen.add(cleaned.lower())

    return topics[:MAX_TOPICS]


def _normalize_topic(topic):
    """Normalize common topic name variations."""
    topic = topic.strip()
    # Common normalizations
    normalizations = {
        "array": "Arrays",
        "arrays": "Arrays",
        "linked list": "Linked Lists",
        "linked lists": "Linked Lists",
        "linkedlist": "Linked Lists",
        "two pointer": "Two Pointers",
        "two pointers": "Two Pointers",
        "sliding window": "Sliding Window",
        "sliding windows": "Sliding Window",
        "tree": "Trees",
        "trees": "Trees",
        "graph": "Graphs",
        "graphs": "Graphs",
        "stack": "Stacks",
        "stacks": "Stacks",
        "queue": "Queues",
        "queues": "Queues",
        "hash": "Hashing",
        "hashing": "Hashing",
        "dynamic programming": "Dynamic Programming",
        "dp": "Dynamic Programming",
        "recursion": "Recursion",
        "sorting": "Sorting",
        "searching": "Searching",
        "binary search": "Binary Search",
        "greedy": "Greedy Algorithms",
        "backtracking": "Backtracking",
        "heap": "Heaps",
        "heaps": "Heaps",
        "trie": "Tries",
        "tries": "Tries",
    }
    return normalizations.get(topic.lower(), topic)


def get_topics(text, user_topics=None):
    """Get topics from user input, AI extraction, or local extraction.

    Priority order:
    1. User-provided topics (from syllabus textarea)
    2. AI extraction (if Gemini available)
    3. Local rule-based extraction (always works)

    Returns (topics, source) where source is 'user', 'ai', or 'local'.
    """
    # 1. User-provided topics (parse comma/semicolon/newline separated)
    if user_topics:
        cleaned = parse_user_topics(user_topics)
        if cleaned:
            return cleaned, "user"

    if not text or not text.strip():
        return [], "none"

    # 2. Try AI extraction
    ai_topics = extract_topics_with_ai(text)
    if ai_topics:
        return ai_topics, "ai"

    # 3. Local extraction (always works)
    local_topics = extract_topics_locally(text)
    if local_topics:
        return local_topics, "local"

    return [], "none"


# ══════════════════════════════════════════════════════════════════════
# WEAK TOPICS & PRIORITIES
# ══════════════════════════════════════════════════════════════════════

def get_weak_topics(performance):
    """Extract weak topics from quiz performance data.

    Returns list of dicts with topic, accuracy, and status.
    """
    if not performance:
        return []
    return [
        {"topic": p["topic"], "accuracy": p.get("accuracy", 0), "status": p["status"]}
        for p in performance
        if p.get("status") in ("Needs Revision", "Improving")
    ]


def calculate_topic_priorities(topics, performance):
    """Calculate priority for each topic based on quiz performance.

    Returns dict mapping topic name → priority level.
    """
    priorities = {}
    perf_map = {}
    if performance:
        for p in performance:
            perf_map[p["topic"].lower()] = p

    for topic in topics:
        topic_lower = topic.lower()
        if topic_lower in perf_map:
            p = perf_map[topic_lower]
            acc = p.get("accuracy", 0)
            status = p.get("status", "")
            if status == "Needs Revision" or acc < ACCURACY_HIGH * 100:
                priorities[topic] = "high"
            elif status == "Improving" or acc < ACCURACY_MEDIUM * 100:
                priorities[topic] = "medium"
            else:
                priorities[topic] = "low"
        else:
            # No quiz data → medium priority (needs assessment)
            priorities[topic] = "medium"

    return priorities


# ══════════════════════════════════════════════════════════════════════
# RULE-BASED PLANNING ENGINE (always works, no API needed)
# ══════════════════════════════════════════════════════════════════════

def generate_rule_based_plan(topics, priorities, weak_topics, daily_minutes,
                             days_available, start_date, exam_date,
                             preferred_study_time="flexible"):
    """Generate a study plan using deterministic rules.

    This is a REAL planning engine that:
    - Allocates more time to high-priority/weak topics
    - Reserves time for revision and practice
    - Respects daily time budgets
    - Schedules a final review before the exam
    - Warns when topics can't fit

    Returns {"days": [...], "warnings": [...], "notes": "..."}.
    """
    warnings = []
    days = []

    if not topics:
        return {"days": [], "warnings": ["No topics provided."], "notes": ""}

    # Calculate total available time
    total_available_min = daily_minutes * days_available

    # Calculate time needed per topic based on priority
    topic_time = {}
    total_needed = 0
    for topic in topics:
        priority = priorities.get(topic, "medium")
        alloc = PRIORITY_ALLOCATION[priority]
        time_needed = alloc["initial"] + alloc["revision"] + alloc["practice"]
        topic_time[topic] = time_needed
        total_needed += time_needed

    # Add final review time (1 day worth)
    review_time = min(daily_minutes, 60)
    total_needed += review_time

    # Check if everything fits
    if total_needed > total_available_min:
        warnings.append(
            f"The available study time ({total_available_min} min over {days_available} days) "
            f"may not be enough to cover all {len(topics)} topics plus revision "
            f"(estimated need: {total_needed} min). Consider more days or more daily study time."
        )

    # Build schedule day by day — spread tasks across ALL available days
    topic_queue = list(topics)
    # Sort: high priority first, then medium, then low
    topic_queue.sort(key=lambda t: {"high": 0, "medium": 1, "low": 2}.get(priorities.get(t, "medium"), 1))

    # Reserve last day for final review if exam date is set
    review_day = None
    if exam_date and days_available > 1:
        review_day = exam_date - timedelta(days=1)
        if review_day <= start_date:
            review_day = None

    # Calculate how many days to fill (excluding review day)
    fill_days = days_available
    if review_day:
        fill_days = (review_day - start_date).days
        if fill_days < 1:
            fill_days = 1

    # Build a flat list of all tasks to distribute
    # Order: all initial studies first, then revisions, then practices
    # This ensures learning precedes revision
    all_tasks = []
    # Phase 1: Initial study for all topics
    for topic in topic_queue:
        priority = priorities.get(topic, "medium")
        alloc = PRIORITY_ALLOCATION[priority]
        all_tasks.append({
            "topic": topic,
            "description": _objective_text("read", topic, priority),
            "duration_minutes": alloc["initial"],
            "activity": "read",
            "priority": priority,
        })
    # Phase 2: Revision for all topics
    for topic in topic_queue:
        priority = priorities.get(topic, "medium")
        alloc = PRIORITY_ALLOCATION[priority]
        all_tasks.append({
            "topic": topic,
            "description": _objective_text("revise", topic, priority),
            "duration_minutes": alloc["revision"],
            "activity": "revise",
            "priority": priority,
        })
    # Phase 3: Practice for topics that need it
    for topic in topic_queue:
        priority = priorities.get(topic, "medium")
        alloc = PRIORITY_ALLOCATION[priority]
        if alloc["practice"] > 0:
            all_tasks.append({
                "topic": topic,
                "description": _objective_text("practice", topic, priority),
                "duration_minutes": alloc["practice"],
                "activity": "practice",
                "priority": priority,
            })

    # Distribute tasks across days, respecting daily budget and preventing duplicates
    total_tasks = len(all_tasks)
    if total_tasks == 0 or fill_days == 0:
        return {"days": [], "warnings": warnings, "notes": ""}

    # Calculate how many tasks per day (spread evenly)
    tasks_per_day = max(1, total_tasks // fill_days)
    remainder = total_tasks % fill_days

    task_idx = 0
    current_date = start_date
    for day_num in range(1, fill_days + 1):
        if task_idx >= total_tasks:
            break
        # Distribute remainder across first few days
        n_tasks = tasks_per_day + (1 if day_num <= remainder else 0)
        day_tasks = []
        day_total = 0
        day_topics = set()  # Track topics already scheduled today
        for _ in range(n_tasks):
            if task_idx >= total_tasks:
                break
            t = all_tasks[task_idx]
            # Skip if this topic is already scheduled for today
            if t["topic"].lower() in day_topics:
                task_idx += 1
                continue
            dur = min(t["duration_minutes"], daily_minutes - day_total)
            if dur < 10:
                break
            day_tasks.append({**t, "duration_minutes": dur})
            day_total += dur
            day_topics.add(t["topic"].lower())
            task_idx += 1
        if day_tasks:
            days.append({
                "day_number": day_num,
                "date": current_date.isoformat(),
                "tasks": day_tasks,
            })
        current_date += timedelta(days=1)

    # Add final review day
    if review_day and days_available > 1:
        review_tasks = []
        # Review weak topics first
        weak_set = {w["topic"].lower() for w in weak_topics}
        for topic in topics:
            if topic.lower() in weak_set or priorities.get(topic) == "high":
                review_tasks.append({
                    "topic": topic,
                    "description": f"Final review: {topic}",
                    "duration_minutes": 20,
                    "activity": "revise",
                    "priority": "high",
                })
        # Add general review
        review_tasks.append({
            "topic": "Overall Review",
            "description": "Review all key concepts and formulas before the exam.",
            "duration_minutes": 30,
            "activity": "quiz",
            "priority": "medium",
        })
        # Trim to fit daily budget
        trimmed = []
        total = 0
        for t in review_tasks:
            if total + t["duration_minutes"] <= daily_minutes:
                trimmed.append(t)
                total += t["duration_minutes"]
        if trimmed:
            days.append({
                "day_number": len(days) + 1,
                "date": review_day.isoformat(),
                "tasks": trimmed,
            })

    # Check for uncovered topics (topics that never appeared in any task)
    scheduled_topics = set()
    for d in days:
        for t in d["tasks"]:
            scheduled_topics.add(t["topic"].lower())
    uncovered = [t for t in topics if t.lower() not in scheduled_topics]
    if uncovered:
        warnings.append(
            "These topics could not be scheduled: " + ", ".join(uncovered) +
            ". Consider increasing available days or daily study time."
        )

    # Add preferred study time note
    time_note = f"Preferred study time: {preferred_study_time}. " if preferred_study_time != "flexible" else ""

    return {
        "days": days,
        "warnings": warnings,
        "notes": f"{time_note}Generated using Smart Planning (built-in engine).",
    }


def _objective_text(activity, topic, priority):
    """Generate a specific, meaningful objective description for a task."""
    # Topic-specific descriptions for common CS topics
    topic_tasks = {
        "Arrays": {
            "read": "Learn array operations, indexing, and time complexity",
            "practice": "Solve traversal, searching, and two-sum problems",
            "revise": "Review common array patterns and edge cases",
        },
        "Linked Lists": {
            "read": "Learn singly and doubly linked list structure",
            "practice": "Implement insertion, deletion, and traversal",
            "revise": "Review pointer manipulation and common patterns",
        },
        "Trees": {
            "read": "Learn tree terminology and binary tree structure",
            "practice": "Implement tree traversals (inorder, preorder, postorder)",
            "revise": "Review BST properties and balancing concepts",
        },
        "Graphs": {
            "read": "Learn graph representations (adjacency list/matrix)",
            "practice": "Implement BFS and DFS traversals",
            "revise": "Review shortest path and cycle detection",
        },
        "Two Pointers": {
            "read": "Learn the two-pointer technique and use cases",
            "practice": "Solve pair sum and container problems",
            "revise": "Review when to use two pointers vs other approaches",
        },
        "Sliding Window": {
            "read": "Learn the sliding window pattern and variations",
            "practice": "Solve substring and subarray problems",
            "revise": "Review fixed vs dynamic window techniques",
        },
        "Stacks": {
            "read": "Learn stack operations and LIFO principle",
            "practice": "Solve parenthesis matching and evaluation problems",
            "revise": "Review stack applications in parsing",
        },
        "Queues": {
            "read": "Learn queue operations and FIFO principle",
            "practice": "Implement BFS using queues",
            "revise": "Review deque and priority queue concepts",
        },
        "Hashing": {
            "read": "Learn hash tables and collision resolution",
            "practice": "Solve frequency counting and lookup problems",
            "revise": "Review hash function design and trade-offs",
        },
        "Dynamic Programming": {
            "read": "Learn DP principles: overlapping subproblems and optimal substructure",
            "practice": "Solve knapsack and LCS problems",
            "revise": "Review memoization vs tabulation approaches",
        },
        "Binary Search": {
            "read": "Learn binary search algorithm and its variants",
            "practice": "Solve search in rotated array problems",
            "revise": "Review boundary conditions and edge cases",
        },
        "Recursion": {
            "read": "Learn recursion patterns and base cases",
            "practice": "Solve tree and backtracking problems",
            "revise": "Review call stack and recursion depth",
        },
        "Sorting": {
            "read": "Learn comparison-based and non-comparison sorts",
            "practice": "Implement merge sort and quick sort",
            "revise": "Review time/space complexity trade-offs",
        },
        "Greedy Algorithms": {
            "read": "Learn greedy choice property and when to apply",
            "practice": "Solve interval scheduling and coin change problems",
            "revise": "Review proof of correctness for greedy approaches",
        },
        "Backtracking": {
            "read": "Learn backtracking template and pruning",
            "practice": "Solve N-Queens and subset generation problems",
            "revise": "Review state space tree and optimization",
        },
        "Heaps": {
            "read": "Learn heap structure and heapify operations",
            "practice": "Solve top-K and merge-K-sorted problems",
            "revise": "Review min-heap vs max-heap use cases",
        },
        "Tries": {
            "read": "Learn trie structure and prefix matching",
            "practice": "Implement autocomplete and word search",
            "revise": "Review space optimization techniques",
        },
    }

    # Get topic-specific description or fall back to generic
    topic_lower = topic.lower()
    for key, tasks in topic_tasks.items():
        if key.lower() in topic_lower or topic_lower in key.lower():
            desc = tasks.get(activity)
            if desc:
                return desc

    # Generic fallbacks based on activity
    generic = {
        "read": f"Study {topic} fundamentals and key concepts",
        "practice": f"Practice {topic} problems and exercises",
        "revise": f"Review {topic} and test your understanding",
        "quiz": f"Take a quiz on {topic} to assess your knowledge",
    }
    return generic.get(activity, f"Study {topic}")


# ══════════════════════════════════════════════════════════════════════
# AI-ENHANCED PLANNING (optional, single API call)
# ══════════════════════════════════════════════════════════════════════

def generate_ai_plan(topics, priorities, weak_topics, daily_minutes,
                     days_available, start_date, exam_date, preferred_study_time):
    """Try to generate an AI-enhanced plan. Returns plan dict or None.

    Makes exactly ONE API call. On any failure, returns None so the
    rule-based engine can take over.
    """
    if config.DEMO:
        return None

    try:
        weak_txt = ", ".join(w["topic"] for w in weak_topics) if weak_topics else "None"
        exam_txt = exam_date.isoformat() if exam_date else "not set"
        topic_list = "\n".join(
            f"{i+1}. {t} [{priorities.get(t, 'medium').upper()}]"
            for i, t in enumerate(topics)
        )

        p = f"""You are a Study Planner Agent. Create a personalized study plan.

Parameters:
- Exam date: {exam_txt}
- Daily study time: {daily_minutes} minutes
- Days available: {days_available}
- Preferred study time: {preferred_study_time}

Topics (with priority):
{topic_list}

Weak topics needing extra attention: {weak_txt}

Rules:
1. Day 1 is {start_date.isoformat()}. Use consecutive days, no later than exam date.
2. Total task time per day MUST NOT exceed {daily_minutes} minutes.
3. Every topic must appear at least once. Do NOT invent new topics.
4. HIGH priority topics get 1.5-2x more time than LOW priority.
5. Activities: "read" (new material), "revise" (review), "practice" (problems), "quiz" (self-test).
6. Reserve the final day before exam for review and self-testing.
7. Keep descriptions short and actionable.

Return ONLY JSON:
{{"plan":[{{"date":"YYYY-MM-DD","topic":"...","activity":"...","duration_minutes":45,"priority":"HIGH","objective":"..."}}]}}"""

        result = ask(p)
        raw_tasks = result.get("plan", [])
        if not raw_tasks:
            return None

        # Convert to day-grouped structure
        days_map = {}
        for t in raw_tasks:
            topic = str(t.get("topic", "")).strip()
            if not topic:
                continue
            dur = int(t.get("duration_minutes", 30))
            act = str(t.get("activity", "read")).lower()
            pri = str(t.get("priority", "medium")).lower()
            obj = str(t.get("objective", "")).strip() or f"Study {topic}."
            if act not in ACTIVITIES:
                act = "read"
            if pri not in PRIORITIES:
                pri = "medium"
            task = {
                "topic": topic,
                "description": obj,
                "duration_minutes": dur,
                "activity": act,
                "priority": pri,
            }
            d = str(t.get("date", ""))
            if d not in days_map:
                days_map[d] = []
            days_map[d].append(task)

        # Build ordered days, respecting daily budget
        days = []
        day_num = 0
        for d in sorted(days_map.keys()):
            day_tasks = []
            total = 0
            for t in days_map[d]:
                if total + t["duration_minutes"] > daily_minutes:
                    continue
                day_tasks.append(t)
                total += t["duration_minutes"]
            if day_tasks:
                day_num += 1
                days.append({
                    "day_number": day_num,
                    "date": d,
                    "tasks": day_tasks,
                })

        if not days:
            return None

        return {
            "days": days,
            "warnings": [],
            "notes": "Generated with AI personalization.",
        }

    except Exception as e:
        log.warning("AI plan generation failed: %s", e)
        return None


# ══════════════════════════════════════════════════════════════════════
# VALIDATION
# ══════════════════════════════════════════════════════════════════════

def validate_plan(days, topics, daily_minutes, days_available, start_date, exam_date):
    """Validate and repair a plan so it never breaks the UI.

    Returns (clean_days, warnings) or raises ValueError if unusable.
    """
    warnings = []
    if not isinstance(days, list) or not days:
        raise ValueError("Plan is empty")

    out_days = []
    seen_topics = set()

    for i, day in enumerate(days[:days_available], 1):
        tasks, total = [], 0
        for t in day.get("tasks", []):
            topic = str(t.get("topic", "")).strip()
            desc = str(t.get("description", "")).strip() or f"Study {topic}."
            try:
                dur = int(t.get("duration_minutes"))
            except (TypeError, ValueError):
                continue
            act = str(t.get("activity", "read")).lower()
            pri = str(t.get("priority", "medium")).lower()
            if not topic or dur <= 0:
                continue
            if act not in ACTIVITIES:
                act = "read"
            if pri not in PRIORITIES:
                pri = "medium"
            if total + dur > daily_minutes:
                warnings.append(
                    f"Day {i}: '{topic}' skipped to stay within the "
                    f"{daily_minutes}-minute daily limit."
                )
                continue
            tasks.append({
                "topic": topic,
                "description": desc,
                "duration_minutes": dur,
                "activity": act,
                "priority": pri,
            })
            total += dur
            seen_topics.add(topic.lower())

        if not tasks:
            continue

        d = start_date + timedelta(days=i - 1)
        if exam_date and d > exam_date:
            warnings.append("Days after the exam date were removed.")
            break

        out_days.append({
            "day_number": i,
            "date": d.isoformat(),
            "tasks": tasks,
        })

    if not out_days:
        raise ValueError("No usable tasks in plan")

    missing = [t for t in topics if t.lower() not in seen_topics]
    if missing:
        warnings.append(
            "These topics could not fit into the available time: " +
            ", ".join(missing) +
            ". Consider more days or more daily study time."
        )

    return out_days, warnings


# ══════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════

def generate_plan(title, exam_date, daily_minutes, days_available, preferred_study_time,
                  material_text=None, topics=None, performance=None,
                  has_performance_data=False):
    """Generate a study plan using the hybrid AI + rule-based engine.

    Flow:
    1. Get topics (user → AI → local)
    2. Calculate priorities from quiz performance
    3. Try AI-enhanced plan (if Gemini available)
    4. Fall back to rule-based plan (always works)
    5. Validate and return

    Returns {"days": [...], "warnings": [...], "notes": "...", "source": "ai"|"smart"}.
    """
    start = date.today()
    exam = date.fromisoformat(exam_date) if exam_date else None

    # Step 1: Get topics
    topic_list, source = get_topics(material_text, topics)
    if not topic_list:
        return {
            "error": "No topics found. Provide a syllabus or upload study material.",
            "days": [],
            "warnings": [],
            "notes": "",
            "source": "none",
        }

    # Step 2: Calculate priorities
    priorities = calculate_topic_priorities(topic_list, performance)
    weak_topics = get_weak_topics(performance)

    # Step 3: Try AI-enhanced plan (never crash if AI fails)
    try:
        ai_plan = generate_ai_plan(
            topic_list, priorities, weak_topics, daily_minutes,
            days_available, start, exam, preferred_study_time,
        )
    except Exception as e:
        log.warning("AI plan generation failed: %s", e)
        ai_plan = None

    if ai_plan:
        try:
            days, warnings = validate_plan(
                ai_plan["days"], topic_list, daily_minutes,
                days_available, start, exam,
            )
            return {
                "days": days,
                "warnings": warnings,
                "notes": ai_plan.get("notes", "Generated with AI personalization."),
                "source": "ai",
            }
        except ValueError:
            pass  # AI plan invalid, fall through to rule-based

    # Step 4: Rule-based plan (always works)
    plan = generate_rule_based_plan(
        topic_list, priorities, weak_topics, daily_minutes,
        days_available, start, exam, preferred_study_time,
    )

    return {
        "days": plan["days"],
        "warnings": plan["warnings"],
        "notes": plan["notes"],
        "source": "smart",
    }
