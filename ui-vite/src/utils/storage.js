export const safeJsonParse = (value, fallback = null) => {
  if (value === null || value === undefined) return fallback;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
};
