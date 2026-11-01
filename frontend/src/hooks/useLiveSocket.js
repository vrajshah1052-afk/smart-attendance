import { useCallback, useEffect, useRef, useState } from 'react'
import { getToken, wsUrl } from '../api/client'

/** WebSocket to /ws/live with automatic reconnect. */
export function useLiveSocket({ enabled = true, onMessage } = {}) {
  const wsRef = useRef(null)
  const handlerRef = useRef(onMessage)
  handlerRef.current = onMessage
  const [state, setState] = useState('closed')

  useEffect(() => {
    if (!enabled) return undefined
    let closedByUs = false
    let retry = 0
    let timer

    const connect = () => {
      const token = getToken()
      if (!token) return
      setState('connecting')
      const ws = new WebSocket(wsUrl(`/ws/live?token=${encodeURIComponent(token)}`))
      wsRef.current = ws
      ws.onopen = () => {
        retry = 0
        setState('open')
      }
      ws.onmessage = (event) => {
        try {
          handlerRef.current?.(JSON.parse(event.data))
        } catch {
          /* ignore malformed frames */
        }
      }
      ws.onclose = () => {
        setState('closed')
        if (!closedByUs) {
          retry += 1
          timer = setTimeout(connect, Math.min(10000, 1000 * 2 ** retry))
        }
      }
    }
    connect()
    const ping = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ type: 'ping' }))
    }, 25000)
    return () => {
      closedByUs = true
      clearTimeout(timer)
      clearInterval(ping)
      wsRef.current?.close()
    }
  }, [enabled])

  const send = useCallback((payload) => {
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload))
      return true
    }
    return false
  }, [])

  return { state, send }
}
