# Report Generation Template

You are tasked with summarizing query results into a structured markdown report.

## User Question
{question}

## Query Executed
```sql
{query}
```

## Results Data
{results}

## Instructions
Please format the narrative response precisely using the following section headers in this deterministic order:

# [Report Title]

## Executive Summary
[A concise 2-3 sentence executive summary explaining the overall findings]

## Key Findings
[List the main insights and key metrics, using a Markdown table where appropriate to summarize the dataset]

## Recommendations
[Any actionable suggestions or next steps based on the findings]

## Data Notes
[Brief documentation on data truncation or metrics, noting original vs. truncated rows if applicable]

