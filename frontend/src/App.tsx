import { useEffect, useState } from 'react'
import Flow from './pages/Flow'
import Landing from './pages/Landing'

export type Page = 'landing' | 'flow'

const pathFor = (p: Page) => (p === 'flow' ? '/check' : '/')
// Amplify 301-redirects /check to /check/, so an EXACT match sent every deep
// link to the landing page on the deployed site while working locally, where
// the dev server adds no trailing slash. Measured 2026-09-20 against the live
// URL. Strip it here rather than relying on a console rewrite rule: this is
// the copy that ships, and ?fixture= deep links are what the demo runs on.
const pageFor = (path: string): Page => (path.replace(/\/+$/, '') === '/check' ? 'flow' : 'landing')

export default function App() {
  const [page, setPage] = useState<Page>(() => pageFor(window.location.pathname))
  // File dropped on the landing page, handed to the flow's upload step.
  const [pendingFile, setPendingFile] = useState<File | null>(null)

  useEffect(() => {
    const onPop = (e: PopStateEvent) => setPage((e.state?.page as Page) ?? pageFor(window.location.pathname))
    window.addEventListener('popstate', onPop)
    // Merge state (Flow's effect ran first and set step); keep the query so ?mock= survives a fresh load.
    history.replaceState({ ...history.state, page }, '', pathFor(page) + window.location.search)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const go = (next: Page) => {
    if (next === page) return
    history.pushState({ page: next }, '', pathFor(next))
    setPage(next)
    window.scrollTo({ top: 0 })
  }

  if (page === 'flow') {
    return <Flow initialFile={pendingFile} onDone={() => go('landing')} />
  }

  return (
    <Landing
      onStart={(file) => {
        setPendingFile(file)
        go('flow')
      }}
    />
  )
}
