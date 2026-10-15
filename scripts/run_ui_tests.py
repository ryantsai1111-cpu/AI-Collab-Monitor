"""Run current offline UI modules, isolating QApplication state per process."""
import argparse
from run_tests import main as run_tests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--visible', action='store_true')
    parser.add_argument('--widgets-only', action='store_true',
                        help='Only test_ui_refresh; old legacy UI modules are not loaded')
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()
    options = ['test_ui_refresh'] if args.widgets_only else ['--ui']
    if args.visible:
        options.append('--visible')
    if args.list:
        options.append('--list')
    return run_tests(options)


if __name__ == '__main__':
    raise SystemExit(main())
