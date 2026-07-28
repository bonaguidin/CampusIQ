import { createClient } from '@supabase/supabase-js';

// Single Supabase client for the whole app. Uses the publishable
// (anon) key only -- every read runs under the signed-in user's own
// session, so Postgres RLS applies. A secret/service-role key must
// never appear here or anywhere else under frontend/.

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabasePublishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;

if (!supabaseUrl || !supabasePublishableKey) {
  throw new Error(
    'Missing VITE_SUPABASE_URL or VITE_SUPABASE_PUBLISHABLE_KEY. Set both in frontend/.env ' +
      '(see frontend/.env.example) before starting the app.',
  );
}

export const supabase = createClient(supabaseUrl, supabasePublishableKey);
