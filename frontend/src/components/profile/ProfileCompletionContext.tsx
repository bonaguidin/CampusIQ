import { createContext, useContext } from 'react';
import type { MissingField } from '../../types/analysis';

export interface ProfileCompletionRequest {
  feature: string;
  missingFields: MissingField[];
  trigger: HTMLElement;
}

export const ProfileCompletionContext = createContext<
  ((request: ProfileCompletionRequest) => void) | null
>(null);

export function useProfileCompletionModal() {
  return useContext(ProfileCompletionContext);
}
