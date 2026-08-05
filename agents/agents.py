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
    kwargs = {"model": model_name, "temperature": 0.3}
    if base_url:
        kwargs["base_url"] = base_url
    if api_key:
        kwargs["api_key"] = api_key
    if not model_name.startswith("openrouter/"):
        kwargs["max_tokens"] = 8192  # Raised from 2000 → 8192 for thorough detailed answers
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

    NEVER gives up: up to MAX_GLOBAL_PASSES full sweeps through all models.
    Between each pass, waits progressively longer so rate-limit windows expire.
    """
    all_llms = [primary_llm]
    for fb in fallback_llms:
        if not any(existing.model == fb.model for existing in all_llms):
            all_llms.append(fb)

    orig_call = primary_llm.call

    # Maximum number of full sweeps through the entire model pool.
    MAX_GLOBAL_PASSES = 4
    # Per-model retry attempts before moving to the next model in the list.
    MAX_RETRIES_PER_MODEL = 3
    # Cooldown seconds to mark an exhausted model.
    EXHAUSTION_COOLDOWN = 90.0

    def resilient_call(*args, **kwargs):
        last_exception = None

        for pass_num in range(MAX_GLOBAL_PASSES):
            # On each pass, rebuild the ordered list so recovered models get priority.
            healthy = [m for m in all_llms if not _is_model_exhausted(m.model)]
            exhausted = [m for m in all_llms if _is_model_exhausted(m.model)]
            ordered_this_pass = healthy + exhausted

            if not ordered_this_pass:
                ordered_this_pass = all_llms  # last resort: try everything

            for llm_idx, llm_instance in enumerate(ordered_this_pass):
                model_name = llm_instance.model
                call_func = orig_call if llm_instance is primary_llm else llm_instance.call

                for attempt in range(1, MAX_RETRIES_PER_MODEL + 1):
                    try:
                        result = call_func(*args, **kwargs)
                        # Success — clear any stale exhaustion mark.
                        _EXHAUSTED_MODELS.pop(model_name, None)
                        return result
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
                            # Non-retriable error — skip to next model immediately.
                            print(f"\n[⚡ Non-retriable Error] Model '{model_name}': {str(e)[:120]}")
                            break

                        parsed_delay = _parse_retry_delay(err_msg)
                        if parsed_delay and parsed_delay < 120:
                            wait_time = parsed_delay + 1.0
                            print(f"\n[⚡ Rate Limit] Model '{model_name}' says wait {wait_time:.1f}s (Attempt {attempt}/{MAX_RETRIES_PER_MODEL})...")
                            time.sleep(wait_time)
                        elif attempt < MAX_RETRIES_PER_MODEL:
                            wait_time = 2.0 * (attempt ** 1.5)
                            print(f"\n[⚡ Backoff] Model '{model_name}' rate-limited. Waiting {wait_time:.1f}s (Attempt {attempt}/{MAX_RETRIES_PER_MODEL})...")
                            time.sleep(wait_time)
                        else:
                            # All retries exhausted for this model — mark and try next.
                            _mark_model_exhausted(model_name, cooldown_seconds=EXHAUSTION_COOLDOWN)
                            print(f"\n[⚡ Exhausted] Model '{model_name}' marked exhausted for {EXHAUSTION_COOLDOWN}s.")

                # Announce switch to next model.
                if llm_idx < len(ordered_this_pass) - 1:
                    next_model = ordered_this_pass[llm_idx + 1].model
                    print(f"\n[⚡ Switching] Moving from '{model_name}' → '{next_model}'...")
                    time.sleep(0.3)

            # End of one full pass — all models tried.
            if pass_num < MAX_GLOBAL_PASSES - 1:
                # Progressive inter-pass wait: 5s, 10s, 20s so rate limits can expire.
                inter_pass_wait = 5.0 * (2 ** pass_num)
                print(f"\n[⚡ Global Retry #{pass_num + 1}] All models tried. Waiting {inter_pass_wait:.0f}s before retry sweep #{pass_num + 2}...")
                time.sleep(inter_pass_wait)
                # Reset exhaustion marks so recovered models are tried again.
                expired = [m for m, exp in list(_EXHAUSTED_MODELS.items()) if time.time() > exp]
                for m in expired:
                    _EXHAUSTED_MODELS.pop(m, None)

        if last_exception is not None:
            raise last_exception
        raise RuntimeError("LLM execution failed after all retries: No response generated.")

    primary_llm.call = resilient_call
    return primary_llm


def _get_llm():
    """
    Create a resilient LLM instance with active model exhaustion tracking.
    Supports Gemini API, Groq, and OpenRouter model pools.
    """
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    groq_key = os.environ.get("GROQ_API_KEY")
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")

    candidate_models = []

    # 1. Gemini models (High reliability and fast inference)
    if gemini_key and gemini_key != "your_gemini_api_key_here":
        os.environ["GOOGLE_API_KEY"] = gemini_key
        os.environ["GEMINI_API_KEY"] = gemini_key
        gemini_models = [
            "gemini/gemini-2.5-flash",
            "gemini/gemini-1.5-flash",
        ]
        for gm in gemini_models:
            candidate_models.append(_create_llm_instance(gm, api_key=gemini_key))

    # 2. Groq models (Diversified suite of free Groq models with separate rate limit tiers)
    if groq_key and groq_key != "your_groq_api_key_here":
        req_model = os.environ.get("MODEL_NAME", "llama-3.3-70b-versatile")
        if req_model.startswith("groq/"):
            req_model = "openai/" + req_model[5:]
        elif not req_model.startswith("openai/") and not req_model.startswith("gemini/"):
            req_model = "openai/" + req_model

        groq_base = "https://api.groq.com/openai/v1"
        if not req_model.startswith("gemini/"):
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

    # 3. OpenRouter free models
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
        if gemini_key:
            ordered = [_create_llm_instance("gemini/gemini-2.5-flash", api_key=gemini_key)]
        elif groq_key:
            ordered = [_create_llm_instance("openai/llama-3.1-8b-instant", "https://api.groq.com/openai/v1", groq_key)]
        else:
            raise RuntimeError("No valid LLM API key configured! Please set GEMINI_API_KEY or GROQ_API_KEY in .env")

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
        max_iter=3,
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
        max_iter=3,
        max_rpm=60,
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
        max_iter=3,
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
            "Synthesize research findings into a precise, evidence-led report that directly "
            "answers the request. Separate sourced facts from analysis, cite evidence beside "
            "the relevant claims, identify material uncertainty, and make prioritized, "
            "decision-ready recommendations in clear professional language."
        ),
        backstory=(
            "You are an experienced research editor who turns source material into concise, "
            "decision-ready briefs. You never manufacture evidence, make uncertainty visible, "
            "and use structure to help a reader understand what is known, what it means, and "
            "what should happen next."
        ),
        llm=llm,
        function_calling_llm=llm,
        verbose=True,
        max_iter=3,
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
