import os
import unittest
from types import SimpleNamespace
from unittest import mock

from src.formatters import markdown_to_html_document
from src.services.run_summary import (
    RUN_SOURCE_ENV,
    RunSummary,
    append_run_summary,
    collect_data_dates,
    format_elapsed_time,
    render_run_summary,
    resolve_run_source,
)


def _result(code: str, data_date: str):
    return SimpleNamespace(code=code, market_snapshot={"trading_date": data_date})


class RunSummaryTests(unittest.TestCase):
    def test_summary_when_all_five_stocks_succeed(self):
        results = [_result(code, "2026-07-31") for code in (
            "002714", "300498", "000876", "605296", "159867"
        )]
        summary = RunSummary(
            planned_count=5,
            success_count=5,
            failed_items=(),
            elapsed_seconds=58,
            data_dates=collect_data_dates(results),
        )

        rendered = render_run_summary(summary)

        self.assertIn("数据日期：2026-07-31", rendered)
        self.assertIn("计划分析：5 个标的", rendered)
        self.assertIn("成功完成：5 个标的", rendered)
        self.assertIn("分析失败：0 个标的", rendered)
        self.assertNotIn("失败标的", rendered)

    def test_summary_when_one_stock_fails(self):
        summary = RunSummary(
            planned_count=5,
            success_count=4,
            failed_items=("300498 温氏股份",),
            elapsed_seconds=588,
            data_dates=("2026-07-31",),
        )

        rendered = render_run_summary(summary)

        self.assertIn("成功完成：4 个标的", rendered)
        self.assertIn("分析失败：1 个标的", rendered)
        self.assertIn("失败标的：300498 温氏股份", rendered)
        self.assertIn("总运行耗时：9 分 48 秒", rendered)

    def test_local_run_source_is_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_run_source(), "本地运行")

    def test_github_run_source_labels(self):
        self.assertEqual(resolve_run_source("scheduled"), "GitHub 定时运行")
        self.assertEqual(resolve_run_source("manual"), "GitHub 手动运行")

    def test_elapsed_time_format(self):
        cases = [(58, "58 秒"), (588, "9 分 48 秒"), (3780, "1 小时 3 分")]
        for seconds, expected in cases:
            with self.subTest(seconds=seconds):
                self.assertEqual(format_elapsed_time(seconds), expected)

    def test_summary_is_safe_and_works_in_text_and_html(self):
        sensitive_values = {
            "OPENAI_API_KEY": "unit-test-secret-openai",
            "TAVILY_API_KEYS": "unit-test-secret-tavily",
            "EMAIL_PASSWORD": "unit-test-secret-email",
            RUN_SOURCE_ENV: "unexpected-secret-source",
        }
        with mock.patch.dict(os.environ, sensitive_values, clear=False):
            report = append_run_summary(
                "# 分析报告\n\n正文",
                RunSummary(
                    planned_count=1,
                    success_count=1,
                    failed_items=(),
                    elapsed_seconds=1,
                    data_dates=("2026-07-31",),
                ),
            )
            html = markdown_to_html_document(report)

        self.assertIn("本次运行摘要", report)
        self.assertIn("本次运行摘要", html)
        self.assertIn("运行来源：本地运行", report)
        for value in sensitive_values.values():
            self.assertNotIn(value, report)
            self.assertNotIn(value, html)


if __name__ == "__main__":
    unittest.main()
