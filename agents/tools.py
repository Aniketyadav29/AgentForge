import urllib.parse
from crewai.tools import BaseTool
from crewai_tools import SerperDevTool, ScrapeWebsiteTool


class TruncatedSerperTool(BaseTool):
    name: str = "search_the_internet"
    description: str = "Search Google for news, statistics, facts, and info. Input should be a concise query string."

    def _run(self, search_query: str) -> str:
        try:
            tool = SerperDevTool(n_results=3)
            raw = tool._run(search_query=search_query)
            return str(raw)[:1500]  # Cap at ~300 tokens
        except Exception as e:
            return f"Search error: {e}"


class TruncatedScrapeTool(BaseTool):
    name: str = "read_website_content"
    description: str = "Extract text from a website URL. Input should be a single URL."

    def _run(self, website_url: str) -> str:
        try:
            tool = ScrapeWebsiteTool()
            raw = tool._run(website_url=website_url)
            return str(raw)[:1500]  # Cap at ~300 tokens
        except Exception as e:
            return f"Scrape error: {e}"


class PollinationsImageGenTool(BaseTool):
    name: str = "generate_ai_image"
    description: str = (
        "Generate a high-quality AI image from a text prompt for free. "
        "Input should be a detailed image description prompt in English."
    )

    def _run(self, prompt: str) -> str:
        try:
            encoded_prompt = urllib.parse.quote(prompt.strip())
            image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
            return f"![Generated AI Image]({image_url})\n\nDirect Link: {image_url}"
        except Exception as e:
            return f"Image generation error: {e}"


def get_search_tool():
    """Returns a truncated search tool instance to prevent token bloat."""
    return TruncatedSerperTool()


def get_scrape_tool():
    """Returns a truncated scrape tool instance to prevent token bloat."""
    return TruncatedScrapeTool()


def get_image_gen_tool():
    """Returns a free AI image generation tool instance."""
    return PollinationsImageGenTool()


def get_all_tools():
    """Return all available tools as a list."""
    return [get_search_tool(), get_scrape_tool(), get_image_gen_tool()]

