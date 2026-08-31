# PLAN-DWG Contracts

This directory is the only repository-owned contract surface shared by PLAN and
DWG. It contains versioned data schemas only and must not import either product.

- `drawing-registration.v1.schema.json`: run-relative drawing registration
  request used when an approved PLAN artifact is opened by DWG.

Absolute user paths and parent traversal are deliberately outside the contract.
