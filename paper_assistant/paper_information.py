"""Read paper identity and reviewed abstract passages for search planning.

These passages do not enter the answer's evidence or citation allow-list.
They retain the original chunks instead of concatenating overlapping text.
"""


def load_paper_information(store, selected_versions, source_registry=None, *, version_chunks=None) -> list[dict]:
    """Use stored titles and available reviewed abstracts without generation."""
    information = []
    for paper_id, parse_revision in selected_versions:
        chunks = (version_chunks[(paper_id, parse_revision)] if version_chunks is not None
                  else store.get_version_chunks(paper_id, parse_revision))
        abstract_ids = (
            set(source_registry.qualified_chunk_ids([(paper_id, parse_revision)]))
            if source_registry is not None else set()
        )
        information.append({
            "paper_id": paper_id,
            "parse_revision": parse_revision,
            "title": chunks[0]["title"],
            "abstract_passages": [
                {"chunk_id": chunk["chunk_id"], "pdf_page": chunk["pdf_page"],
                 "text": chunk["text"]}
                for chunk in chunks if chunk["chunk_id"] in abstract_ids
            ],
        })
    return information
