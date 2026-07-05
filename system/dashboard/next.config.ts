import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  serverExternalPackages: ['gray-matter', 'yaml'],
  allowedDevOrigins: ['192.168.2.114'],
}

export default nextConfig
