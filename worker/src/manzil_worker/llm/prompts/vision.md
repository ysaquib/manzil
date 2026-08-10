---
id: vision
version: 2
cacheable_prefix_marker: <!-- PER-CALL -->
---
Assess only visible kitchen finish quality by comparison with the supplied
reference sheets for ratings 1–5. Ignore rent, location, staging, camera quality,
exterior appearance, and all text claims. Use not_visible when cabinetry,
counters, and major appliances are not sufficiently visible. Give a short
visual rationale and keep `rationale` under 320 characters. Return exactly one
assessment for each target hash and none for reference images.
<!-- PER-CALL -->
Reference and target roles, exact hashes, reference version, and reliable
Source-local Floor Plan associations are carried in the image labels.
