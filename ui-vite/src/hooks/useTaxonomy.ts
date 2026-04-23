// src/hooks/useTaxonomy.ts
/**
 * useTaxonomy — React hook for loading taxonomy options from the API.
 *
 * Caches the result in a module-level promise so that multiple components
 * share a single fetch (no duplicate network requests).
 *
 * Usage:
 *   const { skills, interests, education, loading, error } = useTaxonomy();
 */

import { useState, useEffect } from 'react';
import { fetchTaxonomyList, type TaxonomyList, type TaxonomyOption } from '../services/taxonomyApi';

// ─── Module-level cache ──────────────────────────────────────────────────────
let _cache: TaxonomyList | null = null;
let _promise: Promise<TaxonomyList> | null = null;

function getTaxonomyList(): Promise<TaxonomyList> {
  if (_cache) return Promise.resolve(_cache);
  if (_promise) return _promise;
  _promise = fetchTaxonomyList().then((data) => {
    _cache = data;
    return data;
  });
  return _promise;
}

/** Call this in tests to reset the module-level cache. */
export function _resetTaxonomyCache() {
  _cache = null;
  _promise = null;
}

// ─── Hook ────────────────────────────────────────────────────────────────────

interface UseTaxonomyResult {
  skills: TaxonomyOption[];
  interests: TaxonomyOption[];
  education: TaxonomyOption[];
  loading: boolean;
  error: string | null;
}

const EMPTY: UseTaxonomyResult = {
  skills: [],
  interests: [],
  education: [],
  loading: true,
  error: null,
};

export function useTaxonomy(): UseTaxonomyResult {
  const [state, setState] = useState<UseTaxonomyResult>(EMPTY);

  useEffect(() => {
    let cancelled = false;

    getTaxonomyList()
      .then((data) => {
        if (!cancelled) {
          setState({
            skills: data.skills,
            interests: data.interests,
            education: data.education,
            loading: false,
            error: null,
          });
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setState({
            skills: [],
            interests: [],
            education: [],
            loading: false,
            error: err instanceof Error ? err.message : 'Taxonomy load failed',
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
