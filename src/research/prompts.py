"""Prompt templates for each research pipeline stage."""

from datetime import date

AGENT_SELECTION_PROMPT = """\
You are a research assistant selector. Given a research query, choose the most \
appropriate researcher persona.

Respond with a JSON object containing exactly two fields:
- "agent": a short name with emoji (e.g. "💰 Finance Agent")
- "role": a one-sentence role description for the researcher

Query: "{query}"
"""

PLAN_QUERIES_PROMPT = """\
Write {breadth} focused Google search queries to research the following topic \
from multiple angles. Each query should explore a different aspect.

Topic: "{query}"
Current date: {date}

{context_section}
Respond with ONLY a JSON array of strings, e.g. ["query 1", "query 2"].
"""

FOLLOW_UP_PROMPT = """\
Based on the following research findings, generate {breadth} follow-up search \
queries that explore gaps, unanswered questions, or deeper aspects of the topic.

Original query: "{query}"
Current date: {date}

Findings so far:
{learnings}

Respond with ONLY a JSON array of strings.
"""

REPORT_PROMPT = """\
Information:
\"\"\"{context}\"\"\"

Using the above information, write a detailed research report answering: "{query}"

Requirements:
- At least {min_words} words, well-structured with markdown
- Use ## for major sections and ### for subsections
- Include facts, numbers, and statistics where available
- Use APA in-text citations as markdown hyperlinks: ([Author, Year](url))
- Add a references section at the end with full URLs
- Determine your own concrete opinion based on the evidence
- Prioritize reliable, recent sources
- Use markdown tables for comparisons or structured data
- Current date: {date}
- Language: English
"""

DETAILED_REPORT_PROMPT = """\
Using the following hierarchically researched information and citations:

\"\"\"{context}\"\"\"

Write a comprehensive, in-depth research report answering: "{query}"

Requirements:
- At least {min_words} words with thorough analysis
- Synthesize information from multiple levels of research depth
- Present a coherent narrative from foundational to advanced insights
- Use ## for major sections and ### for subsections
- Use APA in-text citations as markdown hyperlinks: ([Author, Year](url))
- Add a references section at the end with full URLs
- Include markdown tables for comparisons and structured data
- Highlight connections between different research branches
- Include statistics, data, and concrete examples
- Current date: {date}
- Language: English
"""

SUMMARIZE_PROMPT = """\
{text}

Summarize the above text based on the following query: "{query}"
If the query cannot be answered using the text, summarize it briefly.
Include all factual information such as numbers, stats, and quotes.
"""


def format_plan_prompt(query: str, breadth: int, context: str = "") -> str:
    context_section = ""
    if context:
        context_section = (
            f"Use this prior research context to refine your queries:\n{context}\n\n"
        )
    return PLAN_QUERIES_PROMPT.format(
        query=query,
        breadth=breadth,
        date=date.today().isoformat(),
        context_section=context_section,
    )


def format_follow_up_prompt(query: str, breadth: int, learnings: str) -> str:
    return FOLLOW_UP_PROMPT.format(
        query=query,
        breadth=breadth,
        date=date.today().isoformat(),
        learnings=learnings,
    )


def format_report_prompt(
    query: str, context: str, detailed: bool = False, min_words: int = 1000
) -> str:
    template = DETAILED_REPORT_PROMPT if detailed else REPORT_PROMPT
    return template.format(
        query=query,
        context=context,
        date=date.today().isoformat(),
        min_words=min_words,
    )
