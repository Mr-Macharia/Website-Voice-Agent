import path from 'path'
import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  // Multiple lockfiles exist above this directory, so Next would otherwise
  // infer the home directory as the workspace root. Pin it to this project.
  outputFileTracingRoot: path.join(__dirname),
  devIndicators: false
}

export default nextConfig
