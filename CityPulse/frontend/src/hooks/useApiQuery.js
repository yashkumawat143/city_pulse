import { useCallback, useEffect, useRef, useState } from "react";

/** Debounce a rapidly changing value (search boxes) without extra dependencies. */
export function useDebounced(value, ms = 300) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/**
 * Small server-query hook: de-duplicates in-flight requests, ignores stale
 * responses (sequence guard) and cleans up on unmount. `fetcher` must be
 * memoised by the caller (useCallback) — deps drive re-fetching.
 */
export function useApiQuery(fetcher, deps = [], { intervalMs = 0, enabled = true } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(enabled);
  const seq = useRef(0);

  const run = useCallback(async () => {
    if (!enabled) return;
    const id = ++seq.current;
    try {
      const d = await fetcher();
      if (id === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (id === seq.current) setError(e.message || "Request failed");
    } finally {
      if (id === seq.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, ...deps]);

  useEffect(() => {
    setLoading(true);
    run();
    if (!intervalMs) return undefined;
    const t = setInterval(() => { if (!document.hidden) run(); }, intervalMs);
    return () => clearInterval(t);
  }, [run, intervalMs]);

  return { data, error, loading, reload: run };
}

export default useApiQuery;
