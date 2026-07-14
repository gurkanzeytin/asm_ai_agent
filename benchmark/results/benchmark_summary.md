# Benchmark Summary Report

Generated: 2026-07-14 06:51 UTC  
Total duration: 92s  

## Overall Ranking

| Rank | Model | Success Rate | Avg Time | P95 | Avg SQL Time | Timeout | Retries | Overall Score |
|------|-------|-------------:|---------:|----:|-------------:|--------:|--------:|--------------:|
| 1 | qwen3:8b | 93.8% | 5.6 s | 18.4 s | 3.1 s | 0.0% | 0.0% | 0.953 |

## Performance Breakdown

| Model | Avg Workflow | SQL Gen | Analytics | Insight | Report | Total LLM Time |
|-------|-------------:|--------:|----------:|--------:|-------:|---------------:|
| qwen3:8b | 5.6 s | 3.1 s | 0.2 ms | 1.9 s | 0 ms | 5.0 s |

## Accuracy Breakdown

| Model | Listing | Count | Trend | Comparison | Analytics | Ranking | Date | Overall |
|-------|----:|----:|----:|----:|----:|----:|----:|----:|
| qwen3:8b | — | 100.0% | — | 80.0% | — | — | — | 93.8% |

## Failure Analysis

| Model | Timeout | Invalid SQL | Wrong Entity | Wrong Join | Pipeline Error | Empty Result | SQL Gen Failed |
|-------|----:|----:|----:|----:|----:|----:|----:|
| qwen3:8b | 0 | 0 | 0 | 0 | 0 | 1 | 0 |

## Resource Usage

| Model | Avg Prompt Tokens | Avg Completion Tokens | Avg Total Tokens |
|-------|------------------:|----------------------:|-----------------:|
| qwen3:8b | 605 | 70 | 676 |

## Recommendation

**Fastest Model:** qwen3:8b (5.6 s avg)

**Most Accurate Model:** qwen3:8b (93.8% success)

**Best Overall Model:** qwen3:8b (score 0.953)

**Recommended Production Model:** qwen3:8b

**Reason:** 'qwen3:8b' has the highest overall score (0.953) combining a 93.8% success rate with an average total latency of 5.6 s (P95 18.4 s, timeout rate 0.0%).

## Charts

![Average latency per model](../charts/avg_latency.png)

![SQL generation latency](../charts/sql_generation_latency.png)

![Success rate](../charts/success_rate.png)

![Timeout rate](../charts/timeout_rate.png)

![Overall score](../charts/overall_score.png)

![Category accuracy](../charts/category_accuracy.png)

![Token usage](../charts/token_usage.png)

![Latency distribution](../charts/latency_distribution.png)
