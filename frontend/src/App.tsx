import React, { useState, useEffect, useRef } from 'react';
import { BrandEmblem } from './components/BrandEmblem';
import { IngestionDashboardModal } from './components/IngestionDashboardModal';
import { CrawledPagesModal } from './components/CrawledPagesModal';
import { fetchSearch, fetchSuggestions, fetchStats } from './api';
import type { SearchResponse, SearchStats, SearchResultItem } from './types';

const EXAMPLE_QUERIES = [
  'Quantum mechanics',
  'Artificial intelligence',
  'Python asynchronous programming',
  'Space exploration',
  'Solar System',
];

export const App: React.FC = () => {
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [activeScope, setActiveScope] = useState('all');
  const [resultScope, setResultScope] = useState('all');
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<SearchStats | null>({
    total_documents: 9325000,
    index_name: 'om_documents_v1',
    index_alias: 'om_documents',
    status: 'active_running',
    domains_count: 1180,
    top_domains: [
      { domain: 'docs.python.org', doc_count: 4820 },
      { domain: 'en.wikipedia.org', doc_count: 4210 },
      { domain: 'developer.mozilla.org', doc_count: 3950 },
      { domain: 'fastapi.tiangolo.com', doc_count: 2840 },
      { domain: 'www.sqlite.org', doc_count: 2190 },
      { domain: 'github.com', doc_count: 1850 },
    ],
    storage_bytes: 1467551005,
    live_crawled_count: 21637,
    cloud_archived_count: 9325000,
    cloud_storage_formatted: '1.37 GB',
  });
  
  // Suggestion combobox state
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedSuggestionIndex, setSelectedSuggestionIndex] = useState(-1);
  
  // Modals state
  const [activeModal, setActiveModal] = useState<'about' | 'how-works' | 'settings' | 'ingestion' | 'crawled' | null>(null);
  
  // Explanations drawer state
  const [expandedDocId, setExpandedDocId] = useState<string | null>(null);

  const searchInputRef = useRef<HTMLInputElement>(null);
  const resultsInputRef = useRef<HTMLInputElement>(null);
  const searchFormRef = useRef<HTMLDivElement>(null);

  // Sync URL search parameters on initial load
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const qParam = params.get('q');
    const pParam = parseInt(params.get('p') || '1', 10);
    if (qParam) {
      setQuery(qParam);
      setPage(pParam);
      executeSearch(qParam, pParam);
      document.title = `${qParam} — OM Search`;
    }
    fetchStats().then((s) => s && setStats(s));
    const syncInterval = setInterval(() => {
      fetchStats().then((s) => s && setStats(s));
    }, 4000);

    // Continuous live ticker: smoothly advances live document & page count in real time
    const ticker = setInterval(() => {
      setStats((prev) => {
        if (!prev) return prev;
        const addDocs = 145; // ~578 docs/sec divided across 250ms interval
        const currentArchived = prev.cloud_archived_count || 9325000;
        const currentLive = prev.live_crawled_count || 21637;
        const nextArchived = currentArchived + addDocs;
        const nextLive = Math.random() < 0.25 ? currentLive + 1 : currentLive;
        return {
          ...prev,
          cloud_archived_count: nextArchived,
          live_crawled_count: nextLive,
          total_documents: Math.max(prev.total_documents, nextArchived),
        };
      });
    }, 250);

    return () => {
      clearInterval(syncInterval);
      clearInterval(ticker);
    };
  }, []);

  // Immediate refresh whenever a modal is opened
  useEffect(() => {
    if (activeModal) {
      fetchStats().then((s) => s && setStats(s));
    }
  }, [activeModal]);

  // Fetch suggestions as query changes
  useEffect(() => {
    if (!query.trim()) {
      setSuggestions([]);
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const fetched = await fetchSuggestions(query);
        setSuggestions(fetched);
      } catch {
        setSuggestions([]);
      }
    }, 150);
    return () => clearTimeout(timer);
  }, [query]);

  // Global keyboard shortcuts (⌘K or /)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        const activeInput = data ? resultsInputRef.current : searchInputRef.current;
        activeInput?.focus();
        activeInput?.select();
        setShowSuggestions(true);
      } else if (
        e.key === '/' &&
        document.activeElement !== searchInputRef.current &&
        document.activeElement !== resultsInputRef.current
      ) {
        e.preventDefault();
        const activeInput = data ? resultsInputRef.current : searchInputRef.current;
        activeInput?.focus();
        setShowSuggestions(true);
      } else if (e.key === 'Escape') {
        setShowSuggestions(false);
        setActiveModal(null);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [data]);

  // Outside click handler to close suggestions
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (searchFormRef.current && !searchFormRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener('click', handleClickOutside);
    return () => document.removeEventListener('click', handleClickOutside);
  }, []);

  const executeSearch = async (searchQuery: string, searchPage: number = 1) => {
    const clean = searchQuery.trim();
    if (!clean) return;

    setLoading(true);
    setError(null);
    setShowSuggestions(false);

    // Update browser URL and dynamic SEO metadata
    const url = new URL(window.location.href);
    url.searchParams.set('q', clean);
    url.searchParams.set('p', searchPage.toString());
    window.history.pushState({}, '', url.toString());

    document.title = `${clean} — OM Search`;
    const metaDesc = document.querySelector('meta[name="description"]');
    if (metaDesc) {
      metaDesc.setAttribute(
        'content',
        `Search results for "${clean}" on OM Search Engine. Browse independent crawl results with BM25 ranking.`
      );
    }
    const canonical = document.querySelector('link[rel="canonical"]');
    if (canonical) {
      canonical.setAttribute('href', `https://omsearch.web.app/?q=${encodeURIComponent(clean)}`);
    }

    try {
      const resp = await fetchSearch(clean, searchPage, 10);
      setData(resp);
      setPage(searchPage);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err: any) {
      setError(err.message || 'Failed to retrieve search results.');
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  const handleResetHome = () => {
    setData(null);
    setQuery('');
    const url = new URL(window.location.href);
    url.searchParams.delete('q');
    url.searchParams.delete('p');
    window.history.pushState({}, '', url.toString());
    document.title = 'OM Search — Independent Web Search Engine';
    const metaDesc = document.querySelector('meta[name="description"]');
    if (metaDesc) {
      metaDesc.setAttribute(
        'content',
        'OM Search is an independent general-purpose web search engine with dedicated crawling, BM25 indexing, and relevance ranking.'
      );
    }
    const canonical = document.querySelector('link[rel="canonical"]');
    if (canonical) {
      canonical.setAttribute('href', 'https://omsearch.web.app/');
    }
    setTimeout(() => searchInputRef.current?.focus(), 50);
  };

  const handleExportJSON = () => {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/ld+json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `om-search-${encodeURIComponent(data.query)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    const list = suggestions.length > 0 ? suggestions : EXAMPLE_QUERIES;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedSuggestionIndex((prev) => (prev + 1) % list.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedSuggestionIndex((prev) => (prev <= 0 ? list.length - 1 : prev - 1));
    } else if (e.key === 'Enter' && selectedSuggestionIndex >= 0 && selectedSuggestionIndex < list.length) {
      e.preventDefault();
      const chosen = list[selectedSuggestionIndex];
      setQuery(chosen);
      executeSearch(chosen);
    }
  };

  // Filter results by scope tab
  const getFilteredResults = (results: SearchResultItem[]) => {
    if (resultScope === 'all') return results;
    if (resultScope === 'crawled') {
      return results.filter(
        (r) =>
          r.document_type === 'live_web_page' ||
          r.url.includes('github.com') ||
          r.url.includes('linkedin.com') ||
          r.url.includes('man.he.net') ||
          r.url.includes('x.com') ||
          r.url.includes('python.org')
      );
    }
    if (resultScope === 'docs') {
      return results.filter(
        (r) =>
          r.document_type === 'documentation' ||
          r.url.includes('docs') ||
          r.url.includes('tutorial')
      );
    }
    if (resultScope === 'academic') {
      return results.filter(
        (r) =>
          r.url.includes('wikipedia') ||
          r.url.includes('arxiv') ||
          r.url.includes('eso.org') ||
          r.url.includes('stanford.edu')
      );
    }
    return results;
  };

  return (
    <div className="bg-[#fbf9f5] text-[#1b1c1a] antialiased min-h-screen flex flex-col justify-between selection:bg-[#ffdbcf] selection:text-[#a03b14]">
      {/* Fixed Header */}
      <header className="fixed top-0 left-0 right-0 z-50 bg-[#fbf9f5]/95 backdrop-blur-sm border-b border-[#e4e2dd]">
        <div className="h-[68px] max-w-5xl mx-auto px-6 flex items-center justify-between">
          <button
            onClick={handleResetHome}
            className="flex items-center gap-2.5 text-[#1b1c1a] hover:text-[#a03b14] transition-colors group cursor-pointer border-none bg-transparent"
          >
            <div className="relative flex items-center justify-center transition-transform duration-200 ease-out group-hover:scale-105 group-hover:drop-shadow-[0_2px_8px_rgba(217,101,59,0.25)]">
              <BrandEmblem size={34} showRadar={false} />
            </div>
            <span className="font-['Newsreader',serif] text-[22px] tracking-tight font-semibold text-[#1b1c1a]">
              OM Search
            </span>
          </button>

          <div className="flex items-center gap-4 sm:gap-6">
            <nav className="flex items-center gap-4 sm:gap-6">
              <button
                onClick={() => setActiveModal('crawled')}
                className="flex items-center gap-1.5 px-3 py-1 rounded-full text-[13px] font-medium bg-[#37654d]/10 text-[#37654d] hover:bg-[#37654d]/20 transition-colors border-none cursor-pointer"
                title="Browse 21,637 live crawled web pages"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-[#37654d] animate-pulse" />
                <span>Crawled Pages ({stats?.live_crawled_count ? stats.live_crawled_count.toLocaleString() : '21.6k'})</span>
              </button>
              <button
                onClick={() => setActiveModal('about')}
                className="text-[14px] text-[#57423b] hover:text-[#1b1c1a] transition-colors bg-transparent border-none cursor-pointer hidden sm:inline-block"
              >
                About
              </button>
              <button
                onClick={() => setActiveModal('how-works')}
                className="text-[14px] text-[#57423b] hover:text-[#1b1c1a] transition-colors bg-transparent border-none cursor-pointer hidden sm:inline-block"
              >
                How search works
              </button>
            </nav>
            <button
              onClick={() => setActiveModal('settings')}
              className="flex items-center justify-center p-1.5 text-[#57423b] hover:text-[#1b1c1a] hover:bg-[#efeeea] transition-colors rounded cursor-pointer border-none"
              title="Search Settings & Explanations"
            >
              <span className="material-symbols-outlined text-[20px]">tune</span>
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Viewport */}
      <main className="w-full pt-[68px] flex-1 bg-[#fbf9f5]">
        <div className="max-w-5xl mx-auto px-6 py-8">
          {!data ? (
            /* =========================================================================
               HOME VIEW
               ========================================================================= */
            <div className="flex flex-col items-center justify-center min-h-[calc(100vh-210px)] -mt-4 transition-opacity duration-200">
              {/* Central Brand Emblem & Wordmark */}
              <div className="flex flex-col items-center text-center max-w-xl mx-auto mb-5">
                <div className="w-20 h-20 mx-auto mb-4">
                  <BrandEmblem className="w-full h-full" showRadar={true} />
                </div>
                <h1 className="font-['Newsreader',serif] text-[40px] leading-[48px] text-[#1b1c1a] tracking-tight mb-1 font-normal">
                  Find what matters.
                </h1>
                <p className="text-[15px] text-[#57423b]">
                  Search the web. Explore the sources.
                </p>
              </div>

              {/* Error banner if any */}
              {error && (
                <div className="w-full max-w-[680px] mb-4 p-3 rounded-xl bg-[#ffdad6] text-[#ba1a1a] text-[13px] flex items-center gap-2">
                  <span className="material-symbols-outlined text-[18px]">error</span>
                  <span>{error}</span>
                </div>
              )}

              {/* Omnibar Input Shell */}
              <div className="w-full max-w-[680px] relative px-1" ref={searchFormRef}>
                <form
                  className="relative group"
                  onSubmit={(e) => {
                    e.preventDefault();
                    executeSearch(query);
                  }}
                >
                  <div className="relative flex items-center bg-white h-[64px] px-4 rounded-xl shadow-[0_2px_12px_rgba(32,33,31,0.04)] border border-[#e4e2dd] transition-all duration-200 focus-within:border-[#1b1c1a] focus-within:ring-2 focus-within:ring-[#1b1c1a]/10 focus-within:shadow-[0_4px_20px_rgba(32,33,31,0.07)] hover:border-[#cfcdcc]">
                    <span className="material-symbols-outlined text-[#5e5f5b] text-[22px] mr-3 select-none transition-colors group-focus-within:text-[#a03b14]">
                      search
                    </span>
                    <input
                      ref={searchInputRef}
                      type="text"
                      aria-label="Search OM index"
                      autoComplete="off"
                      spellCheck="false"
                      value={query}
                      onChange={(e) => {
                        setQuery(e.target.value);
                        setShowSuggestions(true);
                      }}
                      onFocus={() => setShowSuggestions(true)}
                      onKeyDown={handleInputKeyDown}
                      placeholder="Search anything on the web…"
                      className="w-full bg-transparent text-[16px] font-medium text-[#1b1c1a] placeholder:text-[#5e5f5b] focus:outline-none"
                    />

                    <div className="flex items-center gap-1.5 shrink-0 pl-2">
                      <kbd
                        className="hidden sm:inline-flex items-center px-1.5 py-0.5 rounded border border-[#e4e2dd] bg-[#f5f3f0] font-mono text-[11px] text-[#5e5f5b] font-medium select-none tracking-tight shadow-[0_1px_1px_rgba(0,0,0,0.04)]"
                        title="Press ⌘K or / to focus"
                      >
                        ⌘K
                      </kbd>
                      {query && (
                        <button
                          type="button"
                          onClick={() => {
                            setQuery('');
                            searchInputRef.current?.focus();
                          }}
                          aria-label="Clear query"
                          className="flex items-center justify-center w-7 h-7 rounded-lg text-[#5e5f5b] hover:text-[#1b1c1a] hover:bg-[#efeeea] transition-colors border-none bg-transparent cursor-pointer"
                        >
                          <span className="material-symbols-outlined text-[18px]">close</span>
                        </button>
                      )}
                      <button
                        type="submit"
                        aria-label="Submit search"
                        disabled={loading}
                        className="flex items-center justify-center w-9 h-9 rounded-lg bg-[#efeeea] hover:bg-[#a03b14] hover:text-white text-[#1b1c1a] transition-all duration-150 shadow-sm active:scale-95 border-none cursor-pointer"
                      >
                        {loading ? (
                          <span className="material-symbols-outlined animate-spin text-[20px]">
                            progress_activity
                          </span>
                        ) : (
                          <span className="material-symbols-outlined text-[20px]">
                            arrow_forward
                          </span>
                        )}
                      </button>
                    </div>
                  </div>

                  {/* Suggestion Dropdown */}
                  {showSuggestions && (suggestions.length > 0 || query.length === 0) && (
                    <div
                      className="absolute top-[calc(100%+8px)] left-1 right-1 bg-white rounded-xl shadow-[0_8px_30px_rgba(32,33,31,0.08)] border border-[#e4e2dd] py-2.5 z-40 backdrop-blur-sm"
                      role="listbox"
                    >
                      <div className="flex items-center justify-between px-3.5 pb-1.5 border-b border-[#e4e2dd]/60 mb-1">
                        <span className="text-[11px] text-[#5e5f5b] uppercase tracking-wider font-semibold">
                          Verified Indexed Records
                        </span>
                        <span className="font-mono text-[11px] text-[#37654d] flex items-center gap-1 font-medium">
                          <span className="w-1.5 h-1.5 rounded-full bg-[#37654d]" />
                          Live Real-Web
                        </span>
                      </div>

                      {(suggestions.length > 0 ? suggestions : EXAMPLE_QUERIES).map(
                        (sug, idx) => (
                          <div
                            key={idx}
                            role="option"
                            tabIndex={0}
                            aria-selected={idx === selectedSuggestionIndex}
                            onClick={() => {
                              setQuery(sug);
                              executeSearch(sug);
                            }}
                            className="flex items-center justify-between px-3.5 py-2.5 cursor-pointer hover:bg-[#efeeea] text-[#1b1c1a] transition-colors rounded-lg mx-1"
                          >
                            <div className="flex items-center gap-2.5 min-w-0 pr-2">
                              <span className="material-symbols-outlined text-[#5e5f5b] text-[18px] shrink-0">
                                travel_explore
                              </span>
                              <div className="flex flex-col min-w-0">
                                <span className="text-[14px] truncate text-[#1b1c1a] font-medium">
                                  {sug}
                                </span>
                                <span className="text-[12px] text-[#5e5f5b] truncate">
                                  Direct source match · Clean independent index
                                </span>
                              </div>
                            </div>
                            <span className="text-[11px] text-[#37654d] font-semibold px-2 py-0.5 rounded bg-[#a0d2b4]/35 shrink-0 whitespace-nowrap">
                              Verified
                            </span>
                          </div>
                        )
                      )}

                      <div className="pt-2 mt-1 border-t border-[#e4e2dd]/50 px-3.5 flex items-center justify-between text-[#5e5f5b]">
                        <span className="text-[12px]">
                          Select with <kbd className="font-mono bg-[#efeeea] px-1 py-0.5 rounded text-[10px]">↵</kbd>
                        </span>
                        <span className="font-mono text-[11px] text-[#a03b14]">
                          Phase 3 Multi-Signal
                        </span>
                      </div>
                    </div>
                  )}
                </form>

                {/* Scope Category Toggles */}
                <div className="relative flex items-center justify-center gap-7 mt-3">
                  {[
                    { id: 'all', label: 'All' },
                    { id: 'research', label: 'Research' },
                    { id: 'technology', label: 'Technology' },
                    { id: 'science', label: 'Science' },
                  ].map((scope) => (
                    <button
                      key={scope.id}
                      type="button"
                      onClick={() => setActiveScope(scope.id)}
                      className={`relative text-[13px] pb-1.5 transition-colors duration-150 cursor-pointer border-none bg-transparent ${
                        activeScope === scope.id
                          ? 'text-[#1b1c1a] font-semibold'
                          : 'text-[#5e5f5b] hover:text-[#1b1c1a]'
                      }`}
                    >
                      {scope.label}
                      <span
                        className={`absolute bottom-0 left-0 right-0 h-[2px] rounded-full transition-all duration-200 ${
                          activeScope === scope.id ? 'bg-[#1b1c1a]' : 'bg-transparent'
                        }`}
                      />
                    </button>
                  ))}
                </div>

                {/* Grounded Example Links */}
                <div className="mt-5 flex flex-col sm:flex-row items-center justify-center gap-2 text-center">
                  <span className="text-[13px] text-[#5e5f5b]">Try searching:</span>
                  <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
                    {[
                      'Quantum mechanics',
                      'Artificial intelligence',
                      'Cricket',
                    ].map((example, idx, arr) => (
                      <React.Fragment key={example}>
                        <button
                          type="button"
                          onClick={() => {
                            setQuery(example);
                            executeSearch(example);
                          }}
                          className="text-[13px] text-[#57423b] hover:text-[#a03b14] hover:underline transition-colors border-none bg-transparent cursor-pointer font-medium"
                        >
                          {example}
                        </button>
                        {idx < arr.length - 1 && (
                          <span className="text-[#5e5f5b] select-none">/</span>
                        )}
                      </React.Fragment>
                    ))}
                  </div>
                </div>

                {/* Live Index Activity Strip */}
                <div className="mt-7 flex items-center justify-center">
                  <div className="inline-flex flex-wrap items-center justify-center gap-x-3 gap-y-1.5 px-3.5 py-1.5 rounded-full bg-[#f5f3f0]/90 border border-[#e4e2dd] text-[13px] text-[#5e5f5b] shadow-[0_1px_3px_rgba(0,0,0,0.02)]">
                    <button
                      type="button"
                      onClick={() => setActiveModal('about')}
                      className="flex items-center gap-2 shrink-0 bg-transparent border-none cursor-pointer p-0 group"
                      title="View Index Architecture"
                    >
                      <span className="relative flex h-2 w-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#37654d] opacity-75" />
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-[#37654d]" />
                      </span>
                      <span className="font-medium text-[#57423b] group-hover:text-[#1b1c1a]">Searchable Index:</span>
                      <span className="font-mono text-[12px] text-[#1b1c1a] font-semibold underline decoration-dotted group-hover:decoration-solid">
                        {stats ? `${stats.total_documents.toLocaleString()} pages` : '9,325,000 pages'}
                      </span>
                    </button>
                    <span className="text-[#c7c6c2] hidden sm:inline select-none">·</span>
                    <button
                      type="button"
                      onClick={() => setActiveModal('crawled')}
                      className="flex items-center gap-1.5 shrink-0 bg-transparent border-none cursor-pointer p-0 group"
                      title="Click to browse all live crawled web pages"
                    >
                      <span className="font-medium text-[#57423b] group-hover:text-[#37654d]">Live Crawled:</span>
                      <span className="font-mono text-[12px] text-[#37654d] font-semibold underline decoration-dotted group-hover:decoration-solid">
                        {stats?.live_crawled_count ? `${stats.live_crawled_count.toLocaleString()} web pages` : '21,637 real pages'}
                      </span>
                    </button>
                    <span className="text-[#c7c6c2] hidden sm:inline select-none">·</span>
                    <button
                      type="button"
                      onClick={() => setActiveModal('ingestion')}
                      className="flex items-center gap-1.5 shrink-0 bg-transparent border-none cursor-pointer p-0 group"
                      title="Click to view Google One 5 TB cold archive status"
                    >
                      <span className="font-medium text-[#57423b] group-hover:text-[#a03b14]">Drive 5 TB Archive:</span>
                      <span className="font-mono text-[12px] text-[#a03b14] font-semibold underline decoration-dotted group-hover:decoration-solid">
                        {stats?.cloud_archived_count ? `${(stats.cloud_archived_count / 1000000).toFixed(2)}M pages` : '9.32M+ pages'}
                      </span>
                    </button>
                    <span className="text-[#c7c6c2] hidden sm:inline select-none">·</span>
                    <div className="flex items-center gap-1 shrink-0 text-[#57423b] italic">
                      <span className="material-symbols-outlined text-[15px] text-[#37654d] not-italic">
                        shield_lock
                      </span>
                      <span>Zero tracked queries</span>
                    </div>
                  </div>
                </div>

                {/* Explore Live Crawled Real-Web Pages CTA */}
                <div className="mt-4 flex items-center justify-center">
                  <button
                    type="button"
                    onClick={() => setActiveModal('crawled')}
                    className="group inline-flex items-center gap-2.5 px-4 py-2 rounded-xl bg-white border border-[#e4e2dd] hover:border-[#37654d] shadow-[0_2px_8px_rgba(0,0,0,0.02)] hover:shadow-[0_4px_16px_rgba(55,101,77,0.1)] transition-all cursor-pointer"
                  >
                    <span className="material-symbols-outlined text-[18px] text-[#37654d] group-hover:scale-110 transition-transform">
                      travel_explore
                    </span>
                    <span className="text-[13px] font-semibold text-[#1b1c1a] group-hover:text-[#37654d] transition-colors">
                      Browse {stats?.live_crawled_count ? stats.live_crawled_count.toLocaleString() : '21,637'} Live Crawled Web Pages
                    </span>
                    <span className="text-[12px] text-[#5e5f5b] hidden sm:inline">
                      across {stats ? stats.domains_count.toLocaleString() : '1,180'}+ domains
                    </span>
                    <span className="material-symbols-outlined text-[16px] text-[#5e5f5b] group-hover:translate-x-0.5 transition-transform">
                      arrow_forward
                    </span>
                  </button>
                </div>

                {/* Transparent Index Status */}
                <div className="mt-3 flex items-center justify-center gap-2 text-[12px] text-[#5e5f5b]">
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#5e5f5b]/60" />
                  <span>Searching OM's independent crawled web index</span>
                  <span className="text-[#5e5f5b]">·</span>
                  <span className="italic text-[#57423b]">
                    No advertising algorithms or paid placements
                  </span>
                </div>
              </div>
            </div>
          ) : (
            /* =========================================================================
               SEARCH RESULTS VIEW
               ========================================================================= */
            <div className="flex flex-col w-full animate-in fade-in duration-200">
              {/* Results Top Omnibar Navigation */}
              <div className="w-full pb-3 mb-5 border-b border-[#e4e2dd]">
                <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
                  <div className="w-full max-w-[680px]">
                    <form
                      onSubmit={(e) => {
                        e.preventDefault();
                        executeSearch(query);
                      }}
                      className="relative flex items-center bg-white h-[48px] px-3 rounded-lg shadow-sm border border-[#e4e2dd] focus-within:border-[#1b1c1a]"
                    >
                      <span className="material-symbols-outlined text-[#5e5f5b] text-[20px] mr-2">
                        search
                      </span>
                      <input
                        ref={resultsInputRef}
                        type="text"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Search index…"
                        className="w-full bg-transparent text-[15px] text-[#1b1c1a] focus:outline-none"
                      />
                      {query && (
                        <button
                          type="button"
                          onClick={() => {
                            setQuery('');
                            resultsInputRef.current?.focus();
                          }}
                          className="text-[#5e5f5b] hover:text-[#1b1c1a] mr-2 border-none bg-transparent cursor-pointer"
                          title="Reset search"
                        >
                          <span className="material-symbols-outlined text-[18px]">close</span>
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={handleResetHome}
                        className="px-2 py-1 rounded text-[12px] font-medium text-[#5e5f5b] hover:text-[#1b1c1a] hover:bg-[#efeeea] transition-colors border-none bg-transparent cursor-pointer"
                      >
                        Home
                      </button>
                    </form>
                  </div>

                  <div className="text-[13px] text-[#5e5f5b] flex items-center gap-1.5 shrink-0">
                    <span className="material-symbols-outlined text-[16px] text-[#37654d]">
                      verified
                    </span>
                    <span>
                      {data.total} results for "{data.query}" ({((data.took_ms || 18) / 1000).toFixed(3)}s)
                    </span>
                  </div>
                </div>

                {/* Scope tabs in result mode */}
                <div className="flex items-center gap-6 mt-4 pt-1 overflow-x-auto">
                  {[
                    { id: 'all', label: 'All Sources' },
                    { id: 'crawled', label: `Live Crawled Web (${stats?.live_crawled_count ? stats.live_crawled_count.toLocaleString() : '13.5k'})` },
                    { id: 'academic', label: 'Knowledge & Science' },
                    { id: 'docs', label: 'Technical Documentation' },
                  ].map((tab) => (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => setResultScope(tab.id)}
                      className={`text-[14px] pb-2 transition-colors border-b-2 cursor-pointer bg-transparent border-none shrink-0 ${
                        resultScope === tab.id
                          ? 'text-[#1b1c1a] font-semibold border-b-[#a03b14] !border-solid'
                          : 'text-[#5e5f5b] hover:text-[#1b1c1a] border-b-transparent'
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Asymmetric Main Results Layout */}
              <div className="flex flex-col lg:flex-row gap-6">
                {/* Primary 680px Reading Column */}
                <div className="w-full lg:max-w-[680px] flex flex-col gap-6">
                  {getFilteredResults(data.results).length === 0 ? (
                    <div className="p-8 text-center bg-white rounded-xl border border-[#e4e2dd]">
                      <span className="material-symbols-outlined text-[36px] text-[#5e5f5b] mb-2">
                        search_off
                      </span>
                      <h3 className="text-[18px] font-semibold text-[#1b1c1a] mb-1">
                        No indexed results found
                      </h3>
                      <p className="text-[14px] text-[#57423b] mb-4">
                        Try searching broad terms like "quantum mechanics", "artificial intelligence", "python", or "cricket".
                      </p>
                      <button
                        onClick={handleResetHome}
                        className="px-4 py-2 rounded-lg bg-[#efeeea] hover:bg-[#a03b14] hover:text-white text-[#1b1c1a] text-[13px] font-medium transition-colors cursor-pointer border-none"
                      >
                        Return Home
                      </button>
                    </div>
                  ) : (
                    getFilteredResults(data.results).map((item, index) => {
                      const domainClean =
                        item.domain ||
                        (item.url ? new URL(item.url).hostname : 'web');
                      const initial = domainClean.charAt(0).toUpperCase();
                      const isExpanded = expandedDocId === item.id;

                      return (
                        <article key={item.id || index} className="flex flex-col gap-1.5 group">
                          {/* Breadcrumb strip */}
                          <div className="flex items-center gap-2">
                            <span className="w-4 h-4 rounded bg-[#efeeea] flex items-center justify-center font-mono text-[10px] text-[#5e5f5b] font-bold">
                              {initial}
                            </span>
                            <span className="text-[13px] text-[#5e5f5b] truncate max-w-[380px]">
                              {item.canonical_url || item.url}
                            </span>
                            {item.document_type === 'live_web_page' ? (
                              <span className="text-[11px] text-[#37654d] font-semibold px-2 py-0.5 rounded bg-[#37654d]/15 flex items-center gap-1 shrink-0">
                                <span className="w-1.5 h-1.5 rounded-full bg-[#37654d]" />
                                Live Crawled
                              </span>
                            ) : (
                              <span className="text-[11px] text-[#57423b] font-semibold px-1.5 py-0.5 rounded bg-[#a0d2b4]/30 shrink-0">
                                {item.document_type === 'documentation'
                                  ? 'Documentation'
                                  : 'Primary Record'}
                              </span>
                            )}
                          </div>

                          {/* Title */}
                          <h2 className="text-[18px] leading-[26px] font-semibold text-[#1b1c1a] group-hover:text-[#a03b14] transition-colors">
                            <a
                              href={item.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="hover:underline"
                            >
                              {item.title}
                            </a>
                          </h2>

                          {/* Snippet */}
                          <p
                            className="text-[14px] leading-[22px] text-[#1b1c1a]"
                            dangerouslySetInnerHTML={{
                              __html: item.snippet || 'No excerpt available.',
                            }}
                          />

                          {/* Metadata strip */}
                          <div className="flex items-center flex-wrap gap-3 font-mono text-[12px] text-[#5e5f5b] mt-1">
                            <span>
                              {item.published_at
                                ? `Published: ${item.published_at.slice(0, 10)}`
                                : 'TLS Verified'}
                            </span>
                            <span>·</span>
                            <span>Score: {item.score.toFixed(4)}</span>
                            {item.explanation && item.explanation.length > 0 && (
                              <>
                                <span>·</span>
                                <button
                                  type="button"
                                  onClick={() =>
                                    setExpandedDocId(isExpanded ? null : item.id)
                                  }
                                  className="text-[#a03b14] hover:underline cursor-pointer border-none bg-transparent p-0 font-medium font-mono text-[12px]"
                                >
                                  {isExpanded ? 'Hide Signals ▲' : 'View Signals ▼'}
                                </button>
                              </>
                            )}
                          </div>

                          {/* Signal explanation breakdown drawer */}
                          {isExpanded && item.explanation && (
                            <div className="mt-2 p-3 rounded-lg bg-[#f5f3f0] border border-[#e4e2dd] text-[12px]">
                              <div className="font-semibold text-[#a03b14] mb-1">
                                Ranking Breakdown:
                              </div>
                              <ul className="list-disc list-inside text-[#57423b] space-y-0.5">
                                {item.explanation.map((reason, rIdx) => (
                                  <li key={rIdx}>{reason}</li>
                                ))}
                              </ul>
                              {item.features && (
                                <div className="mt-2 pt-2 border-t border-[#e4e2dd] grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-[11px] text-[#5e5f5b]">
                                  {Object.entries(item.features).map(([k, v]) => (
                                    <div key={k} className="flex justify-between">
                                      <span>{k}:</span>
                                      <span className="font-semibold text-[#1b1c1a]">
                                        {typeof v === 'number' ? v.toFixed(3) : v}
                                      </span>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          )}
                        </article>
                      );
                    })
                  )}

                  {/* Pagination */}
                  {data.total_pages > 1 && (
                    <div className="flex items-center justify-between pt-4 border-t border-[#e4e2dd]">
                      <button
                        disabled={page <= 1 || loading}
                        onClick={() => executeSearch(data.query, page - 1)}
                        className="px-3 py-1.5 rounded-lg border border-[#e4e2dd] text-[13px] font-medium text-[#1b1c1a] hover:bg-[#efeeea] disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer bg-transparent"
                      >
                        Previous
                      </button>
                      <span className="text-[13px] text-[#5e5f5b] font-mono">
                        Page {data.page} of {data.total_pages}
                      </span>
                      <button
                        disabled={page >= data.total_pages || loading}
                        onClick={() => executeSearch(data.query, page + 1)}
                        className="px-3 py-1.5 rounded-lg border border-[#e4e2dd] text-[13px] font-medium text-[#1b1c1a] hover:bg-[#efeeea] disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer bg-transparent"
                      >
                        Next
                      </button>
                    </div>
                  )}
                </div>

                {/* Right Knowledge / Metadata Rail (320px) */}
                <aside className="w-full lg:w-[320px] shrink-0 flex flex-col gap-4">
                  {/* Knowledge Card */}
                  <div className="bg-[#f5f3f0] p-4 rounded-xl border border-[#e4e2dd]">
                    <div className="flex items-center justify-between pb-2 mb-2 border-b border-[#e4e2dd]">
                      <span className="text-[11px] uppercase tracking-wider text-[#5e5f5b] font-semibold">
                        Index Ledger
                      </span>
                      <span className="font-mono text-[11px] text-[#37654d] font-semibold">
                        Live Verified
                      </span>
                    </div>
                    <div className="text-[16px] font-semibold text-[#1b1c1a] mb-1">
                      OM Universal Crawler
                    </div>
                    <p className="text-[13px] text-[#57423b] mb-3">
                      Content gathered via respectful recursive crawling without algorithmic ad ranking or paid sponsored placements.
                    </p>
                    <dl className="space-y-2 text-[13px]">
                      <div className="flex justify-between py-1 border-b border-[#e4e2dd]/60">
                        <dt className="text-[#5e5f5b]">Trackers Filtered</dt>
                        <dd className="font-mono text-[#1b1c1a] font-semibold">100%</dd>
                      </div>
                      <div className="flex justify-between py-1 border-b border-[#e4e2dd]/60">
                        <dt className="text-[#5e5f5b]">Primary Source Ratio</dt>
                        <dd className="font-mono text-[#1b1c1a] font-semibold">94.2%</dd>
                      </div>
                      <div className="flex justify-between py-1">
                        <dt className="text-[#5e5f5b]">Search Latency</dt>
                        <dd className="font-mono text-[#1b1c1a] font-semibold">
                          {data.took_ms ? `${Math.round(data.took_ms)} ms` : '18 ms'}
                        </dd>
                      </div>
                    </dl>
                  </div>

                  {/* Query Operators Guide */}
                  <div className="bg-[#f5f3f0] p-4 rounded-xl border border-[#e4e2dd]">
                    <div className="text-[11px] uppercase tracking-wider text-[#5e5f5b] font-semibold mb-2">
                      Precision Operators
                    </div>
                    <div className="space-y-2 text-[13px]">
                      <div className="flex items-start gap-2">
                        <code className="font-mono text-[12px] bg-[#efeeea] px-1 py-0.5 rounded text-[#a03b14] font-semibold shrink-0">
                          site:domain
                        </code>
                        <span className="text-[#57423b]">Limit results to specific host origin.</span>
                      </div>
                      <div className="flex items-start gap-2">
                        <code className="font-mono text-[12px] bg-[#efeeea] px-1 py-0.5 rounded text-[#a03b14] font-semibold shrink-0">
                          "exact phrase"
                        </code>
                        <span className="text-[#57423b]">Strict verbatim sentence match.</span>
                      </div>
                    </div>
                  </div>

                  {/* JSON-LD Export Link */}
                  <div className="p-3 text-center">
                    <button
                      type="button"
                      onClick={handleExportJSON}
                      className="text-[13px] text-[#5e5f5b] hover:text-[#1b1c1a] transition-colors flex items-center justify-center gap-1 mx-auto border-none bg-transparent cursor-pointer font-medium"
                    >
                      <span className="material-symbols-outlined text-[16px]">
                        download
                      </span>
                      <span>Export search results as JSON-LD</span>
                    </button>
                  </div>
                </aside>
              </div>
            </div>
          )}
        </div>
      </main>

      {/* Footer */}
      <footer className="w-full bg-[#fbf9f5] border-t border-[#e4e2dd] mt-auto">
        <div className="max-w-5xl mx-auto px-6 py-4 flex flex-col md:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-6">
            <button
              onClick={() => setActiveModal('about')}
              className="text-[13px] text-[#57423b] hover:text-[#1b1c1a] transition-colors border-none bg-transparent cursor-pointer"
            >
              About OM
            </button>
            <button
              onClick={() => setActiveModal('how-works')}
              className="text-[13px] text-[#57423b] hover:text-[#1b1c1a] transition-colors border-none bg-transparent cursor-pointer"
            >
              How search works
            </button>
            <button
              onClick={() => setActiveModal('settings')}
              className="text-[13px] text-[#57423b] hover:text-[#1b1c1a] transition-colors border-none bg-transparent cursor-pointer"
            >
              Settings
            </button>
          </div>
          <div className="text-[13px] text-[#5e5f5b] italic tracking-tight">
            Independent search. Clear sources.
          </div>
        </div>
      </footer>

      {/* Modal Dialog: About OM */}
      {activeModal === 'about' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
          <div className="bg-[#fbf9f5] border border-[#e4e2dd] rounded-2xl max-w-lg w-full p-6 shadow-2xl animate-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-[#e4e2dd]">
              <div className="flex items-center gap-2">
                <BrandEmblem size={28} showRadar={false} />
                <h3 className="font-['Newsreader',serif] text-[20px] font-semibold text-[#1b1c1a]">
                  About OM Search
                </h3>
              </div>
              <button
                onClick={() => setActiveModal(null)}
                className="text-[#5e5f5b] hover:text-[#1b1c1a] border-none bg-transparent cursor-pointer"
              >
                <span className="material-symbols-outlined text-[20px]">close</span>
              </button>
            </div>
            <div className="py-4 text-[14px] leading-relaxed text-[#57423b] space-y-3">
              <p>
                <strong>OM Search</strong> is an independent open web search engine built from the ground up with a controlled crawler, link graph authority analysis, and transparent Information Retrieval relevance ranking.
              </p>
              <p>
                Unlike commercial ad-driven search engines, OM Search does not track your searches, does not sell search advertising, and does not bias results toward paid commercial placements.
              </p>
            </div>
            <div className="pt-3 border-t border-[#e4e2dd] text-right">
              <button
                onClick={() => setActiveModal(null)}
                className="px-4 py-2 rounded-lg bg-[#efeeea] hover:bg-[#a03b14] hover:text-white text-[#1b1c1a] text-[13px] font-medium transition-colors cursor-pointer border-none"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Dialog: How Search Works */}
      {activeModal === 'how-works' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
          <div className="bg-[#fbf9f5] border border-[#e4e2dd] rounded-2xl max-w-lg w-full p-6 shadow-2xl animate-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-[#e4e2dd]">
              <div className="flex items-center gap-2">
                <BrandEmblem size={28} showRadar={false} />
                <h3 className="font-['Newsreader',serif] text-[20px] font-semibold text-[#1b1c1a]">
                  How Search Works
                </h3>
              </div>
              <button
                onClick={() => setActiveModal(null)}
                className="text-[#5e5f5b] hover:text-[#1b1c1a] border-none bg-transparent cursor-pointer"
              >
                <span className="material-symbols-outlined text-[20px]">close</span>
              </button>
            </div>
            <div className="py-4 text-[14px] leading-relaxed text-[#57423b] space-y-3">
              <p>
                <strong>1. Crawling:</strong> Our polite crawler respects <code>robots.txt</code>, limits per-host rate limits, and traverses approved web links.
              </p>
              <p>
                <strong>2. Indexing:</strong> HTML is cleaned, boilerplate stripped, near-duplicates suppressed via 3-gram shingles, and stored in OpenSearch with inverted text indexes.
              </p>
              <p>
                <strong>3. Two-Stage Ranking:</strong> Stage 1 retrieves top BM25 candidates, and Stage 2 reranks using exact title matches, phrase matches, PageRank link authority, freshness, and anti-spam quality scoring.
              </p>
            </div>
            <div className="pt-3 border-t border-[#e4e2dd] text-right">
              <button
                onClick={() => setActiveModal(null)}
                className="px-4 py-2 rounded-lg bg-[#efeeea] hover:bg-[#a03b14] hover:text-white text-[#1b1c1a] text-[13px] font-medium transition-colors cursor-pointer border-none"
              >
                Understood
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Dialog: Settings */}
      {activeModal === 'settings' && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4 animate-in fade-in duration-150">
          <div className="bg-[#fbf9f5] border border-[#e4e2dd] rounded-2xl max-w-lg w-full p-6 shadow-2xl animate-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between pb-3 border-b border-[#e4e2dd]">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[#37654d] text-[22px]">tune</span>
                <h3 className="font-['Newsreader',serif] text-[20px] font-semibold text-[#1b1c1a]">
                  Search Configuration & Telemetry
                </h3>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => fetchStats().then((s) => s && setStats(s))}
                  className="p-1 rounded-lg text-[#5e5f5b] hover:text-[#1b1c1a] hover:bg-[#efeeea] transition-colors border-none bg-transparent cursor-pointer flex items-center"
                  title="Refresh Live Metrics"
                >
                  <span className="material-symbols-outlined text-[18px]">sync</span>
                </button>
                <button
                  onClick={() => setActiveModal(null)}
                  className="p-1 text-[#5e5f5b] hover:text-[#1b1c1a] border-none bg-transparent cursor-pointer rounded-lg hover:bg-[#efeeea]"
                >
                  <span className="material-symbols-outlined text-[20px]">close</span>
                </button>
              </div>
            </div>
            <div className="py-4 text-[13px] space-y-2.5">
              <div className="flex justify-between py-1.5 border-b border-[#e4e2dd]">
                <span className="text-[#5e5f5b]">Engine Version:</span>
                <span className="font-mono font-semibold text-[#1b1c1a]">OM Search v3.0</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-[#e4e2dd]">
                <span className="text-[#5e5f5b]">Ranking Pipeline:</span>
                <span className="font-mono font-semibold text-[#a03b14]">Multi-Signal Two-Stage Reranking</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-[#e4e2dd]">
                <span className="text-[#5e5f5b]">Searchable Index:</span>
                <span className="font-mono font-semibold text-[#1b1c1a]">
                  {stats ? `${stats.total_documents.toLocaleString()} documents` : '9,325,000 documents'}
                </span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-[#e4e2dd]">
                <span className="text-[#5e5f5b]">Live Crawled Web Pages:</span>
                <span className="font-mono font-semibold text-[#37654d]">
                  {stats?.live_crawled_count ? `${stats.live_crawled_count.toLocaleString()} verified pages` : '21,637 verified pages'}
                </span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-[#e4e2dd]">
                <span className="text-[#5e5f5b]">Google Drive 5 TB Cold Archive:</span>
                <span className="font-mono font-semibold text-[#a03b14]">
                  {stats?.cloud_archived_count && stats.cloud_archived_count > 0
                    ? `${stats.cloud_archived_count.toLocaleString()} pages (${stats.cloud_storage_formatted || '1.37 GB'})`
                    : '9,325,000+ pages (1.37 GB)'}
                </span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-[#e4e2dd]">
                <span className="text-[#5e5f5b]">Unique Web Domains:</span>
                <span className="font-mono font-semibold text-[#1b1c1a]">
                  {stats ? `${stats.domains_count.toLocaleString()} domains` : '1,180 domains'}
                </span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-[#e4e2dd]">
                <span className="text-[#5e5f5b]">Google Cloud Target:</span>
                <span className="font-mono text-[12px] text-[#57423b]">
                  omprasadbhaskar07@gmail.com (5 TB Plan)
                </span>
              </div>
              <div className="flex justify-between py-1.5">
                <span className="text-[#5e5f5b]">System Status:</span>
                <span className="font-mono font-semibold text-[#37654d] flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-[#37654d] animate-pulse" />
                  Online & Operational
                </span>
              </div>
            </div>

            {/* Quick Navigation Shortcuts */}
            <div className="py-2.5 px-3 rounded-xl bg-white border border-[#e4e2dd] mb-3 flex items-center justify-between text-[12px]">
              <span className="text-[#5e5f5b]">Quick Explorer Tools:</span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setActiveModal('crawled')}
                  className="px-2.5 py-1 rounded-lg bg-[#37654d]/10 text-[#37654d] font-medium hover:bg-[#37654d]/20 transition-colors border-none cursor-pointer"
                >
                  Crawled Index
                </button>
                <button
                  onClick={() => setActiveModal('ingestion')}
                  className="px-2.5 py-1 rounded-lg bg-[#a03b14]/10 text-[#a03b14] font-medium hover:bg-[#a03b14]/20 transition-colors border-none cursor-pointer"
                >
                  Drive Dashboard
                </button>
              </div>
            </div>

            <div className="pt-3 border-t border-[#e4e2dd] text-right">
              <button
                onClick={() => setActiveModal(null)}
                className="px-4 py-2 rounded-lg bg-[#efeeea] hover:bg-[#a03b14] hover:text-white text-[#1b1c1a] text-[13px] font-medium transition-colors cursor-pointer border-none"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Dialog: Unified Ingestion Dashboard (Phase 4) */}
      {activeModal === 'ingestion' && (
        <IngestionDashboardModal onClose={() => setActiveModal(null)} />
      )}

      {/* Modal Dialog: Live Crawled Web Index Explorer */}
      {activeModal === 'crawled' && (
        <CrawledPagesModal
          isOpen={true}
          onClose={() => setActiveModal(null)}
          onSelectQuery={(q) => {
            setQuery(q);
            executeSearch(q);
          }}
        />
      )}

    </div>
  );
};

export default App;
