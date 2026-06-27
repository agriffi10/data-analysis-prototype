import {createContext} from 'react';
import type {AuthContextValue} from './auth.types';

// Kept in its own module so AuthProvider.tsx exports only a component
// (react-refresh) and useAuth.ts can consume the context without a cycle.
// `undefined` default lets useAuth detect usage outside the provider.
export const AuthContext = createContext<AuthContextValue | undefined>(undefined);
