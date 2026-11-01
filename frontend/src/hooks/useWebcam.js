import { useCallback, useEffect, useRef, useState } from 'react'

const ERRORS = {
  NotAllowedError: 'Camera permission was denied. Allow camera access for this site in the browser settings.',
  NotFoundError: 'No camera was found on this device.',
  NotReadableError: 'The camera is being used by another application.',
  OverconstrainedError: 'The selected camera does not support this resolution.',
}

/** getUserMedia wrapper with capture helpers. Frames are captured un-mirrored. */
export function useWebcam({ width = 1280, height = 720, facingMode = 'user' } = {}) {
  const videoRef = useRef(null)
  const streamRef = useRef(null)
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)
  const [devices, setDevices] = useState([])
  const [deviceId, setDeviceId] = useState(null)

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    setStatus('idle')
  }, [])

  const start = useCallback(
    async (preferredId) => {
      if (!navigator.mediaDevices?.getUserMedia) {
        setError('The camera needs a secure page: open the app on https or http://localhost.')
        setStatus('error')
        return
      }
      setStatus('starting')
      setError(null)
      streamRef.current?.getTracks().forEach((t) => t.stop())
      try {
        const id = preferredId ?? deviceId
        const video = id
          ? { deviceId: { exact: id }, width: { ideal: width }, height: { ideal: height } }
          : { facingMode, width: { ideal: width }, height: { ideal: height } }
        const stream = await navigator.mediaDevices.getUserMedia({ video, audio: false })
        streamRef.current = stream
        if (videoRef.current) {
          videoRef.current.srcObject = stream
          await videoRef.current.play().catch(() => {})
        }
        const all = await navigator.mediaDevices.enumerateDevices()
        setDevices(all.filter((d) => d.kind === 'videoinput'))
        setDeviceId(stream.getVideoTracks()[0]?.getSettings().deviceId || id || null)
        setStatus('ready')
      } catch (err) {
        setError(ERRORS[err.name] || `Camera error: ${err.message}`)
        setStatus('error')
      }
    },
    [deviceId, facingMode, height, width],
  )

  const switchCamera = useCallback(() => {
    if (devices.length < 2) return
    const idx = devices.findIndex((d) => d.deviceId === deviceId)
    start(devices[(idx + 1) % devices.length].deviceId)
  }, [deviceId, devices, start])

  const draw = useCallback((maxWidth) => {
    const video = videoRef.current
    if (!video || !video.videoWidth) return null
    const scale = maxWidth ? Math.min(1, maxWidth / video.videoWidth) : 1
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(video.videoWidth * scale)
    canvas.height = Math.round(video.videoHeight * scale)
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height)
    return canvas
  }, [])

  const capture = useCallback(
    (quality = 0.92, maxWidth) =>
      new Promise((resolve) => {
        const canvas = draw(maxWidth)
        if (!canvas) return resolve(null)
        canvas.toBlob((blob) => resolve(blob), 'image/jpeg', quality)
      }),
    [draw],
  )

  const captureDataUrl = useCallback(
    (maxWidth = 640, quality = 0.7) => draw(maxWidth)?.toDataURL('image/jpeg', quality) ?? null,
    [draw],
  )

  useEffect(() => () => streamRef.current?.getTracks().forEach((t) => t.stop()), [])

  return { videoRef, status, error, devices, start, stop, switchCamera, capture, captureDataUrl }
}
