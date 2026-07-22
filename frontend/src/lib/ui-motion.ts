export const uiEase = [0.22, 1, 0.36, 1] as const;

export const uiTransition = {
  duration: 0.2,
  ease: uiEase,
} as const;

export const panelTransition = {
  duration: 0.24,
  ease: uiEase,
} as const;

export const quickTransition = {
  duration: 0.16,
  ease: uiEase,
} as const;
