The `galaxy-collection-wf-crate` example from the Workflow Run RO-Crate
specification (github.com/ResearchObject/workflow-run-crate,
docs/examples/draft/), minus its ro-crate-metadata.json: what Galaxy 23.0's
"export invocation" writes as a model store. Six steps (two collection
inputs, an integer parameter, `__MERGE_COLLECTION__`, `cat_collection`,
`head`), nine datasets (three of them copies), six collections, and the
three `__DATA_FETCH__` upload jobs that made the inputs.
