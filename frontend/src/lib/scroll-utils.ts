export interface ScrollMetrics {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
}

export function isNearScrollBottom(metrics: ScrollMetrics, threshold = 96) {
  return metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight <= threshold;
}
