import config
from agents.llm import ask

DEMO = {
    "title": "Machine Learning Basics (DEMO DATA)",
    "overview": "Sample summary shown because no API key is set.",
    "key_concepts": ["Supervised learning", "Overfitting", "Gradient descent"],
    "definitions": [{"term": "Overfitting", "meaning": "Model memorises training data and fails on new data."}],
    "main_points": ["Supervised models learn from labeled data.", "Regularisation reduces overfitting."],
    "formulas": ["w = w - lr * dLoss/dw"],
    "revision_notes": ["Know the bias-variance trade-off."],
    "sections": [],
}


def _split_into_chunks(text):
    """Split text into meaningful chunks preserving paragraph boundaries."""
    paragraphs = text.split("\n")
    chunks = []
    current_chunk = ""
    current_size = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # If adding this paragraph would exceed chunk size, save current chunk
        if current_size + len(para) > config.CHUNK_SIZE and current_chunk:
            chunks.append(current_chunk)
            # Keep overlap: last 200 chars of current chunk
            overlap = current_chunk[-config.CHUNK_OVERLAP:] if len(current_chunk) > config.CHUNK_OVERLAP else ""
            current_chunk = overlap + "\n" + para if overlap else para
            current_size = len(current_chunk)
        else:
            current_chunk = current_chunk + "\n" + para if current_chunk else para
            current_size += len(para)

    if current_chunk.strip():
        chunks.append(current_chunk)

    # Safety limit
    if len(chunks) > config.MAX_CHUNKS:
        # Merge smallest chunks until under limit
        while len(chunks) > config.MAX_CHUNKS:
            # Find two smallest adjacent chunks and merge them
            min_idx = 0
            min_size = len(chunks[0]) + len(chunks[1])
            for i in range(1, len(chunks) - 1):
                size = len(chunks[i]) + len(chunks[i + 1])
                if size < min_size:
                    min_size = size
                    min_idx = i
            chunks[min_idx] = chunks[min_idx] + "\n" + chunks[min_idx + 1]
            chunks.pop(min_idx + 1)

    return chunks


def _summarize_chunk(chunk_text, chunk_num, total_chunks):
    """Summarize a single chunk of text."""
    prompt = f"""You are a Summarizer Agent creating comprehensive study notes. This is chunk {chunk_num} of {total_chunks}.

Extract and summarize ALL important information from this text section. Include:
- Key concepts and definitions
- Important details, conditions, and exceptions
- Examples and applications
- Formulas and equations with explanations
- Step-by-step processes

Do NOT oversimplify. Do NOT omit information to make it shorter. Preserve technical accuracy.
Use clear, student-friendly language. Do NOT invent facts.

Return ONLY JSON with keys:
- "section_title": short title for this section
- "key_points": list of important points (detailed, not vague)
- "definitions": list of {{"term", "meaning"}} objects
- "examples": list of examples or applications
- "formulas": list of formulas with explanations

TEXT:
{chunk_text}"""

    try:
        result = ask(prompt)
        return result
    except Exception as e:
        # Return a basic structure if chunk summarization fails
        return {
            "section_title": f"Section {chunk_num}",
            "key_points": [f"[Error summarizing section {chunk_num}: {str(e)}]"],
            "definitions": [],
            "examples": [],
            "formulas": [],
        }


def _combine_summaries(chunk_summaries, original_text):
    """Combine chunk summaries into comprehensive final notes."""
    # Build a combined summary text from all chunks
    combined_text = ""
    for i, summary in enumerate(chunk_summaries):
        title = summary.get("section_title", f"Section {i+1}")
        combined_text += f"\n\n=== {title} ===\n"
        for point in summary.get("key_points", []):
            combined_text += f"- {point}\n"
        for definition in summary.get("definitions", []):
            if isinstance(definition, dict):
                combined_text += f"- {definition.get('term', '')}: {definition.get('meaning', '')}\n"
        for example in summary.get("examples", []):
            combined_text += f"- Example: {example}\n"
        for formula in summary.get("formulas", []):
            combined_text += f"- Formula: {formula}\n"

    # Generate comprehensive final notes
    prompt = f"""You are a Summarizer Agent creating final comprehensive study notes.

Based on the following section summaries, create detailed, well-structured study notes.

REQUIREMENTS:
- Include ALL major topics and subtopics from the source
- Provide detailed explanations of important concepts
- Include ALL key definitions with clear explanations
- Include ALL formulas, equations, and their explanations
- Include ALL examples and applications
- Include step-by-step processes and workflows
- Include advantages/disadvantages and comparisons where relevant
- Use headings and subheadings that follow the original structure
- Do NOT oversimplify technical concepts
- Do NOT remove information to make it shorter
- Do NOT invent facts
- Maintain technical accuracy
- Explain concepts in clear, student-friendly language
- Avoid repeating the same information
- Include a "Quick Revision" section at the end with the most important points

The notes should be detailed enough that a student can understand and revise without referring to the original document.

Return ONLY JSON with keys:
- "title": document/chapter title
- "overview": comprehensive introduction (2-3 paragraphs)
- "key_concepts": list of all major concepts
- "definitions": list of {{"term", "meaning"}} objects (ALL definitions)
- "main_points": list of ALL important points (detailed)
- "formulas": list of ALL formulas with explanations
- "examples": list of ALL examples and applications
- "processes": list of step-by-step processes/workflows
- "comparisons": list of comparisons/differences
- "advantages": list of advantages/benefits
- "disadvantages": list of disadvantages/limitations
- "revision_notes": list of key points for quick revision
- "sections": list of {{"title", "content"}} for major sections

SECTION SUMMARIES:
{combined_text[:30000]}"""

    try:
        return ask(prompt)
    except Exception as e:
        # Fallback: return combined chunk summaries as sections
        sections = []
        for i, summary in enumerate(chunk_summaries):
            content = "\n".join(summary.get("key_points", []))
            sections.append({"title": summary.get("section_title", f"Section {i+1}"), "content": content})
        return {
            "title": "Study Notes",
            "overview": f"Combined from {len(chunk_summaries)} sections.",
            "key_concepts": [],
            "definitions": [],
            "main_points": [],
            "formulas": [],
            "examples": [],
            "processes": [],
            "comparisons": [],
            "advantages": [],
            "disadvantages": [],
            "revision_notes": [],
            "sections": sections,
        }


def run(text):
    """Run hierarchical summarization on the input text."""
    if config.DEMO:
        return dict(DEMO)

    # Split into chunks
    chunks = _split_into_chunks(text)

    if len(chunks) == 1:
        # Short document: single-pass summarization with comprehensive prompt
        prompt = f"""You are a Summarizer Agent creating comprehensive study notes.

Create detailed, well-structured study notes from the following text.

REQUIREMENTS:
- Include ALL major topics and subtopics
- Provide detailed explanations of important concepts
- Include ALL key definitions with clear explanations
- Include ALL formulas, equations, and their explanations
- Include ALL examples and applications
- Include step-by-step processes and workflows
- Include advantages/disadvantages and comparisons where relevant
- Use headings and subheadings that follow the original structure
- Do NOT oversimplify technical concepts
- Do NOT remove information to make it shorter
- Do NOT invent facts
- Maintain technical accuracy
- Explain concepts in clear, student-friendly language
- Include a "Quick Revision" section at the end

Return ONLY JSON with keys:
- "title": document/chapter title
- "overview": comprehensive introduction
- "key_concepts": list of all major concepts
- "definitions": list of {{"term", "meaning"}} objects
- "main_points": list of ALL important points
- "formulas": list of ALL formulas with explanations
- "examples": list of ALL examples and applications
- "processes": list of step-by-step processes/workflows
- "comparisons": list of comparisons/differences
- "advantages": list of advantages/benefits
- "disadvantages": list of disadvantages/limitations
- "revision_notes": list of key points for quick revision
- "sections": list of {{"title", "content"}} for major sections

TEXT:
{text[:30000]}"""
        return ask(prompt)

    # Long document: hierarchical summarization
    chunk_summaries = []
    for i, chunk in enumerate(chunks):
        summary = _summarize_chunk(chunk, i + 1, len(chunks))
        chunk_summaries.append(summary)

    # Combine into final comprehensive notes
    return _combine_summaries(chunk_summaries, text)
