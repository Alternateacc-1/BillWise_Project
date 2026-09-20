import { useEffect, type RefObject } from 'react'

/** Adds .is-in the first time `threshold` of the element is on screen, then stops watching. */
export function useRevealOnce(ref: RefObject<HTMLElement | null>, threshold: number) {
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver(
      ([e]) => {
        if (!e.isIntersecting) return
        el.classList.add('is-in')
        io.disconnect() // fires once, never replays
      },
      { threshold },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [ref, threshold])
}
