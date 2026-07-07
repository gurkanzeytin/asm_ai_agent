# Schema Context Template

The target database contains the following structural details:

## Schema Metadata
{metadata}

## Rules
- When generating SQL, strictly use only the tables and columns documented in the metadata.
- If a column is missing, return a validation error. Do not guess names.
