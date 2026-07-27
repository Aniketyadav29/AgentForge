"""
AgentForge — Specialized AI Agent Definitions
Defines 4 specialized agents that collaborate in a research pipeline:
1. Research Strategist — Plans the research approach
2. Web Scraper — Gathers data from the web
3. Data Analyst — Structures and analyzes findings
4. Report Writer — Produces polished reports
"""

import os
import re
import time
from crewai import Agent, LLM
from agents.tools import get_search_tool, get_scrape_tool


def _create_llm_instance(model_name: str, base_url: str = None, api_key: str = None) -> LLM:
    """Helper to create a single LLM instance."""
    kwargs = {"model": model_name, "temperature": 0.1}
    if base_url:
        kwargs["base_url"] = base_url
    if api_key:
        kwargs["api_key"] = api_key
    if not model_name.startswith("openrouter/"):
        kwargs["max_tokens"] = 2000
    return LLM(**kwargs)


# Track models that hit rate limits with a timestamp-based cooldown (model_name -> expiration timestamp)
_EXHAUSTED_MODELS: dict[str, float] = {}


def _mark_model_exhausted(model_name: str, cooldown_seconds: float = 60.0):
    """Mark a model as exhausted for a given cooldown duration."""
    _EXHAUSTED_MODELS[model_name] = time.time() + cooldown_seconds


def _is_model_exhausted(model_name: str) -> bool:
    """Check if a model is currently in cooldown due to rate limits."""
    expire = _EXHAUSTED_MODELS.get(model_name, 0)
    if time.time() > expire:
        _EXHAUSTED_MODELS.pop(model_name, None)
        return False
    return True


def _parse_retry_delay(err_msg: str) -> float:
    """Extract retry delay in seconds from error message if available."""
    match = re.search(r'retry\s+(?:in|after)\s+([\d\.]+)\s*s?', err_msg, re.IGNORECASE)
    if not match:
        match = re.search(r'retry_delay\s*:\s*([\d\.]+)', err_msg, re.IGNORECASE)
    if not match:
        match = re.search(r'([\d\.]+)\s*seconds?', err_msg, re.IGNORECASE)

    if match:
        try:
            val = float(match.group(1))
            if 0 < val <= 120:
                return val
        except ValueError:
            pass
    return None


def _make_resilient_llm(primary_llm: LLM, fallback_llms: list[LLM]) -> LLM:
    """
    Wrap an LLM instance with automatic rate-limit retries, exponential backoff,
    retry-delay parsing, and multi-tier model fallback.
    """
    all_llms = [primary_llm]
    for fb in fallback_llms:
        if not any(existing.model == fb.model for existing in all_llms):
            all_llms.append(fb)

    orig_call = primary_llm.call

    def resilient_call(*args, **kwargs):
        last_exception = None

        # Try up to 2 passes across all candidate models
        for pass_num in range(2):
            for llm_idx, llm_instance in enumerate(all_llms):
                model_name = llm_instance.model
                call_func = orig_call if llm_idx == 0 else llm_instance.call

                # Up to 3 retries per model with exponential backoff / parsed delay
                max_retries_per_model = 3
                for attempt in range(1, max_retries_per_model + 1):
                    try:
                        return call_func(*args, **kwargs)
                    except Exception as e:
                        err_msg = str(e).lower()
                        last_exception = e

                        is_rate_limit = any(k in err_msg for k in [
                            "429", "413", "rate limit", "rate_limit",
                            "tpd", "tpm", "rpm", "quota exceeded",
                            "rate_limit_exceeded", "resource_exhausted"
                        ])
                        is_transient = any(k in err_msg for k in [
                            "500", "502", "503", "504", "connection",
                            "timeout", "overloaded"
                        ])

                        if not (is_rate_limit or is_transient):
                            break

                        parsed_delay = _parse_retry_delay(err_msg)
                        if parsed_delay:
                            wait_time = parsed_delay + 0.5
                            print(f"\n[⚡ Rate Limit] Model '{model_name}' requested wait. Pausing {wait_time:.1f}s before retry (Attempt {attempt}/{max_retries_per_model})...")
                            time.sleep(wait_time)
                        elif attempt < max_retries_per_model:
                            wait_time = 1.5 * (attempt ** 1.3)
                            print(f"\n[⚡ Backoff Retry] Model '{model_name}' hit rate limit/error. Waiting {wait_time:.1f}s (Attempt {attempt}/{max_retries_per_model})...")
                            time.sleep(wait_time)
                        else:
                            _mark_model_exhausted(model_name, cooldown_seconds=60.0)

                # Fallback to next candidate model if available
                if llm_idx < len(all_llms) - 1:
                    next_model = all_llms[llm_idx + 1].model
                    print(f"\n[⚡ Auto Fallback] Model '{model_name}' rate limited/exhausted. Instantly switching to '{next_model}'...")
                    time.sleep(0.5)

            if pass_num == 0:
                print("\n[⚡ Fallback Sweep] Retrying model pool after short 4.0s pause...")
                time.sleep(4.0)

        if last_exception is not None:
            raise last_exception
        raise RuntimeError("LLM execution failed: No response generated.")

    primary_llm.call = resilient_call
    return primary_llm


def _get_llm():
    """
    Create a resilient LLM instance with active model exhaustion tracking.
    Excludes Gemini API per configuration, using Groq and OpenRouter model pools.
    """
    groq_key = os.environ.get("GROQ_API_KEY")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")

    candidate_models = []

    # 1. Groq models (Diversified suite of free Groq models with separate rate limit tiers)
    if groq_key and groq_key != "your_groq_api_key_here":
        req_model = os.environ.get("MODEL_NAME", "llama-3.3-70b-versatile")
        if req_model.startswith("groq/"):
            req_model = "openai/" + req_model[5:]
        elif not req_model.startswith("openai/"):
            req_model = "openai/" + req_model

        groq_base = "https://api.groq.com/openai/v1"
        candidate_models.append(_create_llm_instance(req_model, groq_base, groq_key))

        fallback_models = [
            "openai/llama-3.1-8b-instant",
            "openai/gemma2-9b-it",
            "openai/llama-3.2-11b-vision-preview",
            "openai/llama-3.2-3b-preview",
            "openai/llama-3.2-1b-preview",
            "openai/mixtral-8x7b-32768",
            "openai/deepseek-r1-distill-llama-70b",
            "openai/qwen-2.5-32b",
        ]
        for m in fallback_models:
            if m != req_model:
                candidate_models.append(_create_llm_instance(m, groq_base, groq_key))

    # 2. OpenRouter free models
    if openrouter_key and openrouter_key != "your_openrouter_api_key_here":
        or_models = [
            "openrouter/meta-llama/llama-3.3-70b-instruct:free",
            "openrouter/deepseek/deepseek-r1:free",
            "openrouter/google/gemma-2-9b-it:free",
            "openrouter/mistralai/mistral-7b-instruct:free",
        ]
        for om in or_models:
            candidate_models.append(_create_llm_instance(om, api_key=openrouter_key))

    # Prioritize healthy non-exhausted models
    healthy = [m for m in candidate_models if not _is_model_exhausted(m.model)]
    exhausted = [m for m in candidate_models if _is_model_exhausted(m.model)]

    ordered = healthy + exhausted
    if not ordered:
        if groq_key:
            ordered = [_create_llm_instance("openai/llama-3.1-8b-instant", "https://api.groq.com/openai/v1", groq_key)]
        else:
            raise RuntimeError("No valid LLM API key configured! Please set GROQ_API_KEY in .env")

    primary = ordered[0]
    fallbacks = ordered[1:]
    return _make_resilient_llm(primary, fallbacks)


def create_research_strategist():
    """
    Research Strategist Agent
    Plans the research methodology and identifies key questions to investigate.
    This agent does NOT use tools — it reasons about the best approach.
    """
    llm = _get_llm()
    return Agent(
        role="Research Strategist",
        goal=(
            "Analyze the user's research topic and create a comprehensive research plan. "
            "Identify the key questions that need answering, the types of sources to consult, "
            "and the structure the final report should follow."
        ),
        backstory=(
            "You are a senior research director at a world-class consulting firm. "
            "You've led thousands of research projects across technology, business, finance, "
            "and science. You excel at breaking complex topics into actionable research tasks "
            "and know exactly what data is needed to produce valuable insights. "
            "You think strategically and always consider multiple angles."
        ),
        llm=llm,
        function_calling_llm=llm,
        verbose=True,
        max_iter=1,
        allow_delegation=False,
    )


def create_web_scraper():
    """
    Web Scraper Agent
    Executes web searches and scrapes content from relevant URLs.
    Equipped with SerperDevTool.
    """
    llm = _get_llm()
    return Agent(
        role="Web Research Specialist",
        goal=(
            "Execute targeted web searches based on the research plan. "
            "Extract key information, statistics, quotes, and data points. "
            "Always note the source URL for every piece of information gathered."
        ),
        backstory=(
            "You are an expert OSINT (Open Source Intelligence) analyst with years of "
            "experience in investigative research. You know how to craft precise search "
            "queries that yield the best results quickly and concisely."
        ),
        llm=llm,
        function_calling_llm=llm,
        tools=[get_search_tool()],
        verbose=True,
        max_iter=1,
        max_rpm=30,
        allow_delegation=False,
    )


def create_data_analyst():
    """
    Data Analyst Agent
    Structures raw research data, identifies patterns, and draws insights.
    """
    llm = _get_llm()
    return Agent(
        role="Data Analyst",
        goal=(
            "Take the raw research data gathered by the Web Research Specialist and "
            "organize it into structured categories. Identify key trends, patterns, "
            "contradictions, and gaps. Perform comparative analysis where applicable. "
            "Highlight the most significant findings and rank them by importance."
        ),
        backstory=(
            "You are a senior data analyst at a Fortune 500 company with expertise in "
            "qualitative and quantitative analysis. You have a knack for finding hidden "
            "patterns in data and presenting complex information in clear, logical frameworks. "
            "You use structured thinking — categorization, ranking, and comparative analysis — "
            "to transform raw data into actionable intelligence."
        ),
        llm=llm,
        function_calling_llm=llm,
        verbose=True,
        max_iter=1,
        allow_delegation=False,
    )


def create_report_writer():
    """
    Report Writer Agent
    Synthesizes analyzed data into a polished, comprehensive report.
    """
    llm = _get_llm()
    return Agent(
        role="Report Writer",
        goal=(
            "Synthesize all research findings and analysis into a comprehensive, "
            "well-structured report. The report must include an executive summary, "
            "detailed findings organized by theme, data visualizations described in text, "
            "actionable recommendations, and a list of all sources cited. "
            "The report should be written in clear, professional language suitable for "
            "C-level executives."
        ),
        backstory=(
            "You are an award-winning business writer and communications specialist. "
            "You've authored hundreds of research reports for McKinsey, BCG, and top tech "
            "companies. You know how to distill complex findings into clear narratives, "
            "use compelling data presentation, and write recommendations that drive action. "
            "You always structure reports with clear headings, bullet points, and highlight "
            "key takeaways. Your reports are known for being both thorough and readable."
        ),
        llm=llm,
        function_calling_llm=llm,
        verbose=True,
        max_iter=1,
        allow_delegation=False,
    )


def create_all_agents():
    """Create and return all 4 agents as a dictionary."""
    return {
        "strategist": create_research_strategist(),
        "scraper": create_web_scraper(),
        "analyst": create_data_analyst(),
        "writer": create_report_writer(),
    }
