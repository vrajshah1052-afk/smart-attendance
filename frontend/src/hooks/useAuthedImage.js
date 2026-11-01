import { useEffect, useState } from 'react'
import { api } from '../api/client'

/** <img> cannot send the bearer token, so fetch protected images as blobs. */
export function useAuthedImage(path) {
  const [src, setSrc] = useState(null)
  useEffect(() => {
    if (!path) return undefined
    let url
    let cancelled = false
    api
      .get(path)
      .then((blob) => {
        if (cancelled || !(blob instanceof Blob)) return
        url = URL.createObjectURL(blob)
        setSrc(url)
      })
      .catch(() => setSrc(null))
    return () => {
      cancelled = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [path])
  return src
}
