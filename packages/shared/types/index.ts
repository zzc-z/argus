// Shared TypeScript types between web and (future) api
// Backed by Pydantic schemas in packages/shared/schemas/

export interface User {
  id: string;
  email: string;
  displayName: string;
  avatarUrl?: string;
  createdAt: string;
}

export type ResearchStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface Research {
  id: string;
  userId: string;
  query: string;
  status: ResearchStatus;
  createdAt: string;
  completedAt?: string;
  agentSteps: number;
  totalTokens: number;
}
