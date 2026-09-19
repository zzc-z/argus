import type { SVGProps } from 'react';

export function ArgusLogo(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" {...props}>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.75" opacity="0.3" />
      <path d="M12 3C7.02944 3 3 7.02944 3 12C3 16.9706 7.02944 21 12 21" stroke="currentColor" strokeLinecap="round" strokeWidth="2" />
      <circle cx="12" cy="12" r="4.25" fill="#ffffff" stroke="currentColor" strokeWidth="1.75" />
      <circle cx="12" cy="12" r="2" fill="currentColor" />
      <path d="M12 7.75V3M21 12H16.25M12 21v-4.75M3 12h4.75" stroke="currentColor" strokeLinecap="round" strokeWidth="1.5" opacity="0.5" />
    </svg>
  );
}
