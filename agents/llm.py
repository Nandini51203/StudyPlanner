import json, re, time, config


def ask(prompt, retries=1):
    """Call Gemini via LangChain and parse a JSON object; controlled retry on failure."""
    from langchain_google_genai import ChatGoogleGenerativeAI
    llm = ChatGoogleGenerativeAI(
        model=config.MODEL,
        google_api_key=config.GOOGLE_API_KEY,
        temperature=0.3,
        max_output_tokens=8192,
    )
    last = None
    for i in range(retries + 1):
        try:
            t = llm.invoke(prompt).content
            if isinstance(t, list):
                t = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in t)
            return json.loads(re.search(r"\{.*\}", t, re.S).group(0))
        except Exception as e:
            last = e
            err_str = str(e)
            # Fail fast on rate limit / quota errors — no point retrying
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                raise RuntimeError(f"AI request failed (check API key / rate limit): {last}")
            # Only retry on transient errors (network, timeout, etc.)
            if i < retries:
                time.sleep(2 * (i + 1))
    raise RuntimeError(f"AI request failed (check API key / rate limit): {last}")
