# Benchmark Summary Report

Generated: 2026-07-24 11:26 UTC  
Total duration: 1291s  

## Overall Ranking

| Rank | Model | Success Rate | Avg Time | P95 | Avg SQL Time | Timeout | Retries | Overall Score |
|------|-------|-------------:|---------:|----:|-------------:|--------:|--------:|--------------:|
| 1 | qwen3:8b | 97.3% | 17.4 s | 54.2 s | 2 ms | 0.0% | 0.0% | 0.914 |

## Performance Breakdown

| Model | Avg Workflow | SQL Gen | Analytics | Insight | Report | Total LLM Time |
|-------|-------------:|--------:|----------:|--------:|-------:|---------------:|
| qwen3:8b | 17.4 s | 2 ms | 801.5 ms | 3.1 s | 325 ms | 3.4 s |

## Accuracy Breakdown

| Model | Listing | Count | Trend | Comparison | Analytics | Ranking | Date | Overall |
|-------|----:|----:|----:|----:|----:|----:|----:|----:|
| qwen3:8b | 88.9% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 88.9% | 97.3% |

## Failure Analysis

| Model | Timeout | Invalid SQL | Wrong Entity | Wrong Join | Pipeline Error | Empty Result | SQL Gen Failed | Unneeded Clarification |
|-------|----:|----:|----:|----:|----:|----:|----:|----:|
| qwen3:8b | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |

## Resource Usage

| Model | Avg Prompt Tokens | Avg Completion Tokens | Avg Total Tokens |
|-------|------------------:|----------------------:|-----------------:|
| qwen3:8b | 6 | 4 | 10 |

## Recommendation

**Fastest Model:** qwen3:8b (17.4 s avg)

**Most Accurate Model:** qwen3:8b (97.3% success)

**Best Overall Model:** qwen3:8b (score 0.914)

**Recommended Production Model:** qwen3:8b

**Reason:** 'qwen3:8b' has the highest overall score (0.914) combining a 97.3% success rate with an average total latency of 17.4 s (P95 54.2 s, timeout rate 0.0%).

## Charts

![Average latency per model](../charts/avg_latency.png)

![SQL generation latency](../charts/sql_generation_latency.png)

![Success rate](../charts/success_rate.png)

![Timeout rate](../charts/timeout_rate.png)

![Overall score](../charts/overall_score.png)

![Category accuracy](../charts/category_accuracy.png)

![Token usage](../charts/token_usage.png)

![Latency distribution](../charts/latency_distribution.png)
