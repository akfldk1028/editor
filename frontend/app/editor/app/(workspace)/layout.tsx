import type { ReactNode } from 'react'
import { WorkspaceLayout } from '@/features/workspace/WorkspaceLayout'

export default function Layout({ children }: { children: ReactNode }) {
  return <WorkspaceLayout>{children}</WorkspaceLayout>
}
