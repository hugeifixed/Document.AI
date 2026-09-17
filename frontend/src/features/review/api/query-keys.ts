export const reviewKeys = {
  groups: (filters: Record<string, string | number | undefined>) => ["review-document-groups", filters] as const,
};
