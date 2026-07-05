import type { Metadata, Viewport } from 'next'
import './globals.css'
import Sidebar from '@/components/layout/Sidebar'
import GlobalShortcuts from '@/components/layout/GlobalShortcuts'
import GlobalDropZone from '@/components/layout/GlobalDropZone'

export const metadata: Metadata = {
  title: 'Nexus Campaigns',
  description: 'Nexus Campaigns — Admin Dashboard',
}

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: '#09090b',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className="dark">
      <body className="bg-surface text-zinc-100 min-h-screen">
        <GlobalShortcuts />
        <GlobalDropZone />
        <div className="flex h-screen overflow-hidden">
          <Sidebar />
          <main className="flex-1 overflow-y-auto bg-surface pt-[calc(3.5rem+env(safe-area-inset-top))] md:pt-0">
            {children}
          </main>
        </div>
      </body>
    </html>
  )
}
