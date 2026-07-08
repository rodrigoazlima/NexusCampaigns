export default function HomePage() {
  return (
    <div className="flex flex-col items-center justify-center h-screen gap-4">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/logo-monogram-variant-square.png"
        alt="Nexus Campaigns"
        className="w-24 h-24 animate-pulse"
      />
      <div className="text-xs font-semibold tracking-widest text-zinc-500 uppercase">
        Loading
      </div>
    </div>
  )
}
