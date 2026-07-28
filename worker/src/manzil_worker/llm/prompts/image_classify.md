---
id: image_classify
version: 2
cacheable_prefix_marker: <!-- PER-CALL -->
---
Classify each target image conservatively for apartment-gallery routing. Use only
visible pixels. A kitchen is assessable only when cabinetry, counters, and major
appliances are sufficiently visible to compare finish quality. Mark floor-plan
drawings/rendered diagrams as diagrams, logos/maps/people-only images as
irrelevant, and do not infer a room from listing text. Return exactly one record
for every thumbnail SHA-256 supplied as an image block; content_hash is that
thumbnail hash. The target label carries separate provenance for the original
Property image and must not be used as content_hash.
<!-- PER-CALL -->
The user content labels each thumbnail as target:<original-property-sha256>.
