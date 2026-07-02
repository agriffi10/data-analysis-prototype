import {createContext} from 'react';
import type {AuthContextValue} from './auth.types';

/**
 * Auth context, in its own module so AuthProvider.tsx exports only a component
 * (react-refresh) and useAuth.ts can consume it without a cycle. The
 * `undefined` default lets useAuth detect usage outside the provider.
 */
export const AuthContext = createContext<AuthContextValue | undefined>(undefined);
