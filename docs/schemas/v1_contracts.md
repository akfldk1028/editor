# V1 Data Contracts

## MassInput

JSON polygon input with project id, floor count, footprint points, site edges, access candidates, and use mix.

## ProgramGraph

Spaces are nodes. Adjacency, service, public access, and vertical access rules are edges.

## LayoutCandidate

Rooms are vector polygons. V1 stores circulation separately and keeps walls/doors for later exporters.

## ValidationReport

Every generated candidate receives scores for area, overlap, boundary adherence, circulation, efficiency, and a total score.
