-- P2-5: the five DESIGN §13.3 consistency tables. Realtime applies each
-- subscriber's RLS policies before delivering changes.
alter publication supabase_realtime add table hunt_listings;
alter publication supabase_realtime add table scores;
alter publication supabase_realtime add table comments;
alter publication supabase_realtime add table jobs;
alter publication supabase_realtime add table job_events;
