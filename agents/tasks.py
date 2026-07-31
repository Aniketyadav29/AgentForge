"""
AgentForge — Task Definitions for the Research Pipeline
Each task feeds its output to the next agent in the sequential pipeline:
  Strategist → Scraper → Analyst → Writer
"""

import re
from crewai import Task


# ---------------------------------------------------------------------------
# Language Detection
# ---------------------------------------------------------------------------

# Maps keywords that users may write in their prompt → language instruction
_LANGUAGE_PATTERNS = [
    # Hinglish must come before hindi so it is matched first
    (r"hinglish",      "Hinglish (a natural mix of Hindi and English, as spoken in everyday Indian conversation)"),
    (r"hindi",         "Hindi (Devanagari script)"),
    (r"hinidi",        "Hindi (Devanagari script)"),   # common typo
    (r"spanish",       "Spanish"),
    (r"espanol",       "Spanish"),
    (r"french",        "French"),
    (r"francais",      "French"),
    (r"german",        "German"),
    (r"deutsch",       "German"),
    (r"portuguese",    "Portuguese"),
    (r"italian",       "Italian"),
    (r"arabic",        "Arabic"),
    (r"chinese",       "Chinese (Simplified)"),
    (r"mandarin",      "Chinese (Simplified)"),
    (r"japanese",      "Japanese"),
    (r"korean",        "Korean"),
    (r"russian",       "Russian"),
    (r"bengali",       "Bengali"),
    (r"tamil",         "Tamil"),
    (r"telugu",        "Telugu"),
    (r"marathi",       "Marathi"),
    (r"gujarati",      "Gujarati"),
    (r"punjabi",       "Punjabi"),
    (r"urdu",          "Urdu"),
    (r"english",       "English"),
]


def detect_language_instruction(topic: str) -> str:
    """
    Scan the user's topic for an explicit language preference and return
    a language directive string to append to every task description.

    Returns an empty string when no language keyword is found (agents will
    default to English as usual).
    """
    lower = topic.lower()
    for pattern, lang_name in _LANGUAGE_PATTERNS:
        if re.search(pattern, lower):
            return (
                f"\n\n"
                f"🌐 **LANGUAGE REQUIREMENT (MANDATORY):** "
                f"You MUST write your ENTIRE response in **{lang_name}**. "
                f"This applies to every sentence, heading, bullet point, table, "
                f"recommendation, and any other text you produce. "
                f"Do NOT switch to English unless the user's prompt is specifically "
                f"about an English-language topic. Respond in {lang_name} only."
            )
    return ""


def _user_intent_note(topic: str) -> str:
    return (
        "\n\n🎯 **PRIMARY USER INTENT DIRECTIVE (CRITICAL):**\n"
        f"The primary goal is to answer the user's exact request: '{topic}'.\n"
        "If the user asks for specific recommendations, lists, places, options, or consumer advice "
        "(e.g., 'places to visit for a weekend'), your output MUST directly provide that specific, actionable "
        "information (with place names, travel details, highlights, best season, and costs).\n"
        "Do NOT force a consumer query into a B2B business market report, corporate strategy document, "
        "or market sizing study unless the user explicitly asks for market/industry analysis!"
    )


def create_strategy_task(agent, topic: str, depth: str = "detailed"):
    """
    Task 1: Research Strategy Planning
    The strategist analyzes the topic and creates a research plan.
    """
    depth_instructions = {
        "quick": "Focus on the top 3 most important aspects. Keep the plan concise.",
        "detailed": "Cover 5-7 key aspects with sub-questions for each. Be thorough.",
        "deep": "Perform an exhaustive analysis covering 8-10 aspects with multiple sub-questions, "
                "edge cases, and contrarian viewpoints.",
    }

    lang_note = detect_language_instruction(topic)
    intent_note = _user_intent_note(topic)

    return Task(
        description=(
            f"Create a comprehensive research plan for the following topic:\n\n"
            f"**Topic:** {topic}\n\n"
            f"**Research Depth:** {depth}\n"
            f"**Depth Instructions:** {depth_instructions.get(depth, depth_instructions['detailed'])}\n\n"
            f"Your research plan must include:\n"
            f"1. A clear research objective directly aligned with the user's topic\n"
            f"2. Key questions that directly answer what the user asked for\n"
            f"3. Suggested search queries for the web research specialist\n"
            f"4. Types of sources to prioritize\n"
            f"5. A proposed structure for the final output that directly addresses the prompt"
            f"{intent_note}"
            f"{lang_note}"
        ),
        expected_output=(
            "A structured research plan in markdown format with:\n"
            "- Direct research objective matching the prompt\n"
            "- 5-10 key questions addressing user intent\n"
            "- 5-10 targeted search queries\n"
            "- Proposed report outline aligned with user request"
        ),
        agent=agent,
    )


def create_scraping_task(agent, topic: str):
    """
    Task 2: Web Research Execution
    The scraper uses the research plan to gather data from the web.
    """
    lang_note = detect_language_instruction(topic)
    intent_note = _user_intent_note(topic)

    return Task(
        description=(
            f"Using the research plan provided by the Research Strategist, "
            f"execute web searches on the topic: '{topic}'.\n\n"
            f"Instructions:\n"
            f"1. Perform 4-5 targeted web searches using diverse search queries\n"
            f"2. Extract specific details, names, facts, statistics, quotes, and source URLs\n"
            f"3. Synthesize findings into a rich, comprehensive summary directly answering the user's question\n"
            f"4. Always include source URLs for every key fact\n"
            f"5. Do NOT truncate findings — include all relevant details and data points found"
            f"{intent_note}"
            f"{lang_note}"
        ),
        expected_output=(
            "A comprehensive research summary in markdown format (at least 800 words) containing:\n"
            "- Specific names, details, statistics, and facts directly addressing the topic\n"
            "- Bulleted findings with source URLs for each item\n"
            "- Context, background, and nuanced information to inform the analyst"
        ),
        agent=agent,
    )


def create_analysis_task(agent, topic: str):
    """
    Task 3: Data Analysis & Pattern Recognition
    The analyst processes raw research data into structured insights.
    """
    lang_note = detect_language_instruction(topic)
    intent_note = _user_intent_note(topic)

    return Task(
        description=(
            f"Analyze and structure the research data gathered on: '{topic}'.\n\n"
            f"Instructions:\n"
            f"1. Structure and organize the findings logically to answer the user's specific question\n"
            f"2. Group items/recommendations by category, region, budget, or relevance as appropriate\n"
            f"3. Highlight key features, pros/cons, best times, and practical tips\n"
            f"4. Focus on giving accurate, clear, and actionable insights that directly satisfy the prompt"
            f"{intent_note}"
            f"{lang_note}"
        ),
        expected_output=(
            "A structured analysis document in markdown format directly answering the user query with:\n"
            "- Categorized recommendations/items\n"
            "- Key insights, features, and travel/practical tips"
        ),
        agent=agent,
    )


def create_report_task(agent, topic: str):
    """
    Task 4: Final Report Generation
    The writer produces a polished, user-friendly final output.
    """
    lang_note = detect_language_instruction(topic)
    intent_note = _user_intent_note(topic)

    return Task(
        description=(
            f"Write a COMPREHENSIVE, DETAILED, and WELL-STRUCTURED response directly answering: '{topic}'.\n\n"
            f"⚠️ STRICT OUTPUT ORDER (MANDATORY — do NOT deviate):\n"
            f"  PART 1 — FULL DETAILED ANSWER (write ALL content here first):\n"
            f"    1. **Direct Answer / Overview**: Start by directly providing what the user requested.\n"
            f"    2. **Exhaustive Breakdown**: For EACH item/recommendation, include ALL key details\n"
            f"       (location, distance/accessibility, best time to visit, top attractions, estimated budget,\n"
            f"        activities, why it's special, insider tips, hidden gems).\n"
            f"    3. **Categorization**: Group items logically (by region, interest type, budget tier) with\n"
            f"       clear ## and ### headings.\n"
            f"    4. **Deep Practical Tips**: Comprehensive actionable advice (travel modes, duration,\n"
            f"       itinerary suggestions, local cuisine, safety tips, best season, what to pack).\n"
            f"    5. **Rich Context**: Historical, cultural, or scientific background that enriches understanding.\n"
            f"  PART 2 — SOURCES (ALWAYS LAST, after all content above is complete):\n"
            f"    6. **## Sources & References** section at the very end with all URLs cited.\n\n"
            f"🚫 NEVER mix source URLs into the middle of content sections.\n"
            f"🚫 NEVER put references before the full detailed answer is written.\n"
            f"✅ The reader must be able to read the complete answer without needing to look at sources.\n\n"
            f"NOTE: Deliver a RICH, DETAILED, HIGHLY USEFUL guide — NOT a corporate business report! "
            f"Aim for a thorough response (1500-2500 words of actual content) that leaves the user with everything they need."
            f"{intent_note}"
            f"{lang_note}"
        ),
        expected_output=(
            "A COMPREHENSIVE, HIGHLY DETAILED response in markdown format (1500-2500 words) with STRICT ordering:\n"
            "PART 1 (content first):\n"
            "  - Title and executive summary\n"
            "  - Categorized, exhaustive breakdown of each item/topic with complete details\n"
            "  - Deep practical advice, tips, and rich cultural/scientific context\n"
            "PART 2 (always last):\n"
            "  - ## Sources & References section with all URLs — placed at the VERY END after all content"
        ),
        agent=agent,
    )



def create_all_tasks(agents: dict, topic: str, depth: str = "detailed"):
    """
    Create sequential tasks for the research pipeline tailored to research depth.
    - quick: 2 fast tasks (Scraper → Writer) for ultra-fast execution (~3-5 seconds)
    - detailed: 3 tasks (Scraper → Analyst → Writer) (~8-12 seconds)
    - deep: 4 tasks (Strategist → Scraper → Analyst → Writer) full exhaustive research (~20 seconds)
    """
    if depth == "quick":
        task2 = create_scraping_task(agents["scraper"], topic)
        task4 = create_report_task(agents["writer"], topic)
        task4.context = [task2]
        return [task2, task4]

    elif depth == "detailed":
        task2 = create_scraping_task(agents["scraper"], topic)
        task3 = create_analysis_task(agents["analyst"], topic)
        task3.context = [task2]
        task4 = create_report_task(agents["writer"], topic)
        task4.context = [task3]
        return [task2, task3, task4]

    else:  # deep
        task1 = create_strategy_task(agents["strategist"], topic, depth)
        task2 = create_scraping_task(agents["scraper"], topic)
        task2.context = [task1]
        task3 = create_analysis_task(agents["analyst"], topic)
        task3.context = [task2]
        task4 = create_report_task(agents["writer"], topic)
        task4.context = [task3]
        return [task1, task2, task3, task4]
