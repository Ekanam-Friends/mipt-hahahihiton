import pytest
from regnav.core.parse import Chunk
from scripts.rebind_revisions import rebind


def test_rebind_requires_unique_quote_and_original_hash():
    registry = {'documents': {'d': {'sha256': 'original', 'evidence': [{'chunk_id': 'old', 'quote': 'Дата действия'}]}}}
    chunk = Chunk('new', 'd', 'Document', '1', '', 'Дата действия: 01.01.2026.', meta={'source_sha256': 'original'})
    assert rebind(registry, [chunk])['documents']['d']['evidence'][0]['chunk_id'] == 'new'
    assert registry['documents']['d']['evidence'][0]['chunk_id'] == 'old'
    with pytest.raises(ValueError, match='exactly one'):
        rebind(registry, [chunk, Chunk('other', 'd', 'Document', '2', '', chunk.text, meta=chunk.meta)])
    chunk.meta = {'source_sha256': 'changed'}
    with pytest.raises(ValueError, match='hash'):
        rebind(registry, [chunk])
