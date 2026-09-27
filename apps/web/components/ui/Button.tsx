'use client'

import * as React from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

/**
 * shadcn-new-york Button.
 * Variants aligned to Argus 47-token (no OKLCH).
 * - default   → bg-primary text-on-primary
 * - secondary → bg-surface-container text-on-surface
 * - outline   → border + bg-transparent
 * - ghost     → transparent + hover bg
 * - link      → underline + primary color
 */
const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-container focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 [&_span.material-symbols-outlined]:pointer-events-none',
  {
    variants: {
      variant: {
        default: 'bg-primary text-on-primary hover:bg-primary/90',
        secondary: 'bg-surface-container text-on-surface hover:bg-surface-container-high',
        outline:
          'border border-outline bg-transparent text-on-surface hover:bg-surface-container-low',
        ghost: 'bg-transparent text-on-surface hover:bg-surface-container-low',
        link: 'bg-transparent text-primary underline-offset-4 hover:underline',
        destructive: 'bg-error text-on-error hover:bg-error/90',
      },
      size: {
        default: 'h-9 px-4 py-2',
        sm: 'h-8 rounded-md px-3 text-xs',
        lg: 'h-10 rounded-md px-6 text-base',
        icon: 'h-9 w-9',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button'
    return (
      <Comp className={cn(buttonVariants({ variant, size }), className)} ref={ref} {...props} />
    )
  },
)
Button.displayName = 'Button'

export { Button, buttonVariants }
