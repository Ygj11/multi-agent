from app.knowledge.chunk_post_processor import KnowledgeChunkPostProcessor


def test_chunk_post_processor_maps_compatible_fields_and_keeps_raw_metadata():
    processor = KnowledgeChunkPostProcessor()

    chunks = processor.normalize_many(
        [
            {
                "chunk_text": "外部知识片段",
                "docId": "doc-1",
                "title": "标题",
                "section": "A",
                "namespace": "health",
                "similarity": 0.82,
            }
        ],
        top_k=3,
    )

    assert len(chunks) == 1
    assert chunks[0].content == "外部知识片段"
    assert chunks[0].source == "doc-1"
    assert chunks[0].score == 0.82
    assert chunks[0].metadata["docId"] == "doc-1"
    assert chunks[0].metadata["title"] == "标题"
    assert chunks[0].metadata["raw"]["chunk_text"] == "外部知识片段"


def test_chunk_post_processor_filters_empty_content_truncates_and_dedupes():
    processor = KnowledgeChunkPostProcessor(max_content_chars=10)

    chunks = processor.normalize_many(
        [
            {"content": ""},
            {"text": "1234567890abcdef", "source": "s1", "score": 0.3},
            {"page_content": "1234567890abcdef", "source": "s2", "score": 0.9},
        ],
        top_k=3,
    )

    assert len(chunks) == 1
    assert chunks[0].content == "1234567890"
    assert chunks[0].source == "s1"


def test_chunk_post_processor_sorts_by_score_and_limits_top_k():
    processor = KnowledgeChunkPostProcessor()

    chunks = processor.normalize_many(
        [
            {"content": "low", "score": 0.1},
            {"content": "high", "rerank_score": 0.9},
            {"content": "mid", "distance_score": 0.5},
        ],
        top_k=2,
    )

    assert [chunk.content for chunk in chunks] == ["high", "mid"]
