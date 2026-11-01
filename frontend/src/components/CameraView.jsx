import { useEffect } from 'react'
import { Camera, CameraOff, RefreshCw } from 'lucide-react'

/**
 * Mirrored live preview (like a mirror, which people expect) with an optional
 * face guide. Captured frames are NOT mirrored. `children` render over the video.
 */
export function CameraView({ cam, guide = 'face', autoStart = true, children, className = '' }) {
  const { videoRef, status, error, start, stop, switchCamera, devices } = cam

  useEffect(() => {
    if (autoStart) start()
    return () => stop()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className={`overflow-hidden rounded-2xl border border-line bg-black ${className}`}>
      <div className="relative aspect-[4/3] w-full">
        <video ref={videoRef} playsInline muted className="h-full w-full -scale-x-100 object-cover" />
        {guide === 'face' && status === 'ready' && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center" aria-hidden="true">
            <div className="h-[68%] w-[42%] rounded-[50%] border-2 border-dashed border-white/60" />
          </div>
        )}
        {status !== 'ready' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-white/85">
            {status === 'error' ? (
              <>
                <CameraOff size={28} />
                <p className="max-w-sm text-sm">{error}</p>
                <button className="btn btn-quiet btn-sm" onClick={() => start()}>
                  Try again
                </button>
              </>
            ) : status === 'starting' ? (
              <p className="text-sm">Starting camera…</p>
            ) : (
              <button className="btn btn-quiet" onClick={() => start()}>
                <Camera size={16} /> Turn on camera
              </button>
            )}
          </div>
        )}
        {children}
      </div>
      {status === 'ready' && devices.length > 1 && (
        <div className="flex justify-end border-t border-white/10 bg-black px-2 py-1.5">
          <button className="inline-flex items-center gap-1.5 text-xs text-white/80 hover:text-white" onClick={switchCamera}>
            <RefreshCw size={13} /> Switch camera
          </button>
        </div>
      )}
    </div>
  )
}
