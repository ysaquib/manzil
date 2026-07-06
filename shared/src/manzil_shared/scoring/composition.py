"""Cost composer behind an interface (DESIGN §6, §18 buy-domain seam).

Rent-domain composition (all-in monthly, §9.5) plugs in behind this seam so
`shared` code stays free of rental assumptions. Implemented alongside P0-3.
"""
