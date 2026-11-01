/** Slow-drifting coloured light behind the app (decorative only). */
export function Aurora() {
  return (
    <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden" aria-hidden="true">
      <div className="grid-fade absolute inset-0" />
      <div className="aurora-blob left-[-12%] top-[-18%] h-[38rem] w-[38rem] animate-drift bg-glow1/70" />
      <div className="aurora-blob right-[-14%] top-[8%] h-[32rem] w-[32rem] animate-drift-slow bg-glow2/50" />
      <div
        className="aurora-blob bottom-[-24%] left-[28%] h-[34rem] w-[34rem] animate-drift bg-glow3/45"
        style={{ animationDelay: '-11s' }}
      />
    </div>
  )
}
