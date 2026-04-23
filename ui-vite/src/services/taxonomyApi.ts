// src/services/taxonomyApi.ts
/**
 * Taxonomy API Service
 * ====================
 *
 * Fetches canonical taxonomy lists from the backend.
 * Used to populate dropdowns/selectors without hardcoding values.
 *
 * Endpoint: GET /api/v1/taxonomy/list  (public, no auth required)
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

export interface TaxonomyOption {
  id: string;
  label: string;
}

export interface TaxonomyList {
  skills: TaxonomyOption[];
  interests: TaxonomyOption[];
  education: TaxonomyOption[];
}

/**
 * Fetch the full taxonomy list from the backend.
 * Returns skills, interests, and education options (deprecated entries excluded).
 */
export async function fetchTaxonomyList(): Promise<TaxonomyList> {
  const response = await fetch(`${API_BASE}/api/v1/taxonomy/list`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  });

  if (!response.ok) {
    throw new Error(`Taxonomy fetch failed: ${response.status} ${response.statusText}`);
  }

  const json = await response.json();

  // Response contract: { success: true, data: { skills, interests, education } }
  if (!json.data) {
    throw new Error('Unexpected taxonomy response shape');
  }

  return json.data as TaxonomyList;
}
