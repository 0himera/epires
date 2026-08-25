from sandbox.perf_ab.model_speed import _parse_jsonl


def test_parse_opencode_jsonl_extracts_text_tokens_and_event_latency():
    source = "\n".join(
        [
            '{"type":"step_start","timestamp":1000,"part":{}}',
            '{"type":"text","timestamp":2500,"part":{"text":"hello world"}}',
            '{"type":"step_finish","timestamp":2600,"part":{"tokens":{"input":10,"output":2,"reasoning":1,"cache":{"read":4}}}}',
        ]
    )

    result = _parse_jsonl(source)

    assert result["text"] == "hello world"
    assert result["words"] == 2
    assert result["tokens"] == {"input": 10, "output": 2, "reasoning": 1, "cache_read": 4}
    assert result["first_text_event_seconds"] == 1.5
    assert result["event_span_seconds"] == 1.6
