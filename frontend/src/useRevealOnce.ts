import { useEffect, type RefObject } from 'react'

/** Adds .is-in the first time `threshold` of the element is on screen, then stops watching. */
export function useRevealOnce(ref: RefObject<HTMLElement | null>, threshold: number) {
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver(
      ([e]) => {
        if (!e.isIntersecting) return
        // will-change only for the duration of the entrance: blur() promotes a layer, and we don't want to keep it
        el.style.willChange = 'filter, transform'
        const done = () => {
          el.style.willChange = ''
          clearTimeout(t)
        }
        const t = setTimeout(done, 800)
        el.addEventListener('transitionend', done, { once: true })
        el.classList.add('is-in')
        io.disconnect() // fires once, never replays
      },
      { threshold },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [ref, threshold])
}
