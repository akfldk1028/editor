# Export drawing

Save a new CAD copy only after the host has issued a one-use destination grant.
Never accept, infer, or serialize a filesystem destination path. Invoke
`export.drawing` once with the current document revision and report the returned
verification evidence. The source drawing remains read-only.
