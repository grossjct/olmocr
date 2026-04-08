"""
Monkey-patch wrapper for olmocr bench tools.

Fixes:
  1. Colon-in-argument parsing in convert.py (e.g. endpoint=http://host:8000/v1)
  2. Adds --json_summary to benchmark.py without modifying upstream source

Usage:
  python olmocr_patches.py convert <convert args...>
  python olmocr_patches.py benchmark <benchmark args...>

Examples:
  python olmocr_patches.py convert server:endpoint=http://localhost:8000/v1 --dir ./bench_data
  python olmocr_patches.py benchmark --dir ./bench_data --json_summary summary.json
"""

import json
import re
import sys
from pathlib import Path


def _patch_parse_method_arg():
    """Fix colon splitting so values like http://host:8000 are preserved."""
    import olmocr.bench.convert as convert

    _orig = convert.parse_method_arg

    def patched(method_arg):
        parts = re.split(r":(?=\w+=)", method_arg)
        name = parts[0]
        kwargs = {}
        folder_name = name

        for extra in parts[1:]:
            if "=" in extra:
                key, value = extra.split("=", 1)
                if key == "name":
                    folder_name = value
                    continue
                try:
                    converted = int(value)
                except ValueError:
                    try:
                        converted = float(value)
                    except ValueError:
                        converted = value
                kwargs[key] = converted
            else:
                raise ValueError(f"Extra argument '{extra}' is not in key=value format")

        return name, kwargs, folder_name

    convert.parse_method_arg = patched


def _patch_benchmark_json_summary():
    """Wrap generate_html_report to also emit a JSON summary alongside the HTML."""
    import olmocr.bench.benchmark as benchmark
    import olmocr.bench.report as report

    _orig_main = benchmark.main
    _orig_report = report.generate_html_report

    def main_wrapper():
        # Inject --json_summary arg if not already present
        orig_parse_args = benchmark.argparse.ArgumentParser.parse_args

        def patched_parse_args(self, args=None, namespace=None):
            # Add the argument before parsing
            try:
                self.add_argument(
                    "--json_summary",
                    type=str,
                    default=None,
                    help="Generate a JSON summary of test results.",
                )
            except Exception:
                pass  # already exists
            return orig_parse_args(self, args, namespace)

        benchmark.argparse.ArgumentParser.parse_args = patched_parse_args

        # Capture test_results_by_candidate via the report hook
        captured = {}

        def report_wrapper(test_results_by_candidate, pdf_folder, output_file, **kwargs):
            captured["test_results_by_candidate"] = test_results_by_candidate
            captured["pdf_folder"] = pdf_folder
            return _orig_report(test_results_by_candidate, pdf_folder, output_file, **kwargs)

        report.generate_html_report = report_wrapper
        benchmark.generate_html_report = report_wrapper

        _orig_main()

        # After main() finishes, check if --json_summary was requested
        json_summary = None
        for i, arg in enumerate(sys.argv):
            if arg == "--json_summary" and i + 1 < len(sys.argv):
                json_summary = sys.argv[i + 1]

        if json_summary and "test_results_by_candidate" in captured:
            results = captured["test_results_by_candidate"]
            summary = {}
            for candidate, pdfs in results.items():
                candidate_results = []
                for pdf_name, pages in pdfs.items():
                    for page, tests in pages.items():
                        for test, passed, explanation in tests:
                            entry = {
                                "test_id": test.id,
                                "pdf": pdf_name,
                                "page": page,
                                "type": test.type,
                                "passed": passed,
                            }
                            if not passed:
                                entry["explanation"] = explanation
                            candidate_results.append(entry)
                summary[candidate] = candidate_results

            out_path = Path(json_summary)
            with out_path.open("w") as f:
                json.dump(summary, f, indent=2)
            print(f"\nJSON summary written to {out_path}")

        # Restore
        benchmark.argparse.ArgumentParser.parse_args = orig_parse_args
        report.generate_html_report = _orig_report
        benchmark.generate_html_report = _orig_report

    benchmark.main = main_wrapper


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        sys.exit(0)

    command = sys.argv.pop(1)

    if command == "convert":
        _patch_parse_method_arg()
        from olmocr.bench.convert import main
        main()
    elif command == "benchmark":
        _patch_parse_method_arg()
        _patch_benchmark_json_summary()
        from olmocr.bench import benchmark
        benchmark.main()
    else:
        print(f"Unknown command: {command}. Use 'convert' or 'benchmark'.", file=sys.stderr)
        sys.exit(1)
