// Small conveniences kept in this browser (a draft job description, and similar). Every access is guarded:
// storage can be unavailable in private windows.
export const store = {
  get(key: string, fallback: string): string {
    try {
      return localStorage.getItem(`tailortex:app:${key}`) ?? fallback
    } catch {
      return fallback
    }
  },
  set(key: string, value: string) {
    try {
      localStorage.setItem(`tailortex:app:${key}`, value)
    } catch {
      /* storage unavailable */
    }
  },
}
