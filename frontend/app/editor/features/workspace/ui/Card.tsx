import type React from 'react'
import { cn } from '@/lib/utils'

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode
  className?: string
  padding?: boolean
}

export function Card({
  children,
  className,
  padding = true,
  ...rest
}: CardProps) {
  return (
    <div className={cn(
      'bg-(--color-surface-card) rounded-xl shadow-md',
      padding && 'p-6',
      className
    )} {...rest}>
      {children}
    </div>
  )
}
