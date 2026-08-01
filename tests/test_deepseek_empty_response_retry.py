import unittest
from unittest.mock import patch

from src.analyzer import GeminiAnalyzer


def _response(content, *, reasoning_content=None, finish_reason="stop"):
    return {
        "choices": [
            {
                "message": {
                    "content": content,
                    "reasoning_content": reasoning_content,
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "total_tokens": 12,
        },
    }


def _call(responses, *, model="openai/deepseek-v4-flash", provider="openai"):
    analyzer = GeminiAnalyzer.__new__(GeminiAnalyzer)
    calls = []

    def completion(kwargs):
        calls.append(kwargs)
        return responses[len(calls) - 1]

    response, content = analyzer._call_nonstream_with_deepseek_empty_retry(
        model=model,
        provider=provider,
        call_kwargs={"model": model, "messages": []},
        completion_callable=completion,
    )
    return response, content, calls


class DeepSeekEmptyResponseRetryTests(unittest.TestCase):
    @patch("src.analyzer.time.sleep")
    def test_deepseek_content_does_not_retry(self, sleep_mock):
        _response_obj, content, calls = _call([_response("ok")])

        self.assertEqual(content, "ok")
        self.assertEqual(len(calls), 1)
        self.assertNotIn("extra_body", calls[0])
        sleep_mock.assert_not_called()

    @patch("src.analyzer.time.sleep")
    def test_deepseek_empty_then_content_retries_once_without_thinking(self, sleep_mock):
        _response_obj, content, calls = _call(
            [_response("", reasoning_content="internal"), _response("ok")]
        )

        self.assertEqual(content, "ok")
        sleep_mock.assert_called_once_with(3)
        self.assertEqual(len(calls), 2)
        self.assertNotIn("extra_body", calls[0])
        self.assertEqual(calls[1]["extra_body"], {"thinking": {"type": "disabled"}})

    @patch("src.analyzer.time.sleep")
    def test_deepseek_two_empty_responses_retry_only_once(self, _sleep_mock):
        _response_obj, content, calls = _call([_response(None), _response("   ")])

        self.assertEqual(content, "")
        self.assertEqual(len(calls), 2)

    @patch("src.analyzer.time.sleep")
    def test_non_deepseek_empty_response_does_not_add_deepseek_params(self, sleep_mock):
        _response_obj, content, calls = _call(
            [_response("")],
            model="openai/gpt-test",
            provider="openai",
        )

        self.assertEqual(content, "")
        self.assertEqual(len(calls), 1)
        self.assertNotIn("extra_body", calls[0])
        sleep_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
