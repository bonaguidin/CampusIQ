import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  MIN_SEARCH_LENGTH,
  SEARCH_DEBOUNCE_MS,
  formatCredits,
} from '../lib/termPlanning.mjs';
import type { CatalogSearchResult } from '../lib/termPlanning.mjs';
import { searchCatalog } from '../api/planning';
import type { AnalysisIdentity } from '../api/analysisApi.mjs';

/**
 * The debounced catalog search + results list, extracted verbatim from
 * TermPlanner so the year-view term card can offer the same "plan a course"
 * control without a second copy of the search infrastructure.
 *
 * This component owns ONLY the search: the query box, the debounce, the
 * results, and the disabled/"Planned" state of each Add button. What "Add"
 * does -- which route, which term, planned vs. in-progress -- is entirely the
 * parent's, passed as `onAdd`. TermPlanner keeps its activation-aware
 * handler; the year view passes a force-planned one.
 */
export function CourseSearchAdd({
  identity,
  alreadyAddedCodes,
  onAdd,
  busyCode,
  inputId = 'course-search',
  label = 'Search your course catalog by code or title',
  placeholder = 'e.g. CSCE 121 or Data Structures',
  hint = null,
}: {
  identity: AnalysisIdentity;
  /** Uppercased course codes already added to this term, for disabling Add. */
  alreadyAddedCodes: Set<string>;
  onAdd: (result: CatalogSearchResult) => void;
  busyCode: string | null;
  inputId?: string;
  label?: string;
  placeholder?: string;
  /** Rendered between the input and the search hints (e.g. an activation notice). */
  hint?: ReactNode;
}) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<CatalogSearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  // Debounced search. The timer is cleared on every keystroke and on unmount,
  // so at most one request is in flight per pause.
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    const trimmed = query.trim();
    if (trimmed.length < MIN_SEARCH_LENGTH) {
      setResults([]);
      setSearching(false);
      return undefined;
    }
    setSearching(true);
    searchTimer.current = setTimeout(() => {
      void (async () => {
        const result = await searchCatalog(identity, trimmed);
        setResults(result.results);
        setSearching(false);
      })();
    }, SEARCH_DEBOUNCE_MS);
    return () => { if (searchTimer.current) clearTimeout(searchTimer.current); };
  }, [query, identity]);

  return (
    <>
      <label className="term-search-label" htmlFor={inputId}>{label}</label>
      <input
        id={inputId}
        className="term-search-input"
        type="search"
        value={query}
        placeholder={placeholder}
        onChange={(event) => setQuery(event.target.value)}
        autoComplete="off"
      />
      {hint}
      {query.trim().length > 0 && query.trim().length < MIN_SEARCH_LENGTH && (
        <p className="term-search-hint">Keep typing…</p>
      )}
      {searching && <p className="term-search-hint">Searching…</p>}
      {!searching && query.trim().length >= MIN_SEARCH_LENGTH && results.length === 0 && (
        <p className="term-search-hint">
          No matches. Search matches the start of a course code or title.
        </p>
      )}
      {results.length > 0 && (
        <ul className="term-search-results">
          {results.map((result) => {
            const isAdded = alreadyAddedCodes.has(result.code.toUpperCase());
            const credits = formatCredits(result.credit_min, result.credit_max);
            return (
              <li className="term-search-result" key={result.id}>
                <span className="term-search-result-main">
                  <strong>{result.code}</strong>
                  <small>{result.title}</small>
                </span>
                {credits && <span className="term-search-result-credits">{credits}</span>}
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={isAdded || busyCode === result.code}
                  onClick={() => { onAdd(result); }}
                >
                  {isAdded ? 'Planned' : busyCode === result.code ? 'Adding…' : 'Add'}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
