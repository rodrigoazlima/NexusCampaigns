/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: { serverComponentsExternalPackages: ['gray-matter'] },
  env: { VAULT_ROOT: process.env.VAULT_ROOT ?? 'D:\\Library\\rpg\\dm\\pathway\\knowledge-base' },
  webpack: (config) => {
    config.resolve.symlinks = false
    config.cache = false
    // Windows NTFS: readlink returns EISDIR on regular files; snapshot system
    // must not follow symlinks either.
    config.snapshot = {
      ...(config.snapshot ?? {}),
      managedPaths: [],
      immutablePaths: [],
      module: { timestamp: true, hash: false },
      resolve: { timestamp: true, hash: false },
      resolveBuildDependencies: { timestamp: true, hash: false },
      buildDependencies: { timestamp: true, hash: false },
    }
    return config
  },
}
export default nextConfig
