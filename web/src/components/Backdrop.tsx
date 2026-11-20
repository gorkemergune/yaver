/** The Aurora background: slow colour fields behind the glass panels (fixed, behind
 * everything; switched off with reduced motion by the .yv-drift rule). */
export function Backdrop() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div className="yv-drift absolute -left-32 -top-32 h-[28rem] w-[28rem] rounded-full bg-indigo-300/55 blur-3xl dark:bg-indigo-600/35" />
      <div
        className="yv-drift absolute -right-24 top-1/3 h-96 w-96 rounded-full bg-pink-300/40 blur-3xl dark:bg-fuchsia-600/20"
        style={{ animationDelay: "-6s" }}
      />
      <div
        className="yv-drift absolute -bottom-40 left-1/4 h-[28rem] w-[28rem] rounded-full bg-cyan-300/45 blur-3xl dark:bg-cyan-500/20"
        style={{ animationDelay: "-12s" }}
      />
    </div>
  );
}
