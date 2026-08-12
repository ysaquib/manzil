-- PostgreSQL requires a newly added enum value to commit before it is used.
alter type public.job_state add value if not exists 'deleted';
